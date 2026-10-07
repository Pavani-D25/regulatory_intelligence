"""Tiny migration runner: db/migrations/*.sql in order, then db/seeds/*.sql. Idempotent.

Each applied file is recorded in schema_migrations with its sha256. A file whose content changed after
being applied is reported, never re-run: schema changes go into a new numbered migration.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from regtrack.config import ROOT
from regtrack.db import connect

MIGRATIONS = ROOT / "db" / "migrations"
SEEDS = ROOT / "db" / "seeds"

DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
  name        TEXT PRIMARY KEY,
  kind        TEXT NOT NULL,
  sha256      CHAR(64) NOT NULL,
  applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
)"""


def _files(d: Path) -> list[Path]:
    return sorted(p for p in d.glob("*.sql") if p.is_file())


def migrate(dsn: str | None = None) -> list[str]:
    out: list[str] = []
    with connect(dsn=dsn) as conn:
        conn.execute(DDL)
        conn.commit()
        done = {r["name"]: r["sha256"] for r in conn.execute("SELECT name, sha256 FROM schema_migrations")}
        for kind, d in (("migration", MIGRATIONS), ("seed", SEEDS)):
            for p in _files(d):
                key = f"{kind}/{p.name}"
                sql = p.read_text(encoding="utf-8")
                sha = hashlib.sha256(sql.encode("utf-8")).hexdigest()
                if key in done:
                    if done[key] != sha:
                        out.append(f"WARNING {key} changed after it was applied; add a new migration instead")
                    continue
                with conn.transaction():
                    conn.execute(sql)
                    conn.execute("INSERT INTO schema_migrations (name, kind, sha256) VALUES (%s,%s,%s)",
                                 (key, kind, sha))
                out.append(f"applied {key}")
        conn.commit()
    if not out:
        out.append("up to date")
    return out


if __name__ == "__main__":
    for line in migrate():
        print(line)
