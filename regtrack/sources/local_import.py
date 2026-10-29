"""Documents people saved by hand, per country: <IMPORT_DIR>/TH/... and <IMPORT_DIR>/MY/... (migration 0020).

For official sources the crawlers cannot reach from this network or without a captcha (DLT, the Council of State
law search, the Royal Gazette): a person downloads the PDF in a normal browser and saves it here. The folder is
read only; each file is stored write-once like any download. Its listing id is the relative path plus a hash of
the bytes, so an unchanged file is known (writes nothing), a replaced file is a new version and a removed one gone.
Identity, class and dates come from the content (regtrack/pipeline/thai.py, malaysia.py), never the file name.
"""

from __future__ import annotations

import hashlib
import logging

from regtrack.config import get_settings
from regtrack.db import connect
from regtrack.sources.common import Listing, RunStats, finish_run, mark_gone, record_listing, start_run

log = logging.getLogger(__name__)
SOURCES = {"TH_LOCAL": "TH", "MY_LOCAL": "MY"}
EXTENSIONS = {".pdf", ".html", ".htm", ".docx", ".doc", ".xlsx", ".txt"}
CRAWLS_BY_CODE = True  # regtrack.scheduler calls crawl(<source code>)


def listings(code: str) -> list[Listing]:
    root = get_settings().import_dir / SOURCES[code]
    if not root.is_dir():
        return []
    out = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in EXTENSIONS):
        content = path.read_bytes()
        rel = path.relative_to(root).as_posix()
        digest = hashlib.sha256(content).hexdigest()[:16]
        out.append(
            Listing(
                item_id=f"{rel}#{digest}",
                url=None,
                title=path.stem,
                listing_date=None,
                category="local",
                raw={"path": rel},
                file_name=path.name,
                content=content,
            )
        )
    return out


def crawl(code: str | None = None) -> dict:
    if not code:
        return {c: crawl(c) for c in SOURCES}
    stats = RunStats()
    with connect() as conn:
        run_id = start_run(conn, code)
        notes: list[str] = []
        status = "failed"
        try:
            items = listings(code)
            seen = set()
            for lst in items:
                seen.add(lst.item_id)
                record_listing(conn, None, code, run_id, lst, stats)
            stats.gone = mark_gone(conn, code, seen)
            status = "ok" if not stats.errors else "partial"
            if not items:
                notes.append(f"no files in {get_settings().import_dir / SOURCES[code]}")
        except Exception as e:  # noqa: BLE001
            notes.append(f"{type(e).__name__}: {e}"[:500])
        finish_run(conn, code, run_id, status, stats, "\n".join(notes + stats.notes))
    return {"run_id": run_id, "status": status, **stats.as_dict()}
