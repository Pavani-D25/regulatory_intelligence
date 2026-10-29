"""Shared ingestion helpers for live sources (v4B tables, docs/SCHEMA_V4B.md):
ingestion_runs bookkeeping, write-once download into documents, listings into raw_ingestion_records."""

from __future__ import annotations

import logging
import mimetypes
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import httpx
import psycopg

from regtrack.db import Jsonb
from regtrack.sources import http
from regtrack.storage import normalise_ext, put_bytes, sha256_bytes

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


# crawlers report ok / partial / failed; the v4B tables store success / warning / failed
RUN_STATUS = {"ok": "success", "partial": "warning", "failed": "failed", "running": "running"}


def source_id(conn: psycopg.Connection, code: str) -> int:
    return conn.execute("SELECT id FROM sources WHERE code=%s", (code,)).fetchone()["id"]


def source_region(conn: psycopg.Connection, code: str) -> int:
    return conn.execute("SELECT region_id FROM sources WHERE code=%s", (code,)).fetchone()["region_id"]


def start_run(conn: psycopg.Connection, code: str) -> int:
    rid = conn.execute("INSERT INTO ingestion_runs (source_id, status) VALUES (%s,'running') RETURNING id",
                       (source_id(conn, code),)).fetchone()["id"]
    conn.commit()
    return rid


def finish_run(conn: psycopg.Connection, code: str, run_id: int, status: str, stats: RunStats, log_text: str = "") -> None:
    conn.rollback()  # never inherit an aborted transaction
    st = RUN_STATUS.get(status, status)
    log_text = log_text[:20000] or None
    conn.execute("""UPDATE ingestion_runs SET finished_at=now(), status=%s, stats=%s, log=%s, documents_found=%s,
                    changes_found=%s, error_message=%s WHERE id=%s""",
                 (st, Jsonb(stats.as_dict()), log_text, stats.seen, stats.new_files,
                  log_text.split("\n", 1)[0] if log_text else None, run_id))
    conn.execute("UPDATE sources SET last_synced_at=now(), last_sync_status=%s WHERE code=%s", (st, code))
    conn.commit()


def ext_from(content: bytes, url: str, ctype: str | None) -> str:
    if content[:5] == b"%PDF-":
        return "pdf"
    if content[:4] == b"PK\x03\x04":
        return "docx" if url.lower().endswith(".docx") or "word" in (ctype or "") else normalise_ext(url) or "zip"
    if content[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "doc"
    if content[:1024].lstrip()[:15].lower().startswith((b"<!doctype html", b"<html")):
        return "html"  # a page fetched by the crawler itself (no content-type passed along)
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
    known = conn.execute("SELECT id, document_id, last_seen_at, gone_at FROM raw_ingestion_records "
                         "WHERE source_id=%s AND external_ref=%s", (sid, lst.item_id)).fetchall()
    if known:
        stats.known += 1
        now = datetime.now(UTC)
        for k in known:
            if k["gone_at"] is not None or now - k["last_seen_at"] > SEEN_REFRESH:
                conn.execute("UPDATE raw_ingestion_records SET last_seen_at=now(), gone_at=NULL WHERE id=%s", (k["id"],))
        return
    if not lst.url and lst.content is None:
        stats.skipped += 1
        return
    # the seed import already holds this listing (from the _logs CSV): link it instead of downloading again
    seed = conn.execute(
        """SELECT document_id FROM raw_ingestion_records WHERE source_id=%s AND external_ref LIKE '%%log.csv:%%'
           AND listing_title IS NOT DISTINCT FROM %s::text AND (listing_date IS NOT DISTINCT FROM %s::date OR %s::date IS NULL)""",
        (sid, lst.title, lst.listing_date, lst.listing_date)).fetchall()
    if len(seed) == 1:
        add_listing(conn, sid, run_id, seed[0]["document_id"], lst, {"matched_seed": True})
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
    sha, path, created = put_bytes(content, ext)
    did, new = store_document(conn, source_region(conn, code), sha, str(path), lst.file_name, lst.url,
                              ext, (ctype or "").split(";")[0] or None, len(content))
    stats.new_files += new
    add_listing(conn, sid, run_id, did, lst)
    stats.new_listings += 1
    conn.commit()


def store_document(conn: psycopg.Connection, region_id: int, sha: str, storage_path: str, file_name: str | None,
                   url: str | None, ext: str, mime: str | None, size: int) -> tuple[int, bool]:
    """One row per file content (write-once originals). Returns (document id, newly created)."""
    row = conn.execute(
        """INSERT INTO documents (region_id, checksum_sha256, storage_path, file_name, original_url, file_ext, mime_type,
                                  file_size_bytes, stage)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'downloaded') ON CONFLICT (checksum_sha256) DO NOTHING RETURNING id""",
        (region_id, sha, storage_path, file_name, url, ext, mime, size)).fetchone()
    if row:
        return row["id"], True
    return conn.execute("SELECT id FROM documents WHERE checksum_sha256=%s", (sha,)).fetchone()["id"], False


def add_listing(conn: psycopg.Connection, sid: int, run_id: int | None, document_id: int, lst: Listing,
                extra: dict | None = None) -> bool:
    """The listing as the source showed it: a claim, kept apart from what the document itself says."""
    row = conn.execute(
        """INSERT INTO raw_ingestion_records (document_id, source_id, ingestion_run_id, source_url, external_ref,
                                              listing_title, listing_date, listing_category, payload, processing_status)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'downloaded')
           ON CONFLICT (source_id, external_ref, document_id) DO NOTHING RETURNING id""",
        (document_id, sid, run_id, lst.url, lst.item_id, lst.title, lst.listing_date, lst.category,
         Jsonb({**lst.raw, "file_name": lst.file_name, **(extra or {})}))).fetchone()
    return row is not None


def mark_gone(conn: psycopg.Connection, code: str, seen_ids: set[str], scope_prefix: str | None = None) -> int:
    """Listings no longer published get gone_at (only call after a complete listing pass)."""
    sid = source_id(conn, code)
    rows = conn.execute("SELECT id, external_ref FROM raw_ingestion_records WHERE source_id=%s AND gone_at IS NULL "
                        "AND ingestion_run_id IS NOT NULL AND external_ref NOT LIKE '%%log.csv:%%'",
                        (sid,)).fetchall()
    n = 0
    for r in rows:
        if scope_prefix and not (r["external_ref"] or "").startswith(scope_prefix):
            continue
        if r["external_ref"] not in seen_ids:
            conn.execute("UPDATE raw_ingestion_records SET gone_at=now() WHERE id=%s", (r["id"],))
            n += 1
    return n


__all__ = ["Listing", "RunStats", "record_listing", "start_run", "finish_run", "mark_gone", "sha256_bytes",
           "store_document", "add_listing", "source_id", "source_region"]
