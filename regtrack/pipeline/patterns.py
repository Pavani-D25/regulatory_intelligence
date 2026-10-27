"""Shared deterministic patterns: IDs, dates, references, categories, numeric conditions.

Extended from discovery/analyze.py. Everything here is pure (no DB, no LLM) and unit-tested.
"""

from __future__ import annotations

import re
from datetime import date

MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"])}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())})
MONTHS["sept"] = 9
MONTH_RE = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
            r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)")

# ---------------------------------------------------------------- G.S.R. / S.O.
SERIES_RE = r"(G\s?[.,]?\s?S\s?[.,]?\s?R\s?[.,]?|S\s?\.?\s?O\s?\.?)"
# '(E)' marks the Extraordinary gazette; tolerate '728E)', '377. (E)', '(E' from poor text layers
_E = r"([\(\{\[]\s*E\s*[\)\}\]]|(?<=\d)\s*E\s*[\)\}\]]|[\(\{\[]\s*E\b)"
NUM_ID = re.compile(SERIES_RE + r"\s*(?:No\.?\s*)?(\d{1,5})\s*\.?\s*" + _E + "?", re.I)
# The operative heading of a notification: "G.S.R. 659(E).—In exercise ..." / "S.O. 4143(E).- ..."; poor text layers
# turn the dash into an underscore ("G.s.R.673(E)._The following ...")
NUM_ID_HEAD = re.compile(SERIES_RE + r"\s*(?:No\.?\s*)?(\d{1,5})\s*\.?\s*" + _E + r"?\s*[.,:]?\s*[—–\-_]+\s*", re.I)
# Hindi "सा.का.नि. 659(अ)" / "का.आ. 4143(अ)"
HI_ID = re.compile(r"(सा\.\s?का\.\s?नि\.|का\.\s?आ\.)\s*(\d{1,5})\s*\(\s*अ\s*\)")


def series_code(raw: str) -> str:
    return "GSR" if "G" in raw.upper() else "SO"


def notification_canonical(series: str, number: str | int, year: int | None, extraordinary: bool = True) -> str:
    s = "GSR" if series.upper().startswith("G") else "SO"
    n = str(int(str(number)))
    return f"{s}-{n}{'(E)' if extraordinary else ''}-{year if year else 'XXXX'}"


def parse_notification_canonical(cid: str) -> tuple[str, str, int | None] | None:
    m = re.fullmatch(r"(GSR|SO)-(\d+)(\(E\))?-(\d{4}|XXXX)", cid)
    if not m:
        return None
    return m.group(1), m.group(2) + (m.group(3) or ""), (int(m.group(4)) if m.group(4).isdigit() else None)


# ---------------------------------------------------------------- dates
DATE_DMY = re.compile(r"\b(\d{1,2})\s*(?:st|nd|rd|th)?\s*,?\s*(?:day\s+of\s+)?(" + MONTH_RE + r")[\s.,]*,?\s*(\d{4})\b", re.I)
DATE_MDY = re.compile(r"\b(" + MONTH_RE + r")[\s.]+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", re.I)
DATE_NUM = re.compile(r"\b(\d{1,2})[./\-](\d{1,2})[./\-](\d{4}|\d{2})\b")
DATE_MONTH_YEAR = re.compile(r"\b(" + MONTH_RE + r")[\s.,'’]*(\d{4})\b", re.I)
NEW_DELHI_DATE = re.compile(r"New\s+Delhi,?\s*(?:the\s*)?(.{0,40}?\d{4})", re.I)


def month_num(s: str) -> int | None:
    s = s.lower().rstrip(".")
    return MONTHS.get(s) or MONTHS.get(s[:3])


def safe_date(y: int, m: int, d: int) -> date | None:
    try:
        if 1950 <= y <= 2100:
            return date(y, m, d)
    except ValueError:
        return None
    return None


def parse_date(s: str) -> date | None:
    """First full date in s (day month year, month day year, or dd.mm.yyyy)."""
    m = DATE_DMY.search(s)
    if m:
        mo = month_num(m.group(2))
        if mo:
            return safe_date(int(m.group(3)), mo, int(m.group(1)))
    m = DATE_MDY.search(s)
    if m:
        mo = month_num(m.group(1))
        if mo:
            return safe_date(int(m.group(3)), mo, int(m.group(2)))
    m = DATE_NUM.search(s)
    if m:
        y = int(m.group(3))
        y = y + 2000 if y < 50 else (y + 1900 if y < 100 else y)
        return safe_date(y, int(m.group(2)), int(m.group(1)))
    return None


def all_dates(s: str) -> list[date]:
    out = []
    for m in DATE_DMY.finditer(s):
        mo = month_num(m.group(2))
        d = safe_date(int(m.group(3)), mo, int(m.group(1))) if mo else None
        if d:
            out.append(d)
    return out


def parse_month_year(s: str) -> tuple[int, int] | None:
    m = DATE_MONTH_YEAR.search(s)
    if m:
        mo = month_num(m.group(1))
        if mo and 1950 <= int(m.group(2)) <= 2100:
            return int(m.group(2)), mo
    m = re.search(r"\b(\d{1,2})\s*/\s*(\d{4})\b", s)
    if m and 1 <= int(m.group(1)) <= 12:
        return int(m.group(2)), int(m.group(1))
    return None


# ---------------------------------------------------------------- AIS codes
AIS_CODE = re.compile(
    r"\bAIS\s*[\-:–]?\s*(\d{3})"
    r"(?:\s*/\s*(\d{4}))?"                                          # AIS 021/2004
    r"(?:\s*[\(\[]?\s*Part\s*[\-:]?\s*([IVX]+|\d+)\s*[\)\]]?)?"
    r"(?:\s*[\(\[]?\s*Rev(?:ision)?\s*\.?\s*(\d{1,2})?\s*[\)\]]?)?"
    r"(?:\s*:\s*(\d{4}))?",
    re.I)
ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10}


def _part_num(p: str | None) -> int | None:
    if not p:
        return None
    return int(p) if p.isdigit() else ROMAN.get(p.upper())


def ais_canonical(code: int | str, part: int | None = None, rev: int | None = None) -> str:
    s = f"AIS-{int(code):03d}"
    if part:
        s += f"(Part{part})"
    if rev:
        s += f"(Rev.{rev})"
    return s


def ais_family(code: int | str, part: int | None = None) -> str:
    return f"AIS-{int(code):03d}" + (f"(Part{part})" if part else "")


def parse_ais_code(s: str) -> dict | None:
    """'AIS-038 (Rev. 2)' -> {code:38, part:None, rev:2}. The first AIS code in s."""
    m = AIS_CODE.search(s)
    if not m:
        return None
    rev = None
    if re.search(r"Rev", m.group(0), re.I):
        rev = int(m.group(4)) if m.group(4) else 1
    return {"code": int(m.group(1)), "part": _part_num(m.group(3)), "rev": rev,
            "year": int(m.group(2) or m.group(5)) if (m.group(2) or m.group(5)) else None, "raw": m.group(0)}


def ais_canonical_from_text(s: str) -> str | None:
    p = parse_ais_code(s)
    return ais_canonical(p["code"], p["part"], p["rev"]) if p else None


def parse_canonical_ais(cid: str) -> dict | None:
    m = re.fullmatch(r"AIS-(\d{3})(?:\(Part(\d+)\))?(?:\(Rev\.(\d+)\))?(?:/(Amd|Corr)\.(\d+))?(?:/Table-(.+))?", cid)
    if not m:
        return None
    return {"code": int(m.group(1)), "part": int(m.group(2)) if m.group(2) else None,
            "rev": int(m.group(3)) if m.group(3) else None, "kind": m.group(4), "no": int(m.group(5)) if m.group(5) else None,
            "table": m.group(6)}


# AIS amendment / corrigendum headers (3 formats)
AMD_HEADER = re.compile(
    r"AMENDMENT\s*No\.?\s*(\d{1,2})\b"                       # AMENDMENT NO. 2
    r"(?P<mid>[^\n]{0,60}?(?:\n[^\n]{0,60}?){0,2}?)"        # optional date (same / next lines)
    r"\s*\bTO\b\s*(?P<code>AIS\s*[\-:–]?\s*\d{2,3}\b[^\n]{0,40})",  # 'AIS-37' also occurs
    re.I)
CORR_HEADER = re.compile(
    r"CORRIGENDUM\s*(?:No\.?\s*(\d{1,2}))?\b"
    r"(?P<mid>[^\n]{0,60}?(?:\n[^\n]{0,60}?){0,2}?)"
    r"\s*\bTO\b\s*(?P<code>AIS\s*[\-:–]?\s*\d{2,3}\b[^\n]{0,40})",  # 'AIS-37' also occurs
    re.I)
AIS_COVER = re.compile(r"AUTOMOTIVE\s+INDUSTRY\s+STANDARD", re.I)


def header_date(mid: str) -> tuple[str | None, str | None, str]:
    """Return (iso, precision, header_format) from the text between 'AMENDMENT NO. n' and 'TO AIS'."""
    d = parse_date(mid)
    if d:
        return d.isoformat(), "day", "full_date"
    my = parse_month_year(mid)
    if my:
        return f"{my[0]:04d}-{my[1]:02d}", "month", "month_year"
    return None, None, "no_date"


# ---------------------------------------------------------------- other identifiers
TAP_DOC = re.compile(r"MoRTH\s*/\s*CMVR\s*/\s*TAP\s*[\-–]?\s*115\s*/\s*116", re.I)
TAP_ISSUE = re.compile(r"Issue\s*(?:No\.?)?\s*[:\-]?\s*(\d{1,2})", re.I)
FORM_NO = re.compile(r"\bFORM\s*(?:No\.?\s*)?[\-–]?\s*(\d{1,2}\s?[A-Z]{0,2})\b")
FILE_NO = re.compile(r"\[?\s*F(?:ile)?\s*\.?\s*No\.?\s*[:\-]?\s*((?:RT|R\.T\.|NT|RW|H|S|T|A|Q|G)[A-Za-z0-9\-/\.\(\) ]{4,50}?\d{2,4}(?:[\-–][A-Z\(\)]+)?)\s*[\]\n,;]", re.I)
GAZETTE_ID = re.compile(r"\b(CG\s*[\-–]\s*[A-Z]{2}\s*[\-–]\s*E\s*[\-–]\s*\d{8}\s*[\-–]\s*\d{5,7}|"
                        r"CG\s*[\-–]\s*[A-Z]{2}\s*[\-–]\s*E\s*[\-–]\s*\d{8}|"
                        r"DL\s*[\-–]\s*\d{8}\s*[\-–]\s*\d{5,7}|REGD\.\s*NO\.\s*D\.\s*L\.\s*[\-–]?\s*\d{5})", re.I)
PART_SEC = re.compile(r"PART\s+II\s*[\-—–,.]*\s*Sec(?:tion|\.)?\s*(3|4|1)\s*[\-—–,.]*\s*"
                      r"(?:Sub[\-\s]?Sec(?:tion|\.)?\s*)?\(?\s*(i{1,3}|iv)?\s*\)?", re.I)
SHORT_TITLE = re.compile(r"(?:Central\s+)?Motor\s+Vehicles\s*\(\s*([A-Za-z\-\s]+?)\s*Amendment\s*\)\s*Rules,?\s*(\d{4})", re.I)
SIGNATORY = re.compile(r"\n\s*([A-Z][A-Z\.\s]{4,40}),?\s*\n\s*(?:Joint|Additional|Under|Deputy)?\s*Secy|"
                       r"\n\s*([A-Z][A-Z\.\s]{4,40}),?\s*\n?\s*(?:Jt\.|Joint|Addl\.|Additional|Under|Deputy)\s+Secretary", re.I)

# ---------------------------------------------------------------- references
REF_PATTERNS: dict[str, re.Pattern] = {
    "AIS": AIS_CODE,
    "IS": re.compile(r"\bIS\s*[:\-]?\s*(\d{2,5})(?:\s*\(?\s*Part\s*[\-:]?\s*(\d+)\s*\)?)?(?:\s*[:\-]?\s*((?:19|20)\d{2}))?\b"),
    "UN_R": re.compile(r"\b(?:UN\s*R|UN\s*ECE\s*R|ECE\s*R(?:egulation)?|UN\s*Regulation\s*No\.?)\s*[\-.]?\s*(\d{1,3})\b", re.I),
    "ISO": re.compile(r"\bISO\s*[:\-]?\s*(\d{3,5})(?:\s*[\-:]\s*(\d{1,2}))?(?:\s*:\s*(\d{4}))?\b"),
    "IEC": re.compile(r"\bIEC\s*[:\-]?\s*(\d{4,5})(?:\s*[\-:]\s*(\d{1,2}))?\b"),
    "RULE": re.compile(r"\brule\s+(\d{1,3}[A-Z]{0,2})(?:\s*\(\s*(\d{1,2}[A-Z]?)\s*\))?", re.I),
    "NOTIF": NUM_ID,
}


def norm_ref(kind: str, m: re.Match) -> str | None:
    g = m.groups()
    if kind == "AIS":
        p = parse_ais_code(m.group(0))
        return ais_canonical(p["code"], p["part"], p["rev"]) if p else None
    if kind == "IS":
        return f"IS {g[0]}" + (f"(Part {g[1]})" if g[1] else "") + (f":{g[2]}" if g[2] else "")
    if kind == "UN_R":
        return f"UN R{int(g[0])}"
    if kind == "ISO":
        return f"ISO {g[0]}" + (f"-{g[1]}" if g[1] else "") + (f":{g[2]}" if g[2] else "")
    if kind == "IEC":
        return f"IEC {g[0]}" + (f"-{g[1]}" if g[1] else "")
    if kind == "RULE":
        return f"CMVR Rule {g[0]}" + (f"({g[1]})" if g[1] else "")
    return None


def find_references(text: str, kinds: tuple[str, ...] = ("AIS", "IS", "UN_R", "ISO", "IEC", "RULE")) -> list[str]:
    out: dict[str, None] = {}
    for k in kinds:
        for m in REF_PATTERNS[k].finditer(text):
            r = norm_ref(k, m)
            if r:
                out[r] = None
    return list(out)


# ---------------------------------------------------------------- vehicle categories / powertrains
CAT_CODE = re.compile(r"\b(?:categor(?:y|ies)\s+)?(L[1-7]|M[1-3]|N[1-3]|O[1-4]|T[1-5]|T\b|CEV)(?:\s*[\-]?\s*[A-Z](?![a-z]))?\b")
CAT_LETTER = re.compile(r"\bcategor(?:y|ies)\s+((?:[LMNOT](?:\s*,\s*|\s+and\s+|\s+or\s+|\s*&\s*)?)+)\b")

SYNONYMS: dict[str, list[str]] = {
    "L1": ["moped", "mopeds", "low speed two wheeler"],
    "L2": ["motor cycle", "motorcycle", "motor cycles", "motorcycles", "scooter", "scooters", "two wheeler",
           "two-wheeler", "two wheelers", "two-wheelers", "two wheeled"],
    "L5": ["three wheeler", "three-wheeler", "three wheelers", "three-wheelers", "auto rickshaw", "auto-rickshaw"],
    "QUADRICYCLE": ["quadricycle", "quadricycles"],
    "M1": ["passenger car", "passenger cars", "motor car", "motor cars", "four wheeler", "four-wheeler",
           "four wheelers", "four-wheelers", r"cars?"],
    "M2": ["mini bus", "minibus"],
    "M3": ["bus", "buses", "coach", "coaches", "school bus"],
    "N1": ["light goods vehicle", "light goods vehicles", "light commercial vehicle", "LCV"],
    "N2": ["medium goods vehicle", "medium goods vehicles"],
    "N3": ["heavy goods vehicle", "heavy goods vehicles", "truck", "trucks", "tipper"],
    "O": ["trailer", "trailers", "semi-trailer", "semi trailer"],
    "T": ["agricultural tractor", "agricultural tractors", "tractor", "tractors", "power tiller"],
    "CEV": ["construction equipment vehicle", "construction equipment vehicles"],
    "E_RICKSHAW": ["e-rickshaw", "e rickshaw", "e-rickshaws", "battery operated rickshaw"],
    "E_CART": ["e-cart", "e cart", "e-carts"],
    "ALL": ["all motor vehicles", "every motor vehicle", "all categories of motor vehicles",
            "all categories of vehicles", "all vehicles"],
}
_SYN_RE = {c: re.compile(r"\b(?:" + "|".join(w if "\\" in w or "?" in w else re.escape(w) for w in ws) + r")\b", re.I)
           for c, ws in SYNONYMS.items()}


def norm_category(code: str) -> str | None:
    c = code.upper().replace("-", "").strip()
    if re.fullmatch(r"O[1-4]?", c):
        return "O"
    if re.fullmatch(r"T[1-5]?", c):
        return "T"
    if re.fullmatch(r"L[1-7]|M[1-3]|N[1-3]", c):
        return c
    if c in {"CEV", "ALL", "QUADRICYCLE", "E_RICKSHAW", "E_CART"}:
        return c
    if c in ("L", "M", "N"):
        return c  # family letter; expanded by expand_letters()
    return None


LETTER_EXPANSION = {"L": ["L1", "L2", "L5"], "M": ["M1", "M2", "M3"], "N": ["N1", "N2", "N3"], "O": ["O"], "T": ["T"]}


def expand_letters(cats: list[str]) -> list[str]:
    out: list[str] = []
    for c in cats:
        for x in LETTER_EXPANSION.get(c, [c]):
            if x not in out:
                out.append(x)
    return out


def find_categories(text: str, synonyms: bool = True) -> dict[str, int]:
    """Count category mentions: explicit codes (M1, N2, L5-M), 'category L' letters, and synonym words."""
    counts: dict[str, int] = {}

    def add(c: str | None, n: int = 1) -> None:
        if c:
            counts[c] = counts.get(c, 0) + n

    for m in CAT_CODE.finditer(text):
        add(norm_category(m.group(1)))
    for m in CAT_LETTER.finditer(text):
        for letter in re.findall(r"[LMNOT]", m.group(1)):
            for c in LETTER_EXPANSION[letter]:
                add(c)
    if synonyms:
        for code, rx in _SYN_RE.items():
            n = len(rx.findall(text))
            if n:
                add(code, n)
    return counts


POWERTRAIN_RE: dict[str, re.Pattern] = {
    "bev": re.compile(r"\b(battery operated|battery electric|electric vehicles?|BEV|EV|electric power ?train|e-vehicles?)\b", re.I),
    "hybrid": re.compile(r"\b(hybrid|HEV|PHEV)\b", re.I),
    "cng": re.compile(r"\bCNG\b|compressed natural gas", re.I),
    "lpg": re.compile(r"\bLPG\b|liquefied petroleum gas", re.I),
    "lng": re.compile(r"\bLNG\b|liquefied natural gas", re.I),
    "diesel": re.compile(r"\bdiesel\b|\bCI engine", re.I),
    "petrol": re.compile(r"\b(petrol|gasoline|spark ignition|SI engine)\b", re.I),
    "ethanol_flex": re.compile(r"\b(ethanol|flex[\s\-]?fuel|E\s?(?:20|85|100)\b)", re.I),
    "biodiesel": re.compile(r"\bbio[\s\-]?diesel\b|\bB100\b", re.I),
    "hydrogen": re.compile(r"\bhydrogen\b|fuel cell|\bH-CNG\b", re.I),
    "methanol": re.compile(r"\bmethanol\b|\bM15\b|\bM100\b", re.I),
}


def find_powertrains(text: str, min_hits: int = 1) -> list[str]:
    return [k for k, rx in POWERTRAIN_RE.items() if len(rx.findall(text)) >= min_hits]


USAGE_RE = {
    "transport": re.compile(r"\btransport vehicles?\b|\bcommercial vehicles?\b|\bstage carriage|\bcontract carriage|\bgoods carriage", re.I),
    "private": re.compile(r"\bnon[\s\-]?transport vehicles?\b|\bprivate vehicles?\b|\bpersonal use\b", re.I),
}


def find_usage(text: str) -> list[str]:
    u = [k for k, rx in USAGE_RE.items() if rx.search(text)]
    return ["all"] if len(u) == 2 else u


# ---------------------------------------------------------------- numeric conditions
WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
           "ten": 10, "twelve": 12, "thirteen": 13, "fifteen": 15, "twenty": 20, "twenty-two": 22, "thirty": 30}
_OP = r"(not more than|not exceeding|up to|upto|less than or equal to|less than|below|exceeding|more than|above|over|greater than|at least|<=|>=|≤|≥|<|>)"
OPMAP = {"not more than": "lte", "not exceeding": "lte", "up to": "lte", "upto": "lte", "less than or equal to": "lte",
         "<=": "lte", "less than": "lt", "below": "lt", "<": "lt", "exceeding": "gt", "more than": "gt", "above": "gt",
         "over": "gt", "greater than": "gt", ">": "gt", "at least": "gte", ">=": "gte", "≤": "lte", "≥": "gte"}
COND_RE = {
    "engine_cc": re.compile(_OP + r"\s*(\d{2,4})\s*(?:cc|cubic\s+centimet)", re.I),
    "power_kw": re.compile(_OP + r"\s*(\d+(?:\.\d+)?)\s*kW\b(?!\s*/)", re.I),  # not a power/weight ratio (kw/kg)
    "gvw_kg": re.compile(r"(?:GVW|gross vehicle weight)[^.;]{0,40}?" + _OP + r"\s*(\d[\d,]*(?:\.\d+)?)\s*(kg|kilograms?|tonnes?|t)\b", re.I),
    "seats": re.compile(_OP + r"\s*(\w+(?:-\w+)?)\s+(?:seats|passengers|persons)", re.I),
    "speed_kmh": re.compile(_OP + r"\s*(\d{2,3})\s*km\s*/?\s*h", re.I),
}


def find_conditions(text: str) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for key, rx in COND_RE.items():
        for m in rx.finditer(text):
            op = OPMAP.get(m.group(1).lower())
            raw = m.group(2).replace(",", "").lower()
            try:
                v = float(raw) if raw[0].isdigit() else float(WORDNUM[raw])
            except (KeyError, ValueError, IndexError):
                continue
            if key == "gvw_kg" and m.group(3).lower().startswith("t"):
                v *= 1000
            if op:
                out.setdefault(key, {})[op] = v
                break
    return out

ISO_DATE_RE = r"\d{4}-\d{2}-\d{2}"
