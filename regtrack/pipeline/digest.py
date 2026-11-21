"""Detailed summary of a regulation from its own text, without the LLM (the "digest").

Every regulation gets one, whether or not Qwen has written its AI summary: an overview built from the extracted
metadata, then sections taken from the document's English text by rule (what it changes, its key requirements, the
dates it sets, the standards it cites, its contents). Nothing is invented: each item is a sentence or heading of the
document, cleaned and shortened, or a fact the pipeline already extracted (regulations.data, mandates, relations).

digest(row, text, mandates, relations, labels) -> {"overview": str, "sections": [{"title", "text"?, "items"?}], ...}
load_text(conn, regulation_id) gives the English text of the regulation's best copy (pipeline/text.py page files).
"""

from __future__ import annotations

import re
from datetime import date, datetime
from functools import lru_cache

from regtrack.pipeline.text import english_text, load_pages

MAX_TEXT = 120_000  # long acts and reports: their opening part is enough for a summary
DEV = re.compile(r"[ऀ-ॿ]")
WS = re.compile(r"\s+")
# a sentence end: . ; or : followed by a capital, an opening bracket or a quote
SPLIT = re.compile(
    r"(?<=[.;:])\s+(?=[A-Z(“\"‘])|\s+(?=\d{1,2}(?:\.\d{1,2}){1,3}\s+[A-Z][a-z])|\s+(?=[A-Z]-\d(?:\.\d+)+\s)"
)
# table column markers "(1) (2) (3)", stray quotes before them, "[F. No. ...]" file references, "namely:-"
COLS = re.compile(r"(?:\(\d{1,2}\)\s*){2,}|[“”\"]\s*(?=\(\d)|\[(?:F\.|No\.)[^\]]*\]?|\bnamely\s*:?\s*[-—–]*")
POWERTRAIN = {
    "bev": "Battery electric (BEV)",
    "hybrid": "Hybrid",
    "phev": "Plug-in hybrid",
    "hydrogen": "Hydrogen / fuel cell",
    "petrol": "Petrol",
    "diesel": "Diesel",
    "cng": "CNG",
    "lpg": "LPG",
    "ethanol_flex": "Ethanol / flex fuel",
    "biodiesel": "Biodiesel",
    "lng": "LNG",
    "methanol": "Methanol",
}
NOISE = re.compile(
    r"<<<PAGE \d+>>>|THE GAZETTE OF INDIA\s*:?\s*EXTRAORDINARY|\[PART II[^\]]*\]|PART II\s*[—-]\s*SEC(?:TION)?\.?\s*\d\s*\(\w+\)"
    r"|Page \d+ of \d+|REGISTERED NO\.[^\n]*|REGD\. NO\.[^\n]*|Uploaded by Dte\.[^\n]*|Digitally signed by[^\n]*",
    re.I,
)
BOILER = re.compile(
    r"may be called|shall come into force|copies of the (said )?Gazette|objections and suggestions|inviting objections"
    r"|shall be substituted, namely|shall be inserted, namely|following rules? further to amend|hereby makes the following"
    r"|in exercise of the powers|printed by|on behalf of|secretariat of the ais|published this standard"
    r"|permanent agency to expedite|ARAI may publish|panel and the automotive industry standards committee",
    re.I,
)
CHANGE = re.compile(
    r"shall be (substituted|inserted|added|omitted|renumbered|deleted)|\b(substitute|add|delete|insert|replace)\b"
    r"(?: the)? following",
    re.I,
)
AIS_OP = re.compile(
    r"^(?:\d+(?:\.\d+)*\s+)?((?:clause|annex|annexure|table|para(?:graph)?|figure|appendix|scope|page)\b[^\n]{0,80})",
    re.I,
)
DUTY = re.compile(r"\b(shall|must|is required to|are required to|mandatory|prohibited|not be permitted)\b", re.I)
WEIGHT = re.compile(
    r"vehicle|fitted|compl[yi]|manufactur|test|approv|certificat|register|category|emission|safety|valid", re.I
)
DATE = re.compile(
    r"(?:on and after|on or after|with effect from|w\.e\.f\.?|from|not later than|by|before|till|until|upto|up to)\s+"
    r"(?:the\s+)?(\d{1,2}(?:st|nd|rd|th)?\s+(?:day of\s+)?(?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December),?\s+\d{4})",
    re.I,
)
STANDARD = re.compile(
    r"\b(AIS[- ]?\d{3}(?:\s*\(Part\s*\d+\))?(?:\s*\(Rev\.?\s*\d+\))?|IS\s?:?\s?\d{3,5}(?:\s*\(Part\s*\d+\))?(?::\s?\d{4})?"
    r"|(?:UN\s?)?ECE\s?R\s?\d{1,3}|UN\s?R\s?\d{1,3}|ISO\s?\d{3,5}(?:-\d+)?(?::\d{4})?|TAP[- ]115/116)",
)
HEADING = re.compile(r"^(\d{1,2}(?:\.\d{1,2})?)\.?\s+([A-Z][A-Za-z ,/&()'-]{3,70})$")
CLASS_NAME = {
    "NOTIFICATION_FINAL": "a final notification",
    "NOTIFICATION_DRAFT": "a draft notification (published for comments)",
    "NOTIFICATION_ORDER": "a notification (order)",
    "NOTIFICATION_EXEMPTION": "an exemption notification",
    "NOTIFICATION_CORRIGENDUM": "a corrigendum to a notification",
    "AIS_STANDARD": "an Automotive Industry Standard (AIS)",
    "AIS_AMENDMENT": "an amendment to an Automotive Industry Standard",
    "AIS_DRAFT": "a draft Automotive Industry Standard",
    "AIS_CORRIGENDUM": "a corrigendum to an Automotive Industry Standard",
    "AIS_FORM_TABLE": "a form table of AIS-007",
    "TAP_DOCUMENT": "a TAP-115/116 testing and approval procedure document",
    "CIRCULAR_OM": "a circular / office memorandum",
    "GUIDELINE_POLICY": "a guideline / policy document",
    "ACT": "an Act",
    "CONSOLIDATED_RULES": "a consolidated text of rules",
    "REPORT": "a report",
    "FORM_TEMPLATE": "a form",
    "BIS_REGULATION": "a BIS regulation",
    "OTHER": "a regulatory document",
}
SCOPES = {
    "new_models": "new models",
    "existing_models": "existing models",
    "registered_vehicles": "registered vehicles",
}


def _d(v) -> str | None:
    if isinstance(v, (date, datetime)):
        return v.strftime("%d %b %Y")
    if isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return datetime.strptime(v, "%Y-%m-%d").strftime("%d %b %Y")
    return v


def _short(s: str, n: int = 420) -> str:
    s = WS.sub(" ", s).strip(" -–—,")
    if len(s) <= n:
        return s
    cut = s[:n].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "…"


# ------------------------------------------------------------------ text
@lru_cache(maxsize=256)
def _text_for(sha: str, page_from: int | None, page_to: int | None) -> str:
    try:
        raw = english_text(load_pages(sha), page_from, page_to)
    except OSError:
        return ""
    return clean(raw[:MAX_TEXT])


def load_text(conn, regulation_id: int) -> str:
    """English text of the regulation's best copy (its own page range), cleaned; "" when no text was extracted."""
    p = conn.execute(
        """SELECT d.checksum_sha256 AS sha, p.page_from, p.page_to FROM document_parts p
           JOIN documents d ON d.id = p.document_id WHERE p.regulation_id = %s
           ORDER BY p.is_best_copy DESC LIMIT 1""",
        (regulation_id,),
    ).fetchone()
    return _text_for(p["sha"], p["page_from"], p["page_to"]) if p else ""


def clean(raw: str) -> str:
    """Page markers, gazette headers and Hindi lines out; the English lines kept (one per line)."""
    keep = []
    for line in NOISE.sub("\n", raw).splitlines():
        s = line.strip()
        if not s:
            keep.append("")
            continue
        letters = sum(ch.isalpha() for ch in s)
        if DEV.search(s) and len(DEV.findall(s)) > letters / 3:  # a Hindi line
            continue
        if letters < 2 and not re.search(r"\d", s):
            continue
        keep.append(s)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(keep)).strip()


def sentences(text: str) -> list[str]:
    out = []
    for s in SPLIT.split(WS.sub(" ", text)):
        s = WS.sub(" ", COLS.sub(" ", s)).strip(" “”\"'-–—")
        if 25 < len(s) < 900:  # longer: a table or several clauses run together
            out.append(s)
    return out


def _uniq(items: list[str], n: int) -> list[str]:
    seen, out = set(), []
    for it in items:
        key = re.sub(r"[^a-z0-9]", "", it.lower())[:90]
        if key and key not in seen:
            seen.add(key)
            out.append(it)
        if len(out) >= n:
            break
    return out


def _readable(s: str) -> bool:
    """Not table debris or a garbled scan: mostly words."""
    words = s.split()
    if len(words) < 6:
        return False
    alpha = sum(w.strip(",.;:()").isalpha() for w in words)
    digits = sum(ch.isdigit() for ch in s)
    return alpha >= len(words) * 0.6 and digits <= len(s) * 0.12 and s.count("para.") < 2


# ------------------------------------------------------------------ sections
def changes(text: str, doc_class: str) -> list[str]:
    """What the document amends: the 'in rule x, for sub-rule (y) ... shall be substituted' operations of a notification,
    or the 'Clause 3.4: substitute ...' items of an AIS amendment, each with the start of its new text."""
    out = []
    if doc_class.startswith("AIS") or doc_class == "TAP_DOCUMENT":
        lines = [ln for ln in text.splitlines() if ln.strip()]
        for i, ln in enumerate(lines):
            m = AIS_OP.match(ln.strip())
            if not m:
                continue
            nxt = " ".join(lines[i + 1 : i + 6])
            op = re.match(r"\s*(substitute|add|delete|insert|replace|omit|modify|amend)[^:.\n]{0,120}[:.]?", nxt, re.I)
            if op:
                rest = nxt[op.end() :]
                out.append(_short(f"{m.group(1).strip().rstrip(':')}: {op.group(0).strip()} {rest}", 360))
    for s in sentences(text):
        if CHANGE.search(s) and re.search(
            r"\b(rule|sub-rule|clause|section|table|serial|entry|item|schedule|form|"
            r"paragraph|notification|annex)\b",
            s,
            re.I,
        ):
            out.append(_short(s.replace("namely:-", "").replace("namely :-", "").replace("namely:—", ""), 360))
    # a heading alone ("2.0 Clause No 3.4 (b) Substitute following text:") repeats an item above
    out = [re.sub(r",?\s+\d{1,3}\s*[a-z]?\.?$", ".", o) for o in out]  # a table's next row number at the end
    return _uniq([o for o in out if not (o.endswith(":") and len(o) < 140)], 12)


def requirements(text: str) -> list[str]:
    """The document's own operative sentences ('shall', 'must', 'mandatory'), the substantive ones first."""
    cands = [
        s
        for s in sentences(text)
        if DUTY.search(s)
        and not BOILER.search(s)
        and not CHANGE.search(s)
        and _readable(s)
        and not re.search(r"\bClause No\b|following (text|note)|definitions shall apply", s, re.I)
    ]
    cands.sort(key=lambda s: -len(WEIGHT.findall(s)))  # stable: document order within equal weight
    return [_short(s, 480) for s in _uniq(cands, 10)]


def purpose(text: str, doc_class: str) -> str | None:
    """A standard's scope, or the first substantive paragraph of an order, circular or guideline."""
    flat = WS.sub(" ", text)
    if doc_class.startswith("NOTIFICATION"):  # the enacting sentence says what is made or amended
        m = re.search(
            r"hereby (makes|issues|directs|notifies|specifies|exempts|amends)(.{20,420}?)(?:,? namely|\.\s+(?=[A-Z][a-z])|:)",
            flat,
        )
        return _short(f"The Government {m.group(1)}{m.group(2)}.", 450) if m else None
    m = re.search(r"\b(?:1\.?0?\s+)?SCOPE\b\s*:?\s*(.{60,900}?)(?=\s+(?:2\.?0?|1\.1)\s+[A-Z]|$)", flat)
    if m and _readable(m.group(1)):
        return _short(m.group(1), 700)
    m = re.search(r"(This (?:standard|document|Part|amendment)[^.]{20,400}\.)", flat, re.I)
    if m:
        return _short(m.group(1), 600)
    if doc_class in (
        "CIRCULAR_OM",
        "GUIDELINE_POLICY",
        "NOTIFICATION_ORDER",
        "NOTIFICATION_EXEMPTION",
        "OTHER",
        "REPORT",
    ):
        m = re.search(r"(?:Subject|Sub)\s*[:.-]\s*(.{20,300}?)(?:\s{2,}|Sir|Madam|$)", text)
        if m:
            return _short(m.group(1), 300)
        for s in sentences(text):
            if _readable(s) and not BOILER.search(s) and len(s) > 80:
                return _short(s, 600)
    return None


def dates_in_text(text: str) -> list[str]:
    out = []
    for s in sentences(text):
        if DATE.search(s) and _readable(s) and not BOILER.search(s) and not CHANGE.search(s):
            out.append(_short(s, 300))
    return _uniq(out, 8)


def standards(text: str, known: list[str]) -> list[str]:
    found = [WS.sub(" ", m.group(1)).replace("AIS ", "AIS-") for m in STANDARD.finditer(text)]
    return _uniq([*known, *found], 25)


def contents(text: str) -> list[str]:
    """Numbered section headings ('3.0 Definitions', '5 Requirements') of a standard or report."""
    out = []
    for ln in text.splitlines():
        m = HEADING.match(ln.strip())
        if m and not re.search(r"\b(Page|Annex [A-Z] Page)\b", m.group(2)):
            out.append(f"{m.group(1)} {m.group(2).strip().title() if m.group(2).isupper() else m.group(2).strip()}")
    return _uniq(out, 18)


def _list(v) -> list[str]:
    """A data field that is a list of strings in most shapes, a single string or a list of objects in some."""
    if isinstance(v, str):
        return [v] if v else []
    if isinstance(v, list):
        return [
            x if isinstance(x, str) else str(x.get("canonical_id") or x.get("ref") or x.get("title") or "")
            for x in v
            if x and (isinstance(x, str) or isinstance(x, dict))
        ]
    return []


def _tidy(subject: str) -> str:
    """An obligation's subject is cut from the text: table markers and the amending phrase out."""
    s = WS.sub(" ", COLS.sub(" ", subject)).strip(' “”"-–—')
    return re.sub(r"^For serial numbers? [\w ,()]+? the following entr(?:y|ies) shall be substituted,?\s*", "", s)


# ------------------------------------------------------------------ the digest
def digest(r: dict, text: str, mandates: list[dict], relations: list[dict], labels: dict) -> dict:
    """r: the regulation (pipeline names: canonical_id, doc_class, official_title, issuer, doc_date, effective_date,
    vehicle_categories, domains, powertrains, data); mandates: its in-force obligations; relations: {type, target};
    labels: {"cat": {code: label}, "domain": {code: label}}."""
    data = r.get("data") or {}
    cls = r.get("doc_class") or "OTHER"
    cid = r["canonical_id"]
    title = data.get("official_title") or r.get("official_title") or r.get("title")
    if title and (len(title) < 15 or re.search(r"\b(Secy|Secretary|Director|Joint|Under)\b\.*$", title)):
        title = None  # a signatory's designation read as the title
    cats = [
        labels["cat"].get(c, c.replace("_", "-").title() if "_" in c else c) for c in r.get("vehicle_categories") or []
    ]
    pts = [POWERTRAIN.get(x, x) for x in r.get("powertrains") or []]
    topics = [labels["domain"].get(d, d.replace("_", " ")) for d in r.get("domains") or []]

    # overview: one paragraph from the extracted facts
    parts = [f"{cid} is {CLASS_NAME.get(cls, 'a regulatory document')}"]
    if r.get("issuer"):
        parts[-1] += f" issued by {r['issuer']}"
    if r.get("doc_date"):
        parts[-1] += f" on {_d(r['doc_date'])}"
    parts[-1] += "."
    if title and title != cid:
        parts.append(f"Title: {title}.")
    if _list(data.get("amends_targets")):
        parts.append("It amends " + ", ".join(_list(data["amends_targets"])) + ".")
    dr = data.get("draft_ref") if isinstance(data.get("draft_ref"), dict) else {}
    if dr.get("canonical_id"):
        parts.append(
            f"It finalises draft {dr['canonical_id']}"
            + (f" of {_d(dr.get('date'))}" if dr.get("date") else "")
            + ", after public consultation."
        )
    if _list(data.get("powers")):
        parts.append("Legal basis: " + ", ".join(_list(data["powers"])) + ".")
    if cats:
        parts.append("Vehicle categories: " + ", ".join(cats) + ".")
    if topics:
        parts.append("Topics: " + ", ".join(topics) + ".")
    if isinstance(data.get("commencement"), str) and data["commencement"]:
        parts.append(f"It comes into force on the {data['commencement']}.")
    elif r.get("effective_date"):
        parts.append(f"It applies from {_d(r['effective_date'])}.")

    sections: list[dict] = []
    p = purpose(text, cls) if text else None
    if p:
        sections.append({"title": "Purpose and scope", "text": p})
    ch = changes(text, cls) if text else []
    if ch:
        sections.append({"title": "What it changes", "items": ch})
    req = requirements(text) if text else []
    shown = " ".join(ch).lower()  # what "What it changes" already quotes
    req = [x for x in req if x.rstrip("…").lower()[:120] not in shown]
    mandates = [{**m, "subject": _tidy(m.get("subject") or "")} for m in mandates]
    obl = []
    for m in mandates:
        conds = "; ".join(x for x in (SCOPES.get(m.get("model_scope") or "", ""), m.get("applies_to") or "") if x)
        line = (f"From {_d(m['implementation_date'])}: " if m.get("implementation_date") else "") + _short(
            m["subject"] or "", 300
        )
        if m.get("vehicle_categories"):
            line += f" (categories {', '.join(m['vehicle_categories'])}{'; ' + conds if conds else ''})"
        obl.append(line)
    if req or obl:
        sections.append({"title": "Key requirements", "items": _uniq(obl + req, 12)})
    appl = []
    if cats:
        appl.append("Vehicle categories: " + ", ".join(cats))
    if r.get("powertrains"):
        appl.append("Powertrains: " + ", ".join(pts))
    for m in mandates:
        if m.get("applies_to") and m["applies_to"] != "all":
            appl.append(f"{m['applies_to']} ({', '.join(m.get('vehicle_categories') or [])})")
    if appl:
        sections.append({"title": "Who it applies to", "items": _uniq(appl, 8)})
    dates = []
    if r.get("doc_date"):
        dates.append(f"Published: {_d(r['doc_date'])}")
    if r.get("effective_date"):
        dates.append(f"Effective / applies from: {_d(r['effective_date'])}")
    dates += [
        f"Implementation: {_d(m['implementation_date'])} – {_short(m['subject'] or '', 90)}"
        for m in mandates
        if m.get("implementation_date")
    ]
    if text and not mandates:  # the obligations already give the dates; else the document's own date sentences
        dates += dates_in_text(text)
    if dates:
        sections.append({"title": "Dates and transition", "items": _uniq(dates, 12)})
    refs = _list(data.get("references"))
    std = standards(text, refs) if text else refs
    std = [s for s in std if s.replace(" ", "") != cid.replace(" ", "")]
    if std:
        sections.append({"title": "Standards and documents referred to", "items": std})
    rel = [f"{x['type'].replace('_', ' ')}: {x['target']}" for x in relations]
    if rel:
        sections.append({"title": "Related regulations", "items": _uniq(rel, 15)})
    toc = (
        contents(text)
        if text
        and (
            cls.startswith("AIS") or cls in ("TAP_DOCUMENT", "REPORT", "GUIDELINE_POLICY", "ACT", "CONSOLIDATED_RULES")
        )
        else []
    )
    if len(toc) >= 3:
        sections.append({"title": "Contents of the document", "items": toc})
    signed = [x for x in (data.get("signatory"), data.get("file_no")) if isinstance(x, str) and x]
    if signed:
        sections.append({"title": "Signed / file reference", "text": " · ".join(signed)})
    return {
        "overview": " ".join(parts),
        "sections": sections,
        "source": "Generated from the document text and extracted data (rule-based, no AI)"
        if text
        else "Generated from the extracted data (no readable English text in the document)",
        "has_text": bool(text),
    }
