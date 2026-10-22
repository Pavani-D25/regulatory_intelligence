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


# ------------------------------------------------------------------ Thai legal texts saved by hand (TH_LOCAL)
# Acts (พระราชบัญญัติ), ministerial regulations (กฎกระทรวง), DLT notifications (ประกาศกรมการขนส่งทางบก) and other
# notices, in Thai or in an official English translation. Identity, title and date from the first page.
THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
THAI_MONTH_FULL = {m: i for i, m in enumerate(("มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
                                               "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"), 1)}
FULL_DATE = re.compile(r"(\d{1,2})\s*(" + "|".join(THAI_MONTH_FULL) + r")\s*(?:พ\.\s*ศ\.\s*)?(\d{4})")
LAW_KINDS = [  # (class, pattern on the first page), most specific first
    ("TIS_STANDARD", re.compile(r"มาตรฐานผลิตภัณฑ์อุตสาหกรรม|THAI INDUSTRIAL STANDARD")),
    ("MINISTERIAL_REGULATION", re.compile(r"กฎกระทรวง|Ministerial\s+Regulation", re.I)),
    ("DLT_NOTIFICATION", re.compile(r"ประกาศกรมการขนส่งทางบก|Notification\s+of\s+the\s+Department\s+of\s+Land\s+Transport", re.I)),
    ("TH_ACT", re.compile(r"^\s*พระราชบัญญัติ|\bAct,?\s+B\.\s*E\.\s*\d{4}", re.M | re.I)),
    ("GAZETTE_NOTICE", re.compile(r"ประกาศ(?:กระทรวง|สำนักงาน|กรม)|ราชกิจจานุเบกษา|Notification\s+of\s+the\s+Ministry", re.I)),
]
MR_NO = re.compile(r"กฎกระทรวง\s*(?:ฉบับที่\s*(\d{1,3}))?\s*\(?\s*พ\.\s*ศ\.\s*(\d{4})\s*\)?")
ACT_TITLE = re.compile(r"(พระราชบัญญัติ[^\n]{2,120}?พ\.\s*ศ\.\s*(\d{4}))")
SUBJECT = re.compile(r"เรื่อง\s+([^\n]{4,200})")
MINISTRY = [("MOT", re.compile(r"กระทรวงคมนาคม|Ministry\s+of\s+Transport", re.I)),
            ("MOIND", re.compile(r"กระทรวงอุตสาหกรรม|Ministry\s+of\s+Industry", re.I)),
            ("MOI", re.compile(r"กระทรวงมหาดไทย|Ministry\s+of\s+Interior", re.I))]
EN_YEAR = re.compile(r"B\.\s*E\.\s*(\d{4})")


def thai_digits(text: str) -> str:
    return text.translate(THAI_DIGITS)


def full_thai_date(text: str) -> date | None:
    m = FULL_DATE.search(text)
    if not m:
        return None
    try:
        return date(int(m.group(3)) - 543, THAI_MONTH_FULL[m.group(2)], int(m.group(1)))
    except ValueError:
        return None


def _h8(s: str) -> str:
    import hashlib

    return hashlib.sha1(clean(s).encode("utf-8")).hexdigest()[:8].upper()


def law_class(text: str) -> str | None:
    head = thai_digits(text[:2500])
    return next((dc for dc, rx in LAW_KINDS if rx.search(head)), None)


def law_identity(text: str, doc_class: str) -> dict | None:
    """canonical_id (docs/CLASSIFICATION_DESIGN.md §6.3 style, B.E. year in the id), title, B.E. year, signing date."""
    head = thai_digits(text[:6000])
    if doc_class == "TIS_STANDARD":
        n = tis_number(head)
        return {**n, "title": title_of(head), "date": None} if n else None
    title, year_be, cid = None, None, None
    if doc_class == "MINISTERIAL_REGULATION":
        m = MR_NO.search(head)
        ministry = next((code for code, rx in MINISTRY if rx.search(head)), "TH")
        if m:
            year_be = int(m.group(2))
            line = clean(head[m.start():m.start() + 200].split("\n")[0])
            title = line
            cid = f"TH-MR-{ministry}-{m.group(1)}-{year_be}" if m.group(1) else f"TH-MR-{ministry}-{_h8(line)}-{year_be}"
    elif doc_class == "TH_ACT":
        m = ACT_TITLE.search(head)
        if m:
            title, year_be = clean(m.group(1)), int(m.group(2))
            cid = f"TH-ACT-{year_be}-{_h8(title)}"
    else:  # DLT / other notifications: "เรื่อง <subject>", dated "ประกาศ ณ วันที่ ..."
        s = SUBJECT.search(head)
        d = full_thai_date(head[-3000:]) or full_thai_date(head)
        if s:
            title = clean(s.group(1))
            year_be = (d.year + 543) if d else None
            prefix = "TH-DLT" if doc_class == "DLT_NOTIFICATION" else "TH-NOTICE"
            cid = f"{prefix}-{year_be or 0}-{_h8(title)}"
    if not cid:  # an English translation: "... Act, B.E. 2522" / "Ministerial Regulation No. 5 (B.E. 2551)"
        y = EN_YEAR.search(head)
        first = clean(head[:200].split("\n")[0]) if head.strip() else ""
        if y and first:
            year_be, title = int(y.group(1)), first
            kind = {"TH_ACT": "TH-ACT", "MINISTERIAL_REGULATION": "TH-MR-EN", "DLT_NOTIFICATION": "TH-DLT"}.get(doc_class, "TH-NOTICE")
            cid = f"{kind}-{year_be}-{_h8(title)}"
    if not cid:
        return None
    return {"canonical_id": cid, "title": title, "year_be": year_be, "year": (year_be - 543) if year_be else None,
            "date": full_thai_date(head[-3000:]) or full_thai_date(head)}


# topics of the legal texts (their own vocabulary list, so the TIS domains above stay as they are)
LAW_DOMAIN_WORDS = [
    ("REGISTRATION", re.compile(r"จดทะเบียน|ทะเบียนรถ|registration", re.I)),
    ("DIMENSIONS_WEIGHTS", re.compile(r"ความกว้าง|ความยาว|ความสูง|น้ำหนักรถ|น้ำหนักบรรทุก|dimension|weight", re.I)),
    ("LIGHTING", re.compile(r"โคมไฟ|ไฟหน้า|ไฟท้าย|ไฟเลี้ยว|ไฟส่องสว่าง|ไฟสัญญาณ|lamp|lighting|light-signalling", re.I)),
    ("BRAKING", re.compile(r"ห้ามล้อ|เบรก|brak", re.I)),
    ("EV_ALT_FUEL", re.compile(r"รถยนต์ไฟฟ้า|ยานยนต์ไฟฟ้า|electric\s+vehicle|\bR\s?100\b", re.I)),
    ("BATTERY", re.compile(r"แบตเตอรี่|REESS|traction\s+battery", re.I)),
    ("FUEL_EFFICIENCY", re.compile(r"คาร์บอนไดออกไซด์|อัตราการใช้น้ำมัน|อัตราการใช้เชื้อเพลิง|อีโคสติ๊กเกอร์|ECO\s*Sticker|CO2|fuel\s+consumption", re.I)),
    ("SAFETY_EQUIPMENT", re.compile(r"เข็มขัดนิรภัย|กระจกนิรภัย|ยางล้อ|safety\s+belt", re.I)),
]


def law_domains(text: str) -> list[str]:
    head = thai_digits(text[:12000])
    return [d for d, rx in LAW_DOMAIN_WORDS if rx.search(head)]
