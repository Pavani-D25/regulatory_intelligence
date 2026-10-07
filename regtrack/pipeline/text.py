"""Text stage: 'downloaded' -> 'text'.

PyMuPDF per page; DOCX via word/document.xml; DOC via a UTF-16 string scan; HTM/CSV as text.
Page texts are saved to TEXT_DIR/<sha>.jsonl (one JSON object per page).
Fills page_count, text_layer, scanned_pages (< 100 chars), language_mix (Devanagari share + Kruti Dev
legacy font), pdf_meta, and the English page range used by later stages.
"""

from __future__ import annotations

import html
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from regtrack.config import get_settings

SCAN_CHARS = 100
DEV = re.compile(r"[ऀ-ॿ]")
LAT = re.compile(r"[A-Za-z]")
ENG_WORD = re.compile(r"\b(the|of|and|shall|to|in|vehicles?|rules?|notification|motor|for|with|by|or|be)\b", re.I)
# Kruti Dev / legacy Hindi font extracted as Latin mojibake (discovery/analyze.py `hindi_legacy`, extended).
KRUTI = re.compile(r"(Hkkjr|vlk/kkj\.k|jkti=k|ea=ky;|vf/klwpuk|izkf/kdkj|ifjogu|jktekxZ|ea=kky;|vf/kfu;e|fu;e)")


@dataclass
class PageText:
    page: int
    text: str
    chars: int = 0
    dev: int = 0
    lat: int = 0
    eng_words: int = 0
    kruti: int = 0
    lang: str = "unknown"  # en | hi | hi_legacy | mixed | empty
    ocr: str | None = None

    def analyse(self) -> PageText:
        t = self.text
        self.chars = len(t.strip())
        self.dev = len(DEV.findall(t))
        self.lat = len(LAT.findall(t))
        self.eng_words = len(ENG_WORD.findall(t))
        self.kruti = len(KRUTI.findall(t))
        if self.chars < SCAN_CHARS and not self.ocr:
            self.lang = "empty"
        elif self.dev > self.lat:
            self.lang = "hi" if self.eng_words < 15 else "mixed"
        elif self.kruti >= 2 and self.eng_words < 4 * self.kruti:
            self.lang = "hi_legacy" if self.eng_words < 15 else "mixed"
        elif self.eng_words >= 5:
            self.lang = "en"
        else:
            self.lang = "unknown"
        return self

    @property
    def is_english(self) -> bool:
        return self.lang in ("en", "mixed")

    def to_json(self) -> dict:
        return {"page": self.page, "text": self.text, "chars": self.chars, "lang": self.lang, "ocr": self.ocr}


@dataclass
class TextResult:
    pages: list[PageText]
    page_count: int
    text_layer: bool
    scanned_pages: list[int]
    language_mix: dict
    pdf_meta: dict = field(default_factory=dict)
    english_pages: list[int] = field(default_factory=list)
    error: str | None = None

    @property
    def english_range(self) -> tuple[int | None, int | None]:
        if not self.english_pages:
            return None, None
        return self.english_pages[0], self.english_pages[-1]


# ------------------------------------------------------------------ readers
def read_pdf(path: Path) -> tuple[list[str], dict]:
    import pymupdf

    with pymupdf.open(path) as d:
        meta = {k: v for k, v in (d.metadata or {}).items()
                if v and k in ("title", "producer", "creator", "creationDate", "modDate", "author")}
        meta["encrypted"] = bool(d.is_encrypted)
        return [pg.get_text() for pg in d], meta


def read_docx(path: Path) -> list[str]:
    """Text of word/document.xml; tables keep one row per line, cells separated by ' | '."""
    with zipfile.ZipFile(path) as z:
        x = z.read("word/document.xml").decode("utf-8", "ignore")
    x = re.sub(r"<w:tab/>", "\t", x)
    x = re.sub(r"<w:br[^>]*w:type=\"page\"[^>]*/>", "\f", x)
    x = re.sub(r"<w:br[^>]*/>", "\n", x)
    x = re.sub(r"</w:tc>", " | ", x)
    x = re.sub(r"</w:p>|</w:tr>", "\n", x)
    x = html.unescape(re.sub(r"<[^>]+>", "", x))
    x = re.sub(r"[ \t]+\|\s*\n", "\n", x)
    pages = [p for p in x.split("\f")]
    return pages if any(p.strip() for p in pages) else [x]


def read_doc(path: Path) -> list[str]:
    """Legacy .doc: Word stores text as UTF-16LE (or cp1252) runs; collect the readable runs."""
    raw = path.read_bytes()
    runs = re.findall(rb"(?:[\x20-\x7e\r\n\t]\x00){8,}", raw)
    txt = "\n".join(r.decode("utf-16le", "ignore") for r in runs)
    if len(txt) < 200:
        txt = "\n".join(r.decode("cp1252", "ignore") for r in re.findall(rb"[\x20-\x7e\r\n\t]{12,}", raw))
    return [txt.replace("\r", "\n")]


def read_xlsx(path: Path) -> list[str]:
    """Spreadsheet text: shared strings + inline cell values, one 'page' per sheet."""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        shared = []
        if "xl/sharedStrings.xml" in names:
            x = z.read("xl/sharedStrings.xml").decode("utf-8", "ignore")
            shared = [html.unescape(re.sub(r"<[^>]+>", "", si)) for si in re.findall(r"<si>(.*?)</si>", x, re.S)]
        pages = []
        for n in sorted(x for x in names if re.match(r"xl/worksheets/sheet\d+\.xml$", x)):
            x = z.read(n).decode("utf-8", "ignore")
            rows = []
            for row in re.findall(r"<row[^>]*>(.*?)</row>", x, re.S):
                cells = []
                for attrs, v in re.findall(r"<c([^>]*)>(?:.*?<v>(.*?)</v>)?", row, re.S):
                    if 't="s"' in attrs and v.isdigit() and int(v) < len(shared):
                        cells.append(shared[int(v)])
                    elif v:
                        cells.append(html.unescape(v))
                if cells:
                    rows.append(" | ".join(cells))
            pages.append("\n".join(rows))
    return pages or ["\n".join(shared)]


def read_html(path: Path) -> list[str]:
    t = path.read_text(encoding="utf-8", errors="ignore")
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", t)
    t = re.sub(r"(?i)<br\s*/?>|</p>|</tr>|</h\d>|</li>", "\n", t)
    t = re.sub(r"(?i)</t[dh]>", " | ", t)
    return [html.unescape(re.sub(r"<[^>]+>", "", t))]


def read_plain(path: Path) -> list[str]:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return [raw.decode(enc)]
        except UnicodeDecodeError:
            continue
    return [raw.decode("utf-8", "ignore")]


def extract(path: Path, ext: str) -> TextResult:
    ext = ext.lower()
    meta: dict = {}
    err = None
    try:
        if ext == "pdf":
            texts, meta = read_pdf(path)
        elif ext == "docx":
            texts = read_docx(path)
        elif ext == "doc":
            texts = read_doc(path)
        elif ext in ("xlsx", "xlsm"):
            texts = read_xlsx(path)
        elif ext in ("htm", "html"):
            texts = read_html(path)
        elif ext in ("csv", "txt", "md", "json"):
            texts = read_plain(path)
        else:
            texts, err = [], f"unsupported extension {ext}"
    except Exception as e:  # noqa: BLE001  corrupt files must not stop the run
        texts, err = [], f"{type(e).__name__}: {str(e)[:200]}"
    return build_result(texts, meta, is_paged=(ext == "pdf"), error=err)


def build_result(texts: list[str], meta: dict, is_paged: bool, error: str | None = None) -> TextResult:
    pages = [PageText(i + 1, t.replace("\x00", "")).analyse() for i, t in enumerate(texts)]
    n = len(pages)
    total = sum(p.chars for p in pages)
    scanned = [p.page for p in pages if p.chars < SCAN_CHARS] if is_paged else []
    # a file "has a text layer" when it averages >= 100 chars/page (the profile's definition of a scan)
    text_layer = (total / max(n, 1) >= SCAN_CHARS) if is_paged else total > 0
    eng_pages = [p.page for p in pages if p.is_english]
    return TextResult(pages=pages, page_count=n, text_layer=text_layer, scanned_pages=scanned,
                      language_mix=language_mix(pages), pdf_meta=meta, english_pages=eng_pages, error=error)


def language_mix(pages: list[PageText]) -> dict:
    """Script shares + Kruti Dev detection. A file uses the legacy font if any page carries a Kruti Dev
    fingerprint (often only the running header 'Hkkjr dk jkti=k'), as in the corpus profile."""
    letters_dev = sum(p.dev for p in pages)
    letters_lat = sum(p.lat for p in pages)
    denom = max(letters_dev + letters_lat, 1)
    kruti_pages = [p.page for p in pages if p.kruti >= 1]
    eng = [p.page for p in pages if p.is_english]
    return {
        "en": round(letters_lat / denom, 3),
        "hi": round(letters_dev / denom, 3),
        "hi_legacy_font": bool(kruti_pages),
        "hi_legacy_pages": sum(1 for p in pages if p.lang == "hi_legacy"),
        "hi_pages": sum(1 for p in pages if p.lang == "hi"),
        "en_pages": len(eng),
        "english_range": [eng[0], eng[-1]] if eng else None,
    }


GARBLE_CHARS = re.compile(r"[~�|\\{}<>@#^`]")


def garbled_pages(pages: list[PageText]) -> list[int]:
    """Pages with a text layer that is OCR garbage (old scans with a bad embedded OCR layer).
    These are re-OCR'd like scanned pages. Hindi pages are excluded (their text is not English)."""
    out = []
    for p in pages:
        if p.chars < SCAN_CHARS or p.lang in ("hi", "hi_legacy") or p.dev > 50 or p.kruti:
            continue
        toks = p.text.split()
        if len(toks) < 20:
            continue
        junk = sum(1 for t in toks if GARBLE_CHARS.search(t) or (len(t) > 25 and not t.startswith("http")))
        clean = sum(1 for t in toks if t.isalpha() and t.islower() and len(t) > 2)
        if junk / len(toks) > 0.15 and clean / len(toks) < 0.35:
            out.append(p.page)
    return out


# ------------------------------------------------------------------ page store
def text_path(sha: str) -> Path:
    return get_settings().text_dir / sha[:2] / f"{sha}.jsonl"


def save_pages(sha: str, pages: list[PageText]) -> Path:
    p = text_path(sha)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for pg in pages:
            f.write(json.dumps(pg.to_json(), ensure_ascii=False) + "\n")
    tmp.replace(p)
    return p


def load_pages(sha: str) -> list[PageText]:
    p = text_path(sha)
    if not p.exists():
        return []
    out = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            out.append(PageText(d["page"], d["text"], ocr=d.get("ocr")).analyse())
    return out


def english_text(pages: list[PageText], page_from: int | None = None, page_to: int | None = None,
                 max_chars: int | None = None) -> str:
    """English pages (in order) inside an optional page range, with page markers."""
    sel = [p for p in pages if (page_from is None or p.page >= page_from) and (page_to is None or p.page <= page_to)]
    eng = [p for p in sel if p.is_english] or [p for p in sel if p.lang not in ("hi", "hi_legacy")]
    out = "".join(f"\n<<<PAGE {p.page}>>>\n{p.text}" for p in eng)
    return out[:max_chars] if max_chars else out


def full_text(pages: list[PageText], page_from: int | None = None, page_to: int | None = None) -> str:
    return "".join(f"\n<<<PAGE {p.page}>>>\n{p.text}" for p in pages
                   if (page_from is None or p.page >= page_from) and (page_to is None or p.page <= page_to))


# ------------------------------------------------------------------ cache (extraction can run before the DB is up)
def meta_path(sha: str) -> Path:
    return get_settings().text_dir / sha[:2] / f"{sha}.meta.json"


def result_meta(r: TextResult) -> dict:
    return {"page_count": r.page_count, "text_layer": r.text_layer, "scanned_pages": r.scanned_pages,
            "language_mix": r.language_mix, "pdf_meta": r.pdf_meta, "english_pages": r.english_pages,
            "error": r.error, "version": TEXT_VERSION}


TEXT_VERSION = 1


def extract_cached(sha: str, path: Path, ext: str, force: bool = False) -> dict:
    """Extract once per sha; later calls read TEXT_DIR/<sha>.meta.json."""
    mp = meta_path(sha)
    if not force and mp.exists():
        try:
            m = json.loads(mp.read_text(encoding="utf-8"))
            if m.get("version") == TEXT_VERSION and text_path(sha).exists():
                return m
        except (OSError, ValueError):
            pass
    r = extract(path, ext)
    save_pages(sha, r.pages)
    m = result_meta(r)
    mp.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    return m


def update_meta(sha: str, **changes) -> dict:
    mp = meta_path(sha)
    m = json.loads(mp.read_text(encoding="utf-8"))
    m.update(changes)
    mp.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    return m
