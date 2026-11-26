"""WTO ePing: Thailand's TBT notifications (https://eping.wto.org/en/Search/Index, Area: TBT, Notifying Member:
Thailand). The search page reads a public JSON API (no login, no key):

    GET https://eping.wto.org/api/v1/azureSearch/getAll?language=1&domainIds=1&countryIds=C764&page=N&pageSize=100
        &sortBy=distributionDate&sortDirection=desc        (domainIds 1 = TBT, C764 = Thailand)

Each record carries the notification's WTO document (dolLink, e.g. G\\TBTN25\\THA797.DOCX): the official English
notification form, downloaded write-once from docs.wto.org. Thailand notifies ~1,300 TBT measures (food, electrical,
toys, ...); only the vehicle-related ones (wto.is_vehicle: ICS 43, HS 87 / tyres / batteries, vehicle words) are
downloaded. The pipeline reads them with regtrack/pipeline/wto.py.
"""

from __future__ import annotations

import logging
from datetime import date

from regtrack.db import connect
from regtrack.pipeline import wto
from regtrack.sources import http
from regtrack.sources.common import Listing, RunStats, finish_run, mark_gone, record_listing, start_run

log = logging.getLogger(__name__)
SOURCE = wto.SOURCE
SEARCH = "https://eping.wto.org/api/v1/azureSearch/getAll"
PARAMS = {"language": 1, "domainIds": 1, "countryIds": "C764", "sortBy": "distributionDate", "sortDirection": "desc"}
PAGE_SIZE = 100
# the WTO document in English: "t:" for current documents, "q:" for older ones (2003-era PDFs answer "t:" with a
# "The file is not published" page, which is never stored)
DOC = "https://docs.wto.org/dol2fe/Pages/SS/directdoc2.aspx?filename={}:/{}"
PREFIXES = ("t", "q")
NOT_PUBLISHED = b"The file is not published"


def search(c, max_pages: int = 40) -> list[dict]:
    """Every TBT notification of Thailand, newest first (the API pages 100 at a time)."""
    out: list[dict] = []
    for page in range(1, max_pages + 1):
        r = http.get(
            c, SEARCH, params={**PARAMS, "page": page, "pageSize": PAGE_SIZE}, headers={"Accept": "application/json"}
        )
        d = r.json()
        out += d.get("items") or []
        if not d.get("items") or d.get("endRow", 0) >= d.get("totalCount", 0):
            break
    return out


def to_listing(item: dict) -> Listing | None:
    dol = (item.get("dolLink") or "").replace("\\", "/").strip("/")
    symbol = (item.get("documentSymbol") or "").strip()
    if not dol or not symbol:
        return None
    dist = (item.get("distributionDate") or "")[:10]
    return Listing(
        item_id=symbol,
        url=DOC.format(PREFIXES[0], dol.lower()),
        title=f"{symbol} {wto._plain(item.get('title'))}"[:500],
        listing_date=date.fromisoformat(dist) if dist else None,
        category=item.get("notificationType") or "TBT",
        file_name=dol.rsplit("/", 1)[-1],
        raw={
            "eping_id": item.get("id"),
            "symbol": symbol,
            "notification_type": item.get("notificationType"),
            "notified_document": item.get("notifiedDocumentLink") or None,
            "comment_deadline": (item.get("commentDeadlineDate") or "")[:10] or None,
            "ics": [x.get("code") for x in item.get("icsCodes") or []],
            "hs": [x.get("code") for x in item.get("hsCodes") or []],
        },
    )


def fetch(c, lst: Listing) -> bool:
    """Download the English WTO document into lst.content (lst.url: the address that served it); False when no
    prefix serves a real file."""
    path = lst.url.split(":/", 2)[-1]
    for pre in PREFIXES:
        url = DOC.format(pre, path)
        r = http.get(c, url)
        if r.status_code == 200 and len(r.content) > 500 and not r.content.startswith(NOT_PUBLISHED):
            lst.url, lst.content = url, r.content
            return True
    return False


KNOWN_SQL = """SELECT r.id, d.id AS document_id, d.file_size_bytes, d.file_ext, d.storage_path FROM raw_ingestion_records r
               JOIN sources s ON s.id = r.source_id JOIN documents d ON d.id = r.document_id
               WHERE s.code = %s AND r.external_ref = %s"""


def stored_not_published(conn, symbol: str) -> list[dict]:
    """Sightings of this notification that point at a stored "The file is not published" page (an earlier run)."""
    from regtrack.storage import open_local

    out = []
    for k in conn.execute(KNOWN_SQL, (SOURCE, symbol)).fetchall():
        if k["file_ext"] == "txt" and (k["file_size_bytes"] or 0) < 5000:
            if open_local(k["storage_path"]).read_bytes().startswith(NOT_PUBLISHED):
                out.append(k)
    return out


def repair(conn, c, lst: Listing, bad: list[dict], stats: RunStats) -> None:
    """Re-link those sightings to the real document; the stored page stays (write-once) but is never processed."""
    from regtrack.sources.common import ext_from, source_region, store_document
    from regtrack.storage import put_bytes

    if not fetch(c, lst):
        stats.notes.append(f"{lst.item_id}: still not published in English")
        return
    ext = ext_from(lst.content, lst.url, None)
    sha, path, _ = put_bytes(lst.content, ext)
    did, new = store_document(
        conn, source_region(conn, SOURCE), sha, str(path), lst.file_name, lst.url, ext, None, len(lst.content)
    )
    for k in bad:
        conn.execute(
            "UPDATE raw_ingestion_records SET document_id=%s, source_url=%s, last_seen_at=now() WHERE id=%s",
            (did, lst.url, k["id"]),
        )
        conn.execute(
            "UPDATE documents SET stage='failed', stage_error=%s WHERE id=%s",
            ("WTO 'The file is not published' page; replaced by the published document", k["document_id"]),
        )
    conn.commit()
    stats.new_files += new
    stats.notes.append(f"{lst.item_id}: re-linked to the published document")


def crawl() -> dict:
    stats = RunStats()
    with connect() as conn:
        run_id = start_run(conn, SOURCE)
        notes: list[str] = []
        try:
            with http.client() as c:
                items = search(c)
                seen: set[str] = set()
                vehicle = [i for i in items if wto.is_vehicle(i)]
                stats.skipped += len(items) - len(vehicle)
                for item in vehicle:
                    lst = to_listing(item)
                    if lst is None:
                        stats.skipped += 1
                        continue
                    seen.add(lst.item_id)
                    bad = stored_not_published(conn, lst.item_id)
                    if bad:
                        repair(conn, c, lst, bad, stats)
                        continue
                    if not conn.execute(KNOWN_SQL, (SOURCE, lst.item_id)).fetchone() and not fetch(c, lst):
                        stats.errors += 1
                        stats.notes.append(f"{lst.item_id}: WTO document not published in English")
                        continue
                    record_listing(conn, c, SOURCE, run_id, lst, stats)  # http.get paces 1-2 s per host
            if items:
                stats.gone = mark_gone(conn, SOURCE, seen)
            notes.append(f"{len(items)} TBT notifications of Thailand, {len(vehicle)} vehicle-related")
            status = "ok" if items and not stats.errors else ("partial" if items else "failed")
        except Exception as e:  # noqa: BLE001
            status = "failed"
            notes.append(f"{type(e).__name__}: {e}"[:500])
        finish_run(conn, SOURCE, run_id, status, stats, "\n".join(notes + stats.notes))
    return {"run_id": run_id, "status": status, **stats.as_dict()}
