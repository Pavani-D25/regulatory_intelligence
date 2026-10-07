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

from regtrack import llm
from regtrack.config import get_settings
from regtrack.db import Jsonb
from regtrack.models import model_for
from regtrack.models.enums import DocClass, FlagRule
from regtrack.pipeline import patterns as P
from regtrack.pipeline.dbutil import add_flag, update_if_changed
from regtrack.pipeline.text import PageText, english_text, load_pages
from regtrack.validators import in_scope, validate_data
from regtrack.vocab import find_domains

log = logging.getLogger(__name__)
PROMPT_VERSION = "extract_v1"
RULES_VERSION = "rules_v1"
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


def ais_title(eng: str) -> str | None:
    head = clean(eng[:2500])
    m = re.search(r"AUTOMOTIVE\s+INDUSTRY\s+STANDARD\s+(.{10,250}?)\s+(?:AIS[\s\-:]*\d{3}|PRINTED\s+BY|"
                  r"Date\s+of\s+hosting|Last\s+date|(?:January|February|March|April|May|June|July|August|September|"
                  r"October|November|December)\s+\d{4})", head, re.I)
    if m:
        return m.group(1).strip(" :-")[:250]
    lines = [ln.strip() for ln in eng[:2000].splitlines() if 15 < len(ln.strip()) < 160]
    return lines[0] if lines else None


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
        cols["subject"] = doc.get("official_title") or subject_line(op, targets)
        text_for_tags = op
    elif dc in (DocClass.AIS_STANDARD, DocClass.SAFETY_STANDARD_LEGACY):
        scope = scope_section(eng)
        trans = transitional_section(eng)
        deemed = [P.ais_canonical_from_text(m.group(1)) for m in
                  re.finditer(r"deemed\s+to\s+(?:comply|be\s+in\s+compliance)\s+with\s+(?:the\s+(?:requirements\s+of\s+)?)?(AIS[\s\-:]*\d{3}[^,;.\n]{0,25})", eng, re.I)]
        unr = sorted({f"UN R{int(m.group(1))}" for m in P.REF_PATTERNS["UN_R"].finditer(eng[:20000])})
        title = ais_title(eng)
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
        cols["official_title"] = doc.get("official_title") or title
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
        data.setdefault("title", ais_title(eng))
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
        data["rows"] = bis_catalogue_rows(file_row["storage_path"])
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
    else:
        g = generic_fields(eng, names[0] if names else "")
        model_keys = set(model_for(dc).model_fields)
        data.update({k: v for k, v in g.items() if v not in (None, [], {}) and k in model_keys})
        cols["subject"] = g.get("title")
        cats = categories_of(eng[:20000]) if dc != DocClass.OFF_TOPIC else []
        text_for_tags = eng[:30000]
    if dc != DocClass.OFF_TOPIC:
        cols["usage"] = P.find_usage(text_for_tags[:30000])
        cols["powertrains"] = P.find_powertrains(text_for_tags[:30000], min_hits=2)
        cols["domains"] = find_domains(text_for_tags)
    cols["vehicle_categories"] = cats
    cols["in_scope"] = in_scope(cats) if cats else (None if dc == DocClass.OFF_TOPIC else False)
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


def merge_llm(dc: DocClass, data: dict, cols: dict, conf: dict, r) -> list[str]:
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
        cols["in_scope"] = in_scope(cols["vehicle_categories"])
        conf["vehicle_categories"] = 0.6
    for fc in r.field_confidence:
        conf[fc.field] = round(fc.confidence, 2)
    return needs


# ====================================================================== stage
def stage_extract(conn: psycopg.Connection, f: dict, use_llm: bool = True) -> str:
    pages = load_pages(f["sha256"])
    names = [r["listing_title"] for r in conn.execute(
        "SELECT fs.listing_title FROM file_sighting fs JOIN source s ON s.id=fs.source_id "
        "WHERE fs.file_id=%s AND s.code='LOCAL_SEED' ORDER BY fs.id", (f["id"],))]
    dfs = conn.execute("SELECT * FROM document_file WHERE file_id=%s ORDER BY page_from", (f["id"],)).fetchall()
    for df in dfs:
        doc = conn.execute("SELECT * FROM document WHERE id=%s", (df["document_id"],)).fetchone()
        if not df["is_best_copy"] and doc["extraction"]:
            continue  # extract from the best copy only; other copies are kept as files
        extract_document(conn, doc, df, f, pages, names, use_llm)
    from regtrack.pipeline.dbutil import set_stage

    set_stage(conn, f["id"], "parsed")
    return "parsed"


def extract_document(conn: psycopg.Connection, doc: dict, df: dict, f: dict, pages: list[PageText], names: list[str],
                     use_llm: bool = True) -> None:
    dc = DocClass(doc["doc_class"])
    cols, data, conf = deterministic(doc, pages, df, f, names)
    extraction = {"model": "rules", "rules": RULES_VERSION, "prompt": None, "confidence": conf, "needs_check": [],
                  "source_file": f["sha256"], "pages": [df["page_from"], df["page_to"]]}
    old = doc["extraction"] or {}
    if old.get("model") not in (None, "rules"):  # keep an earlier Qwen result for this document
        extraction.update({k: old[k] for k in ("model", "prompt", "agreement") if k in old})
        data = {**data, **{k: v for k, v in (doc["data"] or {}).items() if k in ("provisions", "instructions")}}
    needs_llm = dc not in (DocClass.OFF_TOPIC, DocClass.FORM_TEMPLATE, DocClass.BIS_CATALOGUE, DocClass.AIS_FORM_TABLE,
                           DocClass.REPORT, DocClass.TAP_DOCUMENT)
    if needs_llm and old.get("model") in (None, "rules"):
        ok = use_llm and llm.reachable()[0]
        if ok:
            eng = english_text(pages, df["page_from"], df["page_to"])
            try:
                r = llm_extract(doc, eng)
                extraction["needs_check"] += merge_llm(dc, data, cols, conf, r)
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
        add_flag(conn, "document", doc["id"], FlagRule.SCHEMA_VIOLATION, {"errors": errors[:10]})
    cats = cols.get("vehicle_categories") or []
    if not cats and (dc.is_notification or dc in (DocClass.AIS_STANDARD,)):
        extraction["needs_check"].append("vehicle_categories")
        add_flag(conn, "document", doc["id"], FlagRule.NO_VEHICLE_CATEGORY, {})
    extraction["needs_check"] = sorted(set(extraction["needs_check"]))
    values = {**{k: v for k, v in cols.items() if v is not None or k == "in_scope"}, "data": Jsonb(data),
              "extraction": Jsonb(extraction)}
    if doc["doc_date"] is None and data.get("date") and re.fullmatch(P.ISO_DATE_RE, str(data["date"])):
        values["doc_date"] = date.fromisoformat(data["date"])
        values["doc_date_precision"] = "day"
    # do not let a weaker copy blank existing values
    for k in ("subject", "official_title"):
        if values.get(k) in (None, "") and doc.get(k):
            values.pop(k, None)
    update_if_changed(conn, "document", {"id": doc["id"]}, values, touch=True)


def double_check(doc: dict, eng: str, data: dict) -> dict:
    """Second, independent prompt for identity/status/date on a 10% sample; agreement per field."""
    r = llm.structured(IdentityCheck, "Read the document header and answer precisely.",
                       f"What is the number, date and status (draft/final) of this document?\n\n{eng[:6000]}")
    norm = lambda s: re.sub(r"[^0-9a-z]", "", (s or "").lower())  # noqa: E731
    return {"number": norm(r.number) in norm(doc["canonical_id"]) if r.number else None,
            "date": (r.date == (data.get("date") or (doc["doc_date"].isoformat() if doc["doc_date"] else None))) if r.date else None,
            "status": (r.status or "").lower().startswith(doc["status"][:5]) if r.status else None}


def enrich_pending(conn: psycopg.Connection, limit: int = 200) -> int:
    """Run the Qwen pass for documents parsed while the LLM was down (llm_pending)."""
    if not llm.reachable()[0]:
        return 0
    rows = conn.execute(
        """SELECT d.*, df.file_id, df.page_from, df.page_to FROM document d
           JOIN document_file df ON df.document_id=d.id AND df.is_best_copy
           WHERE (d.extraction->>'llm_pending')::boolean LIMIT %s""", (limit,)).fetchall()
    n = 0
    for doc in rows:
        f = conn.execute("SELECT * FROM file_object WHERE id=%s", (doc["file_id"],)).fetchone()
        df = {"page_from": doc["page_from"], "page_to": doc["page_to"], "is_best_copy": True}
        d = dict(doc)
        d["extraction"] = {**(doc["extraction"] or {}), "model": None}
        extract_document(conn, d, df, f, load_pages(f["sha256"]), [], use_llm=True)
        n += 1
    return n
