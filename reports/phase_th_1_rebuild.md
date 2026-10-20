# Phase TH-1 (rebuilt): per-country vehicle-category scope

**Date:** 20 October 2026 · **Plan:** `Thailand parity + cascading dashboard country filter` (TH-0..TH-8), continuing from the DB-only handoff validated in `phase_th_db_validate.md`.

**Status:** done — the backend code side of TH-1 (missing from the original handoff) has been rebuilt from `phase_th_1.md`'s description and verified against the live API.

## Why this phase existed

The original `phase_th_1.md`/`phase_th_2.md` reports described code changes (a per-country `IN_SCOPE_CATEGORIES_BY_COUNTRY`, per-country `portal.py` vocab, a dashboard country selector) that were never actually present in this repository — confirmed by grepping the full git history on every branch. Only the DB migrations existed. This phase rebuilds the backend half (TH-1) from the report's description. The dashboard half (TH-2) is separate, not done here.

## What was built

| File | Change |
|---|---|
| `regtrack/models/enums.py` | `IN_SCOPE_CATEGORIES` (bare India-only frozenset) replaced by `IN_SCOPE_CATEGORIES_BY_COUNTRY` (`IN`: L1/L2/M1/N1/ALL, `TH`: L1/L3/M1/N1/ALL) + `in_scope_categories(cc)` |
| `regtrack/validators.py` | `in_scope(categories, cc=None)` now checks against the resolved country's set |
| `regtrack/pipeline/alerts.py` | `_scope_ids` takes `cc`; `evaluate_rules` resolves it once via `country.code()` and threads it through |
| `regtrack/pipeline/extract.py` | `in_scope()` calls in `deterministic()` and `merge_llm()` use the file's own `country` column (`file_row["country"]`, already selected by `repo.FILE_SQL`) instead of the process default — a document from a Thai source is scored against Thailand's scope even if the process default is India |
| `regtrack/scheduler.py` | `crawl_source`, `run_source`, `run_all` take an optional `cc`, defaulting to the current setting when omitted |
| `regtrack/api/app.py` | `/vehicles/applicable` and `/meta` use `in_scope_categories(cc)` instead of the India-only constant |
| `regtrack/api/portal.py` | The module-level `CATEGORIES`/`SCOPE`/`CAT_LABEL`/`DOMAIN_LABEL` globals (one shared cache for every country) replaced by `load_vocab(conn, cc) -> dict`, cached 10 minutes per country code. Every function that used the old globals (`classify_row`, `follow_up`, `regulations`, `summary`, `regulation_list`, `regulation_detail`, `compliance`, `impact`, `impact_cell`, `ask_context`, `_answer`, `reports`, `generate_report`, `alerts`, `portal_meta`) now resolves its own country's vocab. Write endpoints (`set_review`, `set_compliance`, `add_alert`, `run_sync`, `ask`) now resolve `cc` from the request body instead of silently defaulting to the process's `COUNTRY` setting. Hardcoded "India"/"Indian" strings in report titles and the Ask-AI system prompt now use the resolved region's name (`vocab["name"]`). |
| `tests/test_portal.py` | `classify_row` calls updated for the new `vocab` parameter; `test_sync_all_runs_every_source_and_survives_a_failure`'s fake crawler accepts the new optional `cc` argument |
| `tests/test_v4b_schema.py` | `test_reference_rows`'s `region_scope` check scoped to India specifically (it previously checked the whole table, which now legitimately also contains Thailand's own 4 rows); added a matching assertion for Thailand's set |

## Verification

- `pytest`: 111 passed, 1 failed, 2 skipped. The 1 failure (`test_drafts_are_not_published_standards`) was confirmed failing identically on the unmodified code (`git stash` + re-run) — a pre-existing data gap, unrelated to this phase.
- `ruff check`: all checks pass on every touched file.
- Live API, against the validated `regtrack_th_validate` database:
  - `GET /meta?country=TH`: `L3` now `"in_scope": true` (was `false` before this phase — this was the concrete bug the DB-only handoff exposed).
  - `GET /meta?country=IN`: unchanged, `L1/L2/M1/N1/ALL` still `true`, confirming no regression for India.
  - `GET /portal/summary?country=TH`: `by_category` correctly shows Thailand's 4 categories with their own labels, `sources: 8`.
  - `GET /portal/admin?country=TH`: lists all 8 Thailand sources, each correctly flagged `"crawler": false` (no scraper module exists for any of them yet — accurate, not a bug).
  - `GET /portal/impact?country=TH`, `GET /portal/compliance?country=TH`: both return cleanly scoped to Thailand's categories, no errors.

## Open for later phases

- TH-2 (dashboard country dropdown) is not part of this phase — the backend is ready for it (every endpoint already accepts `?country=`), but no frontend code was written.
- TH-3 (actual Thailand scrapers) remains unstarted — `CRAWLERS_BY_COUNTRY["TH"]` is still `{}`. `/portal/admin/sync` for Thailand will run and do nothing until scrapers exist.
