"""Alert events (v4B alert_events): each enabled alert rule is checked at the end of every pipeline run, and every match
is stored once (unique per rule and trigger), then closed when it no longer needs attention.

Conditions (alert_rules.condition->>'type'), the same as the portal's Alerts page:
  high_impact, new_document, draft_published, draft_finalised, date_changed, domain
        a change detected in the last 30 days (regulation_changes) on a matching regulation;
        closed when the change has been reviewed
  due_within (param = days, default 60)
        an open rule version whose implementation date falls within the coming days;
        closed when the version is replaced or the date has passed
Scope: the rule's vehicle category (or ALL), else every in-scope category; only regulations the portal lists (not
off-topic, superseded, withdrawn or reference material).
"""

from __future__ import annotations

import psycopg

from regtrack import country
from regtrack.models.enums import in_scope_categories

WINDOW_DAYS = 30
CHANGE_TYPE = {"new_document": "new_document", "draft_published": "draft_published", "draft_finalised": "draft_finalised",
               "date_changed": "implementation_date_changed"}
# not regulations themselves (kept out of the portal's register by default)
REFERENCE_CLASSES = ("REPORT", "OTHER", "AIS_FORM_TABLE", "FORM_TEMPLATE", "BIS_CATALOGUE", "APPROVED_LIST")


def _scope_ids(conn: psycopg.Connection, rule: dict, region_id: int, cc: str) -> list[int]:
    scope = in_scope_categories(cc)
    if rule["scope_vehicle_category_id"]:
        codes = [r["code"] for r in conn.execute("SELECT code FROM vehicle_categories WHERE id=%s",
                                                 (rule["scope_vehicle_category_id"],))] + ["ALL"]
        codes = [c for c in codes if c in scope]
    else:
        codes = sorted(scope)
    return [r["id"] for r in conn.execute("SELECT id FROM vehicle_categories WHERE region_id=%s AND code = ANY(%s)",
                                          (region_id, codes))]


def _insert(conn, rule_id: int, regulation_id: int | None, message: str, change_id: int | None = None,
            version_id: int | None = None, at=None) -> int:
    cur = conn.execute(
        """INSERT INTO alert_events (rule_id, regulation_id, regulation_change_id, requirement_version_id, message,
                                     triggered_at)
           VALUES (%s,%s,%s,%s,%s,coalesce(%s, now()))
           ON CONFLICT (rule_id, regulation_change_id, requirement_version_id) DO NOTHING""",
        (rule_id, regulation_id, change_id, version_id, message[:500], at))
    return cur.rowcount


def evaluate_rules(conn: psycopg.Connection) -> dict:
    """Store new matches of every enabled rule of the current region; returns counts per rule id."""
    cc = country.code()
    region_id = conn.execute("SELECT id FROM regions WHERE code=%s", (cc,)).fetchone()["id"]
    rules = conn.execute("SELECT * FROM alert_rules WHERE is_enabled AND (scope_region_id=%s OR scope_region_id IS NULL) "
                         "ORDER BY id", (region_id,)).fetchall()
    listed = ("g.local_class <> 'OFF_TOPIC' AND g.legal_status NOT IN ('superseded','withdrawn') "
              "AND g.local_class <> ALL(%(ref)s)")
    out = {}
    for rule in rules:
        cond = (rule["condition"] or {}).get("type")
        scope = _scope_ids(conn, rule, region_id, cc)
        n = 0
        if cond == "due_within":
            days = int((rule["condition"] or {}).get("param") or 60)
            for v in conn.execute(
                    """SELECT v.id, v.source_regulation_id, v.implementation_date, v.is_draft, v.subject,
                              c.requirement_code FROM requirement_versions v
                       JOIN compliance_requirements c ON c.id=v.requirement_id
                       WHERE c.region_id=%(rid)s AND v.valid_to IS NULL AND v.vehicle_category_ids && %(scope)s::int[]
                         AND v.implementation_date BETWEEN current_date AND current_date + %(days)s""",
                    {"rid": region_id, "scope": scope, "days": days}).fetchall():
                msg = (f"{'Proposed' if v['is_draft'] else 'Implementation'} date {v['implementation_date']} within "
                       f"{days} days: {v['requirement_code']}: {v['subject'] or ''}")
                n += _insert(conn, rule["id"], v["source_regulation_id"], msg, version_id=v["id"])
        elif cond in CHANGE_TYPE or cond in ("high_impact", "domain"):
            match = {"high_impact": "g.impact_level = 'high'",
                     "domain": "EXISTS (SELECT 1 FROM regulation_domains l WHERE l.regulation_id=g.id "
                               "AND l.domain_id=%(domain)s)"}.get(cond, "e.change_type = %(ctype)s")
            for e in conn.execute(
                    f"""SELECT e.id, e.regulation_id, e.detected_at, coalesce(e.summary, g.external_code) AS text
                        FROM regulation_changes e JOIN regulations g ON g.id=e.regulation_id
                        WHERE e.region_id=%(rid)s AND e.detected_at > now() - make_interval(days => %(win)s)
                          AND {listed} AND {match}
                          AND EXISTS (SELECT 1 FROM regulation_vehicle_categories l WHERE l.regulation_id=g.id
                                      AND l.vehicle_category_id = ANY(%(scope)s::int[]))""",
                    {"rid": region_id, "win": WINDOW_DAYS, "ref": list(REFERENCE_CLASSES), "scope": scope,
                     "ctype": CHANGE_TYPE.get(cond), "domain": rule["scope_domain_id"]}).fetchall():
                n += _insert(conn, rule["id"], e["regulation_id"], f"{rule['name']}: {e['text']}", change_id=e["id"],
                             at=e["detected_at"])
        out[rule["id"]] = n
    return out


def close_settled(conn: psycopg.Connection) -> int:
    """Close alerts whose change has been reviewed, or whose rule version was replaced or whose date has passed."""
    a = conn.execute("""UPDATE alert_events a SET is_resolved=true, resolved_at=now() FROM regulation_changes e
                        WHERE NOT a.is_resolved AND e.id=a.regulation_change_id AND e.review_status='reviewed'""").rowcount
    b = conn.execute("""UPDATE alert_events a SET is_resolved=true, resolved_at=now() FROM requirement_versions v
                        WHERE NOT a.is_resolved AND v.id=a.requirement_version_id
                          AND (v.valid_to IS NOT NULL OR v.implementation_date < current_date)""").rowcount
    return a + b


def run(conn: psycopg.Connection) -> dict:
    return {"new": sum(evaluate_rules(conn).values()), "closed": close_settled(conn)}
