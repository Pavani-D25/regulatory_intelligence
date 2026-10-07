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


def add_flag(conn: psycopg.Connection, entity: str, entity_id: int, rule: str, details: dict | None = None) -> bool:
    """Insert an open quality_flag unless the same open flag already exists."""
    d = json.dumps(details or {}, sort_keys=True, default=str)
    hit = conn.execute(
        "SELECT 1 FROM quality_flag WHERE entity=%s AND entity_id=%s AND rule=%s AND resolved_at IS NULL "
        "AND coalesce(details,'{}'::jsonb)=%s::jsonb", (entity, entity_id, rule, d)).fetchone()
    if hit:
        return False
    conn.execute("INSERT INTO quality_flag (entity, entity_id, rule, details) VALUES (%s,%s,%s,%s::jsonb)",
                 (entity, entity_id, rule, d))
    return True


def resolve_flags(conn: psycopg.Connection, entity: str, entity_id: int, rule: str) -> int:
    cur = conn.execute("UPDATE quality_flag SET resolved_at=now() WHERE entity=%s AND entity_id=%s AND rule=%s "
                       "AND resolved_at IS NULL", (entity, entity_id, rule))
    return cur.rowcount


def set_stage(conn: psycopg.Connection, file_id: int, stage: str, error: str | None = None) -> None:
    conn.execute("UPDATE file_object SET stage=%s, stage_error=%s WHERE id=%s AND (stage<>%s OR stage_error IS DISTINCT FROM %s)",
                 (stage, error, file_id, stage, error))
