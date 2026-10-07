"""change_event rows for changes detected by live crawls (the one-time seed import emits none).

Idempotent: an event is identified by (event_type, document_id, mandate_id) and written once.
Summary: one line from Qwen when reachable, otherwise a deterministic template (marked review_status='auto').
"""

from __future__ import annotations

import psycopg
from pydantic import BaseModel

from regtrack import llm
from regtrack.db import Jsonb

CLASS_EVENT = {
    "AIS_AMENDMENT": "new_amendment", "AIS_CORRIGENDUM": "corrigendum", "NOTIFICATION_CORRIGENDUM": "corrigendum",
    "NOTIFICATION_DRAFT": "draft_published", "AIS_DRAFT": "draft_published",
}


class OneLine(BaseModel):
    summary: str
    impact: str  # High | Medium | Low


def _exists(conn, etype, doc_id, mandate_id) -> bool:
    return conn.execute("SELECT 1 FROM change_event WHERE event_type=%s AND document_id IS NOT DISTINCT FROM %s "
                        "AND mandate_id IS NOT DISTINCT FROM %s", (etype, doc_id, mandate_id)).fetchone() is not None


def summarise(text: str, fallback: str) -> tuple[str, str | None, bool]:
    if llm.reachable()[0]:
        try:
            r = llm.structured(OneLine, "Summarise a regulatory change for a vehicle manufacturer in one line. "
                                        "impact is High, Medium or Low.", text[:4000], timeout=120)
            return r.summary[:300], r.impact, True
        except Exception:  # noqa: BLE001
            pass
    return fallback, None, False


def emit(conn: psycopg.Connection, etype: str, doc: dict | None, mandate_id: int | None, details: dict,
         fallback: str, context: str = "") -> bool:
    did = doc["id"] if doc else None
    if _exists(conn, etype, did, mandate_id):
        return False
    summary, impact, by_llm = summarise(context or fallback, fallback)
    conn.execute("INSERT INTO change_event (event_type, document_id, mandate_id, summary, impact, details, review_status) "
                 "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                 (etype, did, mandate_id, summary, impact, Jsonb({**details, "summary_by": "qwen" if by_llm else "template"}),
                  "auto" if by_llm else "needs_check"))
    return True


def live_documents(conn: psycopg.Connection) -> list[dict]:
    """Documents with at least one file first seen by a live crawl (not only the seed import)."""
    return conn.execute(
        """SELECT DISTINCT d.* FROM document d JOIN document_file df ON df.document_id=d.id
           JOIN file_sighting s ON s.file_id=df.file_id JOIN source so ON so.id=s.source_id
           WHERE so.code<>'LOCAL_SEED' AND s.crawl_run_id IS NOT NULL
             AND NOT EXISTS (SELECT 1 FROM file_sighting s2 JOIN source so2 ON so2.id=s2.source_id
                             WHERE s2.file_id=df.file_id AND so2.code='LOCAL_SEED')""").fetchall()


def emit_events(conn: psycopg.Connection) -> int:
    n = 0
    for d in live_documents(conn):
        title = d["official_title"] or d["subject"] or ""
        etype = CLASS_EVENT.get(d["doc_class"], "new_revision" if d["doc_class"] == "AIS_STANDARD" and d["revision"]
                                else "new_document")
        n += emit(conn, etype, d, None, {"canonical_id": d["canonical_id"], "doc_class": d["doc_class"]},
                  f"{d['canonical_id']}: {title}"[:300], f"{d['canonical_id']} ({d['doc_class']}) {title}")
        for r in conn.execute("SELECT r.*, t.canonical_id AS target FROM doc_relation r LEFT JOIN document t ON t.id=r.to_doc "
                              "WHERE r.from_doc=%s AND r.type='finalises'", (d["id"],)):
            n += emit(conn, "draft_finalised", d, None, {"draft": r["target"] or r["to_ref"]},
                      f"{d['canonical_id']} finalises draft {r['target'] or r['to_ref']}")
        for m in conn.execute(
                """SELECT m.id, m.mandate_key, m.implementation_date, o.implementation_date AS old_date
                   FROM mandate m JOIN mandate o ON o.superseded_by=m.id WHERE m.source_doc_id=%s""", (d["id"],)):
            if m["old_date"] != m["implementation_date"]:
                n += emit(conn, "implementation_date_changed", d, m["id"],
                          {"key": m["mandate_key"], "old": str(m["old_date"]), "new": str(m["implementation_date"])},
                          f"{m['mandate_key']}: implementation {m['old_date']} -> {m['implementation_date']}")
            else:
                n += emit(conn, "mandate_superseded", d, m["id"], {"key": m["mandate_key"]},
                          f"{m['mandate_key']} superseded by {d['canonical_id']}")
    return n
