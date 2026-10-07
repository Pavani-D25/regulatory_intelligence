"""Mandates: who must comply with which standard from when, versioned in time.

Deterministic parsers:
  * S.O. 1365(E) master-table amendments (Table / Table A / Table B) and CMVR Rule 124(4) table:
      - row/item substitution or insertion with quoted entries  -> new mandate version per item
      - date substitution ("for '21st March, 2022' ... '21st September, 2022' shall be substituted")
        -> close the open version, insert a new one with the new date (same mandate_key)
      - omission -> close the open version
  * CMVR rule amendments with a dated obligation ("manufactured on or after 1st January, 2026 ... IS 14664")
  * Qwen provisions (document.data.provisions) when they exist.
Mandates are never updated in place: a change closes the old row (valid_to, superseded_by) and inserts a new
row with the same mandate_key. Replay is in notification date order.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date

import psycopg

from regtrack.db import Jsonb
from regtrack.pipeline import patterns as P

Q_OPEN = "“‘\"―'«"
Q_CLOSE = "”’\"‖'»"


@dataclass
class Item:
    table: str                   # 'SO-1365(E)-2004 Table' | 'SO-1365(E)-2004 Table A' | 'CMVR Rule 124(4) Table'
    serial: str
    item: str | None
    subject: str | None = None
    standards: list[str] = field(default_factory=list)
    date_text: str | None = None
    implementation_date: date | None = None
    categories: list[str] = field(default_factory=list)
    conditions: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.table} Sr.{self.serial}" + (f"({self.item})" if self.item else "")


@dataclass
class DateSub:
    table: str
    serials: list[str]
    items: list[str]
    old: date | None
    new: date
    evidence: str


@dataclass
class Omit:
    table: str
    serial: str
    items: list[str]


# ---------------------------------------------------------------------- parsing helpers
TABLE_HDR = re.compile(r"in\s+(?:the\s+)?Table\s*([A-Z])?\b(?:\s+Safety\s+Standards[^,\-]*)?", re.I)


def base_table(text: str) -> str | None:
    if re.search(r"S\.?\s?O\.?\s*1365\s*\(\s*E\s*\)", text[:6000], re.I):
        return "SO-1365(E)-2004"
    if re.search(r"rule\s+124[^.]{0,80}sub-rule\s*\(4\)", text[:8000], re.I):
        return "CMVR Rule 124(4)"
    return None


def table_sections(op: str, base: str) -> list[tuple[str, str]]:
    """Split operative text into (table name, text) sections at 'in the Table', 'in Table A', ..."""
    marks = [(m.start(), f"{base} Table" + (f" {m.group(1).upper()}" if m.group(1) else "")) for m in TABLE_HDR.finditer(op)]
    if not marks:
        return [(f"{base} Table", op)]
    out = []
    for i, (pos, name) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(op)
        out.append((name, op[pos:end]))
    return out


def _serials(s: str) -> list[str]:
    return re.findall(r"\d{1,3}", s)


def categories_from(subject: str) -> list[str]:
    s = subject or ""
    cats = P.expand_letters(list(P.find_categories(s)))
    if re.search(r"all\s+(?:motor\s+)?vehicles|fitted\s+in\s+all\s+motor", s, re.I):
        cats = ["ALL"] + [c for c in cats if c != "ALL"]
    if re.search(r"\bL\s+category|category\s+L\b|two\s+and\s+three\s+wheeled", s, re.I):
        cats += [c for c in ("L1", "L2", "L5") if c not in cats]
    return cats


def parse_items(block: str, table: str, default_serial: str | None) -> list[Item]:
    """Quoted entries: '―8 (a)Subject. IS 9436-2018. 21st September 2021. (b)...'."""
    items: list[Item] = []
    text = re.sub(r"<<<PAGE \d+>>>", " ", block)
    text = re.sub(r"\n\s*(?:\d+\s*\n)?\s*THE\s+GAZETTE\s+OF\s+INDIA[^\n]*\n[^\n]*\n", "\n", text, flags=re.I)
    text = re.sub(r"\[भाग[^\n]*\n|भारत का[^\n]*\n", "\n", text)
    serial = default_serial
    # serial markers: a quote followed by a number at line start
    parts = re.split(r"[" + Q_OPEN + r"]\s*(\d{1,3})\s*\n|\n\s*(\d{1,3})\s*\n(?=\s*\([a-z]\))", text)
    chunks: list[tuple[str | None, str]] = []
    cur = parts[0]
    chunks.append((serial, cur))
    i = 1
    while i < len(parts):
        s = parts[i] or parts[i + 1]
        body = parts[i + 2] if i + 2 < len(parts) else ""
        chunks.append((s, body))
        i += 3
    for ser, body in chunks:
        if ser is None:
            ser = serial
        if ser is None:
            continue
        serial = ser
        its = list(re.finditer(r"(?:^|\n|[" + Q_OPEN + r"])[ \t]*\(([a-z]{1,2})\)\s*", body))
        if not its:
            continue
        for k, m in enumerate(its):
            seg = body[m.end(): its[k + 1].start() if k + 1 < len(its) else len(body)]
            seg = seg.split("”;")[0].split("”.")[0]
            stds = [r for r in P.find_references(seg, ("AIS", "IS", "UN_R")) if not r.startswith("CMVR")]
            dates = P.all_dates(seg)
            subj = re.split(r"\s(?:IS[\s:]*\d|AIS[\s:\-]*\d)", clean(seg))[0].strip(" .;:")
            dt = re.search(r"(\d{1,2}(?:st|nd|rd|th)?\s+[A-Z][a-z]+,?\s+\d{4}[^()]{0,120}?)(?=\(|$)", clean(seg))
            it = Item(table=table, serial=ser, item=m.group(1), subject=subj[:300] or None, standards=stds,
                      date_text=dt.group(1).strip()[:200] if dt else None,
                      implementation_date=dates[0] if dates else None, categories=categories_from(subj),
                      conditions=P.find_conditions(subj))
            items.append(it)
    return items


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


SUBST_ROW = re.compile(r"for\s+(?:the\s+)?serial\s+numbers?\s+([\d\s,and]+?)(?:\s*,?\s*(?:and|for)\s+(?:the\s+)?entries|\s+and\s+the\s+entries|\s*,\s*for\s+item)"
                       r"|for\s+item\s+numbers?\s+([\(\)a-z,\s and]+?)\s+and\s+the\s+entries", re.I)
INSERT_ROW = re.compile(r"after\s+serial\s+number\s+(\d{1,3})[^.]{0,200}?(?:shall\s+be\s+inserted|following\s+serial\s+numbers?)", re.I)
DATE_SUB = re.compile(r"for\s+the\s+(?:figures|words)[^“\"']{0,60}[“\"']([^”\"']{6,40})[”\"'][^“\"']{0,140}?[“\"']([^”\"']{6,40})[”\"']\s*shall\s+be\s+substituted", re.I)
OMIT_ROW = re.compile(r"serial\s+number\s+(\d{1,3})[^.]{0,120}?shall\s+be\s+omitted", re.I)


def parse_table_amendments(op: str) -> tuple[list[Item], list[DateSub], list[Omit]]:
    base = base_table(op)
    if not base:
        return [], [], []
    items: list[Item] = []
    dsubs: list[DateSub] = []
    omits: list[Omit] = []
    for table, sec in table_sections(op, base):
        # date substitutions (possibly several clauses per section)
        for clause in re.split(r"\n\s*\(?[a-z]{1,3}\)\s*(?=in\s|against\s)|;\s*\n", sec):
            m = DATE_SUB.search(clause)
            if m:
                old, new = P.parse_date(m.group(1)), P.parse_date(m.group(2))
                if new:
                    sers = _serials(" ".join(re.findall(r"serial\s+numbers?\s+([\d\s,and]+)", clause, re.I)))
                    its = re.findall(r"item\s+(?:number\s+)?\(([a-z])\)", clause, re.I)
                    dsubs.append(DateSub(table, sers, its, old, new, clean(clause)[:300]))
        for m in OMIT_ROW.finditer(sec):
            omits.append(Omit(table, m.group(1), []))
        table_cats = categories_from(sec[:160]) if re.search(r"rickshaw|cart|tractor|trailer", sec[:160], re.I) else []
        # one section can hold several clauses: "(i) In serial number 8, for item (d) ... (ii) In serial number 43, ..."
        starts = [m.start() for m in re.finditer(r"(?:^|\n)\s*(?:\(?[ivx]{1,4}[\).]|\([a-z]\))\s*(?=(?:In|in|for|against|after)\s+(?:the\s+)?serial)", sec)]
        clauses = [sec[a:b] for a, b in zip([0, *starts], [*starts, len(sec)], strict=True) if sec[a:b].strip()]
        for clause in clauses:
            sub = SUBST_ROW.search(clause) or INSERT_ROW.search(clause)
            if not sub:
                continue
            serials = _serials(sub.group(1) or "") if sub.re is SUBST_ROW else [sub.group(1)]
            default = None
            ser_m = re.search(r"(?:in|against)\s+serial\s+number\s+(\d{1,3})", clause[:sub.start() + 200], re.I)
            if ser_m:
                default = ser_m.group(1)
            elif len(serials) == 1:
                default = serials[0]
            for it in parse_items(clause[sub.end():], table, default):
                if not it.categories and table_cats:
                    it.categories = table_cats
                items.append(it)
    # drop cross-reference fragments ('(b), 43 (c) and 43 (d)') and keep one item per key
    items = [it for it in items if (it.standards or it.implementation_date) and it.subject
             and re.match(r"[A-Za-z]", it.subject) and not re.match(r"(?:In\s+serial|vide\s)", it.subject, re.I)]
    seen, uniq = set(), []
    for it in items:
        if it.key not in seen:
            seen.add(it.key)
            uniq.append(it)
    return uniq, dsubs, omits


# ---------------------------------------------------------------------- CMVR rule obligations
OBLIG = re.compile(r"(?:manufactured|sold|registered|fitted)\s+on\s+(?:or|and)\s+after\s+(?:the\s+)?(\d{1,2}(?:st|nd|rd|th)?\s*(?:day\s+of\s+)?[A-Z][a-z]+,?\s+\d{4})"
                   r"|on\s+and\s+from\s+(?:the\s+)?(\d{1,2}(?:st|nd|rd|th)?\s*(?:day\s+of\s+)?[A-Z][a-z]+,?\s+\d{4})", re.I)


@dataclass
class RuleObligation:
    rule: str
    subject: str
    standards: list[str]
    categories: list[str]
    implementation_date: date
    model_scope: str | None
    conditions: dict

    @property
    def key(self) -> str:
        tag = self.standards[0] if self.standards else hashlib.sha1(self.subject.encode()).hexdigest()[:8]
        return f"{self.rule} :: {tag}"


def parse_rule_obligations(op: str) -> list[RuleObligation]:
    out = []
    for m in OBLIG.finditer(op):
        d = P.parse_date(m.group(1) or m.group(2))
        if not d:
            continue
        start = max(0, op.rfind(".", 0, m.start() - 300) + 1)
        end = op.find(".", m.end() + 1)
        sent = clean(op[start:end if end > 0 else m.end() + 400])
        stds = [r for r in P.find_references(sent, ("AIS", "IS", "UN_R"))]
        if not stds:
            continue
        before = op[max(0, m.start() - 3000):m.start()]
        rules = list(re.finditer(r"(?:in\s+)?rule\s+(\d{1,3}[A-Z]{0,2})(?:\s*,\s*(?:in\s+)?sub-rule\s*\((\w+)\))?", before, re.I))
        if not rules:
            continue
        r = rules[-1]
        rule = f"CMVR Rule {r.group(1)}" + (f"({r.group(2)})" if r.group(2) else "")
        scope = "new_models" if re.search(r"new\s+models?", sent, re.I) else \
            "existing_models" if re.search(r"existing\s+models?", sent, re.I) else \
            "registered_vehicles" if re.search(r"registered", sent, re.I) else "all"
        out.append(RuleObligation(rule, sent[:300], stds[:6], categories_from(sent), d, scope, P.find_conditions(sent)))
    seen, uniq = set(), []
    for o in out:
        if (o.key, o.implementation_date) not in seen:
            seen.add((o.key, o.implementation_date))
            uniq.append(o)
    return uniq


# ---------------------------------------------------------------------- DB writes
def open_versions(conn: psycopg.Connection, key: str, is_draft: bool = False) -> list[dict]:
    return conn.execute("SELECT * FROM mandate WHERE mandate_key=%s AND valid_to IS NULL AND is_draft=%s ORDER BY id",
                        (key, is_draft)).fetchall()


def already_recorded(conn: psycopg.Connection, key: str, source_doc: int) -> bool:
    return conn.execute("SELECT 1 FROM mandate WHERE mandate_key=%s AND source_doc_id=%s", (key, source_doc)).fetchone() is not None


def insert_mandate(conn: psycopg.Connection, v: dict) -> int:
    cols = list(v)
    vals = [Jsonb(x) if k == "conditions" else x for k, x in v.items()]
    return conn.execute(f"INSERT INTO mandate ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) RETURNING id",
                        vals).fetchone()["id"]


def close(conn: psycopg.Connection, mid: int, valid_to: date, by: int | None) -> None:
    conn.execute("UPDATE mandate SET valid_to=%s, superseded_by=%s WHERE id=%s AND valid_to IS NULL",
                 (valid_to, by, mid))


def supersede(conn: psycopg.Connection, key: str, values: dict, notified: date, is_draft: bool) -> tuple[int, list[int]]:
    """Insert the new version and close the open ones (same key, same draft flag)."""
    olds = open_versions(conn, key, is_draft)
    new_id = insert_mandate(conn, {**values, "mandate_key": key, "is_draft": is_draft, "valid_from": notified})
    for o in olds:
        close(conn, o["id"], max(notified, o["valid_from"] or notified), new_id)
    return new_id, [o["id"] for o in olds]


def resolve_standard_ids(conn: psycopg.Connection, refs: list[str]) -> list[int]:
    ids = []
    for r in refs:
        if r.startswith("AIS-"):
            row = conn.execute("SELECT id FROM document WHERE canonical_id=%s", (r,)).fetchone() or conn.execute(
                "SELECT id FROM document WHERE family_key=%s AND is_current", (r.split("(Rev")[0],)).fetchone()
            if row:
                ids.append(row["id"])
    return ids


def mandates_for_document(conn: psycopg.Connection, doc: dict, op: str) -> dict:
    """Create mandate versions from one notification. Idempotent per (mandate_key, source document)."""
    stats = {"inserted": 0, "closed": 0, "date_changes": []}
    notified = doc["doc_date"]
    if not notified:
        return stats
    is_draft = doc["status"] == "draft"
    items, dsubs, omits = parse_table_amendments(op)
    common = {"date_of_notification": notified, "effective_date": notified, "source_doc_id": doc["id"],
              "usage": doc.get("usage") or [], "powertrains": doc.get("powertrains") or []}
    for it in items:
        if already_recorded(conn, it.key, doc["id"]):
            continue
        v = {**common, "legal_basis": it.key, "subject": it.subject, "standard_refs": it.standards,
             "standard_doc_ids": resolve_standard_ids(conn, it.standards), "vehicle_categories": it.categories,
             "conditions": it.conditions, "model_scope": "all", "implementation_date": it.implementation_date,
             "implementation_rule": it.date_text}
        _, closed = supersede(conn, it.key, v, notified, is_draft)
        stats["inserted"] += 1
        stats["closed"] += len(closed)
    for ds in dsubs:
        # rows of the named serial numbers whose date equals the old date; if none (an intermediate notification
        # is missing from the corpus), the row's latest-dated open items
        keys = [r["mandate_key"] for r in conn.execute(
            "SELECT DISTINCT mandate_key FROM mandate WHERE valid_to IS NULL AND NOT is_draft AND "
            "(mandate_key = ANY(%s) OR mandate_key LIKE ANY(%s))",
            ([f"{ds.table} Sr.{s}" for s in ds.serials], [f"{ds.table} Sr.{s}(%" for s in ds.serials]))]
        rows = [r for k in keys for r in open_versions(conn, k)]
        if ds.items:
            rows = [r for r in rows if any(r["mandate_key"].endswith(f"({i})") for i in ds.items)]
        hit = [r for r in rows if r["implementation_date"] == ds.old]
        mismatch = False
        if not hit and rows:
            for s in ds.serials:
                srows = [r for r in rows if re.search(rf"Sr\.{s}(\(|$)", r["mandate_key"]) and r["implementation_date"]]
                if srows:
                    mx = max(r["implementation_date"] for r in srows)
                    hit += [r for r in srows if r["implementation_date"] == mx and mx < ds.new]
            mismatch = bool(hit)
        for r in hit:
            if already_recorded(conn, r["mandate_key"], doc["id"]):
                continue
            v = {k: r[k] for k in ("legal_basis", "subject", "standard_refs", "standard_doc_ids", "vehicle_categories",
                                   "conditions", "model_scope", "usage", "powertrains")}
            v.update(common)
            v.update(implementation_date=ds.new, implementation_rule=f"extended from {r['implementation_date']}")
            new_id, closed = supersede(conn, r["mandate_key"], v, notified, is_draft)
            stats["inserted"] += 1
            stats["closed"] += len(closed)
            stats["date_changes"].append({"mandate_id": new_id, "key": r["mandate_key"],
                                          "old": str(r["implementation_date"]), "new": str(ds.new),
                                          "stated_old": str(ds.old), "old_date_mismatch": mismatch})
    for om in omits:
        for r in open_versions(conn, f"{om.table} Sr.{om.serial}"):
            close(conn, r["id"], notified, None)
            stats["closed"] += 1
    if not items and not dsubs:
        for ob in parse_rule_obligations(op):
            if already_recorded(conn, ob.key, doc["id"]):
                continue
            v = {**common, "legal_basis": ob.rule, "subject": ob.subject, "standard_refs": ob.standards,
                 "standard_doc_ids": resolve_standard_ids(conn, ob.standards), "vehicle_categories": ob.categories,
                 "conditions": ob.conditions, "model_scope": ob.model_scope,
                 "implementation_date": ob.implementation_date, "implementation_rule": None}
            supersede(conn, ob.key, v, notified, is_draft)
            stats["inserted"] += 1
    # Qwen provisions (when present and not already covered)
    for prov in (doc.get("data") or {}).get("provisions", []) or []:
        for imp in prov.get("implementation") or []:
            if not imp.get("date") or not prov.get("target"):
                continue
            key = f"{prov['target']} :: {(prov.get('standards') or [prov.get('subject') or ''])[0]}"[:200]
            if already_recorded(conn, key, doc["id"]):
                continue
            v = {**common, "legal_basis": prov["target"], "subject": prov.get("subject"),
                 "standard_refs": prov.get("standards") or [], "standard_doc_ids": resolve_standard_ids(conn, prov.get("standards") or []),
                 "vehicle_categories": P.expand_letters([P.norm_category(c) or c for c in prov.get("categories") or []]),
                 "conditions": prov.get("conditions") or {}, "model_scope": imp.get("model_scope") or "all",
                 "implementation_date": date.fromisoformat(imp["date"]), "implementation_rule": imp.get("rule")}
            supersede(conn, key, v, notified, is_draft)
            stats["inserted"] += 1
    return stats


def finalise_drafts(conn: psycopg.Connection, final_doc: int, draft_doc: int, notified: date) -> int:
    """When a final arrives, its draft's open mandates are closed (superseded by the final's version if any)."""
    n = 0
    for r in conn.execute("SELECT * FROM mandate WHERE source_doc_id=%s AND is_draft AND valid_to IS NULL", (draft_doc,)):
        rep = conn.execute("SELECT id FROM mandate WHERE source_doc_id=%s AND mandate_key=%s", (final_doc, r["mandate_key"])).fetchone()
        close(conn, r["id"], max(notified, r["valid_from"] or notified), rep["id"] if rep else None)
        n += 1
    return n
