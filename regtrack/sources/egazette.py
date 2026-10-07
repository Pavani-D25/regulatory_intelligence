"""e-Gazette (egazette.gov.in) - public 'Search by Ministry' flow rendered with Playwright.

ASP.NET WebForms with the session id in the URL; pages only work through a browser flow (ETL_SPEC 1.5).
We select Ministry of Road Transport and Highways + month/year, read the result grid (gazette id, subject,
part/section, issue and publish dates) and download the PDF of rows that look like motor-vehicle regulation
(highway notifications under the NH Act are skipped). If a page ever shows a captcha or a login form the crawl
stops and reports it - nothing is solved or bypassed.
"""

from __future__ import annotations

import logging
import random
import re
import time
from datetime import date, datetime

from regtrack.config import get_settings
from regtrack.db import connect
from regtrack.sources import http
from regtrack.sources.common import Listing, RunStats, finish_run, record_listing, start_run

log = logging.getLogger(__name__)
HOME = "https://egazette.gov.in/"
MINISTRIES = ["Ministry of Road Transport and Highways"]
SKIP = re.compile(r"NH\s+Act|National\s+Highways?|Section\s+3A|Section\s+3D|Section\s+3G|land\s+acquisition|"
                  r"toll|fee\s+plaza|bypass|entrustment|user\s+fee|P\s*and\s*M\s+File|Arbitrat", re.I)
KEEP = re.compile(r"Motor\s+Vehicles?|CMVR|G\.?S\.?R|vehicle|driving|registration|permit|emission|AIS|helmet|"
                  r"e-?rickshaw|scrapp|fitness|HSRP|FASTag|trailer|tyre", re.I)


class CaptchaRequired(RuntimeError):
    pass


def _pause() -> None:
    time.sleep(random.uniform(1, 2))


def _check_gate(page) -> None:
    if page.locator("img[src*=aptcha], img[id*=aptcha], input[name*=aptcha], [id*=Captcha]").count():
        raise CaptchaRequired(f"captcha on {page.url}")
    if page.locator("input[type=password]").count():
        raise CaptchaRequired(f"login form on {page.url}")


def _d(s: str) -> date | None:
    for fmt in ("%d-%b-%Y", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _cell(row, name: str) -> str:
    loc = row.locator(f"[id^='gvGazetteList_{name}_']")
    return loc.first.inner_text().strip() if loc.count() else ""


def pdf_url(ugid: str) -> str | None:
    """The viewer page embeds ../WriteReadData/<year>/<number>.pdf; 'CG-DL-E-06102026-276841' -> 2026/276841.pdf."""
    m = re.search(r"(\d{2})(\d{2})(\d{4})\s*[\-–]\s*(\d{5,7})$", ugid)
    return f"https://egazette.gov.in/WriteReadData/{m.group(3)}/{m.group(4)}.pdf" if m else None


def months_back(n: int) -> list[tuple[int, int]]:
    t = date.today()
    out = []
    y, m = t.year, t.month
    for _ in range(n):
        out.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def scrape(months: int = 2, download: bool = True, max_pages: int = 30,
           ) -> tuple[list[Listing], list[str]]:
    from playwright.sync_api import sync_playwright

    listings: list[Listing] = []
    notes: list[str] = []
    with sync_playwright() as p:
        try:
            b = p.chromium.launch(channel="chrome", headless=True)
        except Exception:  # noqa: BLE001
            b = p.chromium.launch(headless=True)
        # ASP.NET WebForms only emits its postback scripts (paging, radio buttons) for browsers it recognises, so the
        # real browser UA is sent with our identifier appended: "... Chrome/x Safari/537.36 RegTrackIndia/0.1 (research)"
        probe = b.new_page()
        base_ua = probe.evaluate("navigator.userAgent").replace("HeadlessChrome", "Chrome")
        probe.close()
        ctx = b.new_context(user_agent=f"{base_ua} {get_settings().user_agent}", accept_downloads=True)
        page = ctx.new_page()
        for ministry in MINISTRIES:
            for (y, m) in months_back(months):
                page.goto(HOME, wait_until="networkidle", timeout=120000)
                _pause()
                _check_gate(page)
                page.get_by_text("Search Gazette", exact=True).first.click()
                page.wait_for_load_state("networkidle")
                _pause()
                page.locator("#btnMinistry").click()
                page.wait_for_load_state("networkidle")
                _pause()
                _check_gate(page)
                page.select_option("#ddlMinistry", label=ministry)
                _pause()
                page.select_option("#ddlmonth", index=m - 1)
                page.select_option("#ddlyear", label=str(y))
                page.locator("#ImgSubmitDetails").click()
                page.wait_for_load_state("networkidle")
                _pause()
                _check_gate(page)
                for pno in range(1, max_pages + 1):
                    rows = page.locator("#gvGazetteList tr:has([id^='gvGazetteList_lbl_UGID_'])")
                    for i in range(rows.count()):
                        r = rows.nth(i)
                        ugid = _cell(r, "lbl_UGID")
                        subject = _cell(r, "lbl_Subject")
                        meta = _cell(r, "lbl_metadata")
                        # skip definite highway items; generic subjects are downloaded and judged by content
                        if not ugid or SKIP.search(subject + " " + meta):
                            continue
                        raw = {"gazette_id": ugid, "subject": subject, "metadata": meta, "ministry": _cell(r, "lbl_Ministry"),
                               "department": _cell(r, "lbl_Department"), "part_section": _cell(r, "lbl_PartSection"),
                               "category": _cell(r, "lbl_Category"), "issue_date": _cell(r, "lbl_IssueDate"),
                               "publish_date": _cell(r, "lbl_PublishDate"), "size": _cell(r, "lbl_FileSize")}
                        listings.append(Listing(item_id=ugid, url=pdf_url(ugid) if download else None, title=subject,
                                                listing_date=_d(raw["issue_date"]),
                                                category=f"{ministry}|{raw['part_section']}", raw=raw,
                                                file_name=f"{ugid}.pdf"))
                    # ASP.NET pager: '__doPostBack(gvGazetteList, Page$N)'; pages 11+ sit behind the '...' link
                    nxt = page.locator(f"a[href*=\"'Page${pno + 1}'\"]")
                    if not nxt.count():
                        break
                    first = _cell(rows.nth(0), "lbl_UGID") if rows.count() else None
                    nxt.first.click()  # partial (UpdatePanel) postback: wait until the grid shows other rows
                    advanced = False
                    for _ in range(60):
                        time.sleep(1)
                        rows2 = page.locator("#gvGazetteList tr:has([id^='gvGazetteList_lbl_UGID_'])")
                        try:
                            if rows2.count() and _cell(rows2.nth(0), "lbl_UGID") != first:
                                advanced = True
                                break
                        except Exception:  # noqa: BLE001  grid is being replaced
                            continue
                    if not advanced:
                        notes.append(f"{y}-{m:02d} page {pno + 1}: pager did not advance")
                        break
                    _pause()
                    _check_gate(page)
        b.close()
    return listings, notes


def crawl(months: int = 2) -> dict:
    stats = RunStats()
    with connect() as conn:
        run_id = start_run(conn, "EGAZETTE")
        notes: list[str] = []
        try:
            listings, notes = scrape(months)
            with http.client() as c:  # PDFs are plain public files: polite GETs, known listings are not re-downloaded
                for lst in listings:
                    record_listing(conn, c, "EGAZETTE", run_id, lst, stats)
            status = "ok" if not stats.errors else "partial"
        except CaptchaRequired as e:
            status = "partial"
            notes.append(f"STOPPED: {e} - e-Gazette needs a human here; not automated")
        except Exception as e:  # noqa: BLE001
            status = "failed"
            notes.append(f"{type(e).__name__}: {e}"[:500])
        finish_run(conn, "EGAZETTE", run_id, status, stats, "\n".join(notes + stats.notes))
    return {"run_id": run_id, "status": status, **stats.as_dict()}
