"""TISI mandatory-standards list (TH-0 investigation): www.tisi.go.th's static HTML list of every product
whose มอก. (Thai Industrial Standard) is legally mandatory. No captcha, no login. Each row's "รายละเอียด"
(details) link to www3.tisi.go.th/hscode/hscode_view.asp?id=<n> actually works (TH-0's report found it
404ing; re-checked live and it does not - confirmed by fetching one directly). That detail page has no
separate PDF - it is itself the record - so it is stored as the write-once original (.html), same as any
other downloaded file.

This crawler only discovers, downloads and records listings (with TISI's product group as the listing
category). The pipeline reads the pages with regtrack/pipeline/thai.py: automotive ones become TIS_STANDARD,
the rest (steel, plastics, circuit breakers, ...) OFF_TOPIC.
"""

from __future__ import annotations

import logging
import re
import time

from regtrack.config import get_settings
from regtrack.db import connect
from regtrack.pipeline.thai import parse_thai_date
from regtrack.sources import http
from regtrack.sources.common import Listing, RunStats, finish_run, mark_gone, record_listing, start_run

log = logging.getLogger(__name__)
URL = "https://www.tisi.go.th/website/standardlist/comp_thai/th"
SOURCE = "TH_TISI_MANDATORY"

def _launch(p):
    from regtrack.sources.browser import launch

    return launch(p)


def open_listing(page, attempts: int = 2) -> None:
    for i in range(attempts):
        try:
            page.goto(URL, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_selector("div.ps-1.mb-2", timeout=90000)
            return
        except Exception:  # noqa: BLE001
            if i == attempts - 1:
                raise
            time.sleep(30 * (i + 1))


def scrape() -> list[dict]:
    """One row per mandatory standard: category heading, มอก. number, title, effective date text, detail link."""
    from playwright.sync_api import sync_playwright

    items: list[dict] = []
    with sync_playwright() as p:
        b = _launch(p)
        page = b.new_page(user_agent=get_settings().user_agent)
        open_listing(page)
        accept = page.get_by_text("ยอมรับ", exact=True)
        if accept.count():
            accept.first.click()
            time.sleep(1)
        heads = page.locator("div.ps-1.mb-2")
        for i in range(heads.count()):
            head = heads.nth(i)
            category = re.sub(r"\s*\(\d+\s*รายการ\)\s*$", "", head.inner_text()).strip()
            rows = head.locator("xpath=following-sibling::ol[1]").locator("li")
            for j in range(rows.count()):
                li = rows.nth(j)
                p_loc = li.locator("div.col-8 p")
                if not p_loc.count():
                    continue
                full = p_loc.inner_text()
                b_loc = p_loc.locator("b")
                number = b_loc.inner_text().strip() if b_loc.count() else ""
                rest = full[len(number):] if number and full.startswith(number) else full
                parts = rest.split("วันที่มีผลใช้บังคับ:")
                title = parts[0].strip()
                effective_text = parts[1].strip() if len(parts) > 1 else None
                a_loc = li.locator("div.col-4 a")
                href = a_loc.get_attribute("href") if a_loc.count() else None
                items.append({"category": category, "number": number, "title": title,
                             "effective_text": effective_text, "href": href})
        b.close()
    return items


def to_listing(r: dict) -> Listing | None:
    href = r["href"]
    if not href:
        return None
    m = re.search(r"[?&]id=(\d+)", href)
    item_id = f"id={m.group(1)}" if m else href
    return Listing(item_id=item_id, url=href, title=f"{r['number']} {r['title']}".strip(),
                   listing_date=parse_thai_date(r["effective_text"]), category=r["category"] or None,
                   raw={"number": r["number"], "effective_text": r["effective_text"]})


def crawl() -> dict:
    stats = RunStats()
    with connect() as conn:
        run_id = start_run(conn, SOURCE)
        notes: list[str] = []
        try:
            rows = scrape()
            seen: set[str] = set()
            with http.client() as c:
                for r in rows:
                    lst = to_listing(r)
                    if lst is None:
                        stats.skipped += 1
                        continue
                    seen.add(lst.item_id)
                    record_listing(conn, c, SOURCE, run_id, lst, stats)
            if rows:
                stats.gone = mark_gone(conn, SOURCE, seen)
            status = "ok" if rows and not stats.errors else ("partial" if rows else "failed")
            if not rows:
                notes.append("no rows rendered")
        except Exception as e:  # noqa: BLE001
            status = "failed"
            notes.append(f"{type(e).__name__}: {e}"[:500])
        finish_run(conn, SOURCE, run_id, status, stats, "\n".join(notes + stats.notes))
    return {"run_id": run_id, "status": status, **stats.as_dict()}
