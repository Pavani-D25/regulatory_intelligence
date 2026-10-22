"""Malaysia: JPJ (Road Transport Department) and DOE (Department of Environment) official pages, plus the documents
they link (CTA guideline and application form PDFs, DOE VTA form). Public WordPress pages, no captcha, no login.

Each page is stored as a write-once .html original. Its listing id is the URL plus a hash of the page's main
content (the visitor counters and "Updated Date" stamps around it change on every request), so an unchanged page is
a known listing and writes nothing, while an edited page becomes a new document version. Linked files are listed
by their URL, like every other source.
"""

from __future__ import annotations

import hashlib
import html as htmllib
import logging
import re
from urllib.parse import urljoin, urlparse

from regtrack.db import connect
from regtrack.sources import http
from regtrack.sources.common import Listing, RunStats, finish_run, mark_gone, record_listing, start_run

log = logging.getLogger(__name__)

PAGES = {
    "MY_JPJ_VTA": "https://www.jpj.gov.my/en/vehicle-type-approval-process-vta/",
    "MY_JPJ_CTA": "https://www.jpj.gov.my/en/component-type-approval-cta/",
    "MY_JPJ_AED": "https://www.jpj.gov.my/en/jpj-service-information/automotive-engineering-division/",
    "MY_DOE_EMISSION": "https://www.doe.gov.my/en/emission-control-from-motor-vehicles/",
    "MY_DOE_VTA_GUIDE": "https://www.doe.gov.my/en/motor-vehicle-type-approval-guidelines-for-gas-and-noise-emissions/",
}
DOC_LINK = re.compile(r"""href=["']([^"']+\.(?:pdf|docx?|xlsx?))["'][^>]*>(.*?)</a>""", re.I | re.S)
TITLE = re.compile(r"<title>(.*?)</title>", re.I | re.S)
# the page's own content ends where the shared footer begins
FOOTER = re.compile(r"Contact Information|Contact Us|Hubungi Kami", re.I)


def page_text(raw: bytes) -> str:
    t = raw.decode("utf-8", errors="ignore")
    t = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", t)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", htmllib.unescape(t)).strip()


def main_content(raw: bytes, title: str | None) -> str:
    """The page body between its title and the footer: what the hash of a page version is taken over."""
    text = page_text(raw)
    head = (title or "").split("|")[0].split(" - ")[0].strip()
    start = text.find(f"/ {head}") if head else -1  # breadcrumb "Home / <title>"
    if start < 0 and head:
        start = text.rfind(head, 0, len(text) // 2)
    body = text[max(start, 0):]
    m = FOOTER.search(body)
    body = body[:m.start()] if m else body
    return re.sub(r"\d{1,3}(?:,\d{3})+|\b\d{5,}\b", "", body)  # stray counters inside the body


def page_listing(code: str, url: str, raw: bytes) -> tuple[Listing, list[Listing]]:
    tm = TITLE.search(raw.decode("utf-8", errors="ignore"))
    title = re.sub(r"\s+", " ", htmllib.unescape(tm.group(1))).strip() if tm else None
    digest = hashlib.sha256(main_content(raw, title).encode("utf-8")).hexdigest()[:16]
    page = Listing(item_id=f"{url}#{digest}", url=url, title=title, listing_date=None, category="page",
                   raw={"content_hash": digest}, file_name=urlparse(url).path.strip("/").split("/")[-1] + ".html",
                   content=raw)
    host = urlparse(url).netloc
    seen: set[str] = set()
    files: list[Listing] = []
    for href, label in DOC_LINK.findall(raw.decode("utf-8", errors="ignore")):
        link = urljoin(url, href)
        if urlparse(link).netloc != host or link in seen:
            continue
        seen.add(link)
        name = link.rsplit("/", 1)[-1]
        files.append(Listing(item_id=link, url=link, title=re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", label)).strip() or name,
                             listing_date=None, category="attachment", raw={"page": url}, file_name=name))
    return page, files


CRAWLS_BY_CODE = True  # regtrack.scheduler calls crawl(<source code>)


def crawl(code: str | None = None) -> dict:
    """One source (a scheduler job), or all five pages."""
    with http.client() as c:
        if code:
            return crawl_source(c, code, PAGES[code])
        return {k: crawl_source(c, k, u) for k, u in PAGES.items()}


def crawl_source(c, code: str, url: str) -> dict:
    stats = RunStats()
    with connect() as conn:
        run_id = start_run(conn, code)
        notes: list[str] = []
        status = "failed"
        try:
            r = http.get(c, url)
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code} for {url}")
            page, files = page_listing(code, url, r.content)
            seen = set()
            for lst in [page, *files]:
                seen.add(lst.item_id)
                record_listing(conn, c, code, run_id, lst, stats)
            # an older version of the page is no longer published once its content hash changed
            stats.gone = mark_gone(conn, code, seen)
            status = "ok" if not stats.errors else "partial"
        except Exception as e:  # noqa: BLE001
            notes.append(f"{type(e).__name__}: {e}"[:500])
        finish_run(conn, code, run_id, status, stats, "\n".join(notes + stats.notes))
    return {"run_id": run_id, "status": status, **stats.as_dict()}
