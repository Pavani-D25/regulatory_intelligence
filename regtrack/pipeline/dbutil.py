"""Small DB write helpers that keep every stage idempotent (write only when something changed)."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

import psycopg

from regtrack.db import Jsonb


def _norm(v):
    if isinstance(v, Jsonb):
        v = v.obj
    if isinstance(v, (dict, list)):
        return json.loads(json.dumps(v, sort_keys=True, default=str))
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, tuple):
        return list(v)
    return v


def update_if_changed(conn: psycopg.Connection, table: str, key: dict, values: dict, touch: bool = False) -> bool:
    """UPDATE table SET values WHERE key, only for columns whose value differs. Returns True if written."""
    cols = list(values)
    where = " AND ".join(f"{k}=%s" for k in key)
    row = conn.execute(f"SELECT {', '.join(cols)} FROM {table} WHERE {where}", list(key.values())).fetchone()
    if row is None:
        return False
    changed = {c: values[c] for c in cols if _norm(row[c]) != _norm(values[c])}
    if not changed:
        return False
    sets = ", ".join(f"{c}=%s" for c in changed)
    if touch:
        sets += ", updated_at=now()"
    conn.execute(f"UPDATE {table} SET {sets} WHERE {where}", [*changed.values(), *key.values()])
    return True


FLAG_NOTES = ("resolution", "evidence", "explained")  # added by resolvers; not part of what the flag says
# v4B names: a stored file is a "document", a regulation a "regulation", a rule version a "requirement_version"
FLAG_ENTITIES = ("document", "regulation", "requirement_version", "source")


def add_flag(conn: psycopg.Connection, entity: str, entity_id: int, rule: str, details: dict | None = None) -> bool:
    """Insert an open quality_flags row unless the same flag exists - open, or already resolved with a recorded
    resolution (a flag settled by evidence is not raised again on the next run). Resolver notes are ignored in the
    comparison."""
    if entity not in FLAG_ENTITIES:
        raise ValueError(f"unknown flag entity {entity!r}; use one of {FLAG_ENTITIES}")
    d = json.dumps(details or {}, sort_keys=True, default=str)
    notes = "".join(f" - '{k}'" for k in FLAG_NOTES)
    hit = conn.execute(
        f"SELECT 1 FROM quality_flags WHERE entity=%s AND entity_id=%s AND rule=%s "
        f"AND (coalesce(details,'{{}}'::jsonb){notes}) = %s::jsonb "
        f"AND (resolved_at IS NULL OR details ? 'resolution') LIMIT 1",
        (entity, entity_id, rule, d),
    ).fetchone()
    if hit:
        return False
    conn.execute(
        "INSERT INTO quality_flags (entity, entity_id, rule, details) VALUES (%s,%s,%s,%s::jsonb)",
        (entity, entity_id, rule, d),
    )
    return True


def set_stage(conn: psycopg.Connection, file_id: int, stage: str, error: str | None = None) -> None:
    """Move a stored file (documents) to a stage; its listings follow (downloaded / processed / failed)."""
    cur = conn.execute(
        "UPDATE documents SET stage=%s, stage_error=%s WHERE id=%s AND (stage<>%s OR stage_error IS DISTINCT FROM %s)",
        (stage, error, file_id, stage, error),
    )
    if cur.rowcount:
        status = {"downloaded": "downloaded", "failed": "failed"}.get(stage, "processed")
        conn.execute(
            "UPDATE raw_ingestion_records SET processing_status=%s WHERE document_id=%s "
            "AND processing_status NOT IN (%s, 'needs_review')",
            (status, file_id, status),
        )
