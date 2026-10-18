"""Portal API for the approved 'Regulatory Intelligence Portal v2' design, on RegTrack data.

Scope: India only, vehicle categories L1 / L2 / M1 / N1 (and regulations for ALL vehicles). In the design,
'Region' becomes the vehicle category; 'Authority' is the issuer; 'Domain' the topic.

Impact and status are rule-based until the team sets them (each row says impact_basis 'rules' or 'team'):
  impact  stored in regulations.impact_level by the pipeline (migration 0010, refresh_regulation_fields):
          High   = technical and (an open obligation still to come, a revision needing re-approval,
                   or published in the last 12 months)
          Medium = other technical documents        Low = administrative / procedural
  status  team-set value if any; else Under Review (unreviewed change in the last 30 days or a draft),
          Action Required (High with an obligation still to come), Impact Analysis (other High), Tracked.
Reads and writes the v4B tables (docs/SCHEMA_V4B.md) through regtrack/api/sql.py, which keeps the response shape.
Team decisions are stored where v4 keeps them: regulations (workflow_status, impact_level/impact_basis, owner team,
review_note), compliance_requirements (owner team, status, due date, evidence, note), alert_rules, reports.
Every view shows one country: ?country= if given, else the COUNTRY setting (regtrack/country.py).
"""

from __future__ import annotations

import csv
import html
import io
import re
import threading
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import Response

from regtrack import country
from regtrack.api import sql as S
from regtrack.api.params import CountryParam, resolve_country
from regtrack.db import Jsonb, connect

router = APIRouter(prefix="/portal", tags=["portal"])

CATEGORIES = ["L1", "L2", "M1", "N1"]
SCOPE = CATEGORIES + ["ALL"]
# labels come from the vocabulary tables (vehicle_categories, domains); refreshed every 10 minutes
CAT_LABEL: dict[str, str] = {}
DOMAIN_LABEL: dict[str, str] = {}
_vocab_at: datetime | None = None
IMPACT_RULE = ("High = technical, with an obligation still to come, a revision needing re-approval, or published in the "
               "last 12 months; Medium = other technical; Low = administrative (registration, licences, fees)")
STATUSES = ["Action Required", "Under Review", "Impact Analysis", "Tracked"]
DRAFTS = ("NOTIFICATION_DRAFT", "AIS_DRAFT")
# not regulations themselves: reports, AIS-007 form tables, catalogues, lists, unclassified - kept out of the register by default
REFERENCE_CLASSES = ("REPORT", "OTHER", "AIS_FORM_TABLE", "FORM_TEMPLATE", "BIS_CATALOGUE", "APPROVED_LIST")
AMENDMENT_RULES = re.compile(r"\((?:[\w-]+\s+)?Amendment\)\s+(?:Rules|Regulations?)", re.I)


def _short(label: str) -> str:
    """Drop the bracketed detail: "Two-wheeler (max design speed > 45 km/h)" -> "Two-wheeler"."""
    return label.split("(")[0].strip()


def load_vocab(conn) -> None:
    global _vocab_at
    if _vocab_at and datetime.now() - _vocab_at < timedelta(minutes=10) and CAT_LABEL:
        return
    cats = {r["code"]: f"{r['code']} {_short(r['label'])}"
            for r in conn.execute(f"SELECT code, label FROM vehicle_categories v WHERE {country.region_sql('v')}")}
    CAT_LABEL.clear()
    CAT_LABEL.update(cats)
    CAT_LABEL.setdefault("ALL", "All vehicles")
    DOMAIN_LABEL.clear()
    DOMAIN_LABEL.update({r["code"]: r["label"] for r in conn.execute(
        "SELECT lower(code) AS code, name AS label FROM domains ORDER BY code")})
    _vocab_at = datetime.now()


def _rows(conn, sql: str, args=None) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def _setting(conn, key: str, default: str = "") -> str:
    return S.settings(conn).get(key, default)


def team_id(conn, name: str | None) -> int | None:
    """The team called `name` (created on first use, as migration 0007 did for free-text owners); None for blank."""
    name = (name or "").strip()
    if not name:
        return None
    row = conn.execute("SELECT id FROM teams WHERE name=%s", (name,)).fetchone()
    if row:
        return row["id"]
    code = (re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper() or "TEAM")[:30]
    if conn.execute("SELECT 1 FROM teams WHERE code=%s", (code,)).fetchone():
        code = f"{code[:22]}_{abs(hash(name)) % 10**7}"
    return conn.execute("INSERT INTO teams (code, name) VALUES (%s,%s) RETURNING id", (code, name)).fetchone()["id"]


# ====================================================================== regulations (shared)
REG_SQL = """
SELECT d.id, d.canonical_id, d.doc_class, d.official_title, d.subject, d.issuer, d.status AS doc_status, d.doc_date,
       d.nature, d.vehicle_categories, d.domains, d.family_key, d.is_current,
       coalesce((d.extraction->>'llm_pending')::boolean, false) AS ai_pending,
       (SELECT min(v.implementation_date) FROM requirement_versions v WHERE v.source_regulation_id=d.id
          AND v.valid_to IS NULL AND NOT v.is_draft AND v.implementation_date >= current_date) AS next_obligation,
       (SELECT count(*) FROM requirement_versions v WHERE v.source_regulation_id=d.id AND v.valid_to IS NULL) AS open_mandates,
       EXISTS (SELECT 1 FROM regulation_relations r WHERE r.from_regulation_id=d.id AND r.requires_reapproval) AS reapproval,
       ce.change_type AS last_event, ce.detected_at AS last_event_at, ce.summary AS last_event_summary,
       ce.review AS last_event_review,
       initcap(replace(g.workflow_status, '_', ' ')) AS review_status,
       CASE WHEN g.impact_basis = 'team' THEN initcap(g.impact_level) END AS review_impact,
       CASE WHEN g.impact_basis = 'rules' THEN initcap(g.impact_level) END AS rule_impact,
       t.name AS review_owner, g.review_note
FROM {docs} d
JOIN regulations g ON g.id = d.id
LEFT JOIN teams t ON t.id = g.owner_team_id
LEFT JOIN LATERAL (SELECT e.change_type, e.detected_at, e.summary, {review} AS review FROM regulation_changes e
                   WHERE e.regulation_id=d.id ORDER BY e.detected_at DESC LIMIT 1) ce ON true
WHERE d.doc_class <> 'OFF_TOPIC' AND d.vehicle_categories && %s {where}
"""


def classify_row(r: dict, today: date | None = None) -> dict:
    today = today or date.today()
    technical = r["nature"] == "technical" or (r["doc_class"] or "").startswith(("AIS_", "TAP_"))
    recent = bool(r["doc_date"] and r["doc_date"] >= today - timedelta(days=365))
    upcoming = r["next_obligation"] is not None
    if r.get("review_impact"):
        impact, basis = r["review_impact"], "team"
    elif r.get("rule_impact"):  # stored by the pipeline (migration 0010); the rule below mirrors it for rows not yet refreshed
        impact, basis = r["rule_impact"], "rules"
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
    formal, subject = (r["official_title"] or "").strip(), (r["subject"] or "").strip()
    if formal and subject and subject != formal and AMENDMENT_RULES.search(formal) and not AMENDMENT_RULES.search(subject):
        name, subtitle = subject, formal  # "Amends CMVR Rule 125 ..." tells more than "Central Motor Vehicles (Tenth Amendment) Rules"
    else:
        name, subtitle = formal or subject or r["canonical_id"], None
    r.update(
        name=name, subtitle=subtitle, impact=impact, impact_basis=basis,
        status=status, region=", ".join(cats), categories=cats, authority=r["issuer"] or "—",
        domain=DOMAIN_LABEL.get((r["domains"] or [None])[0], "General") if r["domains"] else "General",
        effective=r["next_obligation"] or r["doc_date"],
    )
    return r


def regulations(conn, category: str | None = None, extra_where: str = "", args: tuple = (),
                history: bool = False, reference: bool = False, cc: str | None = None) -> list[dict]:
    """In-scope regulations of one country (cc, default the setting) with impact/status. history=False leaves out
    superseded and withdrawn documents, reference=False leaves out reports, form tables, catalogues and unclassified
    documents."""
    load_vocab(conn)
    if not history:
        extra_where = "AND d.status NOT IN ('superseded','withdrawn') " + extra_where
    if not reference:
        extra_where = "AND d.doc_class NOT IN ('" + "','".join(REFERENCE_CLASSES) + "') " + extra_where
    cats = [category] if category in CATEGORIES else SCOPE
    if category in CATEGORIES:
        cats = [category, "ALL"]
    rows = _rows(conn, REG_SQL.format(where=extra_where, docs=S.docs(cc), review=S.REVIEW.format(e="e")), (cats, *args))
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
    return f"Confirm applicability for {'/'.join(r['categories'] or CATEGORIES)} models and record the decision."


def detected_change(conn, doc_id: int) -> str:
    rels = _rows(conn, """SELECT r.type, coalesce(t.external_code, r.to_ref) AS target, r.details FROM regulation_relations r
                          LEFT JOIN regulations t ON t.id=r.to_regulation_id
                          WHERE r.from_regulation_id=%s AND r.type <> 'references'
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
def summary(cc: CountryParam = None) -> dict:
    today = date.today()
    cc = resolve_country(cc)
    with connect() as conn:
        regs = regulations(conn, cc=cc)
        months = _rows(conn, f"""SELECT to_char(m, 'Mon') AS label, to_char(m, 'YYYY-MM') AS ym,
                   (SELECT count(*) FROM {S.docs(cc)} d WHERE d.doc_class<>'OFF_TOPIC' AND d.vehicle_categories && %s
                      AND date_trunc('month', d.doc_date)=m) AS n
                   FROM generate_series(date_trunc('month', current_date) - interval '11 months',
                                        date_trunc('month', current_date), interval '1 month') m ORDER BY m""", (SCOPE,))
        changes = _rows(conn, f"""SELECT count(*) AS n, count(*) FILTER (WHERE e.review_status<>'confirmed') AS open
                                 FROM {S.changes(cc)} e JOIN {S.docs(cc)} d ON d.id=e.document_id
                                 WHERE e.detected_at > now() - interval '30 days' AND d.doc_class <> 'OFF_TOPIC'
                                   AND d.vehicle_categories && %s""", (SCOPE,))[0]
        # upcoming obligations: notified (final) and proposed (draft notifications), soonest first
        deadlines = _rows(conn, f"""SELECT m.mandate_key, m.subject, m.implementation_date, m.vehicle_categories,
                   m.is_draft, d.external_code AS canonical_id FROM {S.mandates(cc)} m JOIN regulations d ON d.id=m.source_doc_id
                   WHERE m.valid_to IS NULL AND m.vehicle_categories && %s
                     AND m.implementation_date >= current_date ORDER BY m.implementation_date, m.is_draft, m.mandate_key LIMIT 6""", (SCOPE,))
        recent_deadlines = _rows(conn, f"""SELECT m.mandate_key, m.subject, m.implementation_date, m.vehicle_categories,
                   m.is_draft, d.external_code AS canonical_id FROM {S.mandates(cc)} m JOIN regulations d ON d.id=m.source_doc_id
                   WHERE m.valid_to IS NULL AND NOT m.is_draft AND m.vehicle_categories && %s
                     AND m.implementation_date <= current_date
                   ORDER BY m.implementation_date DESC, m.mandate_key LIMIT 6""", (SCOPE,))
        sources = _rows(conn, f"SELECT count(*) AS n, max(last_run_at) AS last FROM {S.sources(cc)} s "
                              "WHERE code<>'LOCAL_SEED'")[0]
    sev = {k: sum(1 for r in regs if r["impact"] == k) for k in ("High", "Medium", "Low")}
    changed = [r for r in regs if r["last_event_at"] and r["last_event_at"].date() >= today - timedelta(days=30)]
    by_cat = [{"name": CAT_LABEL[c], "code": c, "n": sum(1 for r in regs if c in r["categories"])} for c in CATEGORIES]
    dom: dict[str, int] = {}
    for r in regs:
        for d in r["domains"] or []:
            dom[d] = dom.get(d, 0) + 1
    top_dom = [{"name": DOMAIN_LABEL.get(k, k), "code": k, "n": v} for k, v in sorted(dom.items(), key=lambda kv: -kv[1])[:5]]
    latest = sorted([r for r in regs if r["doc_date"]], key=lambda r: (r["doc_date"], r["canonical_id"]), reverse=True)[:6]
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
            "doc_date", "impact", "impact_basis", "status", "ai_pending", "next_obligation", "family_key", "doc_status",
            "subtitle")
    return {k: r.get(k) for k in keys}


# ====================================================================== regulation library
@router.get("/regulations")
def regulation_list(q: str | None = None, category: str | None = None, impact: str | None = None,
                    status: str | None = None, history: bool = False, reference: bool = False,
                    cc: CountryParam = None) -> dict:
    today = date.today()
    cc = resolve_country(cc)
    with connect() as conn:
        regs = regulations(conn, category, history=history, reference=reference, cc=cc)
        n_reference = conn.execute(f"""SELECT count(*) AS n FROM {S.docs(cc)} d WHERE vehicle_categories && %s
                                      AND doc_class = ANY(%s) AND status NOT IN ('superseded','withdrawn')""",
                                   (SCOPE, list(REFERENCE_CLASSES))).fetchone()["n"]
        superseded = conn.execute(f"""SELECT count(*) AS n FROM {S.docs(cc)} d WHERE doc_class<>'OFF_TOPIC'
                                     AND vehicle_categories && %s AND status IN ('superseded','withdrawn')""",
                                  (SCOPE,)).fetchone()["n"]
    by_issuer: dict[str, int] = {}
    for r in regs:
        by_issuer[r["issuer"] or "Unknown"] = by_issuer.get(r["issuer"] or "Unknown", 0) + 1
    comp = [{"name": k, "n": v} for k, v in sorted(by_issuer.items(), key=lambda kv: (-kv[1], kv[0]))[:6]]
    rows = regs
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in " ".join(str(r.get(k) or "") for k in ("canonical_id", "name", "subtitle", "authority", "domain")).lower()]
    if impact in ("High", "Medium", "Low"):
        rows = [r for r in rows if r["impact"] == impact]
    if status in STATUSES:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["effective"] or date(1900, 1, 1), r["canonical_id"]), reverse=True)
    return {
        "kpis": {"records": len(regs), "new_quarter": sum(1 for r in regs if r["doc_date"] and r["doc_date"] >= today - timedelta(days=90)),
                 "drafts": sum(1 for r in regs if r["doc_class"] in DRAFTS or r["doc_status"] == "draft"),
                 "high": sum(1 for r in regs if r["impact"] == "High"), "superseded": superseded, "reference": n_reference},
        "count": len(rows), "rows": [_reg_out(r) for r in rows], "composition": comp,
    }


@router.get("/regulations/{canonical_id:path}/detail")
def regulation_detail(canonical_id: str, cc: CountryParam = None) -> dict:
    cc = resolve_country(cc)
    with connect() as conn:
        regs = regulations(conn, None, "AND d.canonical_id=%s", (canonical_id,), history=True, reference=True, cc=cc)
        if not regs:
            raise HTTPException(404, "not an in-scope regulation")
        r = regs[0]
        files = _rows(conn, """SELECT fo.checksum_sha256 AS sha256, fo.file_ext AS ext FROM document_parts p
                               JOIN documents fo ON fo.id=p.document_id
                               WHERE p.regulation_id=%s ORDER BY p.is_best_copy DESC LIMIT 1""", (r["id"],))
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
        d = conn.execute(f"SELECT id FROM regulations g WHERE external_code=%s AND {country.region_sql('g')}",
                         (canonical_id,)).fetchone()
        if not d:
            raise HTTPException(404, "unknown document")
        status = (body.get("status") or "Tracked").lower().replace(" ", "_")
        impact = body.get("impact")
        conn.execute("""UPDATE regulations SET workflow_status=%s, owner_team_id=%s, review_note=%s, reviewed_at=now(),
                               impact_level = CASE WHEN %s::text IS NOT NULL THEN lower(%s) ELSE impact_level END,
                               impact_basis = CASE WHEN %s::text IS NOT NULL THEN 'team' ELSE 'rules' END
                        WHERE id=%s""",
                     (status, team_id(conn, body.get("owner")), body.get("note"), impact, impact, impact, d["id"]))
        if not impact:  # back to the rule-based impact at once
            conn.execute("SELECT refresh_regulation_fields(%s)", (country.code(),))
        conn.commit()
    return {"ok": True}


# ====================================================================== change monitor
@router.get("/changes")
def change_monitor(days: int = 365, cc: CountryParam = None) -> dict:
    cc = resolve_country(cc)
    with connect() as conn:
        sla = int(_setting(conn, "review_sla_days", "2"))
        events = _rows(conn, f"""SELECT e.id, e.event_type, e.detected_at, e.summary, e.review_status, e.details,
                   d.external_code AS canonical_id, d.id AS doc_id, d.published_date AS doc_date, d.local_class AS doc_class
                   FROM {S.changes(cc)} e LEFT JOIN regulations d ON d.id=e.document_id
                   WHERE e.detected_at > now() - make_interval(days => %s)
                   ORDER BY e.detected_at DESC, e.id DESC""", (days,))
        regs = {r["id"]: r for r in regulations(conn, history=True, cc=cc)}
    for e in events:
        r = regs.get(e["doc_id"])
        e["impact"] = r["impact"] if r else "Low"
        e["in_scope"] = r is not None
        e["name"] = r["name"] if r else e["canonical_id"]
        e["ai_summary_pending"] = (e["details"] or {}).get("summary_by") == "template"
    events = [e for e in events if e["in_scope"]]
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
        from regtrack.pipeline.alerts import close_settled

        n = conn.execute("""UPDATE regulation_changes SET review_status='reviewed', reviewed_at=now()
                            WHERE id = ANY(%s) AND review_status <> 'reviewed'""", (ids,)).rowcount
        close_settled(conn)  # alerts on these changes are settled
        conn.commit()
    return {"reviewed": n}


# ====================================================================== compliance matrix
# the team's tracking of a rule lives on compliance_requirements; a rule nobody has touched yet has no owner, status
# open, no due date, evidence or note, and shows updated_at NULL ("not tracked")
TRACKED = ("(cr.owner_team_id IS NOT NULL OR cr.status <> 'open' OR cr.due_date IS NOT NULL OR cr.note IS NOT NULL "
           "OR cr.evidence_links <> '[]'::jsonb)")
COMP_STATUS = {"open": "Open", "in_progress": "In Progress", "compliant": "Compliant", "not_applicable": "Not Applicable"}
COMP_SQL = """
SELECT m.mandate_key, m.legal_basis, m.subject, m.standard_refs, m.vehicle_categories, m.implementation_date,
       m.model_scope, d.canonical_id, d.domains, t.name AS owner, cr.evidence_links->0->>'label' AS evidence,
       initcap(replace(cr.status, '_', ' ')) AS status,
       coalesce(cr.due_date, m.implementation_date) AS due_date, cr.note,
       CASE WHEN {tracked} THEN cr.updated_at END AS updated_at
FROM {mandates} m JOIN {docs} d ON d.id=m.source_doc_id
JOIN compliance_requirements cr ON cr.requirement_code=m.mandate_key
     AND cr.region_id=(SELECT id FROM regions WHERE code=m.country)
LEFT JOIN teams t ON t.id=cr.owner_team_id
WHERE m.valid_to IS NULL AND NOT m.is_draft AND m.vehicle_categories && %s
ORDER BY coalesce(cr.due_date, m.implementation_date) DESC NULLS LAST, m.mandate_key
"""


@router.get("/compliance")
def compliance(category: str | None = None, cc: CountryParam = None) -> dict:
    cats = [category, "ALL"] if category in CATEGORIES else SCOPE
    cc = resolve_country(cc)
    with connect() as conn:
        load_vocab(conn)
        rows = _rows(conn, COMP_SQL.format(tracked=TRACKED, mandates=S.mandates(cc), docs=S.docs(cc)), (cats,))
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
    cc = country.code()
    status = body.get("status", "Open").lower().replace(" ", "_")
    evidence = [{"type": "note", "label": body["evidence"]}] if body.get("evidence") else []
    with connect() as conn:
        cur = conn.execute(
            """UPDATE compliance_requirements SET owner_team_id=%s, evidence_links=%s, status=%s, due_date=%s, note=%s,
                      updated_at=now()
               WHERE region_id=(SELECT id FROM regions WHERE code=%s) AND requirement_code=%s""",
            (team_id(conn, body.get("owner")), Jsonb(evidence), status, due, body.get("note"), cc, mandate_key))
        if not cur.rowcount:
            raise HTTPException(404, "unknown requirement")
        conn.commit()
    return {"ok": True}


# ====================================================================== impact view
@router.get("/impact")
def impact(cc: CountryParam = None) -> dict:
    cc = resolve_country(cc)
    region = country.region_sql("x", cc)
    with connect() as conn:
        regs = regulations(conn, cc=cc)
        stds = _rows(conn, f"""SELECT s AS name, count(*) AS n FROM {S.mandates(cc)} m, unnest(m.standard_refs) s
                              WHERE m.valid_to IS NULL AND NOT m.is_draft AND m.vehicle_categories && %s
                              GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 5""", (SCOPE,))
        owners = conn.execute(f"SELECT count(DISTINCT owner_team_id) AS n FROM compliance_requirements x "
                              f"WHERE owner_team_id IS NOT NULL AND {region}").fetchone()["n"]
        wf = conn.execute(f"""SELECT
              (SELECT count(*) FROM regulation_changes x WHERE detected_at > now() - interval '30 days' AND {region}) AS detected,
              (SELECT count(*) FROM documents x WHERE stage NOT IN ('downloaded','text') AND {region}) AS classified,
              (SELECT count(*) FROM documents x WHERE {region}) AS files,
              (SELECT count(*) FROM regulations x WHERE (workflow_status IS NOT NULL OR impact_basis = 'team'
                 OR owner_team_id IS NOT NULL OR review_note IS NOT NULL) AND {region}) AS assessed,
              (SELECT count(*) FROM compliance_requirements x WHERE owner_team_id IS NOT NULL AND {region}) AS mapped,
              (SELECT count(*) FROM {S.mandates(cc)} m WHERE valid_to IS NULL AND NOT is_draft
                 AND vehicle_categories && %s) AS obligations,
              (SELECT count(*) FROM regulation_changes x WHERE review_status='reviewed' AND {region}) AS closed,
              (SELECT count(*) FROM regulation_changes x WHERE {region}) AS changes""", (SCOPE,)).fetchone()
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
    workflow = [
        {"step": "Detect", "text": "New or changed documents found by source monitoring (last 30 days)", "n": wf["detected"], "of": None},
        {"step": "Classify", "text": "Files with identity, category and topic read from content", "n": wf["classified"], "of": wf["files"]},
        {"step": "Assess", "text": "In-scope regulations with a review decision by the team", "n": wf["assessed"], "of": len(regs)},
        {"step": "Map", "text": "Obligations in force with an owner in the Compliance Matrix", "n": wf["mapped"], "of": wf["obligations"]},
        {"step": "Close", "text": "Detected changes marked as reviewed", "n": wf["closed"], "of": wf["changes"]},
    ]
    return {"categories": CATEGORIES, "category_labels": [CAT_LABEL.get(c, c) for c in CATEGORIES], "cells": cells,
            "top_standards": stds, "workflow": workflow,
            "kpis": {"critical": critical,
                     "top1": {"name": DOMAIN_LABEL.get(top[0], top[0]) if top else "—", "n": sum(1 for r in regs if top and top[0] in (r["domains"] or []))},
                     "top2": {"name": DOMAIN_LABEL.get(top[1], top[1]) if len(top) > 1 else "—", "n": sum(1 for r in regs if len(top) > 1 and top[1] in (r["domains"] or []))},
                     "owners": owners}}


@router.get("/impact/cell")
def impact_cell(category: str, domain: str, cc: CountryParam = None) -> dict:
    cc = resolve_country(cc)
    with connect() as conn:
        regs = [r for r in regulations(conn, category, cc=cc) if domain in (r["domains"] or [])]
    regs.sort(key=lambda r: ({"High": 0, "Medium": 1, "Low": 2}[r["impact"]], -(r["effective"] or date(1900, 1, 1)).toordinal()))
    return {"category": category, "domain": DOMAIN_LABEL.get(domain, domain), "count": len(regs),
            "rows": [_reg_out(r) for r in regs[:6]]}


# ====================================================================== ask regulatory AI
@router.get("/ask/context")
def ask_context(cc: CountryParam = None) -> dict:
    """Suggested questions built from the current data, and the sources the assistant searches."""
    cc = resolve_country(cc)
    with connect() as conn:
        regs = regulations(conn, cc=cc)
        sources = _rows(conn, f"""SELECT s.code, s.name, s.last_run_at, s.last_status,
                   (SELECT count(DISTINCT d.id) FROM raw_ingestion_records f JOIN document_parts p ON p.document_id=f.document_id
                      JOIN {S.docs(cc)} d ON d.id=p.regulation_id WHERE f.source_id=s.id AND d.vehicle_categories && %s)
                     AS documents
                   FROM {S.sources(cc)} s ORDER BY s.id""", (SCOPE,))
        chunks = conn.execute(f"SELECT count(*) AS n FROM document_chunks c WHERE in_scope AND NOT is_boilerplate "
                              f"AND {country.region_sql('c', cc)}").fetchone()["n"]
    suggest: list[str] = []
    for c in CATEGORIES:  # most-regulated topic per category (type approval is everywhere, so skipped)
        dom: dict[str, int] = {}
        for r in regs:
            if c in r["categories"]:
                for d in r["domains"] or []:
                    if d != "type_approval":
                        dom[d] = dom.get(d, 0) + 1
        if dom:
            top = max(dom, key=dom.get)
            suggest.append(f"Which rules on {DOMAIN_LABEL.get(top, top)} apply to {c}?")
    latest = sorted([r for r in regs if r["impact"] == "High" and r["doc_date"]], key=lambda r: r["doc_date"], reverse=True)[:2]
    suggest += [f"Summarize {r['canonical_id']}: {r['name'][:60]}" for r in latest]
    return {"suggestions": suggest[:6], "sources": [x for x in sources if x["documents"]], "chunks": chunks}


@router.post("/ask")
def ask(body: dict = Body(...)) -> dict:
    """Answer from the best-matching clauses (Qwen when connected); the exchange is kept in the assistant history."""
    from regtrack.assistant import record_exchange

    q = (body.get("question") or "").strip()
    if not q:
        raise HTTPException(400, "empty question")
    with connect() as conn:
        out, hits = _answer(conn, q)
        out["conversation_id"] = record_exchange(conn, q, out["answer"], hits, body.get("conversation_id"))
        conn.commit()
    return out


@router.get("/ask/conversations/{conversation_id}")
def ask_conversation(conversation_id: int) -> dict:
    from regtrack.assistant import conversation

    with connect() as conn:
        msgs = conversation(conn, conversation_id)
    if not msgs:
        raise HTTPException(404, "unknown conversation")
    return {"conversation_id": conversation_id, "messages": msgs}


def _answer(conn, q: str) -> tuple[dict, list[dict]]:
    from pydantic import BaseModel

    from regtrack import llm
    from regtrack.pipeline.search import search as chunk_search

    cat = next((c for c in CATEGORIES if c.lower() in q.lower().split() or c in q), None)
    hits = chunk_search(conn, q, cat, None, None, None, 8, cc=country.code())["results"]
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
            return {"mode": "qwen", "answer": a.answer, "sources": sources}, hits
        except Exception as e:  # noqa: BLE001
            note = f"AI answer failed ({type(e).__name__}); showing the matching clauses instead."
    else:
        note = "AI answers start once LM Studio is connected; until then these are the best-matching clauses."
    if not hits:
        return {"mode": "search", "answer": "No matching clauses found in the indexed regulations.", "sources": [],
                "note": note}, hits
    lines = [f"Found {len(hits)} matching clause(s) in {len({h['canonical_id'] for h in hits})} document(s):", ""]
    for h in hits[:5]:
        lines.append(f"• {h['canonical_id']}" + (f" clause {h['clause_no']}" if h["clause_no"] else "")
                     + f": {' '.join((h['content'] or '').split())[:200]}…")
    return {"mode": "search", "answer": "\n".join(lines), "sources": sources, "note": note}, hits


# ====================================================================== reports
REPORTS = {
    "executive": "Executive Regulatory Summary",
    "compliance_gap": "Compliance Gap Report",
    "change_impact": "Change Impact Report",
}


# generated reports as the report log the page shows (kind = template name, owner = team name)
REPORT_LOG_SQL = """SELECT r.id, rt.name AS kind, r.parameters->>'scope' AS scope, t.name AS owner,
                           (r.parameters->>'rows')::int AS rows, r.generated_at, rg.code AS country
                    FROM reports r JOIN report_templates rt ON rt.id=r.template_id JOIN teams t ON t.id=r.owner_team_id
                    LEFT JOIN regions rg ON rg.id=r.scope_region_id"""


@router.get("/reports")
def reports(cc: CountryParam = None) -> dict:
    cc = resolve_country(cc)
    with connect() as conn:
        recent = _rows(conn, REPORT_LOG_SQL + " ORDER BY r.generated_at DESC LIMIT 20")
        month = conn.execute("SELECT count(*) AS n FROM reports WHERE generated_at > date_trunc('month', now())").fetchone()["n"]
        awaiting = conn.execute(f"""SELECT count(*) AS n FROM {S.changes(cc)} e JOIN {S.docs(cc)} d ON d.id=e.document_id
                                   WHERE e.review_status<>'confirmed' AND d.doc_class <> 'OFF_TOPIC'
                                     AND d.vehicle_categories && %s""", (SCOPE,)).fetchone()["n"]
        last = conn.execute("SELECT max(generated_at) AS t FROM reports").fetchone()["t"]
    return {"kpis": {"generated_month": month, "last_generated": last, "awaiting_review": awaiting, "templates": len(REPORTS)},
            "scope": ", ".join(CATEGORIES),
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
def generate_report(kind: str, fmt: str = "html", owner: str = "Regulatory Affairs", cc: CountryParam = None) -> Response:
    if kind not in REPORTS:
        raise HTTPException(404, "unknown report")
    cc = resolve_country(cc)
    title = REPORTS[kind]
    stamp = datetime.now().strftime("%d %b %Y %H:%M")
    if kind == "executive":
        s = summary(cc)
        ch = change_monitor(30, cc)
        sections = [
            ("Key figures", ["Measure", "Value"], [[f"Regulations tracked (India, {'/'.join(CATEGORIES)})", s["kpis"]["tracked"]],
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
        c = compliance(None, cc)
        gaps = [r for r in c["rows"] if r["status"] in ("Open", "In Progress")]
        sections = [("Readiness", ["Measure", "Value"], [["Requirements", c["kpis"]["requirements"]], ["Compliant %", c["kpis"]["compliant_pct"]],
                                                         ["In progress %", c["kpis"]["in_progress_pct"]], ["Open %", c["kpis"]["open_pct"]],
                                                         ["Due within 90 days", c["kpis"]["due_90"]]]),
                    ("Open requirements", ["Requirement", "Subject", "Standards", "Categories", "Owner", "Evidence", "Status", "Due"],
                     [[r["legal_basis"], r["subject"], ", ".join(r["standard_refs"] or []), ", ".join(r["categories"]), r["owner"],
                       r["evidence"], r["status"], r["due_date"]] for r in gaps])]
        head, rows = sections[1][1], sections[1][2]
    else:
        ch = change_monitor(365, cc)
        sections = [("Changes by type", ["Type", "Count"], [[t, n] for t, n in ch["by_type"]]),
                    ("Change events", ["Detected", "Type", "Document", "Impact", "Reviewed", "Summary"],
                     [[e["detected_at"].strftime("%d %b %Y"), e["event_type"], e["canonical_id"], e["impact"],
                       "yes" if e["review_status"] == "confirmed" else "no", e["summary"]] for e in ch["events"]])]
        head, rows = sections[1][1], sections[1][2]
    with connect() as conn:
        conn.execute("""INSERT INTO reports (template_id, scope_region_id, owner_team_id, parameters)
                        VALUES ((SELECT id FROM report_templates WHERE name=%s), (SELECT id FROM regions WHERE code=%s),
                                %s, %s)""",
                     (title, cc, team_id(conn, owner) or team_id(conn, _setting(conn, "default_owner", "Regulatory Affairs Team")),
                      Jsonb({"scope": "India · " + "/".join(CATEGORIES), "rows": len(rows)})))
        conn.commit()
    fname = f"{title.replace(' ', '_')}_{date.today().isoformat()}"
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(head)
        w.writerows(rows)
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{fname}.csv"'})
    body = _html(title, f"RegTrack India · India, vehicle categories {', '.join(CATEGORIES)} · generated {stamp}. "
                        f"Impact is rule-based until the AI pass runs.", sections)
    return Response(body, media_type="text/html", headers={"Content-Disposition": f'attachment; filename="{fname}.html"'})


# ====================================================================== alerts
# Rules live in alert_rules; the pipeline stores each match once in alert_events (regtrack/pipeline/alerts.py) and
# closes it when the change is reviewed or the date has passed. The page shows the open ones.
RULE_SQL = """SELECT r.id, r.name,
                     coalesce(vc.code, 'All categories') AS scope, r.condition->>'type' AS condition,
                     coalesce(r.condition->>'param', lower(dm.code)) AS param, r.is_enabled AS enabled, r.created_at,
                     (SELECT count(*) FROM alert_events a WHERE a.rule_id=r.id AND NOT a.is_resolved) AS matches
              FROM alert_rules r LEFT JOIN vehicle_categories vc ON vc.id=r.scope_vehicle_category_id
              LEFT JOIN domains dm ON dm.id=r.scope_domain_id
              WHERE r.scope_region_id IS NULL OR r.scope_region_id=(SELECT id FROM regions WHERE code=%s)
              ORDER BY r.id"""


def _notifications(conn, cc: str) -> list[dict]:
    rows = _rows(conn, """SELECT r.name, r.condition, e.detected_at, e.summary, g.external_code AS canonical_id,
                                 v.implementation_date, v.is_draft, v.subject AS v_subject, c.requirement_code
                          FROM alert_events a JOIN alert_rules r ON r.id=a.rule_id
                          LEFT JOIN regulations g ON g.id=a.regulation_id
                          LEFT JOIN regulation_changes e ON e.id=a.regulation_change_id
                          LEFT JOIN requirement_versions v ON v.id=a.requirement_version_id
                          LEFT JOIN compliance_requirements c ON c.id=v.requirement_id
                          WHERE NOT a.is_resolved AND r.is_enabled
                            AND (r.scope_region_id IS NULL OR r.scope_region_id=(SELECT id FROM regions WHERE code=%s))""",
                  (cc,))
    out = []
    for n in rows:
        if n["implementation_date"]:
            days = int((n["condition"] or {}).get("param") or 60)
            out.append({"when": n["implementation_date"].isoformat(),
                        "title": f"{'Proposed' if n['is_draft'] else 'Implementation'} date within {days} days",
                        "text": f"{n['requirement_code']}: {n['v_subject'] or ''}"[:200], "canonical_id": n["canonical_id"]})
        else:
            out.append({"when": n["detected_at"].strftime("%Y-%m-%d %H:%M") if n["detected_at"] else "",
                        "title": n["name"], "text": (n["summary"] or n["canonical_id"] or "")[:200],
                        "canonical_id": n["canonical_id"]})
    return out


@router.get("/alerts")
def alerts(cc: CountryParam = None) -> dict:
    cc = resolve_country(cc)
    with connect() as conn:
        load_vocab(conn)
        rules = _rows(conn, RULE_SQL, (cc,))
        for r in rules:
            r["matches"] = r["matches"] if r["enabled"] else 0
        notes = _notifications(conn, cc)
        due60 = conn.execute(f"""SELECT count(*) AS n FROM {S.mandates(cc)} m WHERE valid_to IS NULL AND vehicle_categories && %s
                                AND implementation_date BETWEEN current_date AND current_date + 60""", (SCOPE,)).fetchone()["n"]
        resolved = conn.execute(f"""SELECT count(*) AS n FROM regulation_changes x WHERE review_status='reviewed'
                                   AND reviewed_at > date_trunc('month', now()) AND {country.region_sql('x', cc)}""").fetchone()["n"]
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


def _refresh_alerts(conn) -> None:
    """A new or re-enabled rule shows its matches at once, not only after the next pipeline run."""
    from regtrack.pipeline.alerts import run

    run(conn)


@router.post("/alerts")
def add_alert(body: dict = Body(...)) -> dict:
    cond = body.get("condition") or "new_document"
    param = body.get("param")
    cc = country.code()
    with connect() as conn:
        r = conn.execute(
            """INSERT INTO alert_rules (name, scope_region_id, scope_domain_id, scope_vehicle_category_id, condition,
                                        notify_team_id)
               VALUES (%s, (SELECT id FROM regions WHERE code=%s),
                       (SELECT id FROM domains WHERE %s = 'domain' AND code = upper(%s)),
                       (SELECT id FROM vehicle_categories WHERE region_id=(SELECT id FROM regions WHERE code=%s) AND code=%s),
                       %s, (SELECT id FROM teams WHERE code='REG_AFFAIRS'))
               RETURNING id""",
            (body.get("name") or "New regulatory watch", cc, cond, param, cc, body.get("scope"),
             Jsonb({"type": cond, **({"param": str(param)} if param and cond != "domain" else {})}))).fetchone()
        _refresh_alerts(conn)
        conn.commit()
    return {"id": r["id"]}


@router.patch("/alerts/{rule_id}")
def toggle_alert(rule_id: int, body: dict = Body(...)) -> dict:
    with connect() as conn:
        conn.execute("UPDATE alert_rules SET is_enabled=%s WHERE id=%s", (bool(body.get("enabled")), rule_id))
        _refresh_alerts(conn)
        conn.commit()
    return {"ok": True}


@router.delete("/alerts/{rule_id}")
def delete_alert(rule_id: int) -> dict:
    with connect() as conn:
        conn.execute("DELETE FROM alert_rules WHERE id=%s", (rule_id,))  # its alert events go with it
        conn.commit()
    return {"ok": True}


# ====================================================================== admin & sources
_sync_lock = threading.Lock()
_sync_state: dict = {"running": None, "step": None, "done": 0, "total": 0, "last": None}


@router.get("/admin")
def admin(cc: CountryParam = None) -> dict:
    cc = resolve_country(cc)
    with connect() as conn:
        sources = _rows(conn, f"""SELECT s.code, s.name, s.base_url, s.schedule_hours, s.last_run_at, s.last_status,
                   (SELECT count(*) FROM raw_ingestion_records f WHERE f.source_id=s.id) AS sightings
                   FROM {S.sources(cc)} s ORDER BY s.id""")
        runs = _rows(conn, f"""SELECT r.id, s.code, r.started_at, r.finished_at, r.status, r.stats FROM {S.runs(cc)} r
                              JOIN sources s ON s.id=r.source_id ORDER BY r.id DESC LIMIT 15""")
        tot = conn.execute(f"""SELECT count(*) AS n, count(*) FILTER (WHERE status IN ('ok','partial')) AS good,
                              count(*) FILTER (WHERE status='partial') AS partial
                              FROM {S.runs(cc)} r WHERE started_at > now() - interval '30 days'""").fetchone()
        warnings = conn.execute(f"""SELECT count(*) AS n FROM quality_flags q WHERE resolved_at IS NULL
                                   AND rule IN ('low_ocr_confidence','schema_violation','identity_not_found')
                                   AND ((q.entity='regulation' AND q.entity_id IN (SELECT id FROM regulations x
                                                                                   WHERE {country.region_sql('x', cc)}))
                                     OR (q.entity='document' AND q.entity_id IN (SELECT id FROM documents x
                                                                                 WHERE {country.region_sql('x', cc)})))""").fetchone()["n"]
        settings = S.settings(conn)
    from regtrack.scheduler import crawlers

    mods = crawlers(cc)

    now = datetime.now().astimezone()
    live = [s for s in sources if s["code"] != "LOCAL_SEED"]
    last = max((s["last_run_at"] for s in live if s["last_run_at"]), default=None)
    for s in sources:
        s["crawler"] = s["code"] in mods
        s["next_due"] = (s["last_run_at"] + timedelta(hours=min(s["schedule_hours"], 6))
                         if s["crawler"] and s["last_run_at"] and s["schedule_hours"] else None)
        s["overdue"] = bool(s["crawler"] and (s["next_due"] is None or s["next_due"] < now - timedelta(minutes=30)))
    for r in runs:
        st = r["stats"] or {}
        r["documents"] = st.get("seen", st.get("files", 0))
        r["changes"] = st.get("new_files", st.get("file_object_new", 0))
    return {"kpis": {"connected": sum(1 for s in sources if s["crawler"] and s["last_status"] in ("ok", "partial")),
                     "sources": sum(1 for s in sources if s["crawler"]),
                     "success_pct": round(100 * tot["good"] / tot["n"], 1) if tot["n"] else None,
                     "warnings": warnings, "partial_runs": tot["partial"],
                     "last_sync_min": int((now - last).total_seconds() // 60) if last else None},
            "sources": sources, "runs": runs, "settings": {k: v for k, v in settings.items() if k not in ("scheduler_heartbeat", "v4b_switch_verified")},
            "sync": _sync_state, "syncable": ["ALL"] + [s["code"] for s in sources if s["crawler"]],
            "scheduler": scheduler_status(settings), "impact_rule": IMPACT_RULE}


def scheduler_status(settings: dict) -> dict:
    """Alive if the scheduler loop wrote its heartbeat within the last two intervals."""
    from regtrack.scheduler import HEARTBEAT_MIN

    hb = settings.get("scheduler_heartbeat")
    beat = datetime.fromisoformat(hb) if hb else None
    alive = bool(beat and datetime.now().astimezone() - beat < timedelta(minutes=2 * HEARTBEAT_MIN + 1))
    return {"alive": alive, "heartbeat": beat, "auto_sync": settings.get("auto_sync", "true") != "false"}


@router.put("/settings")
def put_settings(body: dict = Body(...)) -> dict:
    allowed = {"default_owner", "review_sla_days", "auto_sync"}
    with connect() as conn:
        for k, v in body.items():
            if k in allowed:
                S.put_setting(conn, k, str(v))
        conn.commit()
    return {"ok": True}


@router.post("/admin/sync")
def run_sync(body: dict = Body(default={})) -> dict:
    """Start a crawl + pipeline run in the background (one at a time). source='ALL' crawls every source in turn,
    then processes once; 'step' tells the page which source is being crawled right now."""
    from regtrack.scheduler import crawlers, run_all, run_source

    mods = crawlers()
    code = body.get("source") or "ALL"
    if code != "ALL" and code not in mods:
        raise HTTPException(400, "unknown source")
    if not _sync_lock.acquire(blocking=False):
        return {"started": False, "running": _sync_state["running"]}

    def step(name: str) -> None:
        _sync_state["step"] = name
        if name in mods:
            _sync_state["done"] = list(mods).index(name)

    def work() -> None:
        try:
            _sync_state.update(running=code, step=None, done=0, total=len(mods) if code == "ALL" else 1)
            if code == "ALL":
                res = run_all(step)
            else:
                step(code)
                res = run_source(code)
            errors = res.get("errors") or {}
            _sync_state["last"] = {"source": code, "finished": datetime.now().isoformat(),
                                   "errors": errors, "ok": [c for c in (res.get("crawl") or {})] if code == "ALL" else [code]}
        except Exception as e:  # noqa: BLE001
            _sync_state["last"] = {"source": code, "error": f"{type(e).__name__}: {e}"[:300]}
        finally:
            _sync_state.update(running=None, step=None)
            _sync_lock.release()

    threading.Thread(target=work, daemon=True).start()
    return {"started": True, "source": code}


@router.get("/meta")
def portal_meta(cc: CountryParam = None) -> dict:
    from regtrack.scheduler import crawlers

    cc = resolve_country(cc)
    with connect() as conn:
        load_vocab(conn)
        s = conn.execute(f"""SELECT count(*) FILTER (WHERE last_status IN ('ok','partial')) AS n, count(*) AS total,
                            max(last_run_at) AS last FROM {S.sources(cc)} s WHERE code = ANY(%s)""",
                         (list(crawlers(cc)),)).fetchone()
        settings = S.settings(conn)
        teams = _rows(conn, "SELECT id, name FROM teams ORDER BY name")
    return {"country": cc, "sources": s["n"], "sources_total": s["total"], "last_sync": s["last"], "teams": teams,
            "scheduler": scheduler_status(settings),
            "categories": [{"code": c, "label": CAT_LABEL.get(c, c)} for c in CATEGORIES],
            "statuses": STATUSES, "domains": [{"code": k, "label": v} for k, v in DOMAIN_LABEL.items()]}
