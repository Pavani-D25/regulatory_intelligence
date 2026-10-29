"""PostgreSQL connection helpers (psycopg 3)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from regtrack.config import get_settings

__all__ = ["connect", "transaction", "is_reachable", "Jsonb"]


def connect(autocommit: bool = False, dsn: str | None = None) -> psycopg.Connection:
    return psycopg.connect(
        dsn or get_settings().psycopg_dsn, autocommit=autocommit, row_factory=dict_row, connect_timeout=5
    )


@contextmanager
def transaction(dsn: str | None = None) -> Iterator[psycopg.Connection]:
    """A connection that commits on success and rolls back on error."""
    conn = connect(dsn=dsn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def is_reachable(dsn: str | None = None) -> tuple[bool, str]:
    try:
        with connect(autocommit=True, dsn=dsn) as c:
            v = c.execute("SHOW server_version").fetchone()["server_version"]
        return True, v
    except Exception as e:  # noqa: BLE001
        return False, str(e).splitlines()[0][:200]


def pgvector_installed(conn: psycopg.Connection) -> str | None:
    row = conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()
    if row:
        return row["extversion"]
    avail = conn.execute("SELECT default_version FROM pg_available_extensions WHERE name='vector'").fetchone()
    return f"available ({avail['default_version']}), not yet created" if avail else None


def vec_literal(v: list[float]) -> str:
    """pgvector text input format."""
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"
