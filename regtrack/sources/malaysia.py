"""Malaysia: JPJ (Road Transport Department) and DOE (Department of Environment) official pages, plus the documents
they link (CTA guideline and application form PDFs, DOE VTA form). Public WordPress pages, no captcha, no login.

Each page is stored as a write-once .html original. Its listing id is the URL plus a hash of the page's main
content (the visitor counters and "Updated Date" stamps around it change on every request), so an unchanged page is
a known listing and writes nothing, while an edited page becomes a new document version. Linked files are listed
by their URL, like every other source.
"""

from __future__ import annotations

import base64
import hashlib
import html as htmllib
import json
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
    # the legal texts (migration 0019): each page shows its act / regulation PDF in a viewer widget
    "MY_JPJ_ACTS": ["https://www.jpj.gov.my/akta-333/", "https://www.jpj.gov.my/akta-334-2/"],
    "MY_DOE_REGS": [
        "https://www.doe.gov.my/en/environmental-quality-control-of-emissions-from-petrol-engines-regulations-1996-p-u-a-543-96/",
        "https://www.doe.gov.my/en/environmental-quality-control-of-emissions-from-diesel-engines-regulations-1996-p-u-a-429-96/",
        "https://www.doe.gov.my/en/environmental-quality-control-emissions-from-diesel-engines-amendment-regulations-2000-p-u-a-488-2000/",
        "https://www.doe.gov.my/en/environmental-quality-control-of-emissions-from-motorcycles-regulations-2003-p-u-a-464-2003/",
    ],
}
DOC_LINK = re.compile(r"""href=["']([^"']+\.(?:pdf|docx?|xlsx?))["'][^>]*>(.*?)</a>""", re.I | re.S)
TITLE = re.compile(r"<title>(.*?)</title>", re.I | re.S)
# the page's own content ends where the shared footer begins
FOOTER = re.compile(r"Contact Information|Contact Us|Hubungi Kami", re.I)
# PDF viewer widgets: their settings, in the page itself, give the PDF's public URL (no token, no session)
FB3D_DATA = re.compile(r"FB3D_CLIENT_DATA\.push\('([A-Za-z0-9+/=]+)'\)")  # JPJ: 3D FlipBook, base64 JSON
DEARFLIP = re.compile(r"window\.option_df_\d+ = (\{.*?\});", re.S)  # DOE: DearFlip options


def viewer_pdfs(html: str) -> list[str]:
    out = []
    for b in FB3D_DATA.findall(html):
        try:
            posts = json.loads(base64.b64decode(b)).get("posts", {})
        except ValueError:
            continue
        out += [(v.get("data") or {}).get("guid") for v in posts.values() if v.get("type") == "pdf"]
    for o in DEARFLIP.findall(html):
        try:
            out.append(json.loads(o).get("source"))
        except ValueError:
            continue
    return [u for u in out if u and u.lower().endswith(".pdf")]


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
    body = text[max(start, 0) :]
    m = FOOTER.search(body)
    body = body[: m.start()] if m else body
    return re.sub(r"\d{1,3}(?:,\d{3})+|\b\d{5,}\b", "", body)  # stray counters inside the body


def page_listing(code: str, url: str, raw: bytes) -> tuple[Listing, list[Listing]]:
    tm = TITLE.search(raw.decode("utf-8", errors="ignore"))
    title = re.sub(r"\s+", " ", htmllib.unescape(tm.group(1))).strip() if tm else None
    digest = hashlib.sha256(main_content(raw, title).encode("utf-8")).hexdigest()[:16]
    page = Listing(
        item_id=f"{url}#{digest}",
        url=url,
        title=title,
        listing_date=None,
        category="page",
        raw={"content_hash": digest},
        file_name=urlparse(url).path.strip("/").split("/")[-1] + ".html",
        content=raw,
    )
    host = urlparse(url).netloc
    seen: set[str] = set()
    files: list[Listing] = []
    html = raw.decode("utf-8", errors="ignore")
    links = DOC_LINK.findall(html) + [(u, title or "") for u in viewer_pdfs(html)]
    for href, label in links:
        link = urljoin(url, href)
        if urlparse(link).netloc != host or link in seen:
            continue
        seen.add(link)
        name = link.rsplit("/", 1)[-1]
        files.append(
            Listing(
                item_id=link,
                url=link,
                title=re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", label)).strip() or name,
                listing_date=None,
                category="attachment",
                raw={"page": url},
                file_name=name,
            )
        )
    return page, files


CRAWLS_BY_CODE = True  # regtrack.scheduler calls crawl(<source code>)
VIEWER_SOURCES = {"MY_JPJ_ACTS", "MY_DOE_REGS"}


def crawl(code: str | None = None) -> dict:
    """One source (a scheduler job), or all five pages."""
    with http.client() as c:
        if code:
            return crawl_source(c, code, PAGES[code])
        return {k: crawl_source(c, k, u) for k, u in PAGES.items()}


def crawl_source(c, code: str, urls: str | list[str]) -> dict:
    stats = RunStats()
    with connect() as conn:
        run_id = start_run(conn, code)
        notes: list[str] = []
        status = "failed"
        try:
            seen = set()
            for url in [urls] if isinstance(urls, str) else urls:
                r = http.get(c, url)
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code} for {url}")
                page, files = page_listing(code, url, r.content)
                # a legal-text page is only a viewer around its PDF: the PDF is the document
                for lst in files if code in VIEWER_SOURCES else [page, *files]:
                    seen.add(lst.item_id)
                    record_listing(conn, c, code, run_id, lst, stats)
            # an older version of the page is no longer published once its content hash changed
            stats.gone = mark_gone(conn, code, seen)
            status = "ok" if not stats.errors else "partial"
        except Exception as e:  # noqa: BLE001
            notes.append(f"{type(e).__name__}: {e}"[:500])
        finish_run(conn, code, run_id, status, stats, "\n".join(notes + stats.notes))
    return {"run_id": run_id, "status": status, **stats.as_dict()}
