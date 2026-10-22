"""Relevance + classification rules (stage 'text' -> 'classified').

Extended from discovery/classify.py to the full doc_class list (DB_DESIGN section 3).
Deterministic first; Qwen only for files still OTHER after the rules (see classify_with_llm).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, Field

from regtrack.models.enums import INDIA_CLASSES, DocClass, Nature
from regtrack.pipeline import malaysia, thai
from regtrack.pipeline import patterns as P
from regtrack.pipeline.text import PageText, english_text, full_text

# folder priority when the same bytes sit in several folders
FOLDER_PRIORITY = ["07", "11", "28", "21", "17", "18", "29", "24", "25", "12", "01", "05", "02", "06", "27"]

AUTO_KW = re.compile(r"motor\s+vehicles?|vehicles?|automotive|\bAIS\b|CMVR|road\s+transport|two[\s\-]wheeler|"
                     r"type\s+approval|driving\s+licen[cs]e|registration\s+(?:mark|certificate)|\bpermit|"
                     r"emission|Bharat\s+Stage|chassis|tyre|helmet|traffic|carriage", re.I)
CMVR_RE = re.compile(r"Central\s+Motor\s+Vehicles?\s+Rules|Motor\s+Vehicles\s+Act|C\.?M\.?V\.?R\.?\b", re.I)
GAZETTE_RE = re.compile(r"Gazette\s+of\s+India|EXTRAORDINARY|PART\s+II\s*[\-—–,]*\s*Sec", re.I)
DRAFT_RE = re.compile(r"draft\s+(?:of\s+)?(?:certain\s+)?(?:rules|notification|amendments?)\b.{0,300}?"
                      r"(?:objections?|suggestions?|expiry\s+of)|objections?\s+(?:and|or)\s+suggestions?.{0,200}?"
                      r"(?:expiry|period\s+of)|after\s+the\s+expiry\s+of\s+(?:a\s+)?period\s+of\s+(?:thirty|forty[\s\-]five|"
                      r"sixty|fifteen|seven|\d+)\s+days", re.I | re.S)
# "Whereas the draft rules ... were published ... vide notification number G.S.R. 117(E), dated ..." (a final).
# A draft itself says "the following draft ... is hereby published" and cites the principal rules (G.S.R. 590(E)),
# so those phrases may not appear between 'draft' and the cited number.
_NOT_DRAFT_SELF = r"(?:(?!hereby\s+published|is\s+published|principal\s+(?:rules|notification)|last\s+amended)[\s\S])"
DRAFT_CITE = re.compile(r"draft\s+(?:of\s+)?(?:certain\s+)?(?:rules|notification|amendments?|scheme)" + _NOT_DRAFT_SELF
                        + r"{0,400}?(?:were|was|had\s+been|have\s+been)\s+published" + _NOT_DRAFT_SELF + r"{0,600}?"
                        + P.SERIES_RE + r"\s*(?:No\.?\s*)?(\d{1,5})\s*\.?\s*\(?\s*E\b", re.I)
FINAL_OF_DRAFT = re.compile(DRAFT_CITE.pattern + r"|whereas\s+the\s+(?:said\s+)?draft", re.I)
CORRIGENDUM_RE = re.compile(r"\bCORRIGENDUM\b|\bCORRIGENDA\b", re.I)
EXEMPT_RE = re.compile(r"hereby\s+exempts?|exempt(?:s|ed)?\s+(?:the\s+)?(?:following|all|any|such|vehicles?|from\s+the\s+(?:provisions|operation))|"
                       r"exemption\s+(?:from|to|of)", re.I)
EXTEND_RE = re.compile(r"extend(?:s|ed|ing)?\s+the\s+(?:date|period|time|validity)|for\s+the\s+(?:words|figures)[^.]{0,80}?"
                       r"(?:20\d\d|19\d\d)[^.]{0,80}?(?:shall\s+be\s+substituted)|postpone", re.I)
OM_RE = re.compile(r"Office\s+Memorandum|\bO\.\s?M\.\s|\bCIRCULAR\b|\bADVISORY\b|\bOrder\b\s*\n|"
                   r"No\.\s*RT[\-\s]?\d", re.I)
GUIDE_RE = re.compile(r"\bguidelines?\b|\bpolicy\b|\bstandard\s+operating\s+procedure\b|\bSOP\b|\bframework\b|\bscheme\b", re.I)
# Act titles are printed in capitals; 'the Motor Vehicles Act, 1988' inside a notification is only a citation
ACT_RE = re.compile(r"\bTHE\s+[A-Z][A-Z ,()]{3,80}ACT,?\s+(?:19|20)\d\d\b|(?i:\bAN\s+ACT\s+(?:further\s+)?to\b)|"
                    r"ARRANGEMENT\s+OF\s+SECTIONS|(?i:BE\s+it\s+enacted)")
STATES = (r"Andhra\s+Pradesh|Arunachal\s+Pradesh|Assam|Bihar|Chh?att?[ie]sgarh|Goa|Gujarat|Haryana|Himachal\s+Pradesh|"
          r"Jharkhand|Karnataka|Kerala|Madhya\s+Pradesh|Maharashtra|Manipur|Meghalaya|Mizoram|Nagaland|Odisha|Orissa|"
          r"Punjab|Rajasthan|Sikkim|Tamil\s+Nadu|Telangana|Tripura|Uttar\s+Pradesh|Uttarakhand|West\s+Bengal|"
          r"Delhi|NCT\s+of\s+Delhi|Jammu\s+and\s+Kashmir|Puducherry|Chandigarh|Ladakh|Mysore|Bombay|Madras")
STATE_HDR = re.compile(r"GOVERNMENT\s+OF\s+(?:THE\s+)?(?:NATIONAL\s+CAPITAL\s+TERRITORY\s+OF\s+)?(" + STATES + r")\b|"
                       r"(" + STATES + r")\s+(?:GAZETTE|Government)", re.I)
STATE_TITLE = re.compile(r"\b(" + STATES + r")\s+Motor\s+Vehicles?|\b(" + STATES + r")\s+(?:\w+\s+){0,3}(?:Tax|Taxation|GST|"
                         r"Goods\s+and\s+Services)", re.I)
CONSOLIDATED_RE = re.compile(r"CHAPTER\s+I\b.{0,80}?PRELIMINARY.{0,200}?Short\s+title\s+(?:and|,)\s+commencement", re.I | re.S)
BEE_RE = re.compile(r"Bureau\s+of\s+Energy\s+Efficiency|Energy\s+Conservation\s+Act|fuel\s+consumption\s+standards|"
                    r"Corporate\s+Average\s+Fuel", re.I)
FUEL_RE = re.compile(r"Motor\s+Spirit\s+and\s+High\s+Speed\s+Diesel|Naphtha|Solvent,?\s+Raffinate|Slop|"
                     r"(?:Prevention|Regulation)\s+of\s+Malpractices|adulteration", re.I)
BIS_RE = re.compile(r"Bureau\s+of\s+Indian\s+Standards|Conformity\s+Assessment|BIS\s+Act", re.I)
LEGACY_SAFETY = re.compile(r"\bIS\s*:?\s*\d{3,5}\b.{0,60}(?:safety|helmet|glass|seat\s+belt)", re.I)

ISSUERS = [
    ("MoRTH", re.compile(r"MINISTRY\s+OF\s+(?:SHIPPING,\s+)?ROAD\s+TRANSPORT|MINISTRY\s+OF\s+SURFACE\s+TRANSPORT|"
                         r"Department\s+of\s+Road\s+Transport|MoRTH|MINISTRY\s+OF\s+TRANSPORT", re.I)),
    ("AISC/ARAI", re.compile(r"AUTOMOTIVE\s+INDUSTRY\s+STANDARD|Automotive\s+Research\s+Association\s+of\s+India|"
                             r"AIS\s+Committee|AISC", re.I)),
    ("MoEFCC", re.compile(r"MINISTRY\s+OF\s+ENVIRONMENT|Central\s+Pollution\s+Control\s+Board", re.I)),
    ("MoPNG", re.compile(r"MINISTRY\s+OF\s+PETROLEUM", re.I)),
    ("MoP/BEE", re.compile(r"MINISTRY\s+OF\s+POWER|Bureau\s+of\s+Energy\s+Efficiency", re.I)),
    ("BIS", re.compile(r"BUREAU\s+OF\s+INDIAN\s+STANDARDS", re.I)),
    ("MoHI", re.compile(r"MINISTRY\s+OF\s+HEAVY\s+INDUSTR", re.I)),
    ("Law Ministry", re.compile(r"MINISTRY\s+OF\s+LAW|Legislative\s+Department", re.I)),
    ("MoF", re.compile(r"MINISTRY\s+OF\s+FINANCE|Department\s+of\s+Revenue", re.I)),
    ("State Government", re.compile(r"GOVERNMENT\s+OF\s+(?!INDIA)[A-Z][A-Za-z ]{3,25}\n|State\s+Government\s+of", re.I)),
]


@dataclass
class FileCtx:
    file_id: int | None
    sha: str
    ext: str
    folders: list[str]
    names: list[str]
    pages: list[PageText]
    page_count: int
    text_layer: bool
    scanned_pages: list[int] = field(default_factory=list)
    listings: list[dict] = field(default_factory=list)   # {source,title,date,category,raw}

    @property
    def folder(self) -> str:
        """Highest-priority folder prefix ('07', '05', ...)."""
        prefixes = [f[:2] for f in self.folders]
        for pr in FOLDER_PRIORITY:
            if pr in prefixes:
                return pr
        return prefixes[0] if prefixes else ""

    @property
    def name(self) -> str:
        return self.names[0] if self.names else ""

    def names_l(self) -> str:
        return " | ".join(self.names).lower()

    @property
    def english(self) -> str:
        return english_text(self.pages)

    def head(self, n: int = 8000) -> str:
        return self.english[:n]


@dataclass
class ClassResult:
    doc_class: DocClass
    status: str = "final"
    issuer: str | None = None
    relevance: dict = field(default_factory=dict)
    nature: str | None = None
    method: str = "rules"
    reason: str = ""


def detect_issuer(text: str, default: str | None = None) -> str | None:
    head = text[:6000]
    for name, rx in ISSUERS:
        if rx.search(head):
            return name
    return default


def state_level(text: str, names: str = "") -> str | None:
    """A State Government document (state MV rules/tax, state schemes): returns the state name."""
    head = text[:1500]
    m = STATE_HDR.search(head) or STATE_TITLE.search(head) or STATE_TITLE.search(names)
    if m and not re.search(r"MINISTRY\s+OF\s+ROAD\s+TRANSPORT|Government\s+of\s+India", head[:m.start() + 400], re.I):
        return next(g for g in m.groups() if g).title()
    return None


def relevance(ctx: FileCtx) -> dict:
    eng = ctx.english
    words = max(len(eng.split()), 1)
    hits = len(AUTO_KW.findall(eng[:40000]))
    cmvr = bool(CMVR_RE.search(eng[:40000]))
    issuer = detect_issuer(eng)
    density = hits / min(words, 6000) * 1000
    central = issuer in ("MoRTH", "AISC/ARAI")
    score = min(1.0, density / 15 + (0.3 if cmvr else 0) + (0.3 if central else 0))
    enough_text = words >= 150
    state = state_level(eng, ctx.names_l())
    automotive = (not enough_text) or central or density >= 4 or (cmvr and density >= 1)
    reason = ("too little English text to judge" if not enough_text else
              f"{hits} automotive keywords/{words} words" + ("; cites CMVR/MV Act" if cmvr else "")
              + (f"; issuer {issuer}" if issuer else ""))
    if state:
        reason += f"; state-level ({state})"
    return {"automotive": automotive, "score": round(score, 2), "reason": reason, "keyword_hits": hits,
            "english_words": words, "cmvr": cmvr, "state": state}


def notification_kind(eng: str, has_id: bool, series: str | None) -> tuple[DocClass, str]:
    head = eng[:12000]
    if CORRIGENDUM_RE.search(head[:3000]) and len(eng) < 9000:
        return DocClass.NOTIFICATION_CORRIGENDUM, "final"
    is_draft = bool(DRAFT_RE.search(head)) and not FINAL_OF_DRAFT.search(head)
    if is_draft:
        return DocClass.NOTIFICATION_DRAFT, "draft"
    if EXEMPT_RE.search(head[:6000]):
        return DocClass.NOTIFICATION_EXEMPTION, "final"
    if EXTEND_RE.search(head[:8000]) and len(eng) < 15000:
        return DocClass.NOTIFICATION_EXTENSION, "final"
    if series == "S.O.":
        return DocClass.NOTIFICATION_ORDER, "final"
    return DocClass.NOTIFICATION_FINAL, "final"


def nature_of(text: str, doc_class: DocClass) -> str | None:
    if doc_class in (DocClass.OFF_TOPIC,):
        return None
    if doc_class.is_ais or doc_class in (DocClass.TAP_DOCUMENT, DocClass.TAP_AMENDMENT, DocClass.SAFETY_STANDARD_LEGACY,
                                         DocClass.FUEL_ORDER, DocClass.ENERGY_STANDARD):
        return Nature.TECHNICAL
    t = text[:30000]
    tech = len(re.findall(r"AIS[\s\-]?\d{3}|\bIS\s*:?\s*\d{3,5}|type\s+approv|emission|safety|brak|lamp|helmet|"
                          r"seat\s+belt|airbag|speed\s+(?:governor|limit)|tyre|battery|Bharat\s+Stage|conform", t, re.I))
    admin = len(re.findall(r"\bfees?\b|registration|licen[cs]e|permit|tax|penalt|insurance|Form\s+\d|"
                           r"learner|driving\s+school|national\s+permit|fitness\s+certificate", t, re.I))
    proc = len(re.findall(r"test(?:ing)?\s+agenc|accredit|conformity\s+of\s+production|\bCoP\b|procedure|"
                          r"automated\s+testing\s+station|inspection", t, re.I))
    best = max((tech, Nature.TECHNICAL), (admin, Nature.ADMINISTRATIVE), (proc, Nature.PROCEDURAL))
    return best[1] if best[0] > 0 else None


def classify(ctx: FileCtx, notif_identity=None, ais_identity=None) -> ClassResult:
    """Rule-based class. notif_identity / ais_identity are identity results already computed from content."""
    fo = ctx.folder
    names = ctx.names_l()
    eng = ctx.english
    head = eng[:8000]
    rel = relevance(ctx)
    issuer = detect_issuer(eng)

    def res(dc: DocClass, status: str = "final", why: str = "", iss: str | None = None) -> ClassResult:
        return ClassResult(dc, status, iss or issuer, rel, nature_of(eng, dc), "rules", why)

    # ---- Thailand: a TISI mandatory-standard page (every product type; only the automotive ones are TIS_STANDARD)
    tisi = [x for x in ctx.listings if x.get("source") == thai.TISI_SOURCE]
    if tisi:
        allt = full_text(ctx.pages)
        cat = tisi[0].get("category")
        if cat == thai.FULL_TEXT:  # the crawler follows full-text links of automotive standards only
            return ClassResult(DocClass.TIS_STANDARD, "final", "TISI", rel, None, "rules", "TISI full text")
        if thai.is_automotive(cat, allt):
            return ClassResult(DocClass.TIS_STANDARD, "final", "TISI", rel, None, "rules", f"TISI automotive ({cat})")
        return ClassResult(DocClass.OFF_TOPIC, "final", "TISI", rel, None, "rules", f"TISI non-automotive ({cat})")

    # ---- Malaysia: JPJ / DOE pages and the files they link (all automotive by source)
    my = malaysia.source_of(ctx.listings)
    if my:
        leg = malaysia.legal_identity(full_text(ctx.pages)) if ctx.ext != "html" else None
        if leg:  # an Act or a P.U.(A) regulation, by its own first page
            dc = DocClass.MY_ACT if leg["kind"] == "act" else DocClass.MY_SUBSIDIARY_LEGISLATION
        else:
            dc = DocClass.MY_FORM if malaysia.is_form(ctx.names, eng) else DocClass.MY_GUIDELINE
        return ClassResult(dc, "final", malaysia.ISSUER[malaysia.MY_SOURCES[my]], rel, None, "rules", f"Malaysia {my}")

    # ---- source/folder rules for document families with a fixed home
    if fo == "28":
        return res(DocClass.FORM_TEMPLATE, why="folder 28 Parivahan forms", iss="MoRTH")
    if fo == "11":
        return res(DocClass.TAP_DOCUMENT, why="folder 11 CMVR-TAP", iss="MoRTH")
    if fo == "17":
        return res(DocClass.APPROVED_LIST, why="folder 17 ARAI approved lists", iss="AISC/ARAI")
    if fo == "21":
        if ctx.ext == "csv":
            return res(DocClass.BIS_CATALOGUE, why="BIS IS catalogue CSV", iss="BIS")
        return res(DocClass.BIS_REGULATION, why="folder 21 BIS", iss="BIS")
    if fo == "29" or (FUEL_RE.search(head) and re.search(r"PETROLEUM", head, re.I)):
        return res(DocClass.FUEL_ORDER, why="fuel quality order", iss="MoPNG")
    if fo == "27" or (fo == "12"):
        return res(DocClass.REPORT, why=f"folder {fo} reports/booklets")
    if ctx.ext == "md":
        return res(DocClass.OTHER, why="markdown note")

    # ---- AIS family
    is_ais_folder = fo == "07" or (fo == "06" and ais_identity is not None and notif_identity is None)
    if fo == "07" or (ais_identity is not None and (P.AIS_COVER.search(head[:4000]) or is_ais_folder)):
        arai = [x for x in ctx.listings if x.get("source") == "ARAI_AIS"]
        code_raw = (arai[0].get("title") or "") if arai else ""
        if ctx.ext == "docx" and (re.search(r"table", names + " " + code_raw, re.I)):
            return res(DocClass.AIS_FORM_TABLE, why="AIS-007 DOCX table", iss="AISC/ARAI")
        if re.search(r"interpretation", names + " " + code_raw + " " + head[:600], re.I):
            return res(DocClass.AIS_INTERPRETATION, why="interpretation manual", iss="AISC/ARAI")
        if code_raw.strip().lower() == "list" or re.search(r"list\s+of\s+(?:published\s+)?AIS", head[:600], re.I):
            return res(DocClass.OTHER, why="list of published AIS", iss="AISC/ARAI")
        draft_marks = re.search(r"\bFinali[sz]ed\s+Draft\b|\bDRAFT\b(?!\s+(?:rules|notification))|Last\s+date\s+for\s+comments",
                                head[:2500]) or \
            re.search(r"\bDraft\s*/?\s*AIS[\s\-]*\d{3}[^\n]{0,40}?/\s*D(?:F\d?|\d)\b", head[:4000], re.I)  # "Draft AIS-221/D0/Dec. 2025"
        if draft_marks or re.search(r"\bdraft\b|\bDF[_\s]", names):
            return res(DocClass.AIS_DRAFT, "draft", why="draft AIS", iss="AISC/ARAI")
        if ais_identity is None and ctx.text_layer is False:
            return res(DocClass.AIS_STANDARD, why="AIS folder, scanned", iss="AISC/ARAI")
        # a short file that is only an amendment / corrigendum
        if ctx.page_count <= 15 and P.AMD_HEADER.search(head[:3000]) and not P.AIS_COVER.search(head[:1500]):
            return res(DocClass.AIS_AMENDMENT, why="stand-alone amendment", iss="AISC/ARAI")
        if ctx.page_count <= 6 and P.CORR_HEADER.search(head[:3000]) and not P.AIS_COVER.search(head[:1500]):
            return res(DocClass.AIS_CORRIGENDUM, why="stand-alone corrigendum", iss="AISC/ARAI")
        return res(DocClass.AIS_STANDARD, why="AIS cover/code", iss="AISC/ARAI")

    if P.TAP_DOC.search(head[:3000]):
        return res(DocClass.TAP_DOCUMENT, why="TAP doc number")

    # ---- non-automotive noise and State Government documents (outside central regulation)
    if not rel["automotive"] or rel.get("state"):
        return res(DocClass.OFF_TOPIC, why=rel["reason"], iss="State Government" if rel.get("state") else None)

    # ---- consolidated rule texts (e.g. cmvr-1989.pdf) reproduce many notifications inside them; the first
    #      G.S.R./S.O. heading found in them is not the identity of the file
    if ctx.page_count > 60 and CONSOLIDATED_RE.search(head[:3000]) and not ACT_RE.search(head[:3000]):
        return res(DocClass.CONSOLIDATED_RULES, why="consolidated rules text (Chapter I, short title)")

    # ---- notifications
    if notif_identity is not None:
        if BEE_RE.search(head) and issuer == "MoP/BEE":
            return res(DocClass.ENERGY_STANDARD, why="BEE fuel consumption standard")
        dc, status = notification_kind(eng, True, notif_identity.series)
        return res(dc, status, why="G.S.R./S.O. heading")

    if BEE_RE.search(head):
        return res(DocClass.ENERGY_STANDARD, why="BEE")
    if fo == "01" or ACT_RE.search(head[:5000]):
        if re.search(r"rules", names) and not ACT_RE.search(head[:3000]):
            return res(DocClass.CONSOLIDATED_RULES, why="consolidated rules")
        return res(DocClass.ACT, why="Act text", iss="Law Ministry")
    if ctx.page_count > 60 and len(CMVR_RE.findall(eng)) > 20 and re.search(r"rules", names):
        return res(DocClass.CONSOLIDATED_RULES, why="long CMVR text")
    if fo in ("24", "25") and GAZETTE_RE.search(head[:3000]):
        dc, status = notification_kind(eng, False, None)
        return res(dc, status, why=f"folder {fo} gazette rules without parsed id")
    if fo in ("05", "02") and ctx.text_layer is False:
        # a scan whose identity could not be read yet (OCR pending) - still a gazette notification
        return res(DocClass.NOTIFICATION_FINAL, why="scanned gazette notification, identity pending")
    if GAZETTE_RE.search(head[:3000]) and fo in ("05", "02"):
        dc, status = notification_kind(eng, False, None)
        return res(dc, status, why="gazette masthead without id")
    if OM_RE.search(head[:3000]) or re.search(r"circular|advisory|\border\b|office memorandum|\bom\b", names):
        if GUIDE_RE.search(names) or GUIDE_RE.search(head[:400]):
            return res(DocClass.GUIDELINE_POLICY, why="guideline")
        return res(DocClass.CIRCULAR_OM, why="office memorandum/circular")
    if GUIDE_RE.search(names) or GUIDE_RE.search(head[:600]):
        return res(DocClass.GUIDELINE_POLICY, why="guideline/policy")
    if re.search(r"report|year\s*book|presentation|review", names):
        return res(DocClass.REPORT, why="report by name")
    if fo == "06":
        return res(DocClass.CIRCULAR_OM, why="folder 06 MoRTH circulars/orders")
    if fo == "18":
        return res(DocClass.CIRCULAR_OM, why="folder 18 HSRP documents")
    return res(DocClass.OTHER, why="no rule matched")


# ------------------------------------------------------------------ Qwen fallback (OTHER leftovers only)
# India's classes only (no Thai classes): same name, so the schema sent to Qwen is unchanged
IndiaDocClass = StrEnum("DocClass", {c.name: c.value for c in INDIA_CLASSES})


class LlmClass(BaseModel):
    doc_class: IndiaDocClass = Field(description="One of the allowed classes")
    automotive: bool = Field(description="Is the document about motor vehicles / road transport regulation?")
    reason: str


CLASSIFY_PROMPT_VERSION = "classify_v1"


def classify_with_llm(ctx: FileCtx) -> ClassResult | None:
    from regtrack import llm

    text = ctx.head(6000) or full_text(ctx.pages)[:6000]
    if len(text.strip()) < 200:
        return None
    sys_p = ("You classify Indian vehicle-regulation documents. Allowed classes: "
             + ", ".join(c.value for c in INDIA_CLASSES)
             + ". Use OFF_TOPIC for documents unrelated to motor vehicles or road transport.")
    r = llm.structured(LlmClass, sys_p, f"File name: {ctx.name}\n\n{text}")
    dc = DocClass.OFF_TOPIC if not r.automotive else DocClass(r.doc_class)
    return ClassResult(dc, "draft" if dc in (DocClass.NOTIFICATION_DRAFT, DocClass.AIS_DRAFT) else "final",
                       detect_issuer(ctx.english), relevance(ctx), nature_of(ctx.english, dc), "qwen", r.reason)
