"""India Code (indiacode.gov.in, DSpace 7) - public REST search, no login.

GET /server/api/discover/search/objects?query=...&size=50&page=N&sort=dc.date.accessioned,DESC
Items -> bundles (ORIGINAL) -> bitstreams -> /content. State-level items (dc.identifier.state_name set) are
skipped: the seed corpus showed they are off-topic for central vehicle regulation.
Stops paging a query once a whole page is already known (incremental runs are cheap).
"""

from __future__ import annotations

import logging
from datetime import date
from urllib.parse import quote

from regtrack.db import connect
from regtrack.sources import http
from regtrack.sources.common import Listing, RunStats, finish_run, record_listing, source_id, start_run

log = logging.getLogger(__name__)
BASE = "https://indiacode.gov.in/server/api"
QUERIES = [
    '"Central Motor Vehicles Rules"',
    '"Motor Vehicles (Amendment)"',
    '"Vehicle Scrapping"',
    '"Battery Waste Management Rules"',
    '"Registered Vehicle Scrapping Facility"',
    '"High Security Registration Plate"',
    '"End-of-Life Vehicles"',
]


def _md(it: dict, key: str) -> str | None:
    v = (it.get("metadata") or {}).get(key) or []
    return v[0]["value"] if v else None


def _d(s: str | None) -> date | None:
    try:
        return date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def is_central(it: dict) -> bool:
    state = (_md(it, "dc.identifier.state_name") or "").strip()
    return not state or state.lower() in ("central", "india", "no state")


def bitstreams(c, item_uuid: str) -> list[dict]:
    r = http.get(c, f"{BASE}/core/items/{item_uuid}/bundles?embed=bitstreams", headers={"Accept": "application/json"})
    r.raise_for_status()
    out = []
    for b in (r.json().get("_embedded") or {}).get("bundles", []):
        if b.get("name") != "ORIGINAL":
            continue
        for bs in ((b.get("_embedded") or {}).get("bitstreams") or {}).get("_embedded", {}).get("bitstreams", []):
            out.append(
                {"id": bs["uuid"], "name": bs.get("name"), "url": f"{BASE}/core/bitstreams/{bs['uuid']}/content"}
            )
    return out


def known(conn, item_id: str, title: str | None) -> bool:
    sid = source_id(conn, "INDIACODE")
    return (
        conn.execute(
            "SELECT 1 FROM raw_ingestion_records WHERE source_id=%s AND (external_ref LIKE %s OR "
            "(external_ref LIKE '%%log.csv:%%' AND listing_title IS NOT DISTINCT FROM %s)) LIMIT 1",
            (sid, item_id + "%", title),
        ).fetchone()
        is not None
    )


def crawl(queries: list[str] | None = None, max_pages: int = 20, size: int = 50) -> dict:
    stats = RunStats()
    notes: list[str] = []
    status = "ok"
    with connect() as conn:
        run_id = start_run(conn, "INDIACODE")
        try:
            with http.client() as c:
                for q in queries or QUERIES:
                    for page in range(max_pages):
                        url = (
                            f"{BASE}/discover/search/objects?query={quote(q)}&size={size}&page={page}"
                            f"&sort=dc.date.accessioned,DESC&dsoType=ITEM"
                        )
                        r = http.get(c, url, headers={"Accept": "application/json"})
                        if r.status_code in (401, 403):
                            notes.append(f"{q}: HTTP {r.status_code} (login required) - stopped")
                            status = "partial"
                            break
                        r.raise_for_status()
                        sr = r.json()["_embedded"]["searchResult"]
                        objs = (sr.get("_embedded") or {}).get("objects") or []
                        if not objs:
                            break
                        page_known = 0
                        for o in objs:
                            it = o["_embedded"]["indexableObject"]
                            if not is_central(it):
                                stats.skipped += 1
                                page_known += 1
                                continue
                            title = it.get("name") or _md(it, "dc.title")
                            item_id = it["uuid"]
                            if known(conn, item_id, title):
                                stats.known += 1
                                stats.seen += 1
                                page_known += 1
                                continue
                            for bs in bitstreams(c, item_id):
                                lst = Listing(
                                    item_id=f"{item_id}:{bs['id']}",
                                    url=bs["url"],
                                    title=title,
                                    listing_date=_d(_md(it, "dc.date.issued")),
                                    category=q,
                                    raw={
                                        "item_id": item_id,
                                        "handle": it.get("handle"),
                                        "query": q,
                                        "bitstream": bs["name"],
                                        "ministry": _md(it, "dc.identifier.ministry_name"),
                                        "act": _md(it, "dc.identifier.act_name"),
                                    },
                                    file_name=bs["name"],
                                )
                                record_listing(conn, c, "INDIACODE", run_id, lst, stats)
                        if page_known == len(objs) or page + 1 >= sr["page"]["totalPages"]:
                            break
        except Exception as e:  # noqa: BLE001
            status = "failed" if not stats.seen else "partial"
            notes.append(f"{type(e).__name__}: {e}"[:500])
        finish_run(
            conn,
            "INDIACODE",
            run_id,
            status if not stats.errors or status != "ok" else "partial",
            stats,
            "\n".join(notes + stats.notes),
        )
    return {"run_id": run_id, "status": status, **stats.as_dict()}
