"""Link stage: 'parsed' -> 'linked'. regulation_relations rows, family versions, rule versions
(compliance_requirements / requirement_versions, written by mandates.py).

Relation sources (deterministic first):
  finalises     final -> draft: "draft ... published vide G.S.R. X dated Y" (regex) or equal file_no (file_no)
  amends/corrects/extends_date/exempts  notification -> notification it changes
  inserts_row / substitutes_row / omits_row  S.O. 1365(E) / Rule 124(4) table changes (details.rows)
  amends / corrects / revises  AIS amendment, corrigendum, new revision (revises => requires_reapproval)
  annex_of      AIS-007 table -> AIS-007(Rev.5);  interprets: interpretation manual -> standard
  supersedes    "deemed to comply with AIS-xxx"
  references    cited AIS / IS / UN R / other notifications
Unknown targets keep to_regulation_id NULL and to_ref = canonical id; resolve_refs() fills them when the target
arrives.
"""

from __future__ import annotations

import re

import psycopg

from regtrack import country
from regtrack.db import Jsonb
from regtrack.models.enums import DocClass, FlagRule
from regtrack.pipeline import country_mandates as CM
from regtrack.pipeline import mandates as M
from regtrack.pipeline import patterns as P
from regtrack.pipeline import repo as R
from regtrack.pipeline.dbutil import add_flag, set_stage, update_if_changed
from regtrack.pipeline.extract import operative_text
from regtrack.pipeline.text import english_text, load_pages


def doc_by_cid(conn: psycopg.Connection, cid: str) -> dict | None:
    return conn.execute(
        "SELECT id, published_date AS doc_date, legal_status AS status, local_class AS doc_class "
        f"FROM regulations WHERE external_code=%s AND {country.region_sql()}",
        (cid,),
    ).fetchone()


def add_relation(
    conn: psycopg.Connection,
    from_doc: int,
    rtype: str,
    to_cid: str | None = None,
    to_doc: int | None = None,
    details: dict | None = None,
    evidence: str | None = None,
    method: str = "regex",
    confidence: float = 0.9,
    requires_reapproval: bool | None = None,
    page: int | None = None,
) -> bool:
    """Insert unless an identical (from, type, target) relation exists. Returns True if inserted."""
    if to_doc is None and to_cid:
        t = doc_by_cid(conn, to_cid)
        to_doc = t["id"] if t else None
    if to_doc == from_doc:
        return False
    ref = to_cid if to_doc is None else (to_cid or None)
    hit = conn.execute(
        "SELECT 1 FROM regulation_relations WHERE from_regulation_id=%s AND type=%s "
        "AND coalesce(to_regulation_id,0)=coalesce(%s,0) AND coalesce(to_ref,'')=coalesce(%s,'') "
        "AND coalesce(details,'{}'::jsonb)=%s::jsonb",
        (from_doc, rtype, to_doc, ref, Jsonb(details or {})),
    ).fetchone()
    if hit:
        return False
    if to_doc is None and not ref:
        return False
    conn.execute(
        """INSERT INTO regulation_relations (from_regulation_id, to_regulation_id, to_ref, type, requires_reapproval,
                                             details, evidence, page, confidence, method)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            from_doc,
            to_doc,
            ref,
            rtype,
            requires_reapproval,
            Jsonb(details) if details else None,
            (evidence or "")[:500] or None,
            page,
            confidence,
            method,
        ),
    )
    return True


# ---------------------------------------------------------------------- per class
def link_notification(conn: psycopg.Connection, doc: dict, op: str) -> None:
    data = doc["data"] or {}
    dc = DocClass(doc["doc_class"])
    # final -> draft
    dref = data.get("draft_ref")
    if dref and doc["status"] == "final":
        add_relation(
            conn,
            doc["id"],
            "finalises",
            to_cid=dref["canonical_id"],
            details={"draft_date": dref.get("date")},
            evidence=f"draft published vide {dref['canonical_id']}",
            method="regex",
        )
        t = doc_by_cid(conn, dref["canonical_id"])
        if t is None:
            add_flag(conn, "regulation", doc["id"], FlagRule.UNRESOLVED_REFERENCE, {"draft": dref["canonical_id"]})
        elif dref.get("date") and t["doc_date"] and str(t["doc_date"]) != dref["date"]:
            add_flag(
                conn,
                "regulation",
                doc["id"],
                FlagRule.DRAFT_FINAL_DATE_MISMATCH,
                {"cited": dref["date"], "draft_doc_date": str(t["doc_date"]), "draft": dref["canonical_id"]},
            )
    elif doc["status"] == "final" and data.get("file_no"):
        for d in conn.execute(
            "SELECT id, external_code AS canonical_id FROM regulations WHERE legal_status='draft' "
            "AND data->>'file_no'=%s AND local_class='NOTIFICATION_DRAFT' "
            f"AND (published_date IS NULL OR published_date <= %s) AND {country.region_sql()}",
            (data["file_no"], doc["doc_date"]),
        ).fetchall():
            add_relation(
                conn,
                doc["id"],
                "finalises",
                to_doc=d["id"],
                to_cid=d["canonical_id"],
                evidence=f"same file no {data['file_no']}",
                method="file_no",
                confidence=0.7,
            )
    # changes to other notifications
    rtype = {
        "NOTIFICATION_CORRIGENDUM": "corrects",
        "NOTIFICATION_EXTENSION": "extends_date",
        "NOTIFICATION_EXEMPTION": "exempts",
    }.get(dc.value, "amends")
    for cid in data.get("amends_notification") or []:
        add_relation(conn, doc["id"], rtype, to_cid=cid, evidence=f"{rtype} {cid}")
    # table rows (S.O. 1365(E) / Rule 124(4))
    items, dsubs, omits = M.parse_table_amendments(op)
    base = M.base_table(op)
    if base:
        target = "SO-1365(E)-2004" if base.startswith("SO-1365") else None
        tref = target or base
        if items:
            rows = sorted({f"{i.table.replace(base, '').strip() or 'Table'} {i.serial}({i.item})" for i in items})
            kind = (
                "inserts_row"
                if re.search(r"shall\s+be\s+inserted", op, re.I)
                and not re.search(r"shall\s+be\s+substituted", op, re.I)
                else "substitutes_row"
            )
            add_relation(conn, doc["id"], kind, to_cid=tref, details={"rows": rows[:60]})
        for ds in dsubs:
            add_relation(
                conn,
                doc["id"],
                "extends_date",
                to_cid=tref,
                details={
                    "table": ds.table,
                    "rows": ds.serials,
                    "old_date": str(ds.old) if ds.old else None,
                    "new_date": str(ds.new),
                },
                evidence=ds.evidence,
            )
        for om in omits:
            add_relation(conn, doc["id"], "omits_row", to_cid=tref, details={"table": om.table, "rows": [om.serial]})
    # references
    for r in (data.get("references") or [])[:40]:
        add_relation(conn, doc["id"], "references", to_cid=r, method="regex", confidence=0.8)
    for cid in (data.get("other_ids") or [])[:20]:
        if cid not in (data.get("amends_notification") or []) and (not dref or cid != dref["canonical_id"]):
            add_relation(conn, doc["id"], "references", to_cid=cid, method="regex", confidence=0.6)


def link_ais(conn: psycopg.Connection, doc: dict) -> None:
    data = doc["data"] or {}
    dc = DocClass(doc["doc_class"])
    if (
        dc in (DocClass.AIS_AMENDMENT, DocClass.AIS_CORRIGENDUM)
        and data.get("amends")
        and not doc["vehicle_categories"]
    ):
        # an amendment applies to the vehicles of the standard it amends
        base = R.find_document(conn, data["amends"])
        if base and base["vehicle_categories"]:
            R.update_document(
                conn,
                doc["id"],
                {
                    "vehicle_categories": base["vehicle_categories"],
                    "in_scope": base["in_scope"],
                    "domains": doc["domains"] or base["domains"],
                    "powertrains": doc["powertrains"] or base["powertrains"],
                },
            )
    if dc == DocClass.AIS_AMENDMENT and data.get("amends"):
        add_relation(conn, doc["id"], "amends", to_cid=data["amends"], details={"amendment_no": doc["amendment_no"]})
    elif dc == DocClass.AIS_CORRIGENDUM and data.get("amends"):
        add_relation(
            conn, doc["id"], "corrects", to_cid=data["amends"], details={"corrigendum_no": doc["corrigendum_no"]}
        )
    elif dc == DocClass.AIS_STANDARD and doc["revision"]:
        p = P.parse_canonical_ais(doc["canonical_id"])
        if p:
            prev = P.ais_canonical(p["code"], p["part"], (p["rev"] - 1) or None)
            add_relation(
                conn, doc["id"], "revises", to_cid=prev, requires_reapproval=True, details={"revision": p["rev"]}
            )
    elif dc == DocClass.AIS_FORM_TABLE and data.get("annex_of"):
        add_relation(conn, doc["id"], "annex_of", to_cid=data["annex_of"], details={"table": data.get("table_ref")})
    elif dc == DocClass.AIS_INTERPRETATION and data.get("interprets"):
        add_relation(conn, doc["id"], "interprets", to_cid=data["interprets"])
    for d in data.get("deemed_compliance") or []:
        add_relation(conn, doc["id"], "supersedes", to_cid=d, details={"basis": "deemed to comply"}, confidence=0.8)
    for r in (data.get("references") or [])[:40]:
        add_relation(conn, doc["id"], "references", to_cid=r, method="regex", confidence=0.8)


# ---------------------------------------------------------------------- versions
def notification_family(doc: dict) -> str | None:
    data = doc["data"] or {}
    if doc["canonical_id"] == "SO-1365(E)-2004" or "SO-1365(E)-2004 Table" in (data.get("amends_targets") or []):
        return "SO-1365-MASTER"
    if any(t.startswith("CMVR Rule 124") for t in data.get("amends_targets") or []):
        return "CMVR-Rule-124"
    return None


def tis_family(conn: psycopg.Connection, rows: list[dict], versioned: list[dict]) -> None:
    """TIS-721-2551, TIS-721-2568, ...: ordered by edition year; the newest is current, the older ones superseded."""
    versioned = sorted(versioned, key=lambda r: (r["year"] or 0, r["id"]))
    current_id = versioned[-1]["id"]
    for r in rows:  # clear the old current first (partial unique index)
        if r["is_current"] and r["id"] != current_id:
            conn.execute("UPDATE regulations SET is_current=false WHERE id=%s", (r["id"],))
    for i, r in enumerate(versioned):
        status = "final" if r["id"] == current_id else "superseded"
        update_if_changed(
            conn,
            "regulations",
            {"id": r["id"]},
            {"version_seq": i + 1, "is_current": r["id"] == current_id, "legal_status": status},
        )


def recompute_family(conn: psycopg.Connection, family_key: str) -> None:
    """version_seq in order, exactly one is_current per family (drafts excluded)."""
    rows = conn.execute(
        """SELECT id, external_code AS canonical_id, local_class AS doc_class, legal_status AS status, revision,
                  amendment_no, corrigendum_no, published_date AS doc_date, version_seq, is_current, year
           FROM regulations WHERE family_key=%s AND """
        + country.region_sql(),
        (family_key,),
    ).fetchall()
    if not rows:
        return
    versioned = [
        r for r in rows if r["doc_class"] not in ("AIS_DRAFT", "NOTIFICATION_DRAFT") and r["status"] != "draft"
    ]
    if versioned and all(r["doc_class"] == "TIS_STANDARD" for r in versioned):
        tis_family(conn, rows, versioned)  # Thai standards: editions differ by their year, not a revision number
        return

    def by_date(r: dict) -> tuple:
        return r["doc_date"] or P.date(1900, 1, 1), r["id"]

    def by_revision(r: dict) -> tuple:
        return (
            r["revision"] or 0,
            r["amendment_no"] or 0,
            r["corrigendum_no"] or 0,
            r["doc_class"] != "AIS_STANDARD",
            r["id"],
        )

    versioned.sort(key=by_date if family_key.startswith(("SO-1365", "CMVR-Rule")) else by_revision)
    current_id = None
    if family_key.startswith(("SO-1365", "CMVR-Rule")):
        current_id = versioned[-1]["id"] if versioned else None
    else:
        bases = [
            r
            for r in versioned
            if r["doc_class"]
            in ("AIS_STANDARD", "SAFETY_STANDARD_LEGACY", "TAP_DOCUMENT", "AIS_FORM_TABLE", "FORM_TEMPLATE")
        ]
        top_rev = max((r["revision"] or 0) for r in versioned) if versioned else 0
        cur = [r for r in bases if (r["revision"] or 0) == top_rev] or bases or versioned
        current_id = cur[-1]["id"] if cur else None
    # clear the old current first (partial unique index)
    for r in rows:
        if r["is_current"] and r["id"] != current_id:
            conn.execute("UPDATE regulations SET is_current=false WHERE id=%s", (r["id"],))
    seq = {r["id"]: i + 1 for i, r in enumerate(versioned)}
    top_rev = max((r["revision"] or 0) for r in versioned) if versioned else 0
    for r in rows:
        status = r["status"]
        if (
            r["doc_class"] == "AIS_STANDARD"
            and (r["revision"] or 0) < top_rev
            and status == "final"
            and not family_key.startswith(("SO-1365", "CMVR-Rule"))
        ):
            status = "superseded"
        elif (
            r["doc_class"] == "AIS_STANDARD"
            and (r["revision"] or 0) >= top_rev
            and status == "superseded"
            and not family_key.startswith(("SO-1365", "CMVR-Rule"))
        ):
            status = "final"  # the newer revision turned out to be a draft (or was retired): this one is in force again
        update_if_changed(
            conn,
            "regulations",
            {"id": r["id"]},
            {"version_seq": seq.get(r["id"]), "is_current": r["id"] == current_id, "legal_status": status},
        )


# ---------------------------------------------------------------------- stage
def stage_link(conn: psycopg.Connection, f: dict) -> str:
    pages = load_pages(f["sha256"])
    families: set[str] = set()
    for df in R.parts_of_file(conn, f["id"], readable_only=True):
        doc = R.get_document(conn, df["document_id"])
        dc = DocClass(doc["doc_class"])
        if dc == DocClass.OFF_TOPIC:
            continue
        if dc.is_notification:
            op = operative_text(english_text(pages, df["page_from"], df["page_to"]))
            link_notification(conn, doc, op)
            fam = notification_family(doc)
            if fam:
                R.update_document(conn, doc["id"], {"family_key": fam})
                families.add(fam)
            if doc["status"] == "final" or dc == DocClass.NOTIFICATION_DRAFT:
                stats = M.mandates_for_document(conn, doc, op)
                record_date_changes(conn, doc, stats)
                for rel in conn.execute(
                    "SELECT to_regulation_id FROM regulation_relations WHERE from_regulation_id=%s "
                    "AND type='finalises' AND to_regulation_id IS NOT NULL",
                    (doc["id"],),
                ).fetchall():
                    M.finalise_drafts(conn, doc["id"], rel["to_regulation_id"], doc["doc_date"])
        elif dc.is_ais:
            link_ais(conn, doc)
        elif dc == DocClass.TIS_STANDARD:
            CM.tis_mandate(conn, doc)
        elif dc == DocClass.MY_GUIDELINE:
            CM.my_mandates(conn, doc, english_text(pages, df["page_from"], df["page_to"]))
        if doc["family_key"]:
            families.add(doc["family_key"])
    for fam in families:
        recompute_family(conn, fam)
    set_stage(conn, f["id"], "linked")
    return "linked"


def record_date_changes(conn: psycopg.Connection, doc: dict, stats: dict) -> None:
    for ch in stats.get("date_changes", []):
        if ch.get("old_date_mismatch"):
            add_flag(
                conn,
                "requirement_version",
                ch["mandate_id"],
                "old_date_mismatch",
                {
                    "key": ch["key"],
                    "stated_old": ch["stated_old"],
                    "replaced": ch["old"],
                    "note": "an intermediate amendment is probably missing from the corpus",
                },
            )
        if doc["doc_date"] and ch["new"] and ch["new"] < str(doc["doc_date"]):
            add_flag(conn, "requirement_version", ch["mandate_id"], FlagRule.IMPLEMENTATION_BEFORE_NOTIFICATION, ch)


def resolve_refs(conn: psycopg.Connection) -> int:
    """Fill to_regulation_id for relations whose target has arrived since (same region as the citing regulation)."""
    cur = conn.execute(f"""UPDATE regulation_relations r SET to_regulation_id=g.id
                           FROM regulations g, regulations src
                           WHERE r.to_regulation_id IS NULL AND r.to_ref=g.external_code AND g.id<>r.from_regulation_id
                             AND src.id=r.from_regulation_id AND src.region_id=g.region_id
                             AND {country.region_sql("g")}""")
    n = cur.rowcount
    # a plain reference without the revision ("AIS-002(Part1)") means the standard: its current edition. Not for
    # amends / revises / finalises, which name one exact document (Rev.1's amendment never amends Rev.3).
    n += conn.execute(f"""UPDATE regulation_relations r SET to_regulation_id=g.id
                          FROM regulations g, regulations src
                          WHERE r.to_regulation_id IS NULL AND r.type='references' AND r.to_ref=g.family_key
                            AND g.is_current AND g.id<>r.from_regulation_id
                            AND src.id=r.from_regulation_id AND src.region_id=g.region_id
                            AND {country.region_sql("g")}""").rowcount
    # G.S.R. 590(E) of 1989 notified the Central Motor Vehicles Rules: a reference to it means the CMVR, held as
    # consolidated texts (the original 1989 notification is not collected) - the most complete one (most pages)
    n += conn.execute(f"""UPDATE regulation_relations r SET to_regulation_id=c.id
                          FROM regulations src,
                               (SELECT g.id, g.region_id FROM regulations g JOIN document_parts p ON p.regulation_id = g.id
                                JOIN documents f ON f.id = p.document_id
                                WHERE g.local_class = 'CONSOLIDATED_RULES' AND {country.region_sql("g")}
                                  AND coalesce(g.title, g.summary) ILIKE '%%CENTRAL MOTOR VEHICLES RULES%%'
                                ORDER BY f.page_count DESC NULLS LAST, g.id LIMIT 1) c
                          WHERE r.to_regulation_id IS NULL AND r.type = 'references' AND r.to_ref = 'GSR-590(E)-1989'
                            AND src.id = r.from_regulation_id AND src.region_id = c.region_id
                            AND r.from_regulation_id <> c.id""").rowcount
    if n:
        conn.execute("""UPDATE quality_flags q SET resolved_at=now() FROM regulation_relations r, regulations g
                        WHERE q.rule='unresolved_reference' AND q.resolved_at IS NULL AND q.entity='regulation'
                          AND q.entity_id=r.from_regulation_id AND r.type='finalises' AND r.to_regulation_id=g.id
                          AND q.details->>'draft'=g.external_code""")
    return n


def rederive_mandates(conn: psycopg.Connection, apply: bool = False, docs: list[str] | None = None) -> list[dict]:
    """After a mandate-parser fix: correct the open mandate versions of notifications (see mandates.py). docs limits the
    rule-obligation pass to those canonical IDs; S.O. 1365 table categories are always checked."""
    out = M.correct_table_categories(conn, apply)
    for row in conn.execute(
        """SELECT p.regulation_id, p.document_id, p.page_from, p.page_to FROM regulations g
               JOIN document_parts p ON p.regulation_id=g.id AND p.is_best_copy
               WHERE g.local_class LIKE 'NOTIFICATION%%' AND """
        + country.region_sql("g")
        + " ORDER BY g.published_date NULLS LAST, g.id"
    ).fetchall():
        doc = R.get_document(conn, row["regulation_id"])
        if docs is not None and doc["canonical_id"] not in docs:
            continue
        if not (doc["status"] == "final" or doc["doc_class"] == DocClass.NOTIFICATION_DRAFT.value):
            continue
        f = R.get_file(conn, row["document_id"])
        op = operative_text(english_text(load_pages(f["sha256"]), row["page_from"], row["page_to"]))
        out += M.correct_rule_obligations(conn, doc, op, apply)
    return out
