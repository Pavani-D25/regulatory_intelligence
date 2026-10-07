"""Shared ingestion helpers for live sources: crawl_run bookkeeping, write-once download, sightings."""

from __future__ import annotations

import logging
import mimetypes
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import httpx
import psycopg

from regtrack.config import get_settings
from regtrack.db import Jsonb
from regtrack.sources import http
from regtrack.storage import normalise_ext, sha256_bytes, store_bytes

log = logging.getLogger(__name__)
SEEN_REFRESH = timedelta(hours=20)  # last_seen_at is refreshed at most this often (a rerun writes nothing)


@dataclass
class Listing:
    item_id: str              # stable id at the source (MoRTH file path, ARAI id, India Code item UUID)
    url: str | None           # download URL
    title: str | None
    listing_date: date | None
    category: str | None
    raw: dict
    file_name: str | None = None
    content: bytes | None = None  # pre-fetched bytes (browser downloads, e.g. e-Gazette postbacks)


@dataclass
class RunStats:
    seen: int = 0
    new_listings: int = 0
    new_files: int = 0
    known: int = 0
    errors: int = 0
    gone: int = 0
    skipped: int = 0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def source_id(conn: psycopg.Connection, code: str) -> int:
    return conn.execute("SELECT id FROM source WHERE code=%s", (code,)).fetchone()["id"]


def start_run(conn: psycopg.Connection, code: str) -> int:
    rid = conn.execute("INSERT INTO crawl_run (source_id, status) VALUES (%s,'running') RETURNING id",
                       (source_id(conn, code),)).fetchone()["id"]
    conn.commit()
    return rid


def finish_run(conn: psycopg.Connection, code: str, run_id: int, status: str, stats: RunStats, log_text: str = "") -> None:
    conn.rollback()  # never inherit an aborted transaction
    conn.execute("UPDATE crawl_run SET finished_at=now(), status=%s, stats=%s, log=%s WHERE id=%s",
                 (status, Jsonb(stats.as_dict()), log_text[:20000] or None, run_id))
    conn.execute("UPDATE source SET last_run_at=now(), last_status=%s WHERE code=%s", (status, code))
    conn.commit()


def ext_from(content: bytes, url: str, ctype: str | None) -> str:
    if content[:5] == b"%PDF-":
        return "pdf"
    if content[:4] == b"PK\x03\x04":
        return "docx" if url.lower().endswith(".docx") or "word" in (ctype or "") else normalise_ext(url) or "zip"
    if content[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "doc"
    if ctype:
        guess = mimetypes.guess_extension(ctype.split(";")[0].strip())
        if guess:
            return guess.lstrip(".")
    return normalise_ext(url)


def record_listing(conn: psycopg.Connection, c: httpx.Client, code: str, run_id: int, lst: Listing, stats: RunStats) -> None:
    """One listing row in its own transaction: a bad row is logged and rolled back, never aborts the run."""
    try:
        _record_listing(conn, c, code, run_id, lst, stats)
        conn.commit()
    except psycopg.Error as e:
        conn.rollback()
        stats.errors += 1
        stats.notes.append(f"{lst.item_id}: {type(e).__name__}: {str(e).splitlines()[0]}"[:300])


def _record_listing(conn: psycopg.Connection, c: httpx.Client, code: str, run_id: int, lst: Listing, stats: RunStats) -> None:
    """Sighting for a listing row; download only when the row is new (new/changed files only)."""
    sid = source_id(conn, code)
    stats.seen += 1
    known = conn.execute("SELECT id, file_id, last_seen_at, gone_at FROM file_sighting WHERE source_id=%s AND source_item_id=%s",
                         (sid, lst.item_id)).fetchall()
    if known:
        stats.known += 1
        now = datetime.now(UTC)
        for k in known:
            if k["gone_at"] is not None or now - k["last_seen_at"] > SEEN_REFRESH:
                conn.execute("UPDATE file_sighting SET last_seen_at=now(), gone_at=NULL WHERE id=%s", (k["id"],))
        return
    if not lst.url and lst.content is None:
        stats.skipped += 1
        return
    # the seed import already holds this listing (from the _logs CSV): link it instead of downloading again
    seed = conn.execute(
        """SELECT file_id FROM file_sighting WHERE source_id=%s AND source_item_id LIKE '%%log.csv:%%'
           AND listing_title IS NOT DISTINCT FROM %s::text AND (listing_date IS NOT DISTINCT FROM %s::date OR %s::date IS NULL)""",
        (sid, lst.title, lst.listing_date, lst.listing_date)).fetchall()
    if len(seed) == 1:
        conn.execute(
            """INSERT INTO file_sighting (file_id, source_id, crawl_run_id, source_url, source_item_id, listing_title,
                                          listing_date, listing_category, listing_raw)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (source_id, source_item_id, file_id) DO NOTHING""",
            (seed[0]["file_id"], sid, run_id, lst.url, lst.item_id, lst.title, lst.listing_date, lst.category,
             Jsonb({**lst.raw, "file_name": lst.file_name, "matched_seed": True})))
        stats.known += 1
        conn.commit()
        return
    if lst.content is not None:
        content, ctype = lst.content, None
    else:
        try:
            r = http.get(c, lst.url)
        except Exception as e:  # noqa: BLE001
            stats.errors += 1
            stats.notes.append(f"download failed {lst.url}: {e}"[:300])
            return
        if r.status_code != 200 or len(r.content) < 200:
            stats.errors += 1
            stats.notes.append(f"HTTP {r.status_code} ({len(r.content)} bytes) {lst.url}"[:300])
            return
        content, ctype = r.content, r.headers.get("content-type")
    ext = ext_from(content, lst.url or lst.file_name or "", ctype)
    sha, path, created = store_bytes(content, ext)
    row = conn.execute(
        """INSERT INTO file_object (sha256, storage_path, mime, ext, size_bytes, stage)
           VALUES (%s,%s,%s,%s,%s,'downloaded') ON CONFLICT (sha256) DO NOTHING RETURNING id""",
        (sha, str(path), (ctype or "").split(";")[0] or None, ext, len(content))).fetchone()
    if row:
        stats.new_files += 1
        fid = row["id"]
    else:
        fid = conn.execute("SELECT id FROM file_object WHERE sha256=%s", (sha,)).fetchone()["id"]
    conn.execute(
        """INSERT INTO file_sighting (file_id, source_id, crawl_run_id, source_url, source_item_id, listing_title,
                                      listing_date, listing_category, listing_raw)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (source_id, source_item_id, file_id) DO NOTHING""",
        (fid, sid, run_id, lst.url, lst.item_id, lst.title, lst.listing_date, lst.category,
         Jsonb({**lst.raw, "file_name": lst.file_name})))
    stats.new_listings += 1
    conn.commit()


def mark_gone(conn: psycopg.Connection, code: str, seen_ids: set[str], scope_prefix: str | None = None) -> int:
    """Listings no longer published get gone_at (only call after a complete listing pass)."""
    sid = source_id(conn, code)
    rows = conn.execute("SELECT id, source_item_id FROM file_sighting WHERE source_id=%s AND gone_at IS NULL "
                        "AND crawl_run_id IS NOT NULL AND source_item_id NOT LIKE '%%log.csv:%%'",
                        (sid,)).fetchall()
    n = 0
    for r in rows:
        if scope_prefix and not (r["source_item_id"] or "").startswith(scope_prefix):
            continue
        if r["source_item_id"] not in seen_ids:
            conn.execute("UPDATE file_sighting SET gone_at=now() WHERE id=%s", (r["id"],))
            n += 1
    return n


def storage_root():
    return get_settings().storage_dir


__all__ = ["Listing", "RunStats", "record_listing", "start_run", "finish_run", "mark_gone", "sha256_bytes"]
