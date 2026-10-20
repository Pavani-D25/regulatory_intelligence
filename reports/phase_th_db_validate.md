# Phase TH-DB-validate: migrations 0012-0015 applied and checked on a fresh database

**Date:** 20 October 2026 · **Scope:** the SQL side of the `phase_th_0/1/2.md` handoff only (no application code was in the handoff — see open issue below).

**Status:** done — DB side confirmed correct on a clean database, independent of the dev DB these migrations were first written against.

## What was done

A new database (`regtrack_th_validate`) was created from scratch on this machine and migrated with no manual steps:

```
python -m regtrack.cli migrate   # (run with DATABASE_URL pointed at the fresh DB)
```

All 15 migration/seed files applied cleanly, in order, no errors:

```
applied migration/0001_init.sql ... migration/0011_drop_old_tables.sql
applied migration/0012_restore_vocab.sql
applied migration/0013_thailand_vehicle_scope.sql
applied migration/0014_fix_hsrp_domain_code.sql
applied migration/0015_subject_source_to_extraction.sql
```

Note: `0012_subject_source_to_extraction.sql` (already in the repo, commit `599e7cd`) collided in number with the handoff's `0012_restore_vocab.sql`. Renamed the former to `0015` (git `mv`, no content change besides its own self-reference comment) since it has no ordering dependency on 0013/0014, unlike the vocab-restore migration which `0014` depends on running first. Safe to rename: it's already applied on the live `regtrack` DB under its old name, and its `UPDATE ... WHERE data ? 'subject_source'` is a no-op on re-run (same idempotency pattern already used for the `0002→0007_thailand.sql` rename).

## Verification queries (on `regtrack_th_validate`)

| Check | Result |
|---|---|
| `regions` | `IN`, `TH`, `UN` (+ pre-existing `EU`, `MY`) all present |
| `vehicle_categories` per region | IN=20, TH=4, UN=19 |
| TH's 4 categories | `L1`, `L3`, `M1`, `N1` — matches 0013's intent (`L3` not `L2`, since UNECE `L2` ≠ India's `L2`) |
| `domains` | only `NUMBER_PLATES` exists, no duplicate `HSRP` row — confirms 0014's fix runs in the correct order after 0012 introduces the bad row |
| `region_scope` | TH=4 (all in-scope rows), IN=5 (pre-existing cosmetic gap, already noted in `phase_th_1.md` as unrelated to Thailand) |
| `sources` for TH | all 8 rows present (`TH_GAZETTE`, `TH_TISI_DB`, `TH_TISI_PORTAL`, `TH_TISI_MANDATORY`, `TH_TISI_NEWS`, `TH_DLT`, `TH_INDUSTRY`, `TH_PCD`), all `is_active = false` |

## Open issue (not part of this validation)

The application code the reports describe (`IN_SCOPE_CATEGORIES_BY_COUNTRY` in `enums.py`, the per-country updates to `validators.py`/`api/app.py`/`api/portal.py`/`pipeline/alerts.py`/`scheduler.py`, and the dashboard country selector in `PortalLayout.jsx`/`api.js`) is not present anywhere in this repository, on any branch, in any commit. Confirmed live: `GET /meta?country=TH` against this validated DB returns Thailand's `L3` category as `"in_scope": false`, because the backend still checks against the hardcoded India-only `IN_SCOPE_CATEGORIES` set. Flagged separately — the DB migrations are correct and ready; the code to make the app actually use them for Thailand still needs to be sent or rebuilt.
