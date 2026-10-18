# v4B phase 8: switch-over (prepared and rehearsed)

**Date:** 18 October 2026 · **Branch:** `v4-schema` · **Plan:** `docs/SCHEMA_V4B.md` §4

**Status:** everything for the switch is built and was rehearsed on a full copy of the live database. **The live database has not been changed**; the switch needs the go-ahead (it changes live data).

## What was built

| Item | What |
|---|---|
| `regtrack/pipeline/report.py` | the regression table, fill rates and validation report on v4B |
| `regtrack/llm_smoke.py`, `scripts/rowcounts.py` | on v4B |
| `regtrack/country.py` | only `code()` and `region_sql()` remain; the old-table helpers had no callers left |
| `db/migrations/0011_drop_old_tables.sql` | drops the 24 tables of migrations 0001–0006 and the two 0006 functions. **Guard:** on a database with old rows it refuses unless `app_settings.v4b_switch_verified = true`; a fresh database passes straight through |
| `regtrack/migrate.py` | `--until N` (stop after a number); each file commits on its own, so a refused 0011 keeps 0007–0010 |
| `scripts/v4b_verify.py` | the phase-1 proof as a command: 25 counts, 11 row-by-row fingerprints, 8 "rules for a vehicle on a date" answers, the wheel-rim history. Exit code 0 only if all pass; `--mark-verified` then allows 0011 |
| tests | the old-table tests ported to v4B (`test_db.py`, `test_universal_schema.py`, `test_v4b_schema.py`), plus a test that 0011 refuses without verification |
| `CLAUDE.md`, `docs/DB_DESIGN.md` | v4B names in the rules and conventions; `SCHEMA_V4B.md` is the authority for tables; DB_DESIGN keeps the design decisions and gets a name map; its §4 is marked as the first schema |
| small fixes found by the rehearsal | embedding-size check read the old `chunk` table; internal flag hidden from Admin settings; stable order for top standards, library rows and class counts |

## Regression numbers (CLAUDE.md), measured on v4B

Measured with the new `report.py` on the v4B tables of `regtrack_dev`, and compared with the old `report.py` on the old tables: **all eight identical**.

| Measure | Expected | Measured |
|---|---|---|
| Files / unique by SHA-256 | 2,274 / 2,016 | 2,274 / 2,018 |
| Scans (< 100 chars per page) | 251 files, 1,742 pages | 248 files, 1,724 pages |
| AIS files with embedded amendments | ≈ 210 | 181 
| AIS files with corrigenda | ≈ 15 | 14 
| Notifications with Kruti Dev Hindi | ≈ 300 | 232 unique files (276 incl. byte-copies) 
| Finals citing their draft (in corpus / missing) | 225 (121 / 104) | 207 (94 / 113) 
| MoRTH title ≠ content ID | 6 | 14 (all sources: 16) 
| Non-automotive files in folder 02 | ≈ 92 (→ OFF_TOPIC) | 138 OFF_TOPIC (47 non-automotive + 91 state-level) 

These are exactly the values in `reports/VALIDATION_REPORT.md` from before the move: the move changed no measurement. The gaps to the design-time estimates already existed there; the move did not cause them.

## Rehearsal on a copy of the live database

1. **Backup of live** (read only): `data/snapshots/regtrack_2026-10-18_pre_v4b.dump` (22 MB). The live database last changed on 12 Oct (last crawl), so the copy is the live state.
2. **Restored** as `regtrack_rehearsal`. Old-code output was captured on it from a checkout of `multi-country` (`D:\installers\mc_worktree`): 37 endpoint snapshots and the validation report.
3. **`scripts/v4b_verify.py regtrack_rehearsal --migrate`** (0007–0010): **all checks passed**. 25/25 counts, 11/11 fingerprints, 8/8 vehicle-on-date answers, wheel-rim history 269 → 288 → 300 → 324.
4. **`post_run` with the new code**, twice:

   | | First run | Second run |
   |---|---|---|
   | impact stored | 2,066 regulations | 0 |
   | stale chunk years corrected | 299 | 0 |
   | alerts new / closed | 51 / 35 | 0 / 0 |
   | change events | 0 | 0 |

   No change event is duplicated.
5. **Old code vs new code, same data:**
   - The 37 endpoints give the same answers. The only differences are the open-alerts list (50 matches → 16 open alerts), `reviewed_at` shown in India time, the new `regulation_id` / `teams` keys, and the order of tied rows (now stable).
   - The change events are the same 140, with the same fields.
   - The validation report is identical apart from the v4B entity names.
6. **`--mark-verified`, then `migrate` (0011):**
   - the 24 old tables were dropped;
   - the database has 40 tables (39 v4B + the migration log) and shrank from about 300 MB to 235 MB;
   - the endpoints give the same answers before and after the drop.
7. **On the switched copy:**
   - pytest: **110 passed, 2 skipped**;
   - `check`: database ok, pgvector ok; the three LLM lines fail only because `LLM_BASE_URL` / `EMBED_MODEL` are placeholders;
   - a full `run`: nothing pending, nothing written;
   - `resolve-flags`: 0;
   - **seed re-import: 0 rows written**.

## The live switch (to run after the go-ahead)

| Step | Command / action | Check |
|---|---|---|
| 1 | Stop the API / portal and the scheduler if running; nothing else connected to `regtrack` | `pg_stat_activity` |
| 2 | Fresh backup: `pg_dump -Fc regtrack` → `data/snapshots/regtrack_<date>_pre_switch.dump` | file size |
| 3 | Move `multi-country` forward to `v4-schema` (fast-forward; `multi-country` has no commits of its own since) | `git log` |
| 4 | `python scripts/v4b_verify.py regtrack --migrate` (0007–0010 + all checks) | ALL CHECKS PASSED |
| 5 | `post_run` once (impact, chunk years, alerts), then once more | second run writes 0 |
| 6 | Endpoint snapshots compared with the rehearsal's | equal |
| 7 | `python scripts/v4b_verify.py regtrack --mark-verified`, then `python -m regtrack.cli migrate` (0011) | old tables gone |
| 8 | pytest against `regtrack`, rebuild the dashboard (`npx vite build`), start the system | tests pass; portal opens |

**Going back if anything fails:**
- **Before step 7:** drop the v4B tables, or simply restore the backup.
- **After step 7:** `dropdb regtrack; createdb regtrack; pg_restore` the step-2 dump, and reset `multi-country` to its old commit (`9aedf73`).
- The original files in `data/raw` and the page text are never touched by the switch.

## Open issues

1. **`compliance_requirements.regulation_id` is empty** (0 of 120). 0007 links a rule to its legal-basis regulation only when the code starts the legal basis, and rule keys like "SO-1365(E)-2004 Table Sr.8(b)" name a regulation that is not stored. Rules created from now on get it when the regulation is stored. A backfill is optional.
2. **After the switch, the multi-country rollout continues on v4B**, starting with the Thai vehicle categories.
3. **The helper scripts and the rehearsal database** (`D:\installers`, `regtrack_rehearsal`, `regtrack_dev`, the worktree) can be removed after the switch.
