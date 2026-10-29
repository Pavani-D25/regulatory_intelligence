"""Split consolidated files into documents (Phase 5).

AIS files: base standard (cover) + embedded amendments (3 header formats) + corrigenda -> page segments.
Pure functions here; pipeline/stages.py writes the documents.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from regtrack.pipeline import patterns as P
from regtrack.pipeline.text import PageText

HEADER_ZONE = 700  # an amendment header must start near the top of a page
STATUS_PAGE = re.compile(
    r"status\s+chart|amendment\s+record|list\s+of\s+amendments|contents|"
    r"composition\s+of|record\s+of\s+amendments",
    re.I,
)


@dataclass
class Segment:
    kind: str  # base | amendment | corrigendum
    page_from: int
    page_to: int
    number: int | None = None
    issued: str | None = None
    precision: str | None = None
    header_format: str | None = None
    target_raw: str | None = None  # 'AIS-038 (Rev.2)' as printed in the header

    @property
    def label(self) -> str:
        if self.kind == "base":
            return "Base standard"
        return f"{'Amendment' if self.kind == 'amendment' else 'Corrigendum'} {self.number or '?'} segment"


def _header_on_page(p: PageText) -> Segment | None:
    zone = p.text[:HEADER_ZONE]
    # a status chart / contents page starts with that heading; the same words inside an amendment's own
    # instructions ("1. Page II, Contents, Annexes ...", "Replace existing Amendment Record") come after its header
    status = STATUS_PAGE.search(zone[:200])

    def before_status(m) -> bool:
        return status is None or m.start() < status.start()

    m = P.AMD_HEADER.search(zone)
    if m and m.start() < HEADER_ZONE - 100 and before_status(m):
        iso, prec, fmt = P.header_date(m.group("mid"))
        return Segment("amendment", p.page, p.page, int(m.group(1)), iso, prec, fmt, m.group("code").strip())
    m = P.CORR_HEADER.search(zone)
    if m and m.start() < HEADER_ZONE - 100 and before_status(m):
        iso, prec, fmt = P.header_date(m.group("mid"))
        return Segment(
            "corrigendum",
            p.page,
            p.page,
            int(m.group(1)) if m.group(1) else None,
            iso,
            prec,
            fmt,
            m.group("code").strip(),
        )
    return None


def _is_cover(p: PageText) -> bool:
    return bool(P.AIS_COVER.search(p.text[:1500]))


def split_ais(pages: list[PageText]) -> list[Segment]:
    """Segments in page order. A file with no headers yields one base segment."""
    if not pages:
        return []
    n = pages[-1].page
    starts: list[Segment] = []
    seen: set[tuple[str, int | None]] = set()
    for p in pages:
        h = _header_on_page(p)
        if h and (h.kind, h.number) not in seen:
            # the same header repeated on following pages (running header) continues the segment
            starts.append(h)
            seen.add((h.kind, h.number))
        elif (
            _is_cover(p)
            and p.page > 1
            and starts
            and starts[-1].kind != "base"
            and not any(s.kind == "base" for s in starts)
        ):
            starts.append(Segment("base", p.page, p.page))
    if not any(s.kind == "base" for s in starts):
        first = starts[0].page_from if starts else n + 1
        if first > 1:
            starts.insert(0, Segment("base", 1, first - 1))
    starts.sort(key=lambda s: s.page_from)
    for i, s in enumerate(starts):
        s.page_to = (starts[i + 1].page_from - 1) if i + 1 < len(starts) else n
        s.page_to = max(s.page_to, s.page_from)
    return starts


def amendment_gaps(numbers: list[int]) -> list[int]:
    """Missing amendment numbers between 1 and max (e.g. [1,2,4] -> [3])."""
    if not numbers:
        return []
    have = set(numbers)
    return [i for i in range(1, max(have) + 1) if i not in have]


# ------------------------------------------------------------------ TAP parts
TAP_PART = re.compile(r"Part[\s_\-]*0*(\d{1,2})", re.I)
TAP_CHAPTER = re.compile(r"Chap(?:ter)?[\s_\-]*0*(\d{1,2})", re.I)


def tap_part_label(file_name: str, text: str = "") -> str:
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", file_name)
    p = TAP_PART.search(stem) or TAP_PART.search(text[:400])
    c = TAP_CHAPTER.search(stem)
    if p:
        return f"Part-{int(p.group(1)):02d}" + (f"/Chapter-{int(c.group(1)):02d}" if c else "")
    return stem[:80]


# ------------------------------------------------------------------ AIS-007 DOCX tables
def ais_table_ref(names: list[str], listing_codes: list[str], text: str) -> str | None:
    for s in listing_codes + names + [text[:300]]:
        m = re.search(r"Table[\s_\-:]*([0-9]{1,3}\s?[A-Z]?(?:\s*\(\s*[a-z]\s*\))?)", s or "", re.I)
        if m:
            return re.sub(r"\s+", "", m.group(1)).upper()
    return None
