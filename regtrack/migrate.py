"""Tiny migration runner: db/migrations/*.sql and db/seeds/*.sql in number order. Idempotent.

A seed runs right after the migration with the same number (0001_init, then 0001_vocab, then 0002…), so a later
migration that reshapes seeded rows (0006) finds them on a fresh database too. Each applied file is recorded in
schema_migrations with its sha256. A file whose content changed after being applied is reported, never re-run:
schema changes go into a new numbered migration.

Each file is committed on its own, so a run that stops at a failing file keeps the files before it. `until` stops
after a number (the v4B switch-over applies 0007-0010, verifies, then 0011: `python -m regtrack.cli migrate --until 10`).
"""

from __future__ import annotations

import hashlib
import re
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


def _ordered() -> list[tuple[str, Path]]:
    """(kind, path) by leading number; for the same number the migration comes before the seed."""
    items = [("migration", p) for p in _files(MIGRATIONS)] + [("seed", p) for p in _files(SEEDS)]
    num = lambda p: int(re.match(r"\d*", p.name).group() or 0)  # noqa: E731
    return sorted(items, key=lambda kp: (num(kp[1]), kp[0] != "migration", kp[1].name))


def migrate(dsn: str | None = None, until: int | None = None) -> list[str]:
    out: list[str] = []
    with connect(dsn=dsn) as conn:
        conn.execute(DDL)
        conn.commit()
        done = {r["name"]: r["sha256"] for r in conn.execute("SELECT name, sha256 FROM schema_migrations")}
        for kind, p in _ordered():
            if until is not None and int(re.match(r"\d*", p.name).group() or 0) > until:
                break
            key = f"{kind}/{p.name}"
            sql = p.read_text(encoding="utf-8")
            sha = hashlib.sha256(sql.encode("utf-8")).hexdigest()
            if key in done:
                if done[key] != sha:
                    out.append(f"WARNING {key} changed after it was applied; add a new migration instead")
                continue
            with conn.transaction():
                conn.execute(sql)
                conn.execute("INSERT INTO schema_migrations (name, kind, sha256) VALUES (%s,%s,%s)", (key, kind, sha))
            conn.commit()
            out.append(f"applied {key}")
        conn.commit()
    if not out:
        out.append("up to date")
    return out


if __name__ == "__main__":
    for line in migrate():
        print(line)
