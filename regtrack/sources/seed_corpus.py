"""Seed corpus import (Phase 2): SEED_CORPUS_DIR is READ-ONLY.

Walks every folder except _logs and _review*, hashes each file, copies it write-once into STORAGE_DIR,
inserts file_object (stage='downloaded') and a LOCAL_SEED file_sighting. The CSV logs in _logs are
attached as sightings of their real sources (MORTH_API, ARAI_AIS, INDIACODE, ARAI_TAP).
Re-running adds nothing.
"""

from __future__ import annotations

import csv
import json
import logging
import mimetypes
import re
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from regtrack.config import get_settings
from regtrack.storage import normalise_ext, put_file, sha256_file, storage_uri

log = logging.getLogger(__name__)

SKIP_DIRS = re.compile(r"^(_logs|_review.*)$", re.I)
MANIFEST_NAME = "seed_manifest.jsonl"


@dataclass
class SeedFile:
    rel: str           # forward-slash path relative to the corpus root
    folder: str        # top-level folder
    name: str
    ext: str
    size: int
    sha256: str
    mtime: float

    @property
    def path(self) -> Path:
        return get_settings().seed_corpus_dir / Path(*self.rel.split("/"))


def iter_corpus(root: Path | None = None) -> Iterator[Path]:
    root = root or get_settings().seed_corpus_dir
    for top in sorted(root.iterdir()):
        if top.is_file() or SKIP_DIRS.match(top.name):
            continue  # README.md at the root is not part of the corpus
        stack = [top]
        while stack:
            d = stack.pop()
            for p in sorted(d.iterdir()):
                if p.is_dir():
                    if not SKIP_DIRS.match(p.name):
                        stack.append(p)
                elif p.is_file():
                    yield p


def manifest_path() -> Path:
    return get_settings().storage_dir.parent / MANIFEST_NAME


def load_manifest() -> dict[str, dict]:
    p = manifest_path()
    if not p.exists():
        return {}
    out = {}
    with open(p, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            out[d["rel"]] = d
    return out


def scan(root: Path | None = None) -> list[SeedFile]:
    """Hash every corpus file (cached in seed_manifest.jsonl by rel path + size + mtime)."""
    root = root or get_settings().seed_corpus_dir
    cache = load_manifest()
    out: list[SeedFile] = []
    mp = manifest_path()
    mp.parent.mkdir(parents=True, exist_ok=True)
    with open(mp, "a", encoding="utf-8") as mf:
        for p in iter_corpus(root):
            rel = p.relative_to(root).as_posix()
            st = p.stat()
            c = cache.get(rel)
            if c and c["size"] == st.st_size and abs(c["mtime"] - st.st_mtime) < 1:
                sf = SeedFile(**c)
            else:
                sf = SeedFile(rel=rel, folder=rel.split("/")[0], name=p.name, ext=normalise_ext(p.name),
                              size=st.st_size, sha256=sha256_file(p), mtime=st.st_mtime)
                mf.write(json.dumps(asdict(sf), ensure_ascii=False) + "\n")
                mf.flush()
            out.append(sf)
    return out


def copy_to_storage(files: list[SeedFile]) -> int:
    created = 0
    for sf in files:
        _, _, c = put_file(sf.path, sf.ext)
        created += c
    return created


# ------------------------------------------------------------------ _logs CSVs
LOG_SOURCES = {
    "morth_download_log.csv": "MORTH_API",
    "ais_download_log.csv": "ARAI_AIS",
    "cmvr_indiacode_log.csv": "INDIACODE",
    "indiacode_multi_log.csv": "INDIACODE",
    "arai_static_log.csv": "ARAI_TAP",
    "retry_failed_log.csv": None,  # source given per row
}
LOG_FOLDERS = {  # where each log's files landed
    "morth_download_log.csv": ("05_MoRTH_Gazette_Notifications", "06_MoRTH_Circulars_Orders", "27_Master_Checklists_and_Indexes",
                               "01_CMVR_Central_Motor_Vehicles_Rules"),
    "ais_download_log.csv": ("07_AIS_Published_Standards",),
    "cmvr_indiacode_log.csv": ("02_CMVR_Amendments_Notifications", "01_CMVR_Central_Motor_Vehicles_Rules"),
    "indiacode_multi_log.csv": ("02_CMVR_Amendments_Notifications", "24_EV_Battery_Waste_Management_EPR",
                                "25_Vehicle_Scrappage_ELV_Rules", "29_Fuel_Quality_MoPNG_Regulations",
                                "01_CMVR_Central_Motor_Vehicles_Rules", "21_BIS_Automobile_Component_Standards_Catalogue"),
    "arai_static_log.csv": None,  # has its own subfolder column
    "retry_failed_log.csv": ("02_CMVR_Amendments_Notifications",),
}


@dataclass
class LogRow:
    log: str
    source: str
    file: str
    title: str | None
    listing_date: date | None
    category: str | None
    item_id: str | None
    url: str | None
    raw: dict


def _d(s: str | None) -> date | None:
    try:
        return date.fromisoformat((s or "").strip()[:10])
    except ValueError:
        return None


def read_logs(root: Path | None = None) -> list[LogRow]:
    root = root or get_settings().seed_corpus_dir
    out: list[LogRow] = []
    for name in LOG_SOURCES:
        p = root / "_logs" / name
        if not p.exists():
            continue
        with open(p, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                status = (r.get("status") or r.get("STATUS") or "").upper()
                fname = r.get("file") or r.get("FILE") or ""
                if not fname or status not in ("OK", "SKIP_EXISTS", "EXISTS", "DUP", "SKIP"):
                    continue
                if name == "morth_download_log.csv":
                    out.append(LogRow(name, "MORTH_API", fname, r.get("title"), _d(r.get("published_date")),
                                      f"{r.get('endpoint')}|{r.get('wing')}", None, None, r))
                elif name == "ais_download_log.csv":
                    out.append(LogRow(name, "ARAI_AIS", fname, r.get("CODE"), None, "published", r.get("SR"), None, r))
                elif name == "arai_static_log.csv":
                    out.append(LogRow(name, "ARAI_TAP", fname, Path(fname).stem, None, r.get("subfolder"), r.get("url"),
                                      r.get("url"), r))
                elif name in ("cmvr_indiacode_log.csv", "indiacode_multi_log.csv"):
                    out.append(LogRow(name, "INDIACODE", fname, r.get("item_name"), None, r.get("query"),
                                      r.get("item_id"), None, r))
                elif name == "retry_failed_log.csv":
                    s = (r.get("source") or "").lower()
                    code = {"indiacode": "INDIACODE", "morth": "MORTH_API", "arai": "ARAI_AIS"}.get(s, "INDIACODE")
                    out.append(LogRow(name, code, fname, r.get("title"), None, r.get("endpoint_or_item"),
                                      r.get("endpoint_or_item"), None, r))
    return out


def match_logs(files: list[SeedFile], rows: list[LogRow]) -> dict[int, list[LogRow]]:
    """Map each log row to the seed file it produced (by folder + file name). Returns {index: rows}."""
    by_name: dict[str, list[int]] = {}
    for i, sf in enumerate(files):
        by_name.setdefault(sf.name.lower(), []).append(i)
    out: dict[int, list[LogRow]] = {}
    for r in rows:
        cands = by_name.get(r.file.lower(), [])
        if r.log == "arai_static_log.csv" and r.category:
            cands = [i for i in cands if files[i].folder == r.category] or cands
        else:
            folders = LOG_FOLDERS.get(r.log)
            if folders:
                cands = [i for i in cands if files[i].folder in folders] or cands
        for i in cands[:1]:
            out.setdefault(i, []).append(r)
    return out


def mime_of(name: str) -> str:
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


# ------------------------------------------------------------------ DB import
def import_seed(limit: int | None = None) -> dict:
    from regtrack.db import Jsonb, transaction

    files = scan()
    if limit:
        files = files[:limit]
    copied = copy_to_storage(files)
    rows = read_logs()
    matched = match_logs(files, rows)
    stats = {"files": len(files), "unique_sha": len({f.sha256 for f in files}), "copied_new": copied,
             "file_object_new": 0, "sighting_new": 0, "log_rows": len(rows), "log_rows_matched": 0}
    with transaction() as conn:
        src = {r["code"]: r["id"] for r in conn.execute("SELECT id, code FROM source")}
        run = conn.execute("INSERT INTO crawl_run (source_id, status, stats) VALUES (%s,'running','{}') RETURNING id",
                           (src["LOCAL_SEED"],)).fetchone()["id"]
        for i, sf in enumerate(files):
            spath = storage_uri(sf.sha256, sf.ext)
            r = conn.execute(
                """INSERT INTO file_object (sha256, storage_path, mime, ext, size_bytes, stage)
                   VALUES (%s,%s,%s,%s,%s,'downloaded') ON CONFLICT (sha256) DO NOTHING RETURNING id""",
                (sf.sha256, str(spath), mime_of(sf.name), sf.ext, sf.size)).fetchone()
            if r:
                stats["file_object_new"] += 1
                fid = r["id"]
            else:
                fid = conn.execute("SELECT id FROM file_object WHERE sha256=%s", (sf.sha256,)).fetchone()["id"]
            sightings = [("LOCAL_SEED", sf.rel, sf.name, None, sf.folder, None,
                          {"folder": sf.folder, "path": sf.rel})]
            for lr in matched.get(i, []):
                stats["log_rows_matched"] += 1
                sightings.append((lr.source, f"{lr.log}:{lr.item_id or lr.file}", lr.title, lr.listing_date,
                                  lr.category, lr.url, {"log": lr.log, "row": lr.raw, "folder": sf.folder, "path": sf.rel}))
            for code, item, title, ldate, cat, url, raw in sightings:
                r = conn.execute(
                    """INSERT INTO file_sighting (file_id, source_id, crawl_run_id, source_url, source_item_id,
                         listing_title, listing_date, listing_category, listing_raw)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (source_id, source_item_id, file_id) DO NOTHING RETURNING id""",
                    (fid, src[code], run, url, item, title, ldate, cat, Jsonb(raw))).fetchone()
                stats["sighting_new"] += bool(r)
        if stats["file_object_new"] or stats["sighting_new"]:
            conn.execute("UPDATE crawl_run SET finished_at=now(), status='ok', stats=%s WHERE id=%s",
                         (Jsonb(stats), run))
            conn.execute("UPDATE source SET last_run_at=now(), last_status='ok' WHERE code='LOCAL_SEED'")
        else:  # idempotent re-run: leave no trace
            conn.execute("DELETE FROM crawl_run WHERE id=%s", (run,))
    return stats
