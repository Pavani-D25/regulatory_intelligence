# CLAUDE.md — RegTrack India (regulatory_intelligence)

You are Claude Code, building this project end to end on a **Windows** laptop (PowerShell, VS Code).

- The database design is decided.
  - The tables are those of `docs/SCHEMA_V4B.md` (ERD v4 + RegTrack additions, migrations 0007–0011); it is authoritative for table and column names.
  - `docs/DB_DESIGN.md` is authoritative for the design decisions, vocabularies and `data` shapes; its §4 lists the first schema's tables, kept for history (name map at its top).
- `docs/ETL_SPEC.md` has source details: the MoRTH JSON API, the ARAI list, e-Gazette, and notification structure.
- If they disagree: SCHEMA_V4B wins on tables, DB_DESIGN on everything else, both over ETL_SPEC.
- In code, a regulation keeps the pipeline's names (`canonical_id`, `doc_class`, `status`, `vehicle_categories[]`); `regtrack/pipeline/repo.py` and `regtrack/api/sql.py` map them to v4B in one place each.
- Work phase by phase from `PROMPTS.md`. Do not start a phase before the previous phase's checks pass.

## Goal

The platform automatically collects Indian vehicle regulations from:

- ARAI AIS standards
- MoRTH Gazette notifications, orders and guidelines
- e-Gazette
- India Code CMVR amendments

It stores the original files write-once, the structured data in PostgreSQL 16 (typed columns + JSONB), and clause-level text in pgvector. It refreshes every 6 hours with no manual work.

Users need four views: by vehicle, by year, by category and by version. They also need a vendor share pack (zip + manifest).

**Scope:**
- In scope: L1 and L2 (two-wheelers), M1 (cars, private and transport use) and N1 (light goods).
- Everything else is stored but marked `in_scope = false`.

## Environment

- Python 3.11+ in `.venv`. PostgreSQL 16 + pgvector runs directly on the machine: conda-forge `postgresql=16.15` + `pgvector=0.8.6` in `D:\pgsql`, data in `data\pg`, started with `python -m regtrack.cli db start` (README "Database").
- Config comes from `.env` (never commit it). Keep `.env.example` up to date:

```
DATABASE_URL=postgresql+psycopg://regtrack:regtrack@localhost:5432/regtrack
STORAGE_DIR=D:\regulatory_intelligence\data\raw           # write-once originals, sha256-named
SEED_CORPUS_DIR=D:\Regulatory_Documents                   # READ-ONLY seed corpus (2,274 files)
LLM_BASE_URL=https://<ngrok-id>.ngrok-free.app/v1         # changes when ngrok restarts
LLM_MODEL=qwen/qwen3.8-27b
LLM_API_KEY=lm-studio
EMBED_MODEL=<embedding model loaded in LM Studio>
EMBED_DIM=768                                             # must match vector(N) in the migration
PG_BIN=D:\pgsql\Library\bin                               # local PostgreSQL programs (pg_ctl, pg_dump…)
PG_DATA=D:\regulatory_intelligence\data\pg                # local PostgreSQL data folder
```

- Use `pathlib` everywhere, never hard-coded `/` paths.
- Open text files with `encoding="utf-8"`, because the Windows default cp1252 breaks on Hindi.
- Wrap `multiprocessing` in `if __name__ == "__main__":`.

## Hard rules

1. **Never modify `D:\Regulatory_Documents`.** Read it only. Never read or touch anything else on the machine (for example, the Downloads folder holds personal files).
2. **Never log in to portals, solve captchas, or reuse tokens embedded in web pages.** ARAI's page has a bearer token; do not use it. Use public JSON APIs, or render public pages with Playwright.
3. **Crawl politely:**
   - 1–2 s between requests
   - exponential backoff on 429/5xx
   - User-Agent `RegTrackIndia/0.1 (research)`
4. **Originals are write-once.** Store them at `STORAGE_DIR/<sha256[:2]>/<sha256>.<ext>` and never overwrite or delete them.
5. **Identity comes from document content, never from the listing title.**
   - In the corpus, 6 MoRTH titles name the wrong notification, and 14 listing dates are placeholders (1 Jan).
   - G.S.R./S.O. numbers repeat across years, so the year is part of the ID: `GSR-659(E)-2022`.
6. **One definition per shape.**
   - Each doc_class's `regulations.data` is a Pydantic model in `regtrack/models/`.
   - The JSON Schema is generated from that model, Qwen fills that model, and the DB validates against it.
   - The DB schema changes only through a new numbered SQL migration in `db/migrations/`.
7. **Resumable and idempotent.**
   - `documents.stage` (one row per stored file) is the resume point.
   - Re-running with no upstream change must write zero rows. Test this.
8. **Qwen use:**
   - Call it only via `ChatOpenAI(base_url=LLM_BASE_URL, model=LLM_MODEL, api_key=LLM_API_KEY, temperature=0).with_structured_output(Model, method="json_schema")`. No agents.
   - Send only the pages the task needs (English pages first).
   - Store model, prompt version and per-field confidence in `regulations.extraction`.
   - If the LLM is unreachable (laptop off, ngrok URL changed), leave files at their current stage and continue other work. Never fail the run.
9. **No manual review step.** A failed check writes a `quality_flags` row; the value is kept and marked `needs_check`.

## Repository layout (create as you go)

```
regulatory_intelligence/
  CLAUDE.md  PROMPTS.md  README.md  .env.example  pyproject.toml  start.bat / start.ps1 / start.sh
  docs/        DB_DESIGN.md  ETL_SPEC.md
  db/migrations/0001_init.sql        (given, tested on PG16)
  db/seeds/0001_vocab.sql            (given: vehicle_category, domain, source)
  discovery/   extract.py analyze.py classify.py ais.py   (given: corpus profiler used for the design)
  regtrack/
    config.py  db.py  storage.py  llm.py
    models/        pydantic models per doc_class (+ json schema export)
    sources/       arai.py morth.py egazette.py indiacode.py seed_corpus.py
    pipeline/      text.py classify.py identity.py split.py extract.py link.py mandates.py version.py chunk.py report.py
                   repo.py (v4B data access) events.py resolve.py alerts.py search.py
    validators.py  scheduler.py  assistant.py
    api/           app.py portal.py workspace.py sql.py (v4B in the dashboard's shape)
  tests/       unit tests + fixtures (small PDFs copied from the seed corpus)
  data/raw/    object storage (gitignored)
```

## Conventions (from DB_DESIGN.md)

**`canonical_id` formats** (stored as `regulations.external_code`, unique per region):

| Kind | Format | Example |
|---|---|---|
| Notification | `GSR-<n>(E)-<yyyy>`, `SO-<n>(E)-<yyyy>` | `GSR-659(E)-2022` |
| AIS standard | `AIS-<nnn>[(Part<k>)][(Rev.<r>)]` | `AIS-038(Rev.2)` |
| AIS amendment / corrigendum | base ID + `/Amd.<a>` or `/Corr.<c>` | `AIS-038(Rev.2)/Amd.4` |
| AIS form table | `AIS-007(Rev.5)/Table-<x>` | `AIS-007(Rev.5)/Table-1B` |
| TAP document | `TAP-115/116(Issue.<i>)` | `TAP-115/116(Issue.4)` |
| Form | `FORM-<n>` | `FORM-20` |

**Other rules:**

- `doc_class`, `relation_type`, `nature` and `domain` values are exactly the lists in DB_DESIGN §3. Enforce them in Python enums.
- Vehicle categories: the seed groups trailers as `O` and tractors as `T`. Map O1–O4 → `O` and T1–T5 → `T`.
- `in_scope` = `vehicle_categories` overlaps {L1, L2, M1, N1, ALL}.
- If a notification names no category but applies to "all motor vehicles", use `ALL`. If nothing can be inferred, leave the list empty and raise a `quality_flags` row.
- Mandates (rule versions, `requirement_versions`) are never updated in place. A change closes the old row (`valid_to`, `superseded_by`) and inserts a new row for the same rule (`compliance_requirements.requirement_code`, the mandate key).
- Exactly one `is_current = true` per `family_key` and region (`regulations`); the DB enforces this with a partial unique index.

## Regression numbers (seed corpus, measured)

Use these as tests after each phase. Small differences are fine if explained in the phase report.

| Measure | Expected |
|---|---|
| Files / unique by SHA-256 | 2,274 / 2,016 |
| Scans (< 100 chars per page) | 251 files, 1,742 pages |
| AIS files with embedded amendments | ≈ 210 |
| AIS files with corrigenda | ≈ 15 |
| Notifications with Kruti Dev Hindi | ≈ 300 |
| Finals citing their draft (in corpus / missing) | 225 (121 / 104) |
| MoRTH title ≠ content ID | 6 |
| Non-automotive files in folder 02 | ≈ 92 (→ `OFF_TOPIC`) |

## Working style

- After each phase, write `reports/phase_<n>.md`: what was built, the numbers measured against the table above, and the open issues.
- Prefer deterministic code (regex, layout) before Qwen. Use Qwen only where DB_DESIGN §7 says so.
- Run `pytest` and `ruff` before calling a phase done.
- Commit after each phase with a clear message.
