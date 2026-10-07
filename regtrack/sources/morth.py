"""MoRTH public JSON API (ETL_SPEC 1.3): gazettes-notifications, orders-and-notices, guidelines.

GET https://morth.gov.in/backend/api/<slug>?page=N&per_page=100&wings=&order_by=desc&search=
Response: page.files[] = groups, each with files_data[]. File URL = https://morth.gov.in/backend/ + file.
Only road-transport material is kept (group 'Motor Vehicle Legislation' or the Road Transport / Road Safety
wings); highway groups (NH Declaration/Entrustment ...) are skipped. Listing titles are claims only.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from urllib.parse import quote

from regtrack.db import connect
from regtrack.sources import http
from regtrack.sources.common import Listing, RunStats, finish_run, mark_gone, record_listing, start_run

log = logging.getLogger(__name__)
BASE = "https://morth.gov.in/backend/"
API = BASE + "api/{slug}?page={page}&per_page={per}&wings=&order_by=desc&search="
SLUGS = ["gazettes-notifications", "orders-and-notices", "guidelines"]
KEEP_GROUPS = re.compile(r"motor\s+vehicle|road\s+safety|road\s+transport|transport", re.I)
SKIP_GROUPS = re.compile(r"\bNH\b|national\s+highway|entrustment|declaration|toll|bridge|land\s+acquisition|"
                         r"de-?notification|EPC|HAM|BOT", re.I)
KEEP_WINGS = re.compile(r"road\s+transport|road\s+safety|transport", re.I)
AUTO_TITLE = re.compile(r"\b(?:G\.?S\.?R|S\.?O)\b|motor\s+vehicle|CMVR|AIS|vehicle|driving|licen[cs]e|registration|"
                        r"permit|emission|fitness|helmet|HSRP|scrapp|e-?rickshaw|trailer|tyre|fastag|road\s+safety", re.I)


def keep(row: dict) -> bool:
    group = row.get("name") or ""
    wings = row.get("wings_division") or ""
    title = row.get("title") or ""
    if SKIP_GROUPS.search(group):
        return False
    if re.search(r"motor\s+vehicle\s+legislation", group, re.I):
        return True
    if KEEP_WINGS.search(wings) or KEEP_GROUPS.search(group):
        return True
    return bool(AUTO_TITLE.search(title))


def _d(s: str | None) -> date | None:
    try:
        return date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def iter_listings(c, slug: str, per_page: int = 100, max_pages: int = 50):
    """Yield (row, group) for every file on every page until a page adds nothing new."""
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        r = http.get(c, API.format(slug=slug, page=page, per=per_page))
        r.raise_for_status()
        groups = (r.json().get("page") or {}).get("files") or []
        new = 0
        for g in groups:
            for fd in g.get("files_data") or [g]:
                key = (fd.get("file") or fd.get("link") or "") + "|" + (fd.get("title") or "")
                if key in seen:
                    continue
                seen.add(key)
                new += 1
                yield fd, g
        if new == 0 or not groups:
            break


def to_listing(slug: str, fd: dict, g: dict) -> Listing | None:
    path = fd.get("file") or ""
    if not path or "/tmp/" in path or path.startswith("tmp"):
        return None  # broken temp links seen in the API
    url = BASE + quote(path.lstrip("/"), safe="/")
    return Listing(item_id=f"{slug}:{path}", url=url, title=(fd.get("title") or "").strip() or None,
                   listing_date=_d(fd.get("published_date")), category=f"{slug}|{g.get('name') or fd.get('name') or ''}",
                   raw={k: fd.get(k) for k in ("title", "file", "published_date", "wings_division", "name",
                                               "document_type_id", "file_size", "page_id", "is_archived", "code",
                                               "circular_guideline_number", "link", "last_date")},
                   file_name=path.rsplit("/", 1)[-1])


def crawl(slugs: list[str] | None = None) -> dict:
    stats = RunStats()
    status, notes = "ok", []
    with connect() as conn:
        run_id = start_run(conn, "MORTH_API")
        seen_ids: set[str] = set()
        complete = True
        try:
            with http.client() as c:
                for slug in slugs or SLUGS:
                    try:
                        for fd, g in iter_listings(c, slug):
                            if not keep({**g, **fd}):
                                continue
                            lst = to_listing(slug, fd, g)
                            if lst is None:
                                stats.skipped += 1
                                continue
                            seen_ids.add(lst.item_id)
                            record_listing(conn, c, "MORTH_API", run_id, lst, stats)
                    except Exception as e:  # noqa: BLE001
                        complete = False
                        stats.errors += 1
                        notes.append(f"{slug}: {type(e).__name__}: {e}"[:300])
            if complete:
                stats.gone = mark_gone(conn, "MORTH_API", seen_ids, scope_prefix=None)
            status = "ok" if complete and not stats.errors else "partial"
        except Exception as e:  # noqa: BLE001
            status = "failed"
            notes.append(f"{type(e).__name__}: {e}"[:500])
        finish_run(conn, "MORTH_API", run_id, status, stats, "\n".join(notes + stats.notes))
    return {"run_id": run_id, "status": status, **stats.as_dict()}
