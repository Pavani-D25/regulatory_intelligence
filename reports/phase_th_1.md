# Phase TH-1: fix hardcoded India-only scope, add Thailand's vehicle categories

**Date:** 19 October 2026 · **Plan:** `Thailand parity + cascading dashboard country filter` (TH-0..TH-8)

**Status:** done.

## What was built

| Item | What |
|---|---|
| `db/migrations/0013_thailand_vehicle_scope.sql` | Thailand's in-scope `vehicle_categories` rows (`L1`, `L3`, `M1`, `N1` - `L3` not `L2`, since UNECE `L2` means three-wheeled moped, not India's motorcycle meaning) + matching `region_scope` rows |
| `db/seeds/0007_thailand.sql` (renamed from `0002_thailand.sql`) | fixed a real ordering bug found while testing: it inserts into `regions`/`regulatory_authorities`/`sources`/`client_requirements`, which migration `0007` creates - numbered `0002` it ran before those tables existed on any from-scratch `migrate` (it had only "worked" on the dev database because, by coincidence of this project's history, `0007` already existed by the time the file was added). All inserts are `ON CONFLICT DO NOTHING`, so re-running it under the new name was a harmless no-op on the already-migrated dev database. |
| `db/migrations/0014_fix_hsrp_domain_code.sql` | fixed a mistake in my own earlier `0012_restore_vocab.sql`: it copied the pre-v4B seed's `'hsrp'` domain row literally instead of applying migration `0006`'s rename to `'number_plates'`. Corrective migration (rename-if-missing else drop-duplicate) since `0012` is already applied and migrations aren't edited after the fact. |
| `regtrack/models/enums.py` | `IN_SCOPE_CATEGORIES` (a bare frozenset) replaced by `IN_SCOPE_CATEGORIES_BY_COUNTRY` + `in_scope_categories(cc)`, India's set kept as the default for unknown/unset countries |
| `regtrack/api/portal.py` | `CATEGORIES`/`SCOPE`/`CAT_LABEL`/`DOMAIN_LABEL` module globals removed. `load_vocab(conn, cc)` now returns a per-country `{cat_label, domain_label, categories, scope}` dict, cached per country code (10 min, same TTL as before), filtered to that region's in-scope codes (not every `vehicle_categories` row it has - see "regression caught" below). All 31 former call sites of the old globals now read from the resolved country's vocab. Write endpoints (`set_review`, `set_compliance`, `add_alert`, `run_sync`) now resolve and use `cc` instead of silently defaulting to the process's `COUNTRY` setting. Hardcoded `"India"`/`"Indian"` strings in report titles and the Ask-AI system prompt now use the resolved region's name. |
| `regtrack/api/app.py` | `/vehicles/applicable`'s `in_scope_category` flag and `/meta`'s category list now use `in_scope_categories(cc)` instead of the India-only constant |
| `regtrack/pipeline/extract.py`, `regtrack/validators.py`, `regtrack/pipeline/alerts.py` | the pipeline-side `in_scope()` check (determines `regulations.in_scope` at extraction time) is now per-country too - this was the most consequential fix: without it, every Thai document with `vehicle_categories=['L3']` would have been marked `in_scope=false` forever, since `L3` isn't in India's set |
| `regtrack/scheduler.py` | `crawl_source`, `run_source`, `run_all` now accept an optional `cc`, so Admin's "Run Source Sync" can target the selected country's crawlers instead of always the process default |
| `tests/test_portal.py`, `tests/test_v4b_schema.py` | updated for the `classify_row`/`crawl_source` signature changes and the (now legitimately larger) `region_scope` set once Thailand's rows exist |

## Regression caught before it shipped

`load_vocab()`'s first draft queried **every** `vehicle_categories` row for a region (20 for India: L1-L7, QUADRICYCLE, M1-M3, N1-N3, O, T, CEV, E_RICKSHAW, E_CART, ALL), not just the 4 in-scope ones the portal is built around - a regression from the original hardcoded `CATEGORIES = ["L1","L2","M1","N1"]`. Caught by comparing against CLAUDE.md's own scope rule before testing; fixed by filtering the query to `in_scope_categories(cc)`.

## Environment fix (unblocks all DB-backed tests, not just this phase)

`regtrack_test` (the throwaway database `tests/conftest.py` drops and recreates every session) couldn't run `CREATE EXTENSION vector` - the `regtrack` role isn't superuser, and pgvector wasn't marked trusted on this install. Installed pgvector into `template1` once (`psql template1 -c "CREATE EXTENSION IF NOT EXISTS vector;"`) so every future `CREATE DATABASE` inherits it without needing the privilege. This was blocking 50 of the suite's tests outright (`ERROR`, not `FAILED`) before any of my code changes were in play.

## Verification

- `curl` smoke test: every `/portal/*` and `/meta` endpoint returns 200 for both `?country=IN` and `?country=TH`; `/meta`, `/impact` return the correct, distinct 4-category scope per country (`L1,L2,M1,N1` vs `L1,L3,M1,N1`) with correct labels; `/portal/admin?country=TH` lists Thailand's 8 sources; `/portal/ask` (POST) now accepts `country` in the body and threads it through to search.
- Dashboard (India, no country switcher yet - that's TH-2): reloaded in the browser, renders identically to before, no console errors.
- `pytest`: 102 passed, 8 failed, 0 errors (was 50 passed / 10 failed / 50 errors before the pgvector fix). All 8 remaining failures are pre-existing data/environment gaps unrelated to this phase's code changes, confirmed individually:
  - 6 need real regulation/chunk data in `regtrack_dev` (`test_views_only_india_scope`, `test_drawer_and_review_roundtrip`, `test_compliance_alerts_reports`, `test_no_static_values`, `test_workspace_teams_watches_schedules`, `test_api.py::test_families_and_document_files`) - this Mac has never run `import-seed` (`SEED_CORPUS_DIR` is a Windows path that doesn't exist here), so `regtrack_dev` has 0 documents.
  - 1 (`test_ask_returns_cited_clauses`) hits the pre-existing `EMBED_DIM=768` vs. actual model `4096` mismatch flagged earlier this session (unrelated to Thailand - the embedding-model decision is deliberately deferred to TH-6 per the plan).
  - 1 (`test_llm_smoke.py::test_dry_run_with_fake_llm`) needs real documents for the same reason as the first group.
- `ruff check .`: all checks pass, repo-wide.

## Open for later phases

- `region_scope` is still empty for India in the *real* dev database (only populated on a from-scratch `migrate`, since it derives from the now-dropped `country_scope`/old `vehicle_category.in_scope` flags) - cosmetic only, since nothing reads `region_scope` directly; the portal and pipeline both use `IN_SCOPE_CATEGORIES_BY_COUNTRY`. Not fixed here - pre-existing, unrelated to Thailand.
- TH-2 (dashboard country dropdown) is next.
