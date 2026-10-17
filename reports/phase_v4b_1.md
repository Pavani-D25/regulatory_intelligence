# v4B phase 1: schema and data copy (migration 0007)

**Date:** 18 October 2026 · **Branch:** `v4-schema` · **Plan:** `docs/SCHEMA_V4B.md` (option B, approved 18 Oct 2026)

## What was built

- **`db/migrations/0007_v4b_schema.sql`**
  - creates all **39 v4B tables** next to the existing ones (the 40th, `schema_migrations`, already exists);
  - copies the data across, keeping ids wherever a table has a direct predecessor;
  - continues every id sequence after the copied ids.
  - **No existing table is changed.** The code keeps using the old tables until it moves (phases 2–7); they are dropped in a later migration (phase 8).
- **Reference data:**
  - the EU region;
  - 15 authorities, plus any other issuer found in documents;
  - the default team "Regulatory Affairs Team" (from the `default_owner` setting);
  - the 3 report templates the portal already offers.
- **`tests/test_v4b_schema.py`**, 8 tests:
  - all tables exist next to the old ones;
  - reference rows: regions, sources, team, India L2 → UNECE L3, India's scope, `NUMBER_PLATES`, templates;
  - a regulation's code is unique per region;
  - an unknown local class is refused;
  - a file is stored once (fingerprint unique);
  - one primary authority per regulation;
  - a citation must point at something;
  - a watch belongs to exactly one user or team;
  - rule versions keep their history, and a version cannot end before it starts.

## Checks on a copy of the live database

Copy: `regtrack_v4check`, made with `pg_dump` / `pg_restore` from the live database on 18 Oct 2026. Script: `check_0007.py` (scratch, not in the repository).

**Counts (old table = new table): 25 of 25 equal**

| What | Rows |
|---|---|
| regions (countries + EU) | 5 |
| sources | 14 |
| vehicle categories | 39 |
| scope | 5 |
| words | 144 |
| document classes | 35 |
| settings | 4 |
| ingestion runs | 31 |
| files | 2,144 |
| listings | 5,970 |
| regulations | 2,066 |
| authority links | 2,009 |
| topic links | 3,158 |
| vehicle links | 2,869 |
| file parts | 2,552 |
| relations | 5,172 |
| chunks | 148,342 |
| rules | 120 |
| rule versions | 178 |
| changes | 140 |
| warnings | 1,383 |
| alert rules | 4 |
| client requirements | 15 |
| reports, client links | 0 |

**Content, row by row: 11 of 11 identical.** These are md5 fingerprints over every row of:
- regulations, files, listings, file parts, relations, rule versions, chunks, changes, warnings;
- the vehicle types per regulation, compared through the new link table;
- the topics per regulation, compared through the new link table.

**"Which rules applied to this vehicle on this date": 8 of 8 identical** (old tables vs new tables):

| Vehicle | Date | Rules |
|---|---|---|
| L2 | 2023-01-01 | 19 |
| L2 | 2023-07-01 | 25 |
| L2 | 2026-10-18 | 26 |
| M1 | 2022-06-01 | 14 |
| M1 | 2026-10-18 | 21 |
| N1 | 2024-03-01 | 13 |
| L1 | 2025-01-01 | 18 |
| ALL | 2025-06-01 | 6 |

**Wheel-rim rule history (S.O. 1365(E)-2004 Table Sr.8(b)), intact:**

| Version | Written by | Comply from | Valid |
|---|---|---|---|
| 269 | SO-1406(E)-2021 | 2021-09-21 | 2021-03-22 → 2022-01-27 |
| 288 | SO-359(E)-2022 | 2022-09-21 | 2022-01-27 → 2022-08-12 |
| 300 | SO-3896(E)-2022 | 2023-06-22 | 2022-08-12 → 2023-09-05 |
| 324 | SO-3947(E)-2023 | 2023-12-22 | 2023-09-05 → still valid |

## Tests

| | Result |
|---|---|
| pytest | **84 passed, 2 skipped** (MinIO not running: storage tests) |
| ruff | clean |
| fresh database | migrations 0001–0007 and the seed apply in order (the test database is built from scratch on every run) |

## Regression numbers (CLAUDE.md)

Not affected: the pipeline still reads and writes the old tables. They are re-measured on the new tables in phase 8.

## Open issues

1. **The live database does not have 0007 yet.**
   - The migration is verified on the copy only.
   - Until the code moves (phases 2–7), anything the pipeline writes goes to the old tables only, so new tables created now would fall behind the old ones.
   - **Options:**
     - (a) apply now and keep the scheduler off until the switch;
     - (b) apply at the start of phase 2, after a backup.
2. **No rule has its legal-basis document stored** (`compliance_requirements.regulation_id` is empty for all 120 rules). The master notices, such as S.O. 1365(E)-2004, are not in the corpus. This is expected, and it fills in when they are crawled.
3. **Decisions still open** (`docs/SCHEMA_V4B.md` §0, §5):
   - D2: the owner of ERD v4;
   - D3: `schema_v3.md` / the v4 specification text;
   - the seed values for `teams`, `systems` and `report_templates` (only the default team and the portal's 3 templates are seeded).
4. **`refresh_universal_fields()` (0006) still works on the old tables.** It moves to the new tables in phase 3.
