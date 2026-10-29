"""Deterministic reading of Malaysia's JPJ / DOE pages and the files they link (regtrack/sources/malaysia.py).

Malaysia uses UNECE category meanings (L1 moped, L3 motorcycle, M1, N1), unlike India's own L2, so the category
words are read here rather than with India's synonym lists. The CTA page's component table and the DOE emission
page's type-approval stages are the mandates of this source (one rule per component / per stage).
"""

from __future__ import annotations

import re
from datetime import date, datetime

MY_SOURCES = {
    "MY_JPJ_VTA": "JPJ",
    "MY_JPJ_CTA": "JPJ",
    "MY_JPJ_AED": "JPJ",
    "MY_DOE_EMISSION": "DOE",
    "MY_DOE_VTA_GUIDE": "DOE",
    "MY_JPJ_ACTS": "JPJ",
    "MY_DOE_REGS": "DOE",
    "MY_LOCAL": None,
}
ISSUER_TEXT = [
    ("JPJ", re.compile(r"JABATAN PENGANGKUTAN JALAN|Road Transport Department|\bJPJ\b", re.I)),
    ("DOE", re.compile(r"JABATAN ALAM SEKITAR|Department of Environment|KUALITI ALAM SEKELILING", re.I)),
]


def issuer_of(source: str, text: str) -> str:
    """JPJ / DOE: by source, or, for a hand-saved file (MY_LOCAL), by its own text; 'MY' when neither."""
    return MY_SOURCES.get(source) or next((k for k, rx in ISSUER_TEXT if rx.search(text[:5000])), "MY")


ISSUER = {"JPJ": "Road Transport Department (JPJ)", "DOE": "Department of Environment (DOE/JAS)"}
PAGE_TITLE = re.compile(r"^\s*(.+?)\s+-\s+(?:Portal Rasmi JPJ|Department of Environment)\s*$", re.M)
FORM = re.compile(r"\b(?:BORANG|FORM|APPLICATION[\s-]FORM)\b", re.I)

UN_CODE = re.compile(r"(?<![A-Za-z])([LMN])\s?([1-7])(?![0-9])")
WORDS = [
    (re.compile(r"\bmotorcycles?\b|\bmotosikal\b", re.I), ("L3",)),
    (re.compile(r"\bmopeds?\b", re.I), ("L1",)),
    (re.compile(r"\bpassenger cars?\b|\bmotor cars?\b", re.I), ("M1",)),
    (re.compile(r"\b(?:light )?goods vehicles?\b|\bcommercial vehicles?\b", re.I), ("N1",)),
    (
        re.compile(
            r"\b(?:all |every |each )?new models? of (?:motor )?vehicles?\b|\bmotor vehicles?\b|\bkenderaan motor\b",
            re.I,
        ),
        ("ALL",),
    ),
]
MY_CATEGORIES = ("L1", "L3", "M1", "N1", "ALL")


def slug(s: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "-", s.upper()).strip("-")[:60]


def source_of(listings: list[dict]) -> str | None:
    return next((x["source"] for x in listings if x.get("source") in MY_SOURCES), None)


def page_title(text: str) -> str | None:
    m = PAGE_TITLE.search(text[:3000])
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else None


def is_form(names: list[str], text: str) -> bool:
    return bool(FORM.search(" ".join(names))) or bool(re.search(r"^\s*BORANG\b", text[:400], re.M))


def identity(source: str, ext: str, names: list[str], text: str) -> dict:
    """MY-<issuer>-<page title | file name>: a page is named by its own title, a file by its published file name."""
    issuer = issuer_of(source, text)
    base = page_title(text) if ext in ("html", "htm") else None
    if not base:
        stem = next((n for n in names if n), "").rsplit(".", 1)[0]
        base = stem or source
    return {"canonical_id": f"MY-{issuer}-{slug(base)}", "issuer": ISSUER.get(issuer, "Malaysia"), "title": base}


def categories_of(text: str) -> list[str]:
    cats: set[str] = {f"{a}{b}" for a, b in UN_CODE.findall(text)}
    for rx, codes in WORDS:
        if rx.search(text):
            cats.update(codes)
    return [c for c in MY_CATEGORIES if c in cats]


# ------------------------------------------------------------------ CTA component table (JPJ)
CTA_ROW = re.compile(r"^\s*(\d{1,2})\.\s*\|\s*([^|]+?)\s*\|\s*(.+)$", re.M)
CTA_END = re.compile(r"CTA Guidelines|Contact Information", re.I)
UN_REF = re.compile(r"\bR\s?(\d{1,3})\b")
MS_REF = re.compile(r"\bMS\s+(?:ISO\s+)?\d+(?::\d{4})?|\bMalaysia Standard \(MS\) \d+")
COMPONENT_CATEGORIES = [
    (re.compile(r"helmet", re.I), ["L1", "L3"]),
    (re.compile(r"tyre", re.I), ["M1", "N1"]),
    (re.compile(r"child|seat|belt|mirror|headlamp|glass", re.I), ["M1", "N1"]),
    (re.compile(r"brake|speed", re.I), ["ALL"]),
]


def cta_components(text: str) -> list[dict]:
    """[{no, component, refs: ['UNR-22', 'MS 1'], text}] from the CTA page's 'BIL. | COMPONENT | REGULATORY' table."""
    start = text.find("COMPONENT")
    if start < 0:
        return []
    body = text[start:]
    m = CTA_END.search(body)
    body = body[: m.start()] if m else body
    rows = list(CTA_ROW.finditer(body))
    out = []
    for i, r in enumerate(rows):
        seg = body[r.start(3) : rows[i + 1].start() if i + 1 < len(rows) else len(body)]
        regs = [re.sub(r"\s+", " ", x).strip(" |") for x in seg.split("|")]
        regs = [x for x in regs if x]
        refs = [f"UNR-{int(n)}" for x in regs for n in UN_REF.findall(x[:6])]
        refs += [re.sub(r"\s+", " ", x) for x in MS_REF.findall(seg)]
        comp = re.sub(r"\s+", " ", r.group(2)).strip()
        cats = next((c for rx, c in COMPONENT_CATEGORIES if rx.search(comp)), ["ALL"])
        out.append(
            {
                "no": int(r.group(1)),
                "component": comp,
                "refs": list(dict.fromkeys(refs)),
                "regulations": regs,
                "vehicle_categories": cats,
            }
        )
    return out


# ------------------------------------------------------------------ DOE type-approval stages
STAGE = re.compile(
    r"TYPE APPROVAL TEST \((PETROL|DIESEL) VEHICLE\)(.{0,1500}?)(?=(?-i:TYPE APPROVAL TEST|DIESEL VEHICLES|Contact Us)|$)",
    re.S | re.I,
)  # the headings are upper case; "diesel vehicles" also occurs inside the text
ON_OR_AFTER = re.compile(r"on or after (\d{1,2} \w+ \d{4})", re.I)
SCHEDULE = re.compile(
    r"((?:First|Second|Third|Fourth|Fifth) Schedule,\s*Environmental Quality \(Control of Emissions from "
    r"(?:Petrol|Diesel) Engines\) Regulations,?\s*\d{4})",
    re.I,
)
SMOKE = re.compile(r"(\d{2})%\s*opacity smoke emission limit", re.I)


def _date(s: str) -> date | None:
    try:
        return datetime.strptime(s, "%d %B %Y").date()
    except ValueError:
        return None


def doe_stages(text: str) -> list[dict]:
    flat = re.sub(r"\s+", " ", text)
    out = []
    for m in STAGE.finditer(flat):
        fuel, seg = m.group(1).lower(), m.group(2)
        d = ON_OR_AFTER.search(seg)
        sch = SCHEDULE.search(seg)
        out.append(
            {
                "key": f"MY-DOE-TA-{fuel.upper()}",
                "fuel": fuel,
                "subject": f"Type-approval exhaust emission standard, new {fuel} vehicle models",
                "legal_basis": re.sub(r"\s+", " ", sch.group(1))
                if sch
                else f"EQ (Control of Emissions from {fuel.title()} Engines) Regulations 1996",
                "effective_date": _date(d.group(1)) if d else None,
                "text": seg.strip()[:500],
            }
        )
    s = SMOKE.search(flat)
    if s:
        out.append(
            {
                "key": "MY-DOE-INUSE-DIESEL-SMOKE",
                "fuel": "diesel",
                "subject": f"In-use diesel smoke: {s.group(1)}% opacity limit (compound); >70% opacity: prohibition order",
                "legal_basis": "EQ (Control of Emissions from Diesel Engines) Regulations 1996",
                "effective_date": None,
                "text": s.group(0),
            }
        )
    return out


# ------------------------------------------------------------------ legal texts (Acts, P.U.(A) regulations)
PUA = re.compile(r"P\.\s*U\.\s*\(\s*A\s*\)\s*(\d{1,4})\s*/\s*(\d{4}|\d{2})(?!\d)")
ACT = re.compile(r"\bAkta\s+(\d{2,4})\s+(AKTA\s+[A-Z][A-Z ]+?\s(\d{4}))\b")  # "Akta 333 AKTA PENGANGKUTAN JALAN 1987"
REG_TITLE = re.compile(r"(PERATURAN-PERATURAN [A-Z][A-Z ()\-,]+?\s(?:\(PINDAAN\)\s)?\d{4})")
MALAY_MONTH = {
    m: i
    for i, m in enumerate(
        (
            "januari",
            "februari",
            "mac",
            "april",
            "mei",
            "jun",
            "julai",
            "ogos",
            "september",
            "oktober",
            "november",
            "disember",
        ),
        1,
    )
}
GAZETTED = re.compile(r"Tarikh diterbitkan dalam Warta\s*:?\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})", re.I)
IN_FORCE = re.compile(r"Tarikh mula berkuat\s*kuasa\s*:?\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})", re.I)


def malay_date(s: str | None) -> date | None:
    m = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", (s or "").strip())
    if not m or m.group(2).lower() not in MALAY_MONTH:
        return _date(s or "")  # English month names
    try:
        return date(int(m.group(3)), MALAY_MONTH[m.group(2).lower()], int(m.group(1)))
    except ValueError:
        return None


def legal_identity(text: str) -> dict | None:
    """A P.U.(A) regulation or an Act, from its own first page: canonical id (DB_DESIGN formats PUA-<n>-<yyyy>,
    MY-ACT-<n>), title, dates. None for anything else (guidelines, forms)."""
    head = re.sub(r"\s+", " ", text[:3000])
    m = PUA.search(head)
    if m:
        n, y = int(m.group(1)), int(m.group(2))
        year = y if y > 99 else (1900 + y if y > 50 else 2000 + y)
        t = REG_TITLE.search(head[m.end() : m.end() + 600])
        g, f = GAZETTED.search(head), IN_FORCE.search(head)
        return {
            "kind": "pua",
            "canonical_id": f"PUA-{n}-{year}",
            "number": str(n),
            "year": year,
            "ref_no": f"P.U. (A) {n}/{m.group(2)}",
            "title": t.group(1).title() if t else None,
            "published": malay_date(g.group(1)) if g else None,
            "in_force": malay_date(f.group(1)) if f else None,
        }
    m = ACT.search(head)
    if m and "UNDANG-UNDANG MALAYSIA" in head.upper():
        return {
            "kind": "act",
            "canonical_id": f"MY-ACT-{m.group(1)}",
            "number": m.group(1),
            "year": int(m.group(3)),
            "ref_no": f"Akta {m.group(1)}",
            "title": m.group(2).title(),
            "published": None,
            "in_force": None,
        }
    return None


# ------------------------------------------------------------------ English names of the legal texts (dashboard)
# Malaysian legislation has official English titles in fixed legal wording: a phrase map, no machine translation
ACT_EN = {
    "333": "Road Transport Act 1987",
    "334": "Commercial Vehicles Licensing Board Act 1987",
    "127": "Environmental Quality Act 1974",
    "715": "Land Public Transport Act 2010",
}
REG_PHRASES = [  # (Malay, English), applied in order
    (r"^Peraturan-Peraturan Kualiti Alam Sekeliling\s*", "Environmental Quality "),
    (r"Kawalan Pelepasan Daripada", "Control of Emissions from"),
    (r"Enjin Petrol", "Petrol Engines"),
    (r"Enjin Diesel", "Diesel Engines"),
    (r"Motosikal", "Motorcycles"),
    (r"\(Pindaan\)", "(Amendment)"),
]


def english_legal_title(kind: str, number: str | None, title: str | None) -> str | None:
    """Official English title of an Act (by number) or an EQ regulation (by its fixed Malay wording)."""
    if kind == "act":
        return ACT_EN.get(number or "")
    if not title or not re.match(r"Peraturan-Peraturan Kualiti Alam Sekeliling", title, re.I):
        return None
    t = title
    for ms, en in REG_PHRASES:
        t = re.sub(ms, en, t, flags=re.I)
    m = re.match(r"(Environmental Quality .*?)\s*((?:\(Amendment\)\s*)?)(\d{4})$", t)
    return f"{m.group(1)} {m.group(2)}Regulations {m.group(3)}".replace("  ", " ") if m else None


# ------------------------------------------------------------------ titles of guideline / form files (dashboard)
LETTERHEAD = re.compile(
    r"^(?:BAHAGIAN|IBU PEJABAT|JABATAN|KEMENTERIAN|DEPARTMENT OF|MINISTRY OF|ROAD TRANSPORT DEPARTMENT|"
    r"JAS/|JPJ/|(?:JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|"
    r"DECEMBER)\s+\d{4}$|LAMPIRAN\b)",
    re.I,
)
MALAY_DOC_EN = [
    (
        re.compile(r"^BORANG PERMOHONAN KELULUSAN JENIS KOMPONEN", re.I),
        "Component Type Approval (CTA) Application Form",
    ),
    (
        re.compile(r"^GARIS PANDUAN PERMOHONAN KELULUSAN JENIS KOMPONEN", re.I),
        "Component Type Approval (CTA) Application Guidelines",
    ),
]


def document_title(text: str) -> tuple[str | None, str | None]:
    """(English title, Malay title or None) of a guideline / form file: its upper-case title block, letterheads,
    form codes and dates skipped; the two JPJ Malay titles by their English names."""
    from regtrack.pipeline.thai import nice_case

    block: list[str] = []
    for ln in (x.strip() for x in text[:3000].splitlines()):
        letters = re.findall(r"[A-Za-z]", ln)
        if ln.startswith("<<<") or not ln:
            continue
        if len(letters) >= 4 and sum(ch.isupper() for ch in letters) / len(letters) > 0.85:
            if ln.endswith(":"):  # a form field label ("BUTIRAN PEMOHON :"): the title is above it
                break
            if LETTERHEAD.search(ln):
                if block:
                    break
                continue
            block.append(ln)
        elif block:
            break
    if not block:
        return None, None
    if len(block) > 1 and block[0].upper() in ("GUIDELINES", "GARIS PANDUAN", "GUIDELINE"):
        block[0] += ":"  # "GUIDELINES" / "APPLICATION FOR ..." -> "Guidelines: Application for ..."
    raw = re.sub(r"\s+", " ", " ".join(block)).strip()
    for rx, en in MALAY_DOC_EN:
        if rx.search(raw):
            return en, nice_case(raw)
    return nice_case(raw), None
