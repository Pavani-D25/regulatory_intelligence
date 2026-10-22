"""Deterministic reading of Thai TISI mandatory-standard pages (www3.tisi.go.th/hscode/hscode_view.asp).

One page per mandatory มอก. standard: number, Thai title, effective date, scope (ขอบข่าย), label text, HS codes.
The TISI list covers every product type (steel, plastics, circuit breakers, ...), so most pages are OFF_TOPIC;
only the automotive ones become TIS_STANDARD. Everything here is regex on the page text, no Qwen.
"""

from __future__ import annotations

import re
from datetime import date

TISI_SOURCE = "TH_TISI_MANDATORY"
AUTOMOTIVE_CATEGORY = "ยานยนต์"  # the TISI list's own "automotive" product group
FULL_TEXT = "fulltext"  # listing category of a standard's full-text PDF (service.tisi.go.th/fulltext/...)
FULL_TEXT_LINK = re.compile(r"""href=["'](https?://service\.tisi\.go\.th/fulltext/[^"']+\.pdf)["']""", re.I)

THAI_MONTH = {"ม.ค.": 1, "ก.พ.": 2, "มี.ค.": 3, "เม.ย.": 4, "พ.ค.": 5, "มิ.ย.": 6,
              "ก.ค.": 7, "ส.ค.": 8, "ก.ย.": 9, "ต.ค.": 10, "พ.ย.": 11, "ธ.ค.": 12}
DATE_RE = re.compile(r"(\d{1,2})\s+([ก-๙.]+)\s+(\d{4}|\d{2})(?!\d)")
# "มอก. 721-2551", "มอก.60947 เล่ม 2-2569", "มอก.60335 เล่ม 2(24)-2563" (เล่ม = part)
# the full-text PDFs print "มอก. 721   2551" (the dash is a lost glyph): a dash, or two or more spaces
TIS_NO = re.compile(r"มอก\.\s*(\d{2,5})(?:\s*เล่ม\s*(\d+(?:\(\d+\))?))?(?:\s*[-–−‐‑—]\s*|[\s\xa0]{2,})(\d{4})(?!\d)")
EFFECTIVE = re.compile(r"วันที่มีผล(?:บังคับ)?ใช้(?:บังคับ)?\s*:?\s*([^)\n]{4,30})")
SCOPE_END = re.compile(r"บทนิยามและรายละเอียด|ข้อความในฉลาก|สอบถามรายละเอียด")
HS_CODE = re.compile(r"\b(\d{4}\.\d{2}(?:\.\d{2})?(?:\.\d{3})?)\b")
# vehicles named in the title that make a non-automotive product group's standard automotive (motorcycle
# helmets, LPG tanks for engines). Title only: scopes name them as exclusions too (มอก.27 LPG cylinders "does not
# cover tanks for internal-combustion engines"); "รถยนต์" alone is not enough (automotive sheet steel)
AUTOMOTIVE_TITLE = re.compile(r"รถจักรยานยนต์|เครื่องยนต์สันดาปภายใน")
# UN vehicle categories as written on the pages: "M1", "M 1", "L 3", or a bare class letter ("M N O และ T")
UN_CODE = re.compile(r"(?<![A-Za-z])([LMNOT])\s?([1-7])(?!\d)")
UN_CLASS = re.compile(r"(?<![A-Za-z])([LMN])(?![A-Za-z0-9]|\s?[1-7])")
CLASS_WORD = re.compile(r"ประเภท")  # bare letters count only right after "category" (not "ภาคผนวก L" = Annex L)
CLASS_WINDOW = 80
# each UN class letter -> the Thailand categories it contains (vehicle_categories rows for TH: L1, L3, M1, N1)
CLASS_CATEGORIES = {"L": ("L1", "L3"), "M": ("M1",), "N": ("N1",)}
TH_CATEGORIES = frozenset({"L1", "L3", "M1", "N1"})
MOTORCYCLE = re.compile(r"รถจักรยานยนต์")
MOPED = re.compile(r"โมเปด")
CAR = re.compile(r"รถยนต์(?!ขนาดใหญ่|เชิงพาณิชย์)")


def parse_thai_date(s: str | None) -> date | None:
    """'14 ก.ค. 2551' or '26 ก.พ. 54' (Buddhist Era, 4- or 2-digit year) -> a Gregorian date, or None."""
    if not s:
        return None
    m = DATE_RE.search(s)
    if not m or m.group(2) not in THAI_MONTH:
        return None
    day, mon, y = int(m.group(1)), THAI_MONTH[m.group(2)], m.group(3)
    year_be = int(y) if len(y) == 4 else 2500 + int(y)
    try:
        return date(year_be - 543, mon, day)
    except ValueError:
        return None


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def tis_number(text: str) -> dict | None:
    """The page's own standard number (its first มอก. heading): number, part, B.E. year, canonical_id."""
    m = TIS_NO.search(text)
    if not m:
        return None
    number, part, year_be = m.group(1), m.group(2), int(m.group(3))
    base = f"TIS-{number}" + (f"(Part{part})" if part else "")
    return {"number": number, "part": part, "year_be": year_be, "year": year_be - 543, "family_key": base,
            "canonical_id": f"{base}-{year_be}", "tis_no": clean(m.group(0)), "end": m.end()}


def tis_numbers(text: str) -> list[dict]:
    """Every มอก. number printed in the text, in order (canonical_id per match)."""
    out = []
    for m in TIS_NO.finditer(text):
        n = tis_number(m.group(0))
        if n:
            out.append(n)
    return out


def full_text_identity(text: str, expected: dict | None) -> tuple[dict | None, str]:
    """A full-text PDF often opens with a ministerial amendment notice or an erratum that cites the previous edition
    ("มอก. 2718−2558") before the standard's own number. Of the numbers the PDF prints, the one of the standard whose
    TISI page links it; else the first. ('content', 'first', or 'link' when the PDF has no readable number at all:
    an old scan with a broken font layer, attached by the link and flagged)."""
    found = tis_numbers(text)
    if expected and any(f["canonical_id"] == expected["canonical_id"] for f in found):
        return expected, "content"
    if found:
        return found[0], "first"
    return (expected, "link") if expected else (None, "none")


def title_of(text: str) -> str | None:
    """The Thai title: the words after the มอก. number, up to the '(วันที่มีผลบังคับใช้ ...)' bracket."""
    n = tis_number(text)
    if not n:
        return None
    rest = text[n["end"]:n["end"] + 600]
    t = clean(re.split(r"\(\s*วันที่มีผล|ขอบข่าย", rest)[0])
    return t or None


def scope_of(text: str) -> str | None:
    if "ขอบข่าย" not in text:
        return None
    s = text.split("ขอบข่าย", 1)[1]
    m = SCOPE_END.search(s)
    return clean(s[:m.start()] if m else s[:3000]) or None


def is_automotive(category: str | None, text: str) -> bool:
    """TISI's own automotive product group, or a standard whose title names a vehicle or engine."""
    if (category or "").strip() == AUTOMOTIVE_CATEGORY:
        return True
    return bool(AUTOMOTIVE_TITLE.search(title_of(text) or ""))


def categories_of(text: str) -> list[str]:
    return categories_from(title_of(text), scope_of(text))


def categories_from(title: str | None, scope: str | None) -> list[str]:
    """Thailand vehicle categories (L1, L3, M1, N1) from the scope's UN codes, else from the vehicle words."""
    scope = scope or ""
    words = f"{title or ''} {scope}"
    cats: set[str] = set()
    for letter, digit in UN_CODE.findall(scope):
        cats.add(f"{letter}{digit}")
    for m in CLASS_WORD.finditer(scope):
        for letter in UN_CLASS.findall(scope[m.end():m.end() + CLASS_WINDOW]):
            cats.update(CLASS_CATEGORIES[letter])
    if MOTORCYCLE.search(words):
        cats.add("L3")
    if MOPED.search(words):
        cats.add("L1")
    if not cats & TH_CATEGORIES and CAR.search(words):
        cats.update(("M1", "N1"))
    return sorted(cats & TH_CATEGORIES)


def fields_of(text: str) -> dict:
    """TisStandardData fields from one TISI page."""
    n = tis_number(text) or {}
    eff = EFFECTIVE.search(text)
    eff_date = parse_thai_date(eff.group(1)) if eff else None
    return {"title": title_of(text), "tis_no": n.get("tis_no"), "year_be": n.get("year_be"),
            "effective_date": eff_date.isoformat() if eff_date else None, "scope_text": scope_of(text),
            "hs_codes": sorted(set(HS_CODE.findall(text)))}


# domains and powertrains from the Thai title + scope (the English vocabularies of regtrack/vocab.py do not apply)
DOMAIN_WORDS = [("EMISSION", re.compile(r"สารมลพิษ|ไอเสีย")),
                ("SAFETY_EQUIPMENT", re.compile(r"ยางล้อ|ยางใน|เข็มขัดนิรภัย|หมวกนิรภัย|กระจกนิรภัย")),
                ("EV_ALT_FUEL", re.compile(r"ก๊าซธรรมชาติ|ก๊าซปิโตรเลียมเหลว"))]
POWERTRAIN_WORDS = [("petrol", re.compile(r"จุดระเบิดด้วยประกายไฟ")), ("diesel", re.compile(r"จุดระเบิดด้วยการอัด")),
                    ("cng", re.compile(r"ก๊าซธรรมชาติ")), ("lpg", re.compile(r"ก๊าซปิโตรเลียมเหลว"))]


def domains_from(title: str | None, scope: str | None) -> list[str]:
    """Every mandatory TIS needs TISI certification (TYPE_APPROVAL), plus the subject's own domain."""
    head = f"{title or ''} {scope or ''}"
    return ["TYPE_APPROVAL"] + [d for d, rx in DOMAIN_WORDS if rx.search(head)]


def powertrains_from(title: str | None, scope: str | None) -> list[str]:
    head = f"{title or ''} {scope or ''}"
    return [p for p, rx in POWERTRAIN_WORDS if rx.search(head)]


def full_text_fields(text: str) -> dict:
    """What a full-text PDF adds: its own number (identity check) and the scope section "1. ขอบข่าย"."""
    n = tis_number(text) or {}
    return {"tis_no": n.get("tis_no"), "year_be": n.get("year_be"), "scope_text": scope_of(text)}
