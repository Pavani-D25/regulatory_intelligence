# v4B phase 2: ingestion on the v4B tables

**Date:** 18 October 2026 · **Branch:** `v4-schema` · **Plan:** `docs/SCHEMA_V4B.md` §4

## Approach change (agreed in the conversation)

Phase 1 suggested applying 0007 to the live database at the start of phase 2 (option b).

**That would have broken the pipeline for new files.** After phase 2, the crawlers write the v4B tables, while the later pipeline steps read the old tables until phases 3–6.

**Instead:**
- The live database and the running system stay on the old tables (branch `multi-country`) until the switch.
- Phases 2–7 are built and tested on a development database, **`regtrack_dev`**: a fresh copy of the live database with 0007 applied.
- At the switch (phase 8): backup, apply 0007 to the live database from its latest data, switch the code, verify as in phase 1.

## What was built

| File | Change |
|---|---|
| `regtrack/sources/common.py` | Crawl bookkeeping in `ingestion_runs`. Statuses `ok` / `partial` / `failed` are stored as `success` / `warning` / `failed`. `documents_found`, `changes_found` and `error_message` are filled in. `sources.last_synced_at` / `last_sync_status` are updated. Files are stored in `documents` (new `store_document`: one row per SHA-256). Listings go into `raw_ingestion_records` (new `add_listing`, `processing_status = downloaded`). The three cases (known / seed log / new) and `mark_gone` work as before, on the new tables. |
| `regtrack/sources/indiacode.py` | "seen before?" checks `raw_ingestion_records` |
| `regtrack/sources/seed_corpus.py` | Seed import writes `ingestion_runs`, `documents`, `raw_ingestion_records`; an idempotent re-run still leaves no trace |
| `regtrack/scheduler.py` | Schedules active sources of the current region from `sources.sync_frequency_minutes` (at most every 6 hours) |
| `regtrack/storage_upload.py` | S3 upload reads and updates `documents` |
| `regtrack/country.py` | New `region_sql()`: the country filter for the v4B tables (`region_id`); the old helpers stay for code not yet moved |
| `tests/test_ingestion_v4b.py` | 5 tests (below) |

**Not moved yet** (later phases):
- the pipeline stages (`regtrack/pipeline/*`), which read `file_object` and the document tables;
- the API and portal;
- the report;
- `quality_flag`, `change_event`.

## Tests

| Test | Shows |
|---|---|
| new listing, then the same again | downloads once; a re-run is "known", downloads nothing, writes nothing (CLAUDE.md rule 7) |
| same file under two URLs | 2 listings, 1 stored file |
| listing already in the seed log | linked to the existing file without downloading (`matched_seed`) |
| run status and disappeared listings | `partial` → `warning`, counts and first error line stored, source status updated; `mark_gone` sets `gone_at` |
| region filter | `region_sql()` builds the right condition |

| | Result |
|---|---|
| pytest | **89 passed, 2 skipped** (MinIO not running) |
| ruff | clean |

## Real runs on `regtrack_dev`

**MoRTH crawl** (`regtrack.cli crawl MORTH_API --no-process`), 24 seconds:

| Measure | Value |
|---|---|
| listings seen | 1,163 |
| already known | 1,155 (1,142 listings' "last seen" refreshed in `raw_ingestion_records`) |
| errors | 5 (the same dead links as before) |
| new listings / new files | 3 / 2 |
| run | id 33, status `warning`, counts and first error line stored |
| old tables | untouched (`crawl_run` still 31 rows, last activity 12 Oct) |

The new material published since 12 October:
- **G.S.R. 760(E) dated 21 August 2026, Amendment in CMVR, 1989.** Listed twice by MoRTH and stored **once** (document 4972).
- **A job notice** ("Application for the post of Consultant… National Road Safety Board"), document 4974. Classification (phase 3) is expected to mark it off-topic.

**Seed import, re-run** (`regtrack.cli import-seed`), 87 seconds:

| Measure | Value |
|---|---|
| files checked | 2,274 (2,018 unique) |
| new files | 0 |
| new listings | 0 |
| run record | removed (no trace) |

**Scheduler query on the v4B tables:** India's 4 crawlers (ARAI_AIS, MORTH_API, EGAZETTE, INDIACODE) every 6 hours; no Thai source is active.

## Regression numbers (CLAUDE.md)

- **Files / unique by SHA-256 (2,274 / 2,018):** unchanged, confirmed by the seed re-run.
- **The other measures** depend on pipeline stages not yet moved, and are re-measured in phase 8.

## Open issues

1. **The checked-out branch decides which tables the code uses.** On `v4-schema`, crawls need the v4B tables, which the live database does not have yet. **Run the live system from `multi-country`** until the switch; the working folder has been switched back to it.
2. **On `regtrack_dev`, the pipeline stops after ingestion** until phase 3: the text stage still reads `file_object`. Documents 4972 and 4974 are waiting at `stage = 'downloaded'`.
3. **The live database has not seen the 2 new MoRTH files.** Its next crawl from `multi-country` records them; the PDFs are already in `data\raw`, so they are not downloaded again.
4. **Still open:**
   - D2 (owner of ERD v4);
   - D3 (`schema_v3.md` / the v4 specification text);
   - the seed values for `teams`, `systems` and `report_templates`.
