"""Portal API for the approved 'Regulatory Intelligence Portal v2' design, on RegTrack data.

Scope: India only, vehicle categories L1 / L2 / M1 / N1 (and regulations for ALL vehicles). In the design,
'Region' becomes the vehicle category; 'Authority' is the issuer; 'Domain' the topic.

Impact and status are rule-based until the Qwen pass runs (each row says impact_basis='rules'):
  impact  High   = technical and (an open obligation still to come, a revision needing re-approval,
                   or published in the last 12 months)
          Medium = other technical documents        Low = administrative / procedural
  status  team-set value if any; else Under Review (unreviewed change in the last 30 days or a draft),
          Action Required (High with an obligation still to come), Impact Analysis (other High), Tracked.
Writes (review, compliance, alerts, settings, sync) go to the workflow tables of migration 0002 only.
"""

from __future__ import annotations

import csv
import html
import io
import threading
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import Response

from regtrack.db import connect

router = APIRouter(prefix="/portal", tags=["portal"])

CATEGORIES = ["L1", "L2", "M1", "N1"]
SCOPE = CATEGORIES + ["ALL"]
CAT_LABEL = {"L1": "L1 Moped", "L2": "L2 Two-wheeler", "M1": "M1 Car", "N1": "N1 Light goods", "ALL": "All vehicles"}
DOMAIN_LABEL = {
    "safety_equipment": "Safety equipment", "braking": "Braking", "lighting": "Lighting", "emission": "Emission",
    "fuel_efficiency": "Fuel efficiency", "ev_alt_fuel": "EV / alt fuel", "battery": "Battery", "charging": "Charging",
    "cybersecurity": "Cybersecurity", "tracking_its": "Tracking / ITS", "type_approval": "Type approval",
    "dimensions_weights": "Dimensions / weights", "registration": "Registration", "hsrp": "HSRP",
    "licensing": "Licensing", "permit": "Permits", "fees": "Fees", "fitness_puc": "Fitness / PUC",
    "recall_scrappage": "Recall / scrappage",
}
STATUSES = ["Action Required", "Under Review", "Impact Analysis", "Tracked"]
DRAFTS = ("NOTIFICATION_DRAFT", "AIS_DRAFT")


def _rows(conn, sql: str, args=None) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def _setting(conn, key: str, default: str = "") -> str:
    r = conn.execute("SELECT value FROM app_setting WHERE key=%s", (key,)).fetchone()
    return r["value"] if r else default


# ====================================================================== regulations (shared)
REG_SQL = """
SELECT d.id, d.canonical_id, d.doc_class, d.official_title, d.subject, d.issuer, d.status AS doc_status, d.doc_date,
       d.nature, d.vehicle_categories, d.domains, d.family_key, d.is_current,
       coalesce((d.extraction->>'llm_pending')::boolean, false) AS ai_pending,
       (SELECT min(m.implementation_date) FROM mandate m WHERE m.source_doc_id=d.id AND m.valid_to IS NULL
          AND NOT m.is_draft AND m.implementation_date >= current_date) AS next_obligation,
       (SELECT count(*) FROM mandate m WHERE m.source_doc_id=d.id AND m.valid_to IS NULL) AS open_mandates,
       EXISTS (SELECT 1 FROM doc_relation r WHERE r.from_doc=d.id AND r.requires_reapproval) AS reapproval,
       ce.event_type AS last_event, ce.detected_at AS last_event_at, ce.summary AS last_event_summary,
       ce.review_status AS last_event_review,
       rv.status AS review_status, rv.impact AS review_impact, rv.owner AS review_owner, rv.note AS review_note
FROM document d
LEFT JOIN LATERAL (SELECT event_type, detected_at, summary, review_status FROM change_event e
                   WHERE e.document_id=d.id ORDER BY detected_at DESC LIMIT 1) ce ON true
LEFT JOIN document_review rv ON rv.document_id=d.id
WHERE d.doc_class <> 'OFF_TOPIC' AND d.vehicle_categories && %s {where}
"""


def classify_row(r: dict, today: date | None = None) -> dict:
    today = today or date.today()
    technical = r["nature"] == "technical" or (r["doc_class"] or "").startswith(("AIS_", "TAP_"))
    recent = bool(r["doc_date"] and r["doc_date"] >= today - timedelta(days=365))
    upcoming = r["next_obligation"] is not None
    if r.get("review_impact"):
        impact, basis = r["review_impact"], "team"
    elif technical and (upcoming or r["reapproval"] or recent):
        impact, basis = "High", "rules"
    elif technical:
        impact, basis = "Medium", "rules"
    else:
        impact, basis = "Low", "rules"
    fresh_change = (r["last_event_at"] and r["last_event_review"] != "confirmed"
                    and r["last_event_at"].date() >= today - timedelta(days=30))
    if r.get("review_status"):
        status = r["review_status"]
    elif fresh_change or r["doc_class"] in DRAFTS or r["doc_status"] == "draft":
        status = "Under Review"
    elif impact == "High" and upcoming:
        status = "Action Required"
    elif impact == "High":
        status = "Impact Analysis"
    else:
        status = "Tracked"
    cats = [c for c in CATEGORIES if c in (r["vehicle_categories"] or [])] or (["ALL"] if "ALL" in (r["vehicle_categories"] or []) else [])
    r.update(
        name=r["official_title"] or r["subject"] or r["canonical_id"], impact=impact, impact_basis=basis,
        status=status, region=", ".join(cats), categories=cats, authority=r["issuer"] or "—",
        domain=DOMAIN_LABEL.get((r["domains"] or [None])[0], "General") if r["domains"] else "General",
        effective=r["next_obligation"] or r["doc_date"],
    )
    return r


def regulations(conn, category: str | None = None, extra_where: str = "", args: tuple = ()) -> list[dict]:
    cats = [category] if category in CATEGORIES else SCOPE
    if category in CATEGORIES:
        cats = [category, "ALL"]
    rows = _rows(conn, REG_SQL.format(where=extra_where), (cats, *args))
    return [classify_row(r) for r in rows]


def follow_up(r: dict) -> str:
    dc = r["doc_class"]
    if r["reapproval"]:
        return "New revision: type approvals to the earlier revision need re-approval - check affected models and plan re-testing."
    if dc == "NOTIFICATION_DRAFT":
        return "Draft rules: review the proposal, assess the impact on affected models and send comments before the comment period ends."
    if dc == "AIS_DRAFT":
        return "Draft standard: compare with current designs and test capability; track until it is published and notified."
    if dc == "NOTIFICATION_EXTENSION":
        return "Implementation date changed: update the compliance plan and supplier timelines to the new date."
    if r["next_obligation"]:
        return f"Obligation from {r['next_obligation']}: confirm applicability per model, map requirements to tests and evidence, assign owners."
    if dc in ("AIS_AMENDMENT", "AIS_CORRIGENDUM"):
        return "Amendment to a standard: check the changed clauses against current homologation evidence."
    if r["nature"] == "administrative":
        return "Administrative change (registration / licence / fees): inform the homologation and dealer-operations teams."
    return "Confirm applicability for L1/L2/M1/N1 models and record the decision."


def detected_change(conn, doc_id: int) -> str:
    rels = _rows(conn, """SELECT r.type, coalesce(t.canonical_id, r.to_ref) AS target, r.details FROM doc_relation r
                          LEFT JOIN document t ON t.id=r.to_doc WHERE r.from_doc=%s AND r.type <> 'references'
                          ORDER BY r.id LIMIT 6""", (doc_id,))
    parts = []
    for r in rels:
        d = r["details"] or {}
        if r["type"] == "extends_date" and d.get("new_date"):
            parts.append(f"extends dates in {r['target']} {d.get('table', '').split()[-1] if d.get('table') else ''} "
                         f"rows {', '.join(d.get('rows', []))}: {d.get('old_date') or '?'} → {d['new_date']}")
        elif r["type"] in ("substitutes_row", "inserts_row", "omits_row"):
            parts.append(f"{r['type'].replace('_', ' ')} in {r['target']} ({', '.join(d.get('rows', [])[:6])})")
        else:
            parts.append(f"{r['type'].replace('_', ' ')} {r['target']}")
    return "; ".join(parts) or "New or updated document detected by the source monitoring."


# ====================================================================== dashboard
@router.get("/summary")
def summary() -> dict:
    today = date.today()
    with connect() as conn:
        regs = regulations(conn)
        months = _rows(conn, """SELECT to_char(m, 'Mon') AS label, to_char(m, 'YYYY-MM') AS ym,
                   (SELECT count(*) FROM document d WHERE d.doc_class<>'OFF_TOPIC' AND d.vehicle_categories && %s
                      AND date_trunc('month', d.doc_date)=m) AS n
                   FROM generate_series(date_trunc('month', current_date) - interval '11 months',
                                        date_trunc('month', current_date), interval '1 month') m ORDER BY m""", (SCOPE,))
        changes = _rows(conn, """SELECT count(*) AS n, count(*) FILTER (WHERE review_status<>'confirmed') AS open
                                 FROM change_event WHERE detected_at > now() - interval '30 days'""")[0]
        # upcoming obligations: notified (final) and proposed (draft notifications), soonest first
        deadlines = _rows(conn, """SELECT m.mandate_key, m.subject, m.implementation_date, m.vehicle_categories,
                   m.is_draft, d.canonical_id FROM mandate m JOIN document d ON d.id=m.source_doc_id
                   WHERE m.valid_to IS NULL AND m.vehicle_categories && %s
                     AND m.implementation_date >= current_date ORDER BY m.implementation_date, m.is_draft LIMIT 6""", (SCOPE,))
        recent_deadlines = _rows(conn, """SELECT m.mandate_key, m.subject, m.implementation_date, m.vehicle_categories,
                   m.is_draft, d.canonical_id FROM mandate m JOIN document d ON d.id=m.source_doc_id
                   WHERE m.valid_to IS NULL AND NOT m.is_draft AND m.vehicle_categories && %s
                     AND m.implementation_date <= current_date
                   ORDER BY m.implementation_date DESC LIMIT 6""", (SCOPE,))
        sources = _rows(conn, "SELECT count(*) AS n, max(last_run_at) AS last FROM source WHERE code<>'LOCAL_SEED'")[0]
    sev = {k: sum(1 for r in regs if r["impact"] == k) for k in ("High", "Medium", "Low")}
    changed = [r for r in regs if r["last_event_at"] and r["last_event_at"].date() >= today - timedelta(days=30)]
    by_cat = [{"name": CAT_LABEL[c], "code": c, "n": sum(1 for r in regs if c in r["categories"])} for c in CATEGORIES]
    dom: dict[str, int] = {}
    for r in regs:
        for d in r["domains"] or []:
            dom[d] = dom.get(d, 0) + 1
    top_dom = [{"name": DOMAIN_LABEL.get(k, k), "code": k, "n": v} for k, v in sorted(dom.items(), key=lambda kv: -kv[1])[:5]]
    latest = sorted([r for r in regs if r["doc_date"]], key=lambda r: r["doc_date"], reverse=True)[:6]
    return {
        "kpis": {"tracked": len(regs), "new_this_quarter": sum(1 for r in regs if r["doc_date"] and r["doc_date"] >= today - timedelta(days=90)),
                 "changes_30d": changes["n"], "changes_open": changes["open"], "high": sev["High"],
                 "action_required": sum(1 for r in regs if r["status"] == "Action Required")},
        "trend": months, "severity": sev, "changed_30d": len(changed), "by_category": by_cat, "top_domains": top_dom,
        "latest": [_reg_out(r) for r in latest], "deadlines": deadlines, "recent_deadlines": recent_deadlines,
        "sources": sources["n"], "last_sync": sources["last"],
    }


def _reg_out(r: dict) -> dict:
    keys = ("id", "canonical_id", "name", "doc_class", "region", "categories", "authority", "domain", "domains", "effective",
            "doc_date", "impact", "impact_basis", "status", "ai_pending", "next_obligation", "family_key")
    return {k: r.get(k) for k in keys}


# ====================================================================== regulation library
@router.get("/regulations")
def regulation_list(q: str | None = None, category: str | None = None, impact: str | None = None,
                    status: str | None = None) -> dict:
    today = date.today()
    with connect() as conn:
        regs = regulations(conn, category)
        comp = _rows(conn, """SELECT coalesce(issuer,'Unknown') AS name, count(*) AS n FROM document
                              WHERE doc_class<>'OFF_TOPIC' AND vehicle_categories && %s GROUP BY 1 ORDER BY 2 DESC LIMIT 6""", (SCOPE,))
    rows = regs
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in " ".join(str(r.get(k) or "") for k in ("canonical_id", "name", "authority", "domain")).lower()]
    if impact in ("High", "Medium", "Low"):
        rows = [r for r in rows if r["impact"] == impact]
    if status in STATUSES:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["effective"] or date(1900, 1, 1)), reverse=True)
    return {
        "kpis": {"records": len(regs), "new_quarter": sum(1 for r in regs if r["doc_date"] and r["doc_date"] >= today - timedelta(days=90)),
                 "drafts": sum(1 for r in regs if r["doc_class"] in DRAFTS or r["doc_status"] == "draft"),
                 "high": sum(1 for r in regs if r["impact"] == "High")},
        "count": len(rows), "rows": [_reg_out(r) for r in rows], "composition": comp,
    }


@router.get("/regulations/{canonical_id:path}/detail")
def regulation_detail(canonical_id: str) -> dict:
    with connect() as conn:
        regs = regulations(conn, None, "AND d.canonical_id=%s", (canonical_id,))
        if not regs:
            raise HTTPException(404, "not an in-scope regulation")
        r = regs[0]
        files = _rows(conn, """SELECT fo.sha256, fo.ext FROM document_file df JOIN file_object fo ON fo.id=df.file_id
                               WHERE df.document_id=%s ORDER BY df.is_best_copy DESC LIMIT 1""", (r["id"],))
        out = _reg_out(r)
        out.update(summary=r["subject"] or r["official_title"] or "No summary yet (AI pending).",
                   change=r["last_event_summary"] and f"{r['last_event'].replace('_', ' ')}: {r['last_event_summary']}"
                   or detected_change(conn, r["id"]),
                   action=follow_up(r), owner=r["review_owner"], note=r["review_note"],
                   file=files[0] if files else None)
    return out


@router.put("/regulations/{canonical_id:path}/review")
def set_review(canonical_id: str, body: dict = Body(...)) -> dict:
    if body.get("status") and body["status"] not in STATUSES:
        raise HTTPException(400, "bad status")
    if body.get("impact") and body["impact"] not in ("High", "Medium", "Low"):
        raise HTTPException(400, "bad impact")
    with connect() as conn:
        d = conn.execute("SELECT id FROM document WHERE canonical_id=%s", (canonical_id,)).fetchone()
        if not d:
            raise HTTPException(404, "unknown document")
        conn.execute("""INSERT INTO document_review (document_id, status, impact, owner, note) VALUES (%s,%s,%s,%s,%s)
                        ON CONFLICT (document_id) DO UPDATE SET status=EXCLUDED.status, impact=EXCLUDED.impact,
                        owner=EXCLUDED.owner, note=EXCLUDED.note, updated_at=now()""",
                     (d["id"], body.get("status") or "Tracked", body.get("impact"), body.get("owner"), body.get("note")))
        conn.commit()
    return {"ok": True}


# ====================================================================== change monitor
@router.get("/changes")
def change_monitor(days: int = 365) -> dict:
    with connect() as conn:
        sla = int(_setting(conn, "review_sla_days", "2"))
        events = _rows(conn, """SELECT e.id, e.event_type, e.detected_at, e.summary, e.review_status, e.details,
                   d.canonical_id, d.id AS doc_id FROM change_event e LEFT JOIN document d ON d.id=e.document_id
                   WHERE e.detected_at > now() - make_interval(days => %s) ORDER BY e.detected_at DESC, e.id DESC""", (days,))
        regs = {r["id"]: r for r in regulations(conn)}
    for e in events:
        r = regs.get(e["doc_id"])
        e["impact"] = r["impact"] if r else "Low"
        e["in_scope"] = r is not None
        e["name"] = r["name"] if r else e["canonical_id"]
        e["ai_summary_pending"] = (e["details"] or {}).get("summary_by") == "template"
    now = datetime.now().astimezone()
    reviewed = [e for e in events if e["review_status"] == "confirmed"]
    open_ = [e for e in events if e["review_status"] != "confirmed"]

    def age(e) -> float:
        end = datetime.fromisoformat(e["details"]["reviewed_at"]) if (e["details"] or {}).get("reviewed_at") else now
        return (end - e["detected_at"]).total_seconds() / 86400

    within = sum(1 for e in reviewed if age(e) <= sla)
    by_type: dict[str, int] = {}
    for e in events:
        by_type[e["event_type"]] = by_type.get(e["event_type"], 0) + 1
    return {
        "kpis": {"detected": len(events), "unreviewed": len(open_), "high": sum(1 for e in events if e["impact"] == "High"),
                 "reviewed": len(reviewed)},
        "events": events[:200], "by_type": sorted(by_type.items(), key=lambda kv: -kv[1]),
        "sla": {"days": sla, "within": within, "reviewed": len(reviewed),
                "buckets": [["≤ 2 days", sum(1 for e in reviewed if age(e) <= 2)],
                            ["3–5 days", sum(1 for e in reviewed if 2 < age(e) <= 5)],
                            ["> 5 days", sum(1 for e in reviewed if age(e) > 5)]],
                "overdue": sum(1 for e in open_ if age(e) > sla)},
    }


@router.post("/changes/review")
def review_changes(body: dict = Body(...)) -> dict:
    ids = [int(i) for i in body.get("ids", [])]
    with connect() as conn:
        n = conn.execute("""UPDATE change_event SET review_status='confirmed',
                            details = coalesce(details,'{}'::jsonb) || jsonb_build_object('reviewed_at', now())
                            WHERE id = ANY(%s) AND review_status <> 'confirmed'""", (ids,)).rowcount
        conn.commit()
    return {"reviewed": n}


# ====================================================================== compliance matrix
COMP_SQL = """
SELECT m.mandate_key, m.legal_basis, m.subject, m.standard_refs, m.vehicle_categories, m.implementation_date,
       m.model_scope, d.canonical_id, d.domains, ci.owner, ci.evidence, coalesce(ci.status, 'Open') AS status,
       coalesce(ci.due_date, m.implementation_date) AS due_date, ci.note, ci.updated_at
FROM mandate m JOIN document d ON d.id=m.source_doc_id
LEFT JOIN compliance_item ci ON ci.mandate_key=m.mandate_key
WHERE m.valid_to IS NULL AND NOT m.is_draft AND m.vehicle_categories && %s
ORDER BY coalesce(ci.due_date, m.implementation_date) DESC NULLS LAST, m.mandate_key
"""


@router.get("/compliance")
def compliance(category: str | None = None) -> dict:
    cats = [category, "ALL"] if category in CATEGORIES else SCOPE
    with connect() as conn:
        rows = _rows(conn, COMP_SQL, (cats,))
        default_owner = _setting(conn, "default_owner", "Regulatory Affairs Team")
    for r in rows:
        r["domain"] = DOMAIN_LABEL.get((r["domains"] or [None])[0], "General") if r["domains"] else "General"
        r["requirement"] = f"{r['legal_basis']}"
        r["categories"] = [c for c in SCOPE if c in (r["vehicle_categories"] or [])]
    n = len(rows) or 1
    count = {s: sum(1 for r in rows if r["status"] == s) for s in ("Compliant", "In Progress", "Open", "Not Applicable")}
    applicable = n - count["Not Applicable"] or 1
    today = date.today()
    by_dom: dict[str, list[int]] = {}
    for r in rows:
        if r["status"] == "Not Applicable":
            continue
        t = by_dom.setdefault(r["domain"], [0, 0])
        t[0] += r["status"] == "Compliant"
        t[1] += 1
    return {
        "kpis": {"compliant_pct": round(100 * count["Compliant"] / applicable), "in_progress_pct": round(100 * count["In Progress"] / applicable),
                 "open_pct": round(100 * count["Open"] / applicable),
                 "due_90": sum(1 for r in rows if r["due_date"] and today <= r["due_date"] <= today + timedelta(days=90)
                               and r["status"] not in ("Compliant", "Not Applicable")),
                 "requirements": len(rows), "tracked": sum(1 for r in rows if r["updated_at"])},
        "rows": rows, "default_owner": default_owner,
        "readiness": sorted([{"name": k, "pct": round(100 * v[0] / v[1]), "n": v[1]} for k, v in by_dom.items()],
                            key=lambda x: -x["n"])[:5],
    }


@router.put("/compliance/{mandate_key:path}")
def set_compliance(mandate_key: str, body: dict = Body(...)) -> dict:
    if body.get("status", "Open") not in ("Open", "In Progress", "Compliant", "Not Applicable"):
        raise HTTPException(400, "bad status")
    due = body.get("due_date") or None
    with connect() as conn:
        if not conn.execute("SELECT 1 FROM mandate WHERE mandate_key=%s LIMIT 1", (mandate_key,)).fetchone():
            raise HTTPException(404, "unknown requirement")
        conn.execute("""INSERT INTO compliance_item (mandate_key, owner, evidence, status, due_date, note)
                        VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (mandate_key) DO UPDATE SET owner=EXCLUDED.owner,
                        evidence=EXCLUDED.evidence, status=EXCLUDED.status, due_date=EXCLUDED.due_date,
                        note=EXCLUDED.note, updated_at=now()""",
                     (mandate_key, body.get("owner"), body.get("evidence"), body.get("status", "Open"), due, body.get("note")))
        conn.commit()
    return {"ok": True}


# ====================================================================== impact view
@router.get("/impact")
def impact() -> dict:
    with connect() as conn:
        regs = regulations(conn)
        stds = _rows(conn, """SELECT s AS name, count(*) AS n FROM mandate m, unnest(m.standard_refs) s
                              WHERE m.valid_to IS NULL AND NOT m.is_draft AND m.vehicle_categories && %s
                              GROUP BY 1 ORDER BY 2 DESC LIMIT 5""", (SCOPE,))
        owners = conn.execute("SELECT count(DISTINCT owner) AS n FROM compliance_item WHERE owner IS NOT NULL AND owner<>''").fetchone()["n"]
    dom: dict[str, int] = {}
    for r in regs:
        for d in r["domains"] or []:
            dom[d] = dom.get(d, 0) + (2 if r["impact"] == "High" else 1)
    top = [d for d, _ in sorted(dom.items(), key=lambda kv: -kv[1])[:5]]
    counts = {d: {c: sum((2 if r["impact"] == "High" else 1) for r in regs if d in (r["domains"] or [])
                         and (c in r["categories"] or "ALL" in (r["vehicle_categories"] or []))) for c in CATEGORIES} for d in top}
    peak = max([v for row in counts.values() for v in row.values()] or [1]) or 1
    score = {d: {c: max(1, min(5, 1 + round(4 * v / peak))) if v else 1 for c, v in row.items()} for d, row in counts.items()}
    cells = [{"domain": DOMAIN_LABEL.get(d, d), "code": d, "scores": [score[d][c] for c in CATEGORIES],
              "counts": [counts[d][c] for c in CATEGORIES]} for d in top]
    critical = sum(1 for d in top if max(score[d].values()) >= 4)
    return {"categories": CATEGORIES, "cells": cells, "top_standards": stds,
            "kpis": {"critical": critical,
                     "top1": {"name": DOMAIN_LABEL.get(top[0], top[0]) if top else "—", "n": sum(1 for r in regs if top and top[0] in (r["domains"] or []))},
                     "top2": {"name": DOMAIN_LABEL.get(top[1], top[1]) if len(top) > 1 else "—", "n": sum(1 for r in regs if len(top) > 1 and top[1] in (r["domains"] or []))},
                     "owners": owners}}


@router.get("/impact/cell")
def impact_cell(category: str, domain: str) -> dict:
    with connect() as conn:
        regs = [r for r in regulations(conn, category) if domain in (r["domains"] or [])]
    regs.sort(key=lambda r: ({"High": 0, "Medium": 1, "Low": 2}[r["impact"]], -(r["effective"] or date(1900, 1, 1)).toordinal()))
    return {"category": category, "domain": DOMAIN_LABEL.get(domain, domain), "count": len(regs),
            "rows": [_reg_out(r) for r in regs[:6]]}


# ====================================================================== ask regulatory AI
@router.post("/ask")
def ask(body: dict = Body(...)) -> dict:
    from pydantic import BaseModel

    from regtrack import llm
    from regtrack.pipeline.search import search as chunk_search

    q = (body.get("question") or "").strip()
    if not q:
        raise HTTPException(400, "empty question")
    cat = next((c for c in CATEGORIES if c.lower() in q.lower().split() or c in q), None)
    with connect() as conn:
        res = chunk_search(conn, q, cat, None, None, None, 8)
    hits = res["results"]
    sources = [{"canonical_id": h["canonical_id"], "clause": h["clause_no"], "pages": f"{h['page_from']}-{h['page_to']}",
                "title": h["official_title"] or h["subject"], "snippet": " ".join((h["content"] or "").split())[:300]} for h in hits]
    ok, _ = llm.reachable()
    if ok and hits:
        class Answer(BaseModel):
            answer: str

        ctx = "\n\n".join(f"[{i + 1}] {h['canonical_id']} clause {h['clause_no']}: {h['content'][:1200]}" for i, h in enumerate(hits))
        try:
            a = llm.structured(Answer, "Answer questions about Indian vehicle regulations using only the numbered sources. "
                                       "Cite sources as [n]. Say so if the sources do not answer the question.",
                               f"Question: {q}\n\nSources:\n{ctx}", timeout=180)
            return {"mode": "qwen", "answer": a.answer, "sources": sources}
        except Exception as e:  # noqa: BLE001
            note = f"AI answer failed ({type(e).__name__}); showing the matching clauses instead."
    else:
        note = "AI answers start once LM Studio is connected; until then these are the best-matching clauses."
    if not hits:
        return {"mode": "search", "answer": "No matching clauses found in the indexed regulations.", "sources": [], "note": note}
    lines = [f"Found {len(hits)} matching clause(s) in {len({h['canonical_id'] for h in hits})} document(s):", ""]
    for h in hits[:5]:
        lines.append(f"• {h['canonical_id']}" + (f" clause {h['clause_no']}" if h["clause_no"] else "")
                     + f": {' '.join((h['content'] or '').split())[:200]}…")
    return {"mode": "search", "answer": "\n".join(lines), "sources": sources, "note": note}


# ====================================================================== reports
REPORTS = {
    "executive": "Executive Regulatory Summary",
    "compliance_gap": "Compliance Gap Report",
    "change_impact": "Change Impact Report",
}


@router.get("/reports")
def reports() -> dict:
    with connect() as conn:
        recent = _rows(conn, "SELECT * FROM report_log ORDER BY generated_at DESC LIMIT 20")
        month = conn.execute("SELECT count(*) AS n FROM report_log WHERE generated_at > date_trunc('month', now())").fetchone()["n"]
        awaiting = conn.execute("SELECT count(*) AS n FROM change_event WHERE review_status<>'confirmed'").fetchone()["n"]
    return {"kpis": {"generated_month": month, "scheduled": 0, "awaiting_review": awaiting, "templates": len(REPORTS)},
            "templates": [{"kind": k, "name": v} for k, v in REPORTS.items()], "recent": recent}


def _html(title: str, intro: str, sections: list[tuple[str, list[str], list[list]]]) -> str:
    out = [f"<!doctype html><meta charset='utf-8'><title>{html.escape(title)}</title><style>body{{font-family:Segoe UI,Arial;"
           f"margin:32px;color:#172033}}h1{{font-size:22px}}h2{{font-size:15px;margin-top:26px}}table{{border-collapse:collapse;"
           f"width:100%;font-size:12px}}th,td{{border-bottom:1px solid #e3e8f0;padding:6px 8px;text-align:left}}"
           f"th{{background:#fafbfd;color:#6f7b8e;text-transform:uppercase;font-size:10px}}</style>",
           f"<h1>{html.escape(title)}</h1><p>{html.escape(intro)}</p>"]
    for h, head, rows in sections:
        out.append(f"<h2>{html.escape(h)}</h2><table><tr>" + "".join(f"<th>{html.escape(x)}</th>" for x in head) + "</tr>")
        for r in rows:
            out.append("<tr>" + "".join(f"<td>{html.escape(str(x if x is not None else ''))}</td>" for x in r) + "</tr>")
        out.append("</table>")
    return "".join(out)


@router.get("/reports/{kind}")
def generate_report(kind: str, fmt: str = "html", owner: str = "Regulatory Affairs") -> Response:
    if kind not in REPORTS:
        raise HTTPException(404, "unknown report")
    title = REPORTS[kind]
    stamp = datetime.now().strftime("%d %b %Y %H:%M")
    if kind == "executive":
        s = summary()
        ch = change_monitor(30)
        sections = [
            ("Key figures", ["Measure", "Value"], [["Regulations tracked (India, L1/L2/M1/N1)", s["kpis"]["tracked"]],
                                                   ["Changes in last 30 days", s["kpis"]["changes_30d"]],
                                                   ["High impact (rule-based)", s["kpis"]["high"]],
                                                   ["Action required", s["kpis"]["action_required"]]]),
            ("Regulations by vehicle category", ["Category", "Documents"], [[c["name"], c["n"]] for c in s["by_category"]]),
            ("Top topics", ["Topic", "Documents"], [[d["name"], d["n"]] for d in s["top_domains"]]),
            ("Latest regulations", ["ID", "Regulation", "Date", "Impact", "Status"],
             [[r["canonical_id"], r["name"], r["doc_date"], r["impact"], r["status"]] for r in s["latest"]]),
            ("Upcoming implementation dates", ["Requirement", "Subject", "Date", "Source"],
             [[d["mandate_key"], d["subject"], d["implementation_date"], d["canonical_id"]] for d in s["deadlines"]]),
            ("Changes in the last 30 days", ["Detected", "Type", "Document", "Summary"],
             [[e["detected_at"].strftime("%d %b %Y"), e["event_type"], e["canonical_id"], e["summary"]] for e in ch["events"][:30]]),
        ]
        head, rows = sections[3][1], sections[3][2]
    elif kind == "compliance_gap":
        c = compliance()
        gaps = [r for r in c["rows"] if r["status"] in ("Open", "In Progress")]
        sections = [("Readiness", ["Measure", "Value"], [["Requirements", c["kpis"]["requirements"]], ["Compliant %", c["kpis"]["compliant_pct"]],
                                                         ["In progress %", c["kpis"]["in_progress_pct"]], ["Open %", c["kpis"]["open_pct"]],
                                                         ["Due within 90 days", c["kpis"]["due_90"]]]),
                    ("Open requirements", ["Requirement", "Subject", "Standards", "Categories", "Owner", "Evidence", "Status", "Due"],
                     [[r["legal_basis"], r["subject"], ", ".join(r["standard_refs"] or []), ", ".join(r["categories"]), r["owner"],
                       r["evidence"], r["status"], r["due_date"]] for r in gaps])]
        head, rows = sections[1][1], sections[1][2]
    else:
        ch = change_monitor(365)
        sections = [("Changes by type", ["Type", "Count"], [[t, n] for t, n in ch["by_type"]]),
                    ("Change events", ["Detected", "Type", "Document", "Impact", "Reviewed", "Summary"],
                     [[e["detected_at"].strftime("%d %b %Y"), e["event_type"], e["canonical_id"], e["impact"],
                       "yes" if e["review_status"] == "confirmed" else "no", e["summary"]] for e in ch["events"]])]
        head, rows = sections[1][1], sections[1][2]
    with connect() as conn:
        conn.execute("INSERT INTO report_log (kind, scope, owner, rows) VALUES (%s,%s,%s,%s)",
                     (title, "India · L1/L2/M1/N1", owner, len(rows)))
        conn.commit()
    fname = f"{title.replace(' ', '_')}_{date.today().isoformat()}"
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(head)
        w.writerows(rows)
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{fname}.csv"'})
    body = _html(title, f"RegTrack India · India, vehicle categories L1/L2/M1/N1 · generated {stamp}. "
                        f"Impact is rule-based until the AI pass runs.", sections)
    return Response(body, media_type="text/html", headers={"Content-Disposition": f'attachment; filename="{fname}.html"'})


# ====================================================================== alerts
def _evaluate(conn, rule: dict, regs: dict) -> list[dict]:
    scope = rule["scope"]

    def in_scope(cats) -> bool:
        return scope == "All categories" or scope in (cats or []) or "ALL" in (cats or [])

    out = []
    if rule["condition"] == "due_within":
        days = int(rule["param"] or 60)
        for m in _rows(conn, """SELECT m.mandate_key, m.subject, m.implementation_date, m.vehicle_categories, d.canonical_id,
                                m.is_draft FROM mandate m JOIN document d ON d.id=m.source_doc_id WHERE m.valid_to IS NULL
                                AND m.vehicle_categories && %s AND m.implementation_date BETWEEN current_date AND current_date + %s""",
                           (SCOPE, days)):
            if in_scope(m["vehicle_categories"]):
                out.append({"when": m["implementation_date"].isoformat(),
                            "title": f"{'Proposed' if m['is_draft'] else 'Implementation'} date within {days} days",
                            "text": f"{m['mandate_key']}: {m['subject'] or ''}"[:200], "canonical_id": m["canonical_id"]})
        return out
    events = _rows(conn, """SELECT e.id, e.event_type, e.detected_at, e.summary, e.document_id, d.canonical_id
                            FROM change_event e LEFT JOIN document d ON d.id=e.document_id
                            WHERE e.detected_at > now() - interval '30 days' ORDER BY e.detected_at DESC""")
    want = {"new_document": "new_document", "draft_published": "draft_published", "draft_finalised": "draft_finalised",
            "date_changed": "implementation_date_changed"}
    for e in events:
        r = regs.get(e["document_id"])
        if not r or not in_scope(r["vehicle_categories"]):
            continue
        cond = rule["condition"]
        hit = (cond == "high_impact" and r["impact"] == "High") or (cond in want and e["event_type"] == want[cond]) \
            or (cond == "domain" and rule["param"] in (r["domains"] or []))
        if hit:
            out.append({"when": e["detected_at"].strftime("%Y-%m-%d %H:%M"), "title": rule["name"],
                        "text": (e["summary"] or e["canonical_id"] or "")[:200], "canonical_id": e["canonical_id"]})
    return out


@router.get("/alerts")
def alerts() -> dict:
    with connect() as conn:
        rules = _rows(conn, "SELECT * FROM alert_rule ORDER BY id")
        regs = {r["id"]: r for r in regulations(conn)}
        notes = []
        for rule in rules:
            if rule["enabled"]:
                n = _evaluate(conn, rule, regs)
                rule["matches"] = len(n)
                notes += n
            else:
                rule["matches"] = 0
        due60 = conn.execute("""SELECT count(*) AS n FROM mandate WHERE valid_to IS NULL AND vehicle_categories && %s
                                AND implementation_date BETWEEN current_date AND current_date + 60""", (SCOPE,)).fetchone()["n"]
        resolved = conn.execute("""SELECT count(*) AS n FROM change_event WHERE review_status='confirmed'
                                   AND (details->>'reviewed_at')::timestamptz > date_trunc('month', now())""").fetchone()["n"]
    seen, uniq = set(), []
    for n in sorted(notes, key=lambda x: x["when"], reverse=True):
        k = (n["title"], n["canonical_id"], n["when"])
        if k not in seen:
            seen.add(k)
            uniq.append(n)
    return {"kpis": {"active": sum(1 for r in rules if r["enabled"]), "action": len(uniq), "due_soon": due60, "resolved": resolved},
            "rules": rules, "notifications": uniq[:50],
            "conditions": ["high_impact", "new_document", "draft_published", "draft_finalised", "date_changed", "due_within", "domain"],
            "domains": [{"code": k, "label": v} for k, v in DOMAIN_LABEL.items()]}


@router.post("/alerts")
def add_alert(body: dict = Body(...)) -> dict:
    with connect() as conn:
        r = conn.execute("INSERT INTO alert_rule (name, scope, condition, param) VALUES (%s,%s,%s,%s) RETURNING id",
                         (body.get("name") or "New regulatory watch", body.get("scope") or "All categories",
                          body.get("condition") or "new_document", body.get("param"))).fetchone()
        conn.commit()
    return {"id": r["id"]}


@router.patch("/alerts/{rule_id}")
def toggle_alert(rule_id: int, body: dict = Body(...)) -> dict:
    with connect() as conn:
        conn.execute("UPDATE alert_rule SET enabled=%s WHERE id=%s", (bool(body.get("enabled")), rule_id))
        conn.commit()
    return {"ok": True}


@router.delete("/alerts/{rule_id}")
def delete_alert(rule_id: int) -> dict:
    with connect() as conn:
        conn.execute("DELETE FROM alert_rule WHERE id=%s", (rule_id,))
        conn.commit()
    return {"ok": True}


# ====================================================================== admin & sources
_sync_lock = threading.Lock()
_sync_state: dict = {"running": None, "last": None}


@router.get("/admin")
def admin() -> dict:
    with connect() as conn:
        sources = _rows(conn, """SELECT s.code, s.name, s.base_url, s.schedule_hours, s.last_run_at, s.last_status,
                   (SELECT count(*) FROM file_sighting f WHERE f.source_id=s.id) AS sightings
                   FROM source s ORDER BY s.id""")
        runs = _rows(conn, """SELECT r.id, s.code, r.started_at, r.finished_at, r.status, r.stats FROM crawl_run r
                              JOIN source s ON s.id=r.source_id ORDER BY r.id DESC LIMIT 15""")
        tot = conn.execute("""SELECT count(*) AS n, count(*) FILTER (WHERE status IN ('ok','partial')) AS good,
                              count(*) FILTER (WHERE status='partial') AS partial
                              FROM crawl_run WHERE started_at > now() - interval '30 days'""").fetchone()
        warnings = conn.execute("""SELECT count(*) AS n FROM quality_flag WHERE resolved_at IS NULL
                                   AND rule IN ('low_ocr_confidence','schema_violation','identity_not_found')""").fetchone()["n"]
        settings = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM app_setting")}
    live = [s for s in sources if s["code"] != "LOCAL_SEED"]
    last = max((s["last_run_at"] for s in live if s["last_run_at"]), default=None)
    for r in runs:
        st = r["stats"] or {}
        r["documents"] = st.get("seen", st.get("files", 0))
        r["changes"] = st.get("new_files", st.get("file_object_new", 0))
    return {"kpis": {"connected": sum(1 for s in live if s["last_status"] in ("ok", "partial")), "sources": len(live),
                     "success_pct": round(100 * tot["good"] / tot["n"], 1) if tot["n"] else None,
                     "warnings": warnings, "partial_runs": tot["partial"],
                     "last_sync_min": int((datetime.now().astimezone() - last).total_seconds() // 60) if last else None},
            "sources": sources, "runs": runs, "settings": settings, "sync": _sync_state}


@router.put("/settings")
def put_settings(body: dict = Body(...)) -> dict:
    allowed = {"default_owner", "review_sla_days", "high_impact_rule", "auto_sync", "auto_compliance_task"}
    with connect() as conn:
        for k, v in body.items():
            if k in allowed:
                conn.execute("INSERT INTO app_setting (key, value) VALUES (%s,%s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",
                             (k, str(v)))
        conn.commit()
    return {"ok": True}


@router.post("/admin/sync")
def run_sync(body: dict = Body(default={})) -> dict:
    """Start one source crawl + pipeline run in the background (one at a time)."""
    from regtrack.scheduler import run_source

    code = body.get("source") or "MORTH_API"
    if code not in ("MORTH_API", "ARAI_AIS", "EGAZETTE", "INDIACODE"):
        raise HTTPException(400, "unknown source")
    if not _sync_lock.acquire(blocking=False):
        return {"started": False, "running": _sync_state["running"]}

    def work() -> None:
        try:
            _sync_state["running"] = code
            res = run_source(code)
            _sync_state["last"] = {"source": code, "finished": datetime.now().isoformat(), "crawl": res.get("crawl")}
        except Exception as e:  # noqa: BLE001
            _sync_state["last"] = {"source": code, "error": f"{type(e).__name__}: {e}"[:300]}
        finally:
            _sync_state["running"] = None
            _sync_lock.release()

    threading.Thread(target=work, daemon=True).start()
    return {"started": True, "source": code}


@router.get("/meta")
def portal_meta() -> dict:
    with connect() as conn:
        s = conn.execute("""SELECT count(*) FILTER (WHERE code<>'LOCAL_SEED' AND last_status IN ('ok','partial')) AS n,
                            max(last_run_at) FILTER (WHERE code<>'LOCAL_SEED') AS last FROM source""").fetchone()
    return {"sources": s["n"], "last_sync": s["last"], "categories": [{"code": c, "label": CAT_LABEL[c]} for c in CATEGORIES],
            "statuses": STATUSES, "domains": [{"code": k, "label": v} for k, v in DOMAIN_LABEL.items()]}
