"""Identity from document content (never from the listing title).

Notifications: G.S.R./S.O. number + date + year from the English operative heading.
AIS: code / Part / Rev from the cover. TAP: doc no + issue. Forms: form number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from regtrack.pipeline import patterns as P


@dataclass
class NotificationId:
    series: str  # GSR | SO
    number: str  # '659'
    extraordinary: bool
    date: date | None
    year: int | None
    pos: int = 0
    heading: bool = False  # found as an operative heading ("G.S.R. 659(E).—In exercise")
    hindi: bool = False

    @property
    def canonical_id(self) -> str:
        return P.notification_canonical(self.series, self.number, self.year, self.extraordinary)

    @property
    def number_label(self) -> str:
        return f"{int(self.number)}{'(E)' if self.extraordinary else ''}"

    @property
    def series_label(self) -> str:
        return "G.S.R." if self.series == "GSR" else "S.O."


@dataclass
class Identity:
    kind: str  # notification | ais | tap | form | none
    canonical_id: str | None = None
    series: str | None = None
    number: str | None = None
    year: int | None = None
    part: str | None = None
    revision: int | None = None
    doc_date: date | None = None
    doc_date_precision: str | None = None
    family_key: str | None = None
    others: list[str] = field(default_factory=list)
    ref_numbers: list[str] = field(default_factory=list)  # every G.S.R./S.O. number cited, year or not
    evidence: str | None = None


# ------------------------------------------------------------------ notifications
REF_BEFORE = re.compile(r"(vide|number|No\.?|dated|notification|in|of)\s*$", re.I)  # a citation, not a heading
_INTRO = re.compile(r"(NOTIFICATION|ORDER|CORRIGENDUM|ADDENDUM|New\s+Delhi)", re.I)


def _date_before(text: str, pos: int, window: int = 600) -> date | None:
    """The notification date: 'New Delhi, the 25th August, 2022' just before the heading."""
    seg = text[max(0, pos - window) : pos]
    ms = list(P.NEW_DELHI_DATE.finditer(seg))
    for m in reversed(ms):
        d = P.parse_date(m.group(1))
        if d:
            return d
    ds = P.all_dates(seg[-250:])
    return ds[-1] if ds else None


def _year_before(text: str, pos: int, window: int = 300) -> int | None:
    """Fallback when the day is garbled: 'New Delhi, the ~th March, 2014' -> 2014."""
    seg = text[max(0, pos - window) : pos]
    # skip years that belong to a title ("Central Motor Vehicles Rules, 1989", "Motor Vehicles Act, 1988 (59 of 1988)")
    ys = [
        m.group(1)
        for m in re.finditer(r"(?<!\d)(19[5-9]\d|20[0-4]\d)(?!\d)", seg)
        if not re.search(r"(?:Rules|Act|of)\s*,?\s*$", seg[max(0, m.start() - 12) : m.start()], re.I)
    ]
    return int(ys[-1]) if ys else None


def _masthead_year(text: str) -> int | None:
    """Year from the Gazette masthead 'NEW DELHI, MONDAY, DECEMBER 19, 2022'."""
    m = re.search(r"NEW\s+DELHI,\s*[A-Z]+DAY,\s*(" + P.MONTH_RE + r")\s+\d{1,2},\s*(\d{4})", text[:6000], re.I)
    if m:
        return int(m.group(2))
    m = re.search(r"CG\s*[\-–]\s*[A-Z]{2}\s*[\-–]\s*E\s*[\-–]\s*\d{4}(\d{4})", text[:6000])
    return int(m.group(1)) if m else None


def notification_ids(text: str) -> list[NotificationId]:
    """All G.S.R./S.O. ids in English text, operative headings first."""
    found: list[NotificationId] = []
    seen: set[tuple[str, str, bool]] = set()
    masthead_year = _masthead_year(text)
    for heading_pass in (True, False):
        rx = P.NUM_ID_HEAD if heading_pass else P.NUM_ID
        for m in rx.finditer(text):
            series = P.series_code(m.group(1))
            num = str(int(m.group(2)))
            ext = bool(m.group(3))
            key = (series, num, ext)
            if key in seen:
                continue
            # heading must look operative: followed by 'In exercise', 'Whereas', 'The Central Government' ... (the words
            # in any case: OCR gives 'whereas the draft', 'the draft rules'); otherwise any capitalised word
            if heading_pass:
                tail = text[m.end() : m.end() + 80]
                if not re.match(
                    r"\s*((?i:In\s+exercise|exercise|Whereas|The\s+Central|The\s+draft|In\s+the|"
                    r"In\s+pursuance|Notwithstanding|The\s*following|In\s+supersession|Corrigendum)|"
                    r"[A-Z])",
                    tail,
                ):
                    continue
            if heading_pass:
                d = _date_before(text, m.start())
                year = d.year if d else (_year_before(text, m.start()) or masthead_year)
            else:  # a reference: 'S.O. 1365(E), dated the 13th December, 2004'
                after = re.match(r"[\s,]*(?:dated|dt\.?|of)\s*(?:the\s*)?(.{0,40})", text[m.end() : m.end() + 60], re.I)
                d = P.parse_date(after.group(1)) if after else None
                ym = re.match(r"\s*(?:,|of|dated)?\s*(\d{4})", text[m.end() : m.end() + 12])
                year = d.year if d else (int(ym.group(1)) if ym and 1950 < int(ym.group(1)) < 2100 else None)
            found.append(NotificationId(series, num, ext, d, year, pos=m.start(), heading=heading_pass))
            seen.add(key)
    return found


def notification_identity(english: str, hindi_text: str | None = None) -> Identity | None:
    ids = notification_ids(english)
    heads = [i for i in ids if i.heading and i.year]
    primary = heads[0] if heads else None
    if primary is None:
        # first id within the first 3000 chars with a resolvable date
        early = [
            i for i in ids if i.pos < 3000 and i.year and not REF_BEFORE.search(english[max(0, i.pos - 40) : i.pos])
        ]
        primary = early[0] if early else None
    if primary is None and hindi_text:
        m = P.HI_ID.search(hindi_text)
        if m:
            yr = _masthead_year(hindi_text)
            if yr:
                primary = NotificationId(
                    "GSR" if m.group(1).startswith("सा") else "SO", str(int(m.group(2))), True, None, yr, hindi=True
                )
    if primary is None:
        return None
    others = [i.canonical_id for i in ids if i is not primary and i.year]
    return Identity(
        kind="notification",
        canonical_id=primary.canonical_id,
        series=primary.series_label,
        number=primary.number_label,
        year=primary.year,
        doc_date=primary.date,
        doc_date_precision="day" if primary.date else "year",
        others=list(dict.fromkeys(others))[:20],
        ref_numbers=sorted({f"{i.series}-{i.number}" for i in ids if i is not primary}),
        evidence=english[max(0, primary.pos - 120) : primary.pos + 120].strip(),
    )


def title_notification_ids(title: str) -> list[tuple[str, str]]:
    """IDs claimed by a listing title (series, number) - used only for the mismatch check."""
    out = [
        (P.series_code(m.group(1)), str(int(m.group(2))))
        for m in P.NUM_ID.finditer(title or "")
        if not re.match(r"\s*(cc|kw|km)", title[m.end() : m.end() + 4] or "", re.I)
    ]
    # ranges: "S.O. 425(E) to 426(E)"
    for m in re.finditer(
        P.SERIES_RE + r"\s*(\d{1,5})\s*\(?E?\)?\s*(?:to|-|–|&|and)\s*(\d{1,5})\s*\(\s*E\s*\)", title or "", re.I
    ):
        out.append((P.series_code(m.group(1)), str(int(m.group(3)))))
    return out


# ------------------------------------------------------------------ AIS
def cover_month(text: str, today: date | None = None) -> tuple[int, int] | None:
    """The cover's month/year: the first one that is not in the future (later dates on a cover page are
    implementation dates such as 'w.e.f. October 2027', not the publication month)."""
    today = today or date.today()
    for m in P.DATE_MONTH_YEAR.finditer(text):
        mo = P.month_num(m.group(1))
        y = int(m.group(2))
        if mo and 1950 <= y and (y, mo) <= (today.year, today.month):
            return y, mo
    for m in re.finditer(r"\b(\d{1,2})\s*/\s*(\d{4})\b", text):
        mo, y = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 1950 <= y and (y, mo) <= (today.year, today.month):
            return y, mo
    return None


def ais_identity(cover: str) -> Identity | None:
    """AIS code/Part/Rev from the cover (first ~2 pages)."""
    head = cover[:5000]
    # prefer the code printed right after 'AUTOMOTIVE INDUSTRY STANDARD' or at the top
    m = P.AIS_COVER.search(head)
    cands = list(P.AIS_CODE.finditer(head))
    if not cands:
        return None
    best = cands[0]
    if m:
        near = [c for c in cands if abs(c.start() - m.start()) < 600]
        if near:
            best = near[0]
    p = P.parse_ais_code(best.group(0))
    # Rev/Part are sometimes printed on the following line: look a little further
    window = head[best.start() : best.end() + 60]
    if p["rev"] is None:
        r = re.search(r"\(\s*Rev(?:ision)?\s*\.?\s*(\d{1,2})\s*\)", window, re.I)
        if r:
            p["rev"] = int(r.group(1))
    if p["part"] is None:
        r = re.search(r"\(\s*Part\s*[\-:]?\s*([IVX]+|\d+)\s*\)", window, re.I)
        if r:
            p["part"] = P._part_num(r.group(1))
    cid = P.ais_canonical(p["code"], p["part"], p["rev"])
    ym = cover_month(head[best.end() : best.end() + 1500])
    return Identity(
        kind="ais",
        canonical_id=cid,
        number=f"{p['code']:03d}",
        part=str(p["part"]) if p["part"] else None,
        revision=p["rev"],
        year=ym[0] if ym else p.get("year"),
        family_key=P.ais_family(p["code"], p["part"]),
        doc_date=date(ym[0], ym[1], 1) if ym else None,
        doc_date_precision="month" if ym else None,
        evidence=best.group(0),
    )


# ------------------------------------------------------------------ ARAI listing code strings
# 'Amd. 1 to 4', 'Amds. 1 to 13', 'Amendments 1 to 9', 'Amendment No. 1' (not 'Corrigendum 1 to Amd. 5')
ARAI_AMD = re.compile(
    r"(?<!to )\bAm(?:en)?d(?:ment)?s?\.?\s*(?:No\.?\s*)?(\d{1,2})(?:\s*(?:to|-|–)\s*(\d{1,2}))?", re.I
)


def parse_arai_code(code: str) -> dict:
    """ARAI 'code' free text -> structured (ETL_SPEC 1.1). It is a listing CLAIM, used as a hint only."""
    s = code.strip()
    out: dict = {
        "raw": s,
        "kind": "standard",
        "code": None,
        "part": None,
        "rev": None,
        "year": None,
        "amendments": [],
        "corrigenda": [],
        "draft": False,
        "draft_stage": None,
        "table": None,
        "draft_amendment_no": None,
        "hosted_on": None,
        "comments_until": None,
    }
    if s.lower() == "list":
        out["kind"] = "list"
        return out
    if re.search(r"interpretation", s, re.I):
        out["kind"] = "interpretation"
    if re.match(r"\s*(Revised\s+)?Draft", s, re.I):
        out["draft"] = True
        out["kind"] = "draft"
        da = re.search(r"Draft\s+Amd\.?\s*(\d+)", s, re.I)
        if da:
            out["draft_amendment_no"] = int(da.group(1))
            out["kind"] = "draft_amendment"
        st = re.search(r"/\s*(D\d{1,2}|DF|F)\b", s)
        out["draft_stage"] = st.group(1) if st else ("revised" if s.lower().startswith("revised") else None)
    p = P.parse_ais_code(s)
    if p:
        out.update(code=p["code"], part=p["part"], rev=p["rev"], year=p["year"])
    t = re.search(r"Table\s*[\-:]?\s*([0-9]+[A-Z]?(?:\s*\([a-z]\))?)", s, re.I)
    if t:
        out["table"] = t.group(1).replace(" ", "")
        out["kind"] = "table"
    for m in ARAI_AMD.finditer(s):
        if out["draft_amendment_no"] and re.match(r"Draft", s[max(0, m.start() - 6) : m.start()].strip() or "x"):
            continue
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        out["amendments"].extend(range(a, b + 1))
    # 'Amd. No.1 & Amd. No.2' handled above; 'Amd. 1, 2 & 3'
    extra = re.search(r"Amd\.?\s*(?:No\.?\s*)?\d+((?:\s*[,&]\s*(?:Amd\.?\s*(?:No\.?\s*)?)?\d+)+)", s, re.I)
    if extra:
        out["amendments"].extend(int(x) for x in re.findall(r"\d+", extra.group(1)))
    out["amendments"] = sorted(set(out["amendments"]))
    for m in re.finditer(r"Corrigendum\s*(?:No\.?\s*)?(\d+)?", s, re.I):
        out["corrigenda"].append(int(m.group(1)) if m.group(1) else 1)
    h = re.search(r"Date of hosting on website:\s*([^)]+)\)", s, re.I)
    if h:
        d = P.parse_date(h.group(1))
        out["hosted_on"] = d.isoformat() if d else None
    c = re.search(r"Last date for comments:?\s*([^)]+)\)?", s, re.I)
    if c:
        d = P.parse_date(c.group(1))
        out["comments_until"] = d.isoformat() if d else None
    return out


# ------------------------------------------------------------------ TAP / forms
def tap_identity(text: str) -> Identity | None:
    if not P.TAP_DOC.search(text[:8000]):
        return None
    m = P.TAP_ISSUE.search(text[:8000])
    issue = int(m.group(1)) if m else 4
    return Identity(
        kind="tap",
        canonical_id=f"TAP-115/116(Issue.{issue})",
        number="115/116",
        family_key="TAP-115/116",
        evidence=m.group(0) if m else None,
    )


def form_identity(text: str, file_name: str = "") -> Identity | None:
    m = P.FORM_NO.search(text[:1500])
    if not m:
        m = re.search(r"form[\s_\-]*(\d{1,2}\s?[A-Z]{0,2})\b", file_name, re.I)
    if not m:
        return None
    no = m.group(1).replace(" ", "").upper()
    return Identity(kind="form", canonical_id=f"FORM-{no}", number=no, family_key=f"FORM-{no}", evidence=m.group(0))
