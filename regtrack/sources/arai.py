"""ARAI AIS list (ETL_SPEC 1.1) via a Playwright page render - never the bearer token embedded in the page.

The public page https://www.araiindia.com/downloads/ais-downloads shows the list 10 rows at a time (tabs
Published / Draft). We read the rendered rows (SR, CODE, TITLE, file link) page by page with 1-2 s pauses.
The 'code' string is a listing claim; identity comes from the document cover. hmr.araiindia.com's member
portal (login + captcha) is never touched; only the public /storage/ais-details/ file links are downloaded.
"""

from __future__ import annotations

import logging
import random
import time

from regtrack.config import get_settings
from regtrack.db import connect
from regtrack.pipeline.identity import parse_arai_code
from regtrack.sources import http
from regtrack.sources.common import Listing, RunStats, finish_run, mark_gone, record_listing, start_run

log = logging.getLogger(__name__)
URL = "https://www.araiindia.com/downloads/ais-downloads"
TABS = ["Published", "Draft"]


def _launch(p):
    try:
        return p.chromium.launch(channel="chrome", headless=True)  # the installed Chrome: no browser download
    except Exception:  # noqa: BLE001
        return p.chromium.launch(headless=True)


def read_rows(page) -> list[dict]:
    out = []
    rows = page.locator("table tbody tr")
    for i in range(rows.count()):
        tr = rows.nth(i)
        cells = tr.locator("td")
        if cells.count() < 3:
            continue
        links = [a.get_attribute("href") for a in tr.locator("a").all() if a.get_attribute("href")]
        out.append({"sr": cells.nth(0).inner_text().strip(), "code": cells.nth(1).inner_text().strip(),
                    "title": cells.nth(2).inner_text().strip(), "links": links})
    return out


def open_listing(page, attempts: int = 2) -> None:
    """Load the AIS page and wait for the table itself. 'networkidle' can hang on a slow site or background
    trackers, so wait for the DOM and then for the first table row; retry once after a pause on timeout."""
    for i in range(attempts):
        try:
            page.goto(URL, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_selector("table tbody tr td", timeout=90000)
            return
        except Exception:  # noqa: BLE001
            if i == attempts - 1:
                raise
            time.sleep(30 * (i + 1))


def scrape(max_pages: int = 80) -> list[dict]:
    from playwright.sync_api import sync_playwright

    items: list[dict] = []
    with sync_playwright() as p:
        b = _launch(p)
        page = b.new_page(user_agent=get_settings().user_agent)
        open_listing(page)
        for tab in TABS:
            t = page.get_by_text(tab, exact=True)
            if t.count():
                t.first.click()
                time.sleep(random.uniform(1, 2))
            prev_first = None
            for _ in range(max_pages):
                rows = read_rows(page)
                if not rows or rows[0]["sr"] == prev_first:
                    break
                prev_first = rows[0]["sr"]
                for r in rows:
                    items.append({**r, "tab": tab})
                nxt = page.locator("button, a").filter(has_text="Next")
                if not nxt.count() or not nxt.first.is_enabled():
                    break
                nxt.first.click()
                time.sleep(random.uniform(1, 2))
        b.close()
    return items


def to_listing(r: dict) -> list[Listing]:
    out = []
    parsed = parse_arai_code(r["code"])
    for href in r["links"] or [None]:
        if href and "/storage/" not in href:
            continue  # only public storage links
        out.append(Listing(item_id=f"{r['tab']}:{href or r['code']}", url=href, title=r["code"], listing_date=None,
                           category=r["tab"].lower(), raw={"sr": r["sr"], "code": r["code"], "title": r["title"],
                                                           "tab": r["tab"], "parsed": parsed},
                           file_name=(href or "").rsplit("/", 1)[-1] or None))
    return out


def crawl() -> dict:
    stats = RunStats()
    with connect() as conn:
        run_id = start_run(conn, "ARAI_AIS")
        notes: list[str] = []
        try:
            rows = scrape()
            seen: set[str] = set()
            with http.client() as c:
                for r in rows:
                    for lst in to_listing(r):
                        seen.add(lst.item_id)
                        record_listing(conn, c, "ARAI_AIS", run_id, lst, stats)
            if rows:
                stats.gone = mark_gone(conn, "ARAI_AIS", seen)
            status = "ok" if rows and not stats.errors else ("partial" if rows else "failed")
            if not rows:
                notes.append("no rows rendered")
        except Exception as e:  # noqa: BLE001
            status = "failed"
            notes.append(f"{type(e).__name__}: {e}"[:500])
        finish_run(conn, "ARAI_AIS", run_id, status, stats, "\n".join(notes + stats.notes))
    return {"run_id": run_id, "status": status, **stats.as_dict()}
