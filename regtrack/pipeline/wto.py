"""WTO TBT notifications (ePing): the fields of the WTO's own English notification document, by rule.

A regular notification (or its revision) is the numbered TBT form: 1 notifying member, 2 agency, 4 products (ICS),
5 notified document (title, link), 6 description, 7 objective, 8 relevant documents, 9 proposed dates, 10 comments.
An addendum says what happened to the notified measure: adopted / published / enters into force (dates ticked [X])
and where the final text is. The WTO symbol (G/TBT/N/THA/797/Add.1) and the distribution date are in the
document's own first-page header (pipeline/text.py reads Word headers).

is_vehicle(item) decides, from an ePing search record, whether the crawler downloads the notification at all.
"""

from __future__ import annotations

import re
from datetime import date, datetime

SOURCE = "TH_EPING_TBT"
SYMBOL = re.compile(r"G\s*/\s*TBT\s*/\s*N\s*/\s*([A-Z]{3})\s*/\s*(\d{1,4})((?:\s*/\s*(?:Rev|Add|Corr|Suppl)\.\s*\d+)*)")
OLD_SYMBOL = re.compile(
    r"G\s*/\s*TBT\s*/\s*(Notif\.\s*\d{2}|10\.7\s*/\s*N)\s*[/.]\s*(\d{1,4})((?:\s*/\s*(?:Rev|Add|Corr|Suppl)\.\s*\d+)*)"
)
DATE = re.compile(
    r"(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)"
    r",?\s+(\d{4})"
)
URL = re.compile(r"https?://[^\s|<>\"']+")
ICS = re.compile(r"\b(\d{2}\.\d{3}(?:\.\d{2})?)\b")
KIND = {"Rev": "revision", "Add": "addendum", "Corr": "corrigendum", "Suppl": "supplement"}

# ---- which ePing records are about vehicles: ICS 43 (road vehicle engineering), HS 87 / tyres / batteries, or words
VEHICLE_WORDS = re.compile(
    r"\b(motor ?vehicles?|automotive|motorcycles?|mopeds?|automobiles?|tyres?|tires?|vehicles?|helmets?|"
    r"safety glazing|brake|head ?lamps?|electric vehicle|EV charg\w*|cars?|trucks?|buses|seat belts?|"
    r"child restraint|traction batter\w*|REESS|wheels?)\b",
    re.I,
)
VEHICLE_HS = ("87", "4011", "4012", "4013", "8507", "8512", "8708", "8714", "7007", "9401.20")


def _plain(s: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>|&nbsp;", " ", s or "")).strip()


def is_vehicle(item: dict) -> bool:
    """An ePing search record (api/v1/azureSearch/getAll) about vehicles, their parts or their equipment."""
    ics = [x.get("code") or "" for x in item.get("icsCodes") or []]
    hs = [x.get("code") or "" for x in item.get("hsCodes") or []]
    words = f"{_plain(item.get('title'))} {_plain(item.get('productsFreeText'))}"
    return (
        any(c.startswith("43") for c in ics)
        or any(h.replace(".", "").startswith(tuple(p.replace(".", "") for p in VEHICLE_HS)) for h in hs)
        or bool(VEHICLE_WORDS.search(words))
    )


# ---- the document
def parse_date(s: str | None) -> date | None:
    m = DATE.search(s or "")
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %B %Y").date()
    except ValueError:
        return None


def _symbol(m: re.Match, old: bool) -> dict:
    suffix = re.sub(r"\s+", "", m.group(3) or "")
    if old:  # 1995-2000 numbering: G/TBT/Notif.99/401, Article 10.7: G/TBT/10.7/N/22 (member named in the text)
        series = re.sub(r"\s+", "", m.group(1))
        member, base = None, f"G/TBT/{series}/{int(m.group(2))}"
    else:
        member, base = m.group(1), f"G/TBT/N/{m.group(1)}/{int(m.group(2))}"
    parts = re.findall(r"(Rev|Add|Corr|Suppl)\.\d+", suffix)
    after = re.sub(r"^[\s*(\-]+", "", m.string[m.end() : m.end() + 60])
    return {
        "canonical_id": base + suffix,
        "family_key": base,
        "kind": KIND[parts[-1]] if parts else "regular",
        "member": member,
        "number": int(m.group(2)),
        "date": parse_date(after) if DATE.match(after) else None,
    }


def symbol_of(text: str) -> dict | None:
    """The document's own WTO symbol and distribution date: {canonical_id, family_key, kind, member, number, date}.
    The page header prints the symbol followed by the date; the body may cite other notifications ("notified under
    G/TBT/N/THA/428"), and an old Word file keeps its header at the end of the text, so the symbol with a date wins,
    else the most specific one."""
    found = [_symbol(m, False) for m in SYMBOL.finditer(text)] + [_symbol(m, True) for m in OLD_SYMBOL.finditer(text)]
    if not found:
        return None
    dated = [f for f in found if f["date"]]
    if dated:
        return dated[0]
    return max(found, key=lambda f: (f["canonical_id"].count("."), -found.index(f)))


# the labels of the TBT notification form (identical in every version since 1995; the item numbers are not)
LABELS = [
    ("agency", r"Agency responsible\s*:"),
    ("_comments_agency", r"Name and address \(including"),
    ("_article", r"Notified under Article"),
    ("products", r"Products covered\b[^:]{0,220}:"),
    (
        "title",
        r"(?:Title, number of pages and language\(s\) of the notified document|Details of notified document\(s\)"
        r"[^:]{0,120}|Title of the notified document)\s*:",
    ),
    ("_links", r"Link to notified document\(s\)[^:]{0,160}:"),
    ("_enquiry", r"WTO/TBT Enquiry Point"),
    ("description", r"Description of content\s*:"),
    ("objective", r"Objective and rationale[^:]{0,120}:"),
    ("relevant", r"Relevant documents\s*:"),
    ("proposed_adoption", r"Proposed date of adoption\s*:"),
    ("proposed_entry_into_force", r"Proposed date of entry into force\s*:"),
    ("comments", r"Final date for comments\s*:"),
    ("_texts", r"Texts? available from\s*:"),
]


def _segments(text: str) -> dict[str, str]:
    """Each label's text, up to the next label (first occurrence of each label, in document order)."""
    hits = []
    for key, rx in LABELS:
        m = re.search(rx, text, re.I)
        if m:
            hits.append((m.start(), m.end(), key))
    hits.sort()
    out: dict[str, str] = {}
    for i, (_, e, key) in enumerate(hits):
        nxt = hits[i + 1][0] if i + 1 < len(hits) else len(text)
        v = re.sub(r"\s*\n\s*\d{1,2}\.\s*\|?\s*$", "", text[e:nxt].strip())  # the next box's number
        out[key] = v.strip(" |\n")
    return out


def _one(s: str | None) -> str | None:
    s = re.sub(r"\s+", " ", (s or "").replace("|", " ")).strip(" :;")
    return s or None


def _near(text: str, word: str, last: bool = False) -> str:
    """The text right after a word, up to the end of its sentence (for a date written next to it)."""
    m = re.search(word + r"([^.;]{0,120})", text, re.I)
    if not m:
        return ""
    s = m.group(1)
    if last:  # "will enter into force after 60 days of publication (21 January 2019)": the date that ends it
        dates = list(DATE.finditer(s))
        return dates[-1].group(0) if dates else ""
    return s


def _ticked(text: str, label: str) -> date | None:
    """An addendum's '[X] | Notified measure adopted - date: 14 August 2025' (unticked '[ ]' boxes are ignored)."""
    m = re.search(r"\[\s*X\s*\][\s|]*" + label + r"[^\n]*?date\s*:\s*([^\n]*)", text, re.I)
    return parse_date(m.group(1)) if m else None


def fields(text: str) -> dict:
    """WtoTbtNotificationData fields (regtrack/models/data.py) from the document text."""
    ident = symbol_of(text) or {}
    d: dict = {
        "symbol": ident.get("canonical_id"),
        "kind": ident.get("kind"),
        "distribution_date": ident["date"].isoformat() if ident.get("date") else None,
    }
    if re.search(r"Reason for Addendum", text, re.I):  # the structured addendum form (since ~2019)
        d["kind"] = d.get("kind") if d.get("kind") not in (None, "regular") else "addendum"
        m = re.search(r"\n\s*Title\s*:\s*(.+?)(?:\n\s*\n|Reason for Addendum)", text, re.S)
        d["title"] = _one(m.group(1)) if m else None
        d["adopted_date"] = _iso(_ticked(text, r"Notified measure adopted"))
        d["published_date"] = _iso(_ticked(text, r"Notified measure published"))
        d["entry_into_force_date"] = _iso(_ticked(text, r"Notified measure enters into force"))
        d["withdrawn_date"] = _iso(_ticked(text, r"Notified measure withdrawn"))
        m = re.search(
            r"\[\s*X\s*\][\s|]*Text of final measure available from\s*:?(.*?)(?:\n\s*\[\s*X?\s*\]|$)", text, re.I | re.S
        )
        d["document_links"] = URL.findall(m.group(1)) if m else []
        m = re.search(r"\n\s*Description\s*:\s*(.+?)(?:_{3,}|$)", text, re.S)
        d["description"] = _one(m.group(1)) if m else None
    elif re.search(r"^\s*(?:Addendum|Corrigendum|Revision)\s*$", text, re.I | re.M) and not re.search(
        r"Description of content\s*:|Agency responsible\s*:", text, re.I
    ):  # a free-text addendum / corrigendum (a revision is a full form: next branch)
        kind = re.search(r"^\s*(Addendum|Corrigendum|Revision)\s*$", text, re.I | re.M).group(1).lower()
        d["kind"] = d.get("kind") if d.get("kind") not in (None, "regular") else kind
        body = re.split(r"_{5,}", text, maxsplit=1)[-1]
        body = re.split(r"_{5,}", body)[0]
        lines = [
            x.strip() for x in body.split("\n") if x.strip() and not URL.fullmatch(x.strip()) and "<<<PAGE" not in x
        ]
        if lines:
            d["title"] = _one(lines[0]) if len(lines) > 1 and len(lines[0]) < 300 else None
            d["description"] = _one(" ".join(lines[1:] if d.get("title") else lines))
        desc = d.get("description") or ""
        d["adopted_date"] = _iso(parse_date(_near(desc, r"\badopted\b")))
        d["published_date"] = _iso(parse_date(_near(desc, r"\bpublished\b")))
        d["entry_into_force_date"] = _iso(parse_date(_near(desc, r"\binto force\b", last=True)))
        d["document_links"] = [u for u in URL.findall(body) if re.search(r"crnattachments|\.(?:pdf|docx?)$", u, re.I)]
    else:
        seg = _segments(text)
        d["agency"] = _one((seg.get("agency") or "").strip().split("\n")[0])
        prod = seg.get("products") or ""
        d["products"] = _one(prod)
        d["ics_codes"] = sorted(set(ICS.findall(prod)))
        title = seg.get("title") or ""
        d["title"] = _one(re.split(r";?\s*\(\s*\d+\s*pages?|;\s*\(", title)[0])
        # the notified texts, not the enquiry point's website further down the box
        urls = URL.findall(title + "\n" + (seg.get("_links") or ""))
        d["document_links"] = [u for u in urls if re.search(r"crnattachments|\.(?:pdf|docx?)$", u, re.I)]
        d["description"] = _one(seg.get("description"))
        d["objective"] = _one(seg.get("objective"))
        rel = seg.get("relevant") or ""
        d["relevant_documents"] = [_one(x) for x in re.split(r"\n|;\s+(?=[A-Z0-9])", rel) if _one(x)][:12]
        d["proposed_adoption"] = _one((seg.get("proposed_adoption") or "").split("\n")[0])
        d["proposed_entry_into_force"] = _one((seg.get("proposed_entry_into_force") or "").split("\n")[0])
        d["comment_deadline"] = _iso(parse_date((seg.get("comments") or "")[:80]))
    return {k: v for k, v in d.items() if v not in (None, "", [], {})}


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def status_of(f: dict) -> str:
    """draft: notified for comments; final: the measure was adopted / published / entered into force; withdrawn."""
    if f.get("withdrawn_date"):
        return "withdrawn"
    if f.get("adopted_date") or f.get("published_date") or f.get("entry_into_force_date"):
        return "final"
    return "draft"


# ---- vehicle categories (UNECE codes as the notification writes them, else the vehicle words)
UN = re.compile(r"(?<![A-Za-z0-9])([LMNO])\s?([1-7])(?:G)?(?![0-9])")
WORDS = [
    (re.compile(r"\bmotorcycles?\b|\btwo[- ]wheel", re.I), ["L3"]),
    (re.compile(r"\bmopeds?\b", re.I), ["L1"]),
    (re.compile(r"\bpassenger cars?\b|\bcar seats?\b|\bchild restraint", re.I), ["M1"]),
    (re.compile(r"\blight[- ]duty\b", re.I), ["M1", "N1"]),
    (re.compile(r"\bheavy (?:motor )?vehicles?\b", re.I), ["M3", "N3"]),
]


def categories(text: str) -> list[str]:
    cats = {f"{a}{b}" if a != "O" else "O" for a, b in UN.findall(text)}
    if not cats:
        for rx, codes in WORDS:
            if rx.search(text):
                cats.update(codes)
    order = ["L1", "L2", "L3", "L4", "L5", "L6", "L7", "M1", "M2", "M3", "N1", "N2", "N3", "O"]
    return [c for c in order if c in cats]
