# Phase 1 — Database

## Built
- `regtrack/migrate.py`: applies `db/migrations/*.sql` in order, then `db/seeds/*.sql`; each recorded in
  `schema_migrations` with its sha256 (a changed file is reported, never re-run). Idempotent.
- `regtrack/models/`: enums (`DocClass`, `RelationType`, `Nature`, `Status`, `Role`, `Stage`, `Domain`, plus
  `VehicleCategory`, `Usage`, `Powertrain`, `ModelScope`, `ChangeEventType`, `FlagRule`) and one Pydantic model per
  doc_class (`models/data.py`); JSON Schemas exported to `regtrack/models/schemas/*.json` (28 files, generated).
- `regtrack/validators.py`: document.data is validated against the generated schema before writes
  (PostgreSQL 16 has no built-in JSON Schema check, so validation is in the write path; failures → `schema_violation`).
- `regtrack/vocab.py` reads category synonyms and domain keywords from `db/seeds/0001_vocab.sql` (one definition).

## Checks
| Check | Result |
|---|---|
| Migrations applied twice | first: `applied migration/0001_init.sql`, `applied seed/0001_vocab.sql`; second: `up to date` |
| DB / pgvector | PostgreSQL 16.15, vector 0.8.7 |
| Partial unique index rejects a 2nd `is_current` in a family | `UniqueViolation` (test_db.py) |
| DB_DESIGN §6 queries on a sample | scooter query, category view, version view pass |
| pytest / ruff | 38 passed / clean |

## Open issues
- `vector(768)` unchanged: the embedding model's dimension cannot be measured until `LLM_BASE_URL` and
  `EMBED_MODEL` are set. If it differs, add `db/migrations/0002_embedding_dim.sql`
  (`ALTER TABLE chunk ALTER COLUMN embedding TYPE vector(N)` + rebuild the HNSW index) — chunks have no vectors yet,
  so this is a cheap change.
