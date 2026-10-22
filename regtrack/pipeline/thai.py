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

THAI_MONTH = {"ม.ค.": 1, "ก.พ.": 2, "มี.ค.": 3, "เม.ย.": 4, "พ.ค.": 5, "มิ.ย.": 6,
              "ก.ค.": 7, "ส.ค.": 8, "ก.ย.": 9, "ต.ค.": 10, "พ.ย.": 11, "ธ.ค.": 12}
DATE_RE = re.compile(r"(\d{1,2})\s+([ก-๙.]+)\s+(\d{4}|\d{2})(?!\d)")
# "มอก. 721-2551", "มอก.60947 เล่ม 2-2569", "มอก.60335 เล่ม 2(24)-2563" (เล่ม = part)
TIS_NO = re.compile(r"มอก\.\s*(\d{2,5})(?:\s*เล่ม\s*(\d+(?:\(\d+\))?))?\s*-\s*(\d{4})")
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
    """Thailand vehicle categories (L1, L3, M1, N1) from the scope's UN codes, else from the vehicle words."""
    scope = scope_of(text) or ""
    words = f"{title_of(text) or ''} {scope}"
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


def domains_of(text: str) -> list[str]:
    """Every mandatory TIS needs TISI certification (TYPE_APPROVAL), plus the subject's own domain."""
    head = f"{title_of(text) or ''} {scope_of(text) or ''}"
    return ["TYPE_APPROVAL"] + [d for d, rx in DOMAIN_WORDS if rx.search(head)]


def powertrains_of(text: str) -> list[str]:
    head = f"{title_of(text) or ''} {scope_of(text) or ''}"
    return [p for p, rx in POWERTRAIN_WORDS if rx.search(head)]
