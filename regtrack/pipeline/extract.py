"""Extract stage: 'classified' -> 'parsed'.

Deterministic first (dates, file no, gazette part, references, categories via the synonym table, numeric
conditions, domains); Qwen fills the doc_class Pydantic model from English pages only when reachable.
If the LLM is down, the deterministic result is written with extraction.llm_pending = true and the Qwen
pass runs on a later pipeline run (see enrich_pending), so the rest of the pipeline never blocks on it.
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import re
from datetime import date

import psycopg
from pydantic import BaseModel, Field, create_model

from regtrack import country, llm
from regtrack.config import get_settings
from regtrack.db import Jsonb
from regtrack.models import model_for
from regtrack.models.enums import DocClass, FlagRule, Status
from regtrack.pipeline import malaysia, thai
from regtrack.pipeline import patterns as P
from regtrack.pipeline import repo as R
from regtrack.pipeline.dbutil import add_flag
from regtrack.pipeline.text import PageText, english_text, full_text, load_pages
from regtrack.storage import open_local
from regtrack.validators import in_scope, validate_data
from regtrack.vocab import find_domains

log = logging.getLogger(__name__)
PROMPT_VERSION = "extract_v1"
RULES_VERSION = "rules_v2"  # v2: Motor Vehicles Acts / CMVR apply to ALL; pre-1988 MV law superseded
MAX_LLM_CHARS = 24000


# ====================================================================== deterministic helpers
def operative_text(eng: str) -> str:
    """English notification text from the 'NOTIFICATION' heading on (skips the Gazette masthead)."""
    m = re.search(r"\n\s*(NOTIFICATION|ORDER|CORRIGENDUM)\s*\n", eng)
    return eng[m.start():] if m else eng


def categories_of(text: str) -> list[str]:
    """Explicit codes ('M1', 'category L') count once; plain words ('truck', 'car') need two mentions in long texts."""
    codes = P.find_categories(text, synonyms=False)
    allc = P.find_categories(text)
    need = 1 if len(text) < 3000 else 2
    keep = [c for c, n in allc.items() if c in codes or n >= need or c == "ALL"]
    cats = P.expand_letters(keep)
    order = ["L1", "L2", "L3", "L4", "L5", "L6", "L7", "QUADRICYCLE", "M1", "M2", "M3", "N1", "N2", "N3", "O", "T",
             "CEV", "E_RICKSHAW", "E_CART", "ALL"]
    return [c for c in order if c in cats]


def scope_section(eng: str) -> str | None:
    m = re.search(r"\n\s*1\.?0?\s*\.?\s*\n?\s*SCOPE\b[^\n]*\n(.{20,2500}?)(?=\n\s*2\.?0?\s*\.?\s*\n?\s*[A-Z][A-Za-z ]{3,40}\n|\Z)",
                  eng[:60000], re.I | re.S)
    if not m:
        m = re.search(r"\bSCOPE\b\s*[:\-]?\s*\n(.{20,1500}?)(?=\n\s*\d\.\s|\Z)", eng[:60000], re.S)
    return clean(m.group(1))[:1500] if m else None


def transitional_section(eng: str) -> str | None:
    m = re.search(r"TRANSITIONAL\s+PROVISIONS?\s*\n(.{20,2500}?)(?=\n\s*\d{1,2}\.?0?\s+[A-Z][A-Za-z ]{3,40}\n|\n\s*ANNEX|\Z)",
                  eng, re.I | re.S)
    return clean(m.group(1))[:1500] if m else None


def clean(s: str) -> str:
    s = re.sub(r"<<<PAGE \d+>>>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# lines on AIS / notification covers that are never a title
JUNK_TITLE = re.compile(r"^\W*(date\s+of\s+hosting|last\s+date|page\s*(no\.?\s*)?\d|\d+\s*\|\s*p\s*a\s*g\s*e|registered\s+no|"
                        r"government\s+of\s+india|the\s+gazette|ministry\s+of|extraordinary|finalised\s+draft\s*$|check\s*list|"
                        r"duration|comments|printed\s+by|status\s+chart|\(\d+\)|replace\s+clause|substitute|c\s+o\s+n\s+t|"
                        r"\d+(\.\d+)?\s|\w+\s+highlighted|automotive\s+industry\s+standards?\s*$|s?\s*committee\b|the\s+government\s+of\s+india\s+felt|"
                        r"\d{1,2}(st|nd|rd|th)?\s+\w+,?\s+\d{4}\s*$|amends\s+cmvr\s*$)", re.I)
ID_WORDS = {"draft", "part", "revision", "rev", "amendment", "amendments", "amd", "corrigendum", "corri", "and", "with",
            "jan", "feb", "march", "april", "may", "june", "july", "aug", "sept", "oct", "nov", "dec"}


def is_junk_title(t: str | None) -> bool:
    """No title, a cover-page line (hosting date, page number, Gazette header ...), or mostly OCR garbage."""
    if not t or len(t.strip()) < 12:
        return True
    t = t.strip()
    if PLACEHOLDER.search(t):  # a draft's unfilled blanks: "(………Amendment) Rules"
        return True
    garbage = sum(not (c.isascii() and (c.isalnum() or c in " .,:;()[]-–/&'\"%+")) for c in t)
    if re.match(r"^\W*(draft\W*)?ais\W*\d{3}", t, re.I):  # "AIS-137 (Part 5)", "Draft AIS-221/D0/Dec. 2025": an id, not a title
        words = [w for w in re.findall(r"[A-Za-z]{3,}", t) if w.lower() not in ID_WORDS and w.upper() != "AIS"]
        if len(words) < 2:
            return True
    return bool(JUNK_TITLE.match(t)) or garbage > 0.25 * len(t) or "hosting on" in t.lower()


AIS_DRAFT_COVER = re.compile(r"((?:Revised\s+)?Draft\s+(?:Amendment|Corrigendum)\s+No\.?\s*\d+)[^A-Za-z]{0,30}?\bto\s+"
                             r"(AIS[\s\-:]*\d{3}(?:\s*\((?:Part|PART)\s*\d+\))?(?:\s*\(Rev\.?\s*\d+\))?)\s*[:\-–]?\s*"
                             r"(.{10,200}?)(?=\s+(?:Part\s+[A-Z]\b|\d{1,2}\.\d?\s|Page\b|SR\.|1/\d|Sr\.|$))", re.I)


AIS_DRAFT_COVER_TITLE = re.compile(r"(?:Revised\s+)?Draft\s+(?:Amendment|Corrigendum)\s+No", re.I)


def ais_title(eng: str) -> str | None:
    head = clean(eng[:2500])
    m = AIS_DRAFT_COVER.search(clean(eng[:4000]))
    if m:  # "Draft Corrigendum No. 1 (…) To AIS-185 Approval of vehicles ..." -> "Draft Corrigendum No. 1 to AIS-185: Approval ..."
        std = re.sub(r"[\s:]+", "-", m.group(2).strip(), count=1)
        return f"{m.group(1)} to {std}: {m.group(3).strip(' :-')}"[:250]
    m = re.search(r"AUTOMOTIVE\s+INDUSTRY\s+STANDARD(?!S)\s*(?:\(AIS\))?\s*[–\-]?\s*(?:\d{3}\s*)?(?:\(\s*AIS\s*[–\-]\s*\d{3}\s*\)\s*)?"
                  r"(?:regarding\s+)?(.{10,250}?)\s+(?:AIS[\s\-:]*\d{3}|PRINTED\s+BY|Comments|Duration|"
                  r"Date\s+of\s+hosting|Last\s+date|(?:January|February|March|April|May|June|July|August|September|"
                  r"October|November|December)\s+\d{4})", head, re.I)
    if m and not is_junk_title(m.group(1)):
        return re.sub(r"^\(?AIS[\s\-]*\d{3}[^:]{0,25}:\s*(?:\d{4}\s+)?", "", m.group(1).strip(" :-.")).strip(" ()")[:250]
    return None


def own_ais_title(eng: str, number: int | None) -> str | None:
    """'TO AIS 123(PART 1): CMVR Type Approval of ...' - the standard's own title as quoted by its amendment pages."""
    if not number:
        return None
    m = re.search(rf"AIS[\s\-]*0*{number}\b(?:\s*\((?:PART|Part)\s*\d+\))?(?:\s*\(Rev\.?\s*\d+\))?\s*:\s*(?!\d{{4}})"
                  r"(.{15,180}?)(?=\s+(?:\d{1,2}\.\d|Page|Part\s+[A-Z]\b|PRINTED|$))", clean(eng[:80000]))
    return m.group(1).strip(" :-.") if m and not is_junk_title(m.group(1)) else None


# "These rules may be called the Motor Vehicles (Driving) Regulations, 2017."
CALLED = re.compile(r"(?:rules|regulations|order|scheme|notification)\s*,?\s*may\s+be\s+called\s+(?:as\s+)?the\s+"
                    r"([A-Z][^.;:]{8,170}?,?\s*(?:19|20)\d\d)", re.I)
ACT_TITLE = re.compile(r"\b(THE\s+[A-Z][A-Za-z\s\(\)\-']{4,90}?\s+ACT,?\s*(?:19|20)\d\d)")


PLACEHOLDER = re.compile(r"[…_]{2,}|\.{3,}|-{3,}|…")  # … = the ellipsis character


def called_title(text: str) -> str | None:
    """Short title; a draft's blank ordinal is dropped: 'Central Motor Vehicles (……Amendment) Rules' -> '(Amendment)'."""
    m = CALLED.search(clean(text[:15000]))
    if not m:
        return None
    t = re.sub(r"\(\s*(?:(?:[…_.]+|-{2,})\s*)+", "(", m.group(1).strip())
    return re.sub(r"\s+", " ", PLACEHOLDER.sub(" ", t)).strip()


def signatory(eng: str) -> str | None:
    m = re.search(r"\n\s*\(?([A-Z][A-Z\.\s]{4,40}?)\)?\s*,?\s*\n?\s*(?:Jt\.|Joint|Addl\.|Additional|Under|Deputy|Dy\.)\s*Secy|"
                  r"\n\s*\(?([A-Z][A-Z\.\s]{4,40}?)\)?\s*,?\s*\n?\s*(?:Joint|Additional|Under|Deputy)\s+Secretary", eng)
    if not m:
        return None
    name = (m.group(1) or m.group(2) or "").strip(" ,.")
    return name.title() if 4 < len(name) < 45 else None


POWERS = re.compile(r"(?:section|sections)\s+(\d{1,3}[A-Z]?)(?:\s*(?:,|and)\s*(\d{1,3}[A-Z]?))*\s+of\s+the\s+Motor\s+Vehicles\s+Act", re.I)
COMMENCE = re.compile(r"shall\s+come\s+into\s+(?:force|effect)\s+(on\s+the\s+date\s+of\s+(?:their|its)\s+(?:final\s+)?publication|"
                      r"on\s+(?:and\s+from\s+)?(?:the\s+)?[^.;]{4,60}?\d{4})", re.I)
DAYS_WORDS = {"seven": 7, "fifteen": 15, "thirty": 30, "forty-five": 45, "forty five": 45, "sixty": 60, "ninety": 90}


def comment_days(eng: str) -> int | None:
    m = re.search(r"expiry\s+of\s+(?:a\s+)?period\s+of\s+([a-z\- ]+?|\d+)\s+days", eng, re.I)
    if not m:
        return None
    w = m.group(1).strip().lower()
    return int(w) if w.isdigit() else DAYS_WORDS.get(w)


def amends_targets(op: str) -> tuple[list[str], list[str]]:
    targets, notifs = [], []
    if re.search(r"Central\s+Motor\s+Vehicles\s+Rules", op[:4000], re.I):
        for m in re.finditer(r"in\s+rule\s+(\d{1,3}[A-Z]{0,2})(?:\s*,\s*(?:in\s+)?sub-rule\s*\((\w+)\))?", op[:20000], re.I):
            t = f"CMVR Rule {m.group(1)}" + (f"({m.group(2)})" if m.group(2) else "")
            if t not in targets:
                targets.append(t)
        if not targets:
            targets.append("CMVR")
    for m in re.finditer(r"(?:amendments?|corrections?|corrigendum)\s+(?:in|to)\s+the\s+(?:said\s+)?notification[^.]{0,250}?"
                         + P.SERIES_RE + r"\s*(\d{1,5})\s*\(?\s*E\s*\)?[,\s]*(?:dated\s+(?:the\s+)?)?([^;]{0,40}?\d{4})?",
                         op[:8000], re.I):
        d = P.parse_date(m.group(3) or "")
        y = d.year if d else (int(re.search(r"\d{4}", m.group(3)).group(0)) if m.group(3) else None)
        cid = P.notification_canonical(P.series_code(m.group(1)), m.group(2), y)
        if "XXXX" not in cid and cid not in notifs:
            notifs.append(cid)
        if cid.startswith("SO-1365(E)"):
            targets.append("SO-1365(E)-2004 Table")
    return list(dict.fromkeys(targets)), notifs


def notification_references(eng: str, own: str | None) -> list[str]:
    refs = P.find_references(eng, ("AIS", "IS", "UN_R"))
    return [r for r in refs if r != own][:60]


def ais_annexes(eng: str) -> list[dict]:
    out, seen = [], set()
    for m in re.finditer(r"\n\s*ANNEX(?:URE)?\s*[\-:]?\s*([A-Z0-9]{1,3}(?:\.\d)?)\s*\n\s*([^\n]{4,120})", eng):
        if m.group(1) not in seen:
            seen.add(m.group(1))
            out.append({"id": m.group(1), "title": m.group(2).strip()})
    return out[:60]


def amendment_instructions(seg: str) -> list[dict]:
    out = []
    for m in re.finditer(r"(Add|Insert)\s+(?:the\s+following\s+)?(?:new\s+)?(?:clauses?|para(?:graph)?s?)\s+([\d\.,\sand]+?)\s+after\s+"
                         r"(?:clause|para(?:graph)?)\s+([\d\.]+)", seg, re.I):
        cl = [c for c in re.split(r"[,\s]+(?:and\s+)?", m.group(2).strip()) if re.match(r"\d", c)]
        out.append({"action": "add", "clauses": cl, "after": m.group(3).rstrip(".")})
    for m in re.finditer(r"(?:clause|para(?:graph)?)\s+([\d\.]+)[^\n]{0,60}?\n?[^\n]{0,30}?(substitut\w+|delet\w+|omit\w+|correct\w+)", seg, re.I):
        act = m.group(2).lower()
        action = "substitute" if act.startswith("substitut") else "delete" if act[:4] in ("dele", "omit") else "correct"
        out.append({"action": action, "clause": m.group(1).rstrip(".")})
    return out[:80]


def circular_fields(eng: str) -> dict:
    head = eng[:5000]
    ref = re.search(r"\bNo\.?\s*[:\-]?\s*((?:RT|R\.T\.|NT|RW|H|S|T|A|Q|G)[\w\-/\.\(\) ]{4,50}?\d{2,4}(?:-[A-Z\(\)]+)?)", head)
    subj = re.search(r"Sub(?:ject)?\s*[:\-–.]\s*(.{5,300}?)(?:\n\s*\n|Sir|Madam|\n\s*\d\.)", head, re.I | re.S)
    d = P.parse_date(head)
    to = re.search(r"\nTo,?\s*\n(.{5,500}?)\n\s*(?:Sub|Subject)", head, re.I | re.S)
    addressees = [clean(x) for x in to.group(1).split("\n") if len(x.strip()) > 3][:10] if to else []
    return {"ref_no": clean(ref.group(1)) if ref else None, "date": d.isoformat() if d else None,
            "subject": clean(subj.group(1))[:300] if subj else None, "addressees": addressees}


def generic_fields(eng: str, name: str) -> dict:
    lines = [ln.strip() for ln in eng[:3000].splitlines() if 12 < len(ln.strip()) < 200 and not ln.strip().startswith("<<<")]
    d = P.parse_date(eng[:4000])
    return {"title": lines[0] if lines else None, "date": d.isoformat() if d else None,
            "references": P.find_references(eng[:60000], ("AIS", "IS", "UN_R"))[:40], "file_name": name or None}


def bis_catalogue_rows(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        txt = f.read()
    for r in csv.DictReader(io.StringIO(txt)):
        keys = {k.lower().strip(): v for k, v in r.items() if k}
        isn = next((v for k, v in keys.items() if k.startswith("is") and v), None) or next(iter(keys.values()), None)
        title = next((v for k, v in keys.items() if "title" in k), None)
        if isn:
            rows.append({"is_no": isn.strip()[:60], "title": (title or "").strip()[:300] or None})
    return rows


# Motor vehicle law. Titles are often OCR-damaged ("MOTOR VEHIC ES", "VEHICIJES", "Noor Vehicles"), so the opening
# lines are checked too. The 1914 and 1939 Acts were repealed by the Motor Vehicles Act, 1988; Acts amending them
# are history (superseded), the 1988 Act, its amendments and the CMVR 1989 are in force.
MV_TITLE = re.compile(r"motor\W{0,3}vehi\w{0,5}\W{0,3}e?s?\s*(\(\s*amendment\s*\)\s*)?act|central\s+motor\s+vehicles\s+rules", re.I)
MV_AMENDS = re.compile(r"(amend|menl)\w*\s+the\s+(indian\s+)?[\w~]{2,7}\s+vehicles\s+act,?\s*(\d{4})", re.I)
MV_AMENDMENT_ACT = re.compile(r"motor\s+vehicles\s*\(\s*amendment\s*\)\s*act", re.I)


def motor_vehicle_law(title: str, head: str) -> str | None:
    """'in_force' / 'repealed' for the Motor Vehicles Acts and CMVR, None for any other Act."""
    amends = MV_AMENDS.search(head)
    if amends:
        return "repealed" if int(amends.group(3)) < 1988 else "in_force"
    if not (MV_TITLE.search(title) or MV_AMENDMENT_ACT.search(head[:1500])):
        return None
    years = [int(y) for y in re.findall(r"\b(1[89]\d\d|20\d\d)\b", title)]
    if "rules" in title.lower() or (years and max(years) >= 1988):
        return "in_force"
    return "repealed" if years else "in_force"


# ====================================================================== deterministic extraction per document
def deterministic(doc: dict, pages: list[PageText], df: dict, file_row: dict, names: list[str]) -> tuple[dict, dict, dict]:
    """Returns (columns, data, confidence)."""
    dc = DocClass(doc["doc_class"])
    a, b = df["page_from"] or 1, df["page_to"] or (pages[-1].page if pages else 1)
    eng = english_text(pages, a, b)
    cols: dict = {}
    data: dict = dict(doc["data"] or {})
    conf: dict = {}
    if dc.is_notification:
        op = operative_text(eng)
        targets, notifs = amends_targets(op)
        powers = [f"MV Act s.{m.group(1)}" for m in POWERS.finditer(op[:3000])]
        cm = COMMENCE.search(op)
        data.update({k: v for k, v in {
            "signatory": signatory(op), "powers": list(dict.fromkeys(powers)),
            "commencement": ("date of publication" if cm and "publication" in cm.group(1).lower() else clean(cm.group(1)) if cm else None),
            "comment_period_days": comment_days(op) if doc["status"] == "draft" else None,
            "amends_targets": targets, "amends_notification": notifs,
            "references": notification_references(op, doc["canonical_id"]),
        }.items() if v not in (None, [], {})})
        cats = categories_of(op[:30000])
        named = called_title(op) or called_title(eng)
        subj = subject_line(op, targets)
        if not subj or (subj.startswith("Amends ") and "Rule" not in subj and named):
            subj = named or subj  # "Amends CMVR" says less than "Central Motor Vehicles (Amendment) Rules, 2026"
        if named and is_junk_title(doc.get("official_title")):
            cols["official_title"] = named
        cols["subject"] = subj
        text_for_tags = op
    elif dc in (DocClass.AIS_STANDARD, DocClass.SAFETY_STANDARD_LEGACY):
        scope = scope_section(eng)
        trans = transitional_section(eng)
        deemed = [P.ais_canonical_from_text(m.group(1)) for m in
                  re.finditer(r"deemed\s+to\s+(?:comply|be\s+in\s+compliance)\s+with\s+(?:the\s+(?:requirements\s+of\s+)?)?(AIS[\s\-:]*\d{3}[^,;.\n]{0,25})", eng, re.I)]
        unr = sorted({f"UN R{int(m.group(1))}" for m in P.REF_PATTERNS["UN_R"].finditer(eng[:20000])})
        title = ais_title(eng)
        if is_junk_title(title):
            title = own_ais_title(eng, doc.get("number")) or title
        cats = categories_of(scope) if scope else categories_of(eng[:8000])
        data.update({k: v for k, v in {
            "title": title, "scope_text": scope, "transitional_text": trans,
            "applicability": {"categories": cats, "raw": scope[:400]} if scope else None,
            "deemed_compliance": [d for d in dict.fromkeys(deemed) if d and d != doc["canonical_id"]],
            "based_on": unr[:10], "annexes": ais_annexes(eng),
            "references": [r for r in P.find_references(eng[:120000], ("AIS", "IS", "UN_R", "ISO", "IEC"))
                           if r != doc["canonical_id"]][:80],
            "cover_month": doc["doc_date"].strftime("%Y-%m") if doc.get("doc_date") else None,
        }.items() if v not in (None, [], {})})
        cols["official_title"] = title if is_junk_title(doc.get("official_title")) else doc["official_title"]
        cols["subject"] = title
        conf.update({"scope_text": 0.8 if scope else 0.0, "title": 0.7 if title else 0.0})
        text_for_tags = (scope or "") + " " + (title or "") + " " + eng[:20000]
    elif dc in (DocClass.AIS_AMENDMENT, DocClass.AIS_CORRIGENDUM):
        data["instructions"] = amendment_instructions(eng) or data.get("instructions", [])
        base = doc["data"].get("amends") if doc.get("data") else None
        cols["subject"] = f"{'Amendment' if dc == DocClass.AIS_AMENDMENT else 'Corrigendum'} "\
                          f"{doc.get('amendment_no') or doc.get('corrigendum_no') or ''} to {base}".strip()
        cats = []
        text_for_tags = eng[:15000]
    elif dc == DocClass.AIS_DRAFT:
        title = ais_title(eng)
        data["title"] = title if not is_junk_title(title) else (own_ais_title(eng, doc.get("number")) or title)
        data["scope_text"] = scope_section(eng)
        cats = categories_of(data["scope_text"] or eng[:8000])
        cols["subject"] = data.get("title")
        text_for_tags = eng[:20000]
    elif dc in (DocClass.CIRCULAR_OM, DocClass.GUIDELINE_POLICY):
        cf = circular_fields(eng)
        data.update({k: v for k, v in cf.items() if v not in (None, [], {})})
        cols["subject"] = cf.get("subject") or generic_fields(eng, names[0] if names else "")["title"]
        cats = categories_of(eng[:20000])
        text_for_tags = eng[:30000]
    elif dc == DocClass.BIS_CATALOGUE:
        data["rows"] = bis_catalogue_rows(str(open_local(file_row["storage_path"])))
        cols["subject"] = f"BIS automotive standards catalogue ({len(data['rows'])} standards)"
        cats, text_for_tags = [], ""
    elif dc == DocClass.TAP_DOCUMENT:
        data.update({"doc_no": "MoRTH/CMVR/TAP-115/116", "issue": 4})
        cols["subject"] = "Document on test method, testing equipment and related procedures for type approval (CMVR-TAP-115/116)"
        cols["official_title"] = "MoRTH/CMVR/TAP-115/116 Issue 4"
        cats = categories_of(eng[:20000])
        text_for_tags = eng[:20000]
    elif dc == DocClass.FORM_TEMPLATE:
        cols["subject"] = data.get("purpose")
        cats, text_for_tags = [], eng[:5000]
    elif dc == DocClass.TIS_STANDARD:
        # a Thai TISI page: every field is read from its Thai text (regtrack/pipeline/thai.py); the English
        # keyword vocabularies (usage, powertrains, domains) do not apply to it
        allt = full_text(pages, a, b)
        if file_row.get("ext") == "pdf":
            # the standard's full text (linked from its TISI page): the page's fields stay, the PDF fills gaps only
            data.update({k: v for k, v in thai.full_text_fields(allt).items() if v and not data.get(k)})
            cover = thai.english_cover_title(allt)
            # TISI's own English beats a machine translation; a better reading of the cover replaces an older one
            if cover and (data.get("title_en_source") != "cover" or data.get("title_en") != cover):
                data.update(title_en=cover, title_en_source="cover")
        else:
            data.update({k: v for k, v in thai.fields_of(allt).items() if v not in (None, [], {})})
        cols["subject"] = data.get("title")  # Thai title; the portal shows the English one first (official_title)
        if data.get("title_en"):
            cols["official_title"] = data["title_en"]
        title, scope = data.get("title"), data.get("scope_text")
        cats = thai.categories_from(title, scope)
        text_for_tags = ""
        cols["domains"], cols["powertrains"] = thai.domains_from(title, scope), thai.powertrains_from(title, scope)
        if data.get("effective_date"):
            cols["effective_date"] = date.fromisoformat(data["effective_date"])  # วันที่มีผลบังคับใช้
        conf["subject"] = 0.9 if cols["subject"] else 0.0
    elif dc in (DocClass.MINISTERIAL_REGULATION, DocClass.DLT_NOTIFICATION, DocClass.TH_ACT, DocClass.GAZETTE_NOTICE):
        # a Thai Act / ministerial regulation / DLT notification saved by hand: rules only (thai.law_identity); the
        # LLM is not asked (its category codes are India's)
        allt = full_text(pages, a, b)
        n = thai.law_identity(allt, dc.value) or {}
        data.update({k: v for k, v in {"title": n.get("title"), "ref_no": n.get("canonical_id"),
                                       "date": n["date"].isoformat() if n.get("date") else None,
                                       "file_name": names[0] if names else None}.items() if v})
        cols["subject"] = n.get("title")
        head = thai.thai_digits(allt[:8000])
        cats = thai.categories_from(n.get("title"), head)
        if not cats and re.search(r"รถ|vehicle", head, re.I):
            cats = ["ALL"]  # a motor-vehicle law naming no category applies to all motor vehicles (CLAUDE.md)
        cols["domains"] = thai.law_domains(allt)
        text_for_tags = ""
    elif dc in (DocClass.MY_ACT, DocClass.MY_SUBSIDIARY_LEGISLATION):
        # a Malaysian Act / P.U.(A) regulation (Malay, often with English pages): identity, title and dates from its
        # own first page (malaysia.legal_identity); the Malay cover is not an "English" page, so the full text
        allt = full_text(pages, a, b)
        leg = malaysia.legal_identity(allt) or {}
        data.update({k: v for k, v in {"title": leg.get("title"), "ref_no": leg.get("ref_no"),
                                       "date": leg["published"].isoformat() if leg.get("published") else None,
                                       "file_name": names[0] if names else None}.items() if v})
        # official Malay title kept; the official English name (fixed legal wording, no LLM) is what the portal shows
        cols["official_title"] = leg.get("title")
        cols["subject"] = malaysia.english_legal_title(leg.get("kind", ""), leg.get("number"), leg.get("title")) or leg.get("title")
        if leg.get("in_force"):
            cols["effective_date"] = leg["in_force"]
        cats = malaysia.categories_of(allt[:20000])
        text_for_tags = allt[:30000]
    elif dc in (DocClass.MY_GUIDELINE, DocClass.MY_FORM):
        # a JPJ / DOE page (its own <title>) or a linked PDF/DOCX; UNECE category words (malaysia.py)
        g = generic_fields(eng, names[0] if names else "")
        malay = None
        if file_row.get("ext") in ("html", "htm"):
            title = malaysia.page_title(eng) or g.get("title")
        else:  # a PDF / DOCX: its title block (letterheads, form codes skipped), JPJ Malay titles by their English name
            title, malay = malaysia.document_title(full_text(pages, a, b))
            title = title or g.get("title")
        refs = [f"{c['component']}: {', '.join(c['refs'])}" for c in malaysia.cta_components(eng)]
        data.update({k: v for k, v in {"title": title, "references": refs, "file_name": names[0] if names else None}.items()
                     if v not in (None, [], {})})
        cols["subject"] = title
        if malay:
            cols["official_title"] = malay
        cats = malaysia.categories_of(eng[:20000])
        text_for_tags = eng[:30000]
    else:
        g = generic_fields(eng, names[0] if names else "")
        model_keys = set(model_for(dc).model_fields)
        data.update({k: v for k, v in g.items() if v not in (None, [], {}) and k in model_keys})
        cols["subject"] = g.get("title")
        if dc in (DocClass.ACT, DocClass.CONSOLIDATED_RULES) and is_junk_title(cols["subject"]):
            listed = [clean_listing(n) for n in names if n]
            listed = [t for t in listed if not is_junk_title(t) and not re.fullmatch(r"[\w.\-() ]{0,20}", t)]
            m = ACT_TITLE.search(clean(eng[:4000]))
            if listed:
                cols["subject"] = max(listed, key=len)[:240]
            elif m and motor_vehicle_law(m.group(1), eng[:2000]):
                cols["subject"] = re.sub(r"\s+", " ", m.group(1)).title()
        cats = categories_of(eng[:20000]) if dc != DocClass.OFF_TOPIC else []
        text_for_tags = eng[:30000]
    if dc not in (DocClass.OFF_TOPIC, DocClass.TIS_STANDARD) + (DocClass.MINISTERIAL_REGULATION, DocClass.DLT_NOTIFICATION, DocClass.TH_ACT, DocClass.GAZETTE_NOTICE):
        cols["usage"] = P.find_usage(text_for_tags[:30000])
        cols["powertrains"] = P.find_powertrains(text_for_tags[:30000], min_hits=2)
        cols["domains"] = find_domains(text_for_tags)
    if dc in (DocClass.ACT, DocClass.CONSOLIDATED_RULES):
        law = motor_vehicle_law(f"{cols.get('subject') or ''} {(names[0] if names else '').replace('_', ' ')}", eng[:2000])
        if law:
            # the Motor Vehicles Act / CMVR govern all motor vehicles; category words inside them are only mentions
            cats = ["ALL"]
            if law == "repealed":
                cols["status"] = Status.SUPERSEDED.value
    cols["vehicle_categories"] = cats
    cols["in_scope"] = in_scope(cats, file_row.get("country")) if cats else (None if dc == DocClass.OFF_TOPIC else False)
    conf["vehicle_categories"] = 0.7 if cats else 0.0
    return cols, data, conf


HEREBY = re.compile(r"hereby\s+(specifies|notifies|exempts|directs|appoints|extends|declares|prescribes|"
                    r"authori[sz]es|constitutes|rescinds|amends|corrects)\s+(.{15,220}?)(?:[;:]|,\s*namely|\.\s|$)", re.I)


def subject_line(op: str, targets: list[str] | None = None) -> str | None:
    """Deterministic one-liner: the operative 'hereby specifies ...' clause, else the rules it amends."""
    t = clean(op[:6000])
    m = HEREBY.search(t)
    if m and not re.match(r"(?:the\s+)?following\s+(?:rules|amendments)", m.group(2), re.I):
        return f"{m.group(1).capitalize()} {m.group(2).strip()}"[:240]
    rules = [x for x in (targets or []) if x.startswith("CMVR Rule")]
    if rules:
        return ("Amends " + ", ".join(rules[:6]))[:240]
    if targets:
        return ("Amends " + ", ".join(targets[:4]))[:240]
    return None


# ====================================================================== Qwen
class FieldConfidence(BaseModel):
    field: str
    confidence: float = Field(ge=0, le=1)


def llm_model_for(dc: DocClass) -> type[BaseModel]:
    base = model_for(dc)
    return create_model(
        f"{base.__name__}Extraction",
        data=(base, ...),
        subject=(str | None, Field(None, description="One-line plain English summary of what the document does")),
        vehicle_categories=(list[str], Field(default_factory=list, description="Codes from: L1 L2 L3 L4 L5 L6 L7 M1 M2 M3 "
                                                                                "N1 N2 N3 O T CEV QUADRICYCLE E_RICKSHAW E_CART ALL. "
                                                                                "ALL only when it applies to all motor vehicles.")),
        field_confidence=(list[FieldConfidence], Field(default_factory=list)),
    )


SYSTEM = ("You extract structured data from Indian vehicle-regulation documents (MoRTH Gazette notifications, AIS "
          "standards). Use only facts present in the text. Dates as YYYY-MM-DD. Leave a field empty when the text "
          "does not state it. Never invent standard numbers.")


def llm_text(dc: DocClass, eng: str) -> str:
    if dc in (DocClass.AIS_STANDARD, DocClass.AIS_DRAFT):
        parts = [eng[:6000], scope_section(eng) or "", transitional_section(eng) or ""]
        return "\n\n".join(p for p in parts if p)[:MAX_LLM_CHARS]
    return eng[:MAX_LLM_CHARS]


def llm_extract(doc: dict, eng: str):
    dc = DocClass(doc["doc_class"])
    model = llm_model_for(dc)
    return llm.structured(model, SYSTEM, f"doc_class={dc.value} canonical_id={doc['canonical_id']}\n\n{llm_text(dc, eng)}")


class IdentityCheck(BaseModel):
    number: str | None = Field(None, description="G.S.R./S.O. number with (E), or AIS code")
    date: str | None = Field(None, description="Date of the notification/issue YYYY-MM-DD")
    status: str | None = Field(None, description="draft or final")


def in_double_sample(canonical_id: str) -> bool:
    return int(hashlib.sha256(canonical_id.encode()).hexdigest(), 16) % 10 == 0


def merge_llm(dc: DocClass, data: dict, cols: dict, conf: dict, r, cc: str | None = None) -> list[str]:
    """Deterministic values win for fixed-format fields; Qwen fills the rest. Returns needs_check fields."""
    fixed = {"series", "number", "date", "gazette", "file_no", "draft_ref", "amendment_no", "corrigendum_no", "amends"}
    needs: list[str] = []
    llm_data = r.data.model_dump(exclude_none=True)
    for k, v in llm_data.items():
        if v in ([], {}, None):
            continue
        if k in fixed and data.get(k) not in (None, [], {}):
            if data.get(k) != v:
                needs.append(k)
            continue
        if data.get(k) in (None, [], {}) or k in ("provisions", "instructions", "scope_text", "transitional_text"):
            data[k] = v
    if r.subject:
        cols["subject"] = r.subject[:300]
    if r.vehicle_categories and not cols.get("vehicle_categories"):
        cats = [P.norm_category(c) or c for c in r.vehicle_categories]
        cols["vehicle_categories"] = [c for c in dict.fromkeys(P.expand_letters(cats))]
        cols["in_scope"] = in_scope(cols["vehicle_categories"], cc)
        conf["vehicle_categories"] = 0.6
    for fc in r.field_confidence:
        conf[fc.field] = round(fc.confidence, 2)
    return needs


# ====================================================================== stage
def stage_extract(conn: psycopg.Connection, f: dict, use_llm: bool = True) -> str:
    pages = load_pages(f["sha256"])
    names = [r["listing_title"] for r in R.listings_of_file(conn, f["id"]) if r["code"] == "LOCAL_SEED"]
    for df in R.parts_of_file(conn, f["id"]):
        doc = R.get_document(conn, df["document_id"])
        if not df["is_best_copy"] and doc["extraction"] and doc["doc_class"] != DocClass.TIS_STANDARD:
            continue  # extract from the best copy only; other copies are kept as files (a TIS summary page
            #           always is: its fields win over the full-text PDF's, whichever file comes first)
        extract_document(conn, doc, df, f, pages, names, use_llm)
    from regtrack.pipeline.dbutil import set_stage

    set_stage(conn, f["id"], "parsed")
    return "parsed"


LISTING_NOISE = re.compile(r"^\d{4}-\d{2}-\d{2}_|\.pdf$|_[0-9a-f]{8}$|_\d$", re.I)
LISTING_PREFIX = re.compile(r"^\s*(?:G\.?\s*S\.?\s*R\.?|S\.?\s*O\.?)\s*\d{1,5}\s*\(?\s*E?\s*\)?\s*"
                            r"(?:dated\s+)?(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\s*)?(?:regarding|-|–|:)?\s*", re.I)


def clean_listing(raw: str) -> str:
    t = LISTING_NOISE.sub("", raw.strip())  # dates / extension / hash suffix first, while the underscores are still there
    t = LISTING_NOISE.sub("", t).replace("_", " ").strip()
    t = re.sub(r"\s*\((?:Last\s+date|Date\s+of\s+hosting)[^)]*\)", "", t, flags=re.I)
    t = re.sub(r"^\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+,?\s+\d{4}\s*(?:regarding\s+)?", "", t, flags=re.I)
    return LISTING_PREFIX.sub("", t).strip(" -–:.")


def ais_listing_matches(doc: dict, lr: dict) -> bool:
    code = lr.get("code") or ""
    m = re.search(r"AIS[\s\-]*(\d{3})", code)
    if not m or not doc.get("number") or int(m.group(1)) != int(re.sub(r"\D", "", str(doc["number"])) or 0):
        return False
    part = re.search(r"Part\s*(\d+)", code, re.I)
    if (str(doc.get("part") or "") or None) != (part.group(1) if part else None):
        return False
    return (lr.get("tab") == "Draft" or "draft" in code.lower()) == (doc.get("doc_class") == "AIS_DRAFT" or doc.get("status") == "draft")


def listing_subject(conn: psycopg.Connection, doc: dict, file_id: int) -> str | None:
    """A human description from the source listings, used only when the content gives none. Rule 5: listing titles never
    give identity, and 6 MoRTH titles name the wrong notification - so a title that names any number other than this
    document's own is skipped."""
    from regtrack.pipeline.identity import title_notification_ids

    rows = R.listings_of_file(conn, file_id)
    num = re.match(r"\d+", str(doc.get("number") or ""))
    own = (P.series_code(doc["series"]) if doc.get("series") else None, str(int(num.group(0))) if num else None)
    numbered = doc.get("series") in ("G.S.R.", "S.O.", "GSR", "SO") and own[1] is not None
    best = None
    for r in rows:
        for raw in (r["listing_title"], (r["listing_raw"] or {}).get("title")):
            if not raw:
                continue
            ids = title_notification_ids(raw)
            if (ids and own not in ids) or (numbered and own not in ids):
                continue  # names another notification, or does not name this one
            lr = r["listing_raw"] or {}
            if str(doc.get("doc_class", "")).startswith("AIS_"):
                if not ais_listing_matches(doc, lr):
                    continue
                if raw is r["listing_title"]:
                    continue  # ARAI's listing_title is the code; the description is in listing_raw.title
            t = clean_listing(raw)
            if not is_junk_title(t) and not re.fullmatch(r"[\w.\-() ]{0,20}", t) and (best is None or len(t) > len(best)):
                best = t
    return best[:240] if best else None


def extract_document(conn: psycopg.Connection, doc: dict, df: dict, f: dict, pages: list[PageText], names: list[str],
                     use_llm: bool = True) -> None:
    dc = DocClass(doc["doc_class"])
    cols, data, conf = deterministic(doc, pages, df, f, names)
    data.pop("subject_source", None)  # provenance belongs in extraction (an older version wrote it into data)
    subject_source = None
    if dc in (DocClass.AIS_STANDARD, DocClass.AIS_DRAFT, DocClass.SAFETY_STANDARD_LEGACY) and not AIS_DRAFT_COVER_TITLE.match(cols.get("subject") or ""):
        alt = listing_subject(conn, doc, f["id"])
        if alt:
            cols["subject"] = alt
            data["title"] = alt
            subject_source = "ARAI listing (code-matched)"
            conf["subject"] = 0.8
            if dc != DocClass.AIS_DRAFT and is_junk_title(doc.get("official_title")):
                cols["official_title"] = alt
    if dc not in (DocClass.OFF_TOPIC, DocClass.AIS_AMENDMENT, DocClass.AIS_CORRIGENDUM, DocClass.TIS_STANDARD) \
            and is_junk_title(cols.get("subject")):
        alt = listing_subject(conn, doc, f["id"])
        if alt:
            cols["subject"] = alt
            subject_source = "listing"
            conf["subject"] = 0.4
    if dc in (DocClass.AIS_AMENDMENT, DocClass.AIS_CORRIGENDUM) and not cols.get("vehicle_categories") and data.get("amends"):
        # an amendment applies to the vehicles of the standard it amends (same rule as link.link_ais)
        base = R.find_document(conn, data["amends"])
        if base and base["vehicle_categories"]:
            cols.update(vehicle_categories=base["vehicle_categories"], in_scope=base["in_scope"],
                        domains=cols.get("domains") or base["domains"], powertrains=cols.get("powertrains") or base["powertrains"])
            conf["vehicle_categories"] = 0.6
    extraction = {"model": "rules", "rules": RULES_VERSION, "prompt": None, "confidence": conf, "needs_check": [],
                  "source_file": f["sha256"], "pages": [df["page_from"], df["page_to"]]}
    if subject_source:  # where the subject line came from when the content gave none
        extraction["subject_source"] = subject_source
    old = doc["extraction"] or {}
    if old.get("model") not in (None, "rules"):  # keep an earlier Qwen result for this document
        extraction.update({k: old[k] for k in ("model", "prompt", "agreement") if k in old})
        data = {**data, **{k: v for k, v in (doc["data"] or {}).items() if k in ("provisions", "instructions")}}
    # TIS_STANDARD: a one-page TISI summary in Thai, read completely by the rules (thai.py)
    needs_llm = dc not in (DocClass.OFF_TOPIC, DocClass.FORM_TEMPLATE, DocClass.BIS_CATALOGUE, DocClass.AIS_FORM_TABLE,
                           DocClass.REPORT, DocClass.TAP_DOCUMENT, DocClass.TIS_STANDARD, DocClass.MY_ACT,
                           DocClass.MY_SUBSIDIARY_LEGISLATION) + (DocClass.MINISTERIAL_REGULATION, DocClass.DLT_NOTIFICATION, DocClass.TH_ACT, DocClass.GAZETTE_NOTICE)
    if needs_llm and old.get("model") in (None, "rules"):
        ok = use_llm and llm.reachable()[0]
        if ok:
            eng = english_text(pages, df["page_from"], df["page_to"])
            try:
                r = llm_extract(doc, eng)
                extraction["needs_check"] += merge_llm(dc, data, cols, conf, r, f.get("country"))
                extraction.update(model=get_settings().llm_model, prompt=PROMPT_VERSION)
                if in_double_sample(doc["canonical_id"]):
                    extraction["agreement"] = double_check(doc, eng, data)
            except llm.LLMUnavailable:
                extraction["llm_pending"] = True
            except Exception as e:  # noqa: BLE001  a bad LLM answer is a quality flag, not a crash
                extraction["llm_error"] = f"{type(e).__name__}: {str(e)[:200]}"
                extraction["llm_pending"] = True
        else:
            extraction["llm_pending"] = True
    errors = validate_data(dc.value, data)
    if errors:
        extraction["needs_check"].append("data")
        add_flag(conn, "regulation", doc["id"], FlagRule.SCHEMA_VIOLATION, {"errors": errors[:10]})
    cats = cols.get("vehicle_categories") or []
    if not cats and (dc.is_notification or dc in (DocClass.AIS_STANDARD, DocClass.TIS_STANDARD)):
        extraction["needs_check"].append("vehicle_categories")
        add_flag(conn, "regulation", doc["id"], FlagRule.NO_VEHICLE_CATEGORY, {})
    extraction["needs_check"] = sorted(set(extraction["needs_check"]))
    if f.get("ext") in ("html", "htm") and dc in (DocClass.MY_GUIDELINE, DocClass.MY_FORM):
        data.pop("date", None)  # a web page has no publication date: "Updated Date" / copyright stamps are not one
    values = {**{k: v for k, v in cols.items() if v is not None or k == "in_scope"}, "data": Jsonb(data),
              "extraction": Jsonb(extraction)}
    if doc["doc_date"] is None and data.get("date") and re.fullmatch(P.ISO_DATE_RE, str(data["date"])):
        d = date.fromisoformat(data["date"])
        if d <= date.today():  # a later date in the text is a validity/implementation date, not the document's
            values["doc_date"] = d
            values["doc_date_precision"] = "day"
    final_date = values.get("doc_date") or doc["doc_date"]
    if final_date and final_date > date.today():
        extraction["needs_check"] = sorted(set(extraction["needs_check"]) | {"doc_date"})
        values["extraction"] = Jsonb(extraction)
        add_flag(conn, "regulation", doc["id"], FlagRule.DOC_DATE_IN_FUTURE, {"doc_date": str(final_date)})
    if not doc.get("issuer"):
        # no ministry header in the text: the publishing source is the issuer (provenance, not identity)
        listed = R.listings_of_document(conn, doc["id"])
        srcs = {r["code"] for r in listed}
        folders = {((r["listing_raw"] or {}).get("folder") or "")[:2] or None for r in listed}
        issuer = ("AISC/ARAI" if srcs & {"ARAI_AIS", "ARAI_TAP"} or folders & {"07", "17", "18"} else
                  "BIS" if "21" in folders else "MoPNG" if "29" in folders else
                  "MoRTH" if srcs & {"MORTH_API", "EGAZETTE"} or folders & {"05", "06", "11", "27", "28"} else None)
        if issuer:
            values["issuer"] = issuer
            extraction["confidence"]["issuer"] = 0.5
    # do not let a weaker copy blank existing values
    for k in ("subject", "official_title"):
        if values.get(k) in (None, "") and doc.get(k):
            values.pop(k, None)
    R.update_document(conn, doc["id"], values, touch=True)


def double_check(doc: dict, eng: str, data: dict) -> dict:
    """Second, independent prompt for identity/status/date on a 10% sample; agreement per field."""
    r = llm.structured(IdentityCheck, "Read the document header and answer precisely.",
                       f"What is the number, date and status (draft/final) of this document?\n\n{eng[:6000]}")
    norm = lambda s: re.sub(r"[^0-9a-z]", "", (s or "").lower())  # noqa: E731
    return {"number": norm(r.number) in norm(doc["canonical_id"]) if r.number else None,
            "date": (r.date == (data.get("date") or (doc["doc_date"].isoformat() if doc["doc_date"] else None))) if r.date else None,
            "status": (r.status or "").lower().startswith(doc["status"][:5]) if r.status else None}


def enrich_pending(conn: psycopg.Connection, limit: int = 200) -> int:
    """Run the Qwen pass for documents parsed while the LLM was down (llm_pending).

    What the portal shows comes first (current, in-scope), documents whose last attempt failed go last, and each
    document is committed on its own, so an interrupted run keeps what it has done."""
    if not llm.reachable()[0]:
        return 0
    rows = conn.execute(
        """SELECT p.regulation_id, p.document_id AS file_id, p.page_from, p.page_to FROM regulations g
           JOIN document_parts p ON p.regulation_id=g.id AND p.is_best_copy
           WHERE (g.extraction->>'llm_pending')::boolean AND """ + country.region_sql("g") + """
           ORDER BY g.in_scope DESC, g.is_current DESC, g.extraction ? 'llm_error', g.updated_at LIMIT %s""",
        (limit,)).fetchall()
    conn.commit()
    n = 0
    for row in rows:
        doc = R.get_document(conn, row["regulation_id"])
        f = R.get_file(conn, row["file_id"])
        df = {"page_from": row["page_from"], "page_to": row["page_to"], "is_best_copy": True}
        d = dict(doc)
        d["extraction"] = {**(doc["extraction"] or {}), "model": None}
        try:
            extract_document(conn, d, df, f, load_pages(f["sha256"]), [], use_llm=True)
            conn.commit()
        except Exception:  # noqa: BLE001  one bad document must not undo the others
            conn.rollback()
            log.exception("Qwen pass failed for regulation %s", row["regulation_id"])
            continue
        n += 1
        if (d2 := R.get_document(conn, row["regulation_id"])) and (d2["extraction"] or {}).get("llm_pending") \
                and not llm.reachable()[0]:
            break  # the LLM went away mid-run: leave the rest for the next run
    return n
