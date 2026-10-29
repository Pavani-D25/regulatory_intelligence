"""regulation_changes rows for changes detected by live crawls (the one-time seed import emits none).

Idempotent: a change is identified by (change_type, regulation_id, requirement_version_id) and written once.
Summary: one line from Qwen when reachable (details.summary_by = 'qwen'), otherwise a deterministic template
('template': the summary still needs a look). Every new change is 'pending' review until a person reviews it;
sla_due_at = detected_at + the review_sla_days setting.
"""

from __future__ import annotations

import psycopg
from pydantic import BaseModel

from regtrack import country, llm
from regtrack.db import Jsonb
from regtrack.pipeline import repo as R

CLASS_EVENT = {
    "AIS_AMENDMENT": "new_amendment",
    "AIS_CORRIGENDUM": "corrigendum",
    "NOTIFICATION_CORRIGENDUM": "corrigendum",
    "NOTIFICATION_DRAFT": "draft_published",
    "AIS_DRAFT": "draft_published",
}


class OneLine(BaseModel):
    summary: str
    impact: str  # High | Medium | Low


def _exists(conn, etype, doc_id, mandate_id) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM regulation_changes WHERE change_type=%s AND regulation_id IS NOT DISTINCT FROM %s "
            "AND requirement_version_id IS NOT DISTINCT FROM %s",
            (etype, doc_id, mandate_id),
        ).fetchone()
        is not None
    )


def summarise(text: str, fallback: str) -> tuple[str, str | None, bool]:
    if llm.reachable()[0]:
        try:
            r = llm.structured(
                OneLine,
                "Summarise a regulatory change for a vehicle manufacturer in one line. impact is High, Medium or Low.",
                text[:4000],
                timeout=120,
            )
            return r.summary[:300], r.impact, True
        except Exception:  # noqa: BLE001
            pass
    return fallback, None, False


def emit(
    conn: psycopg.Connection,
    etype: str,
    doc: dict | None,
    mandate_id: int | None,
    details: dict,
    fallback: str,
    context: str = "",
) -> bool:
    did = doc["id"] if doc else None
    if _exists(conn, etype, did, mandate_id):
        return False
    summary, impact, by_llm = summarise(context or fallback, fallback)
    severity = impact.lower() if impact and impact.lower() in ("high", "medium", "low") else None
    conn.execute(
        """INSERT INTO regulation_changes (region_id, change_type, regulation_id, requirement_version_id, severity, summary,
                                           details, review_status, sla_due_at)
           VALUES ((SELECT id FROM regions WHERE code=%s), %s, %s, %s, %s, %s, %s, 'pending',
                   now() + make_interval(days => coalesce((SELECT value::int FROM app_settings
                                                           WHERE key='review_sla_days'), 2)))""",
        (
            country.code(),
            etype,
            did,
            mandate_id,
            severity,
            summary,
            Jsonb({**details, "summary_by": "qwen" if by_llm else "template"}),
        ),
    )
    return True


def live_documents(conn: psycopg.Connection) -> list[dict]:
    """Regulations with at least one file first seen by a live crawl (not only the seed import)."""
    ids = conn.execute(
        """SELECT DISTINCT p.regulation_id AS id FROM document_parts p
           JOIN raw_ingestion_records s ON s.document_id=p.document_id JOIN sources so ON so.id=s.source_id
           JOIN regulations g ON g.id=p.regulation_id
           WHERE so.code<>'LOCAL_SEED' AND s.ingestion_run_id IS NOT NULL AND """
        + country.region_sql("g")
        + """
             AND NOT EXISTS (SELECT 1 FROM raw_ingestion_records s2 JOIN sources so2 ON so2.id=s2.source_id
                             WHERE s2.document_id=p.document_id AND so2.code='LOCAL_SEED')
           ORDER BY 1"""
    ).fetchall()
    return [R.get_document(conn, r["id"]) for r in ids]


def emit_events(conn: psycopg.Connection) -> int:
    n = 0
    for d in live_documents(conn):
        title = d["official_title"] or d["subject"] or ""
        etype = CLASS_EVENT.get(
            d["doc_class"], "new_revision" if d["doc_class"] == "AIS_STANDARD" and d["revision"] else "new_document"
        )
        n += emit(
            conn,
            etype,
            d,
            None,
            {"canonical_id": d["canonical_id"], "doc_class": d["doc_class"]},
            (f"{d['canonical_id']}: {title}" if title else f"{d['canonical_id']} ({d['doc_class']})")[:300],
            f"{d['canonical_id']} ({d['doc_class']}) {title}",
        )
        for r in conn.execute(
            "SELECT r.*, t.external_code AS target FROM regulation_relations r "
            "LEFT JOIN regulations t ON t.id=r.to_regulation_id "
            "WHERE r.from_regulation_id=%s AND r.type='finalises'",
            (d["id"],),
        ).fetchall():
            n += emit(
                conn,
                "draft_finalised",
                d,
                None,
                {"draft": r["target"] or r["to_ref"]},
                f"{d['canonical_id']} finalises draft {r['target'] or r['to_ref']}",
            )
        for m in conn.execute(
            """SELECT m.id, c.requirement_code AS mandate_key, m.implementation_date, o.implementation_date AS old_date
                   FROM requirement_versions m JOIN compliance_requirements c ON c.id=m.requirement_id
                   JOIN requirement_versions o ON o.superseded_by=m.id WHERE m.source_regulation_id=%s""",
            (d["id"],),
        ).fetchall():
            if m["old_date"] != m["implementation_date"]:
                n += emit(
                    conn,
                    "implementation_date_changed",
                    d,
                    m["id"],
                    {"key": m["mandate_key"], "old": str(m["old_date"]), "new": str(m["implementation_date"])},
                    f"{m['mandate_key']}: implementation {m['old_date']} -> {m['implementation_date']}",
                )
            else:
                n += emit(
                    conn,
                    "mandate_superseded",
                    d,
                    m["id"],
                    {"key": m["mandate_key"]},
                    f"{m['mandate_key']} superseded by {d['canonical_id']}",
                )
    return n
