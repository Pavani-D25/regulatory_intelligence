# v4B phase 6: monitoring on the v4B tables

**Date:** 18 October 2026 · **Branch:** `v4-schema` · **Plan:** `docs/SCHEMA_V4B.md` §4 · **Tested on:** `regtrack_test`, `regtrack_dev`

## What was built

| File | Change |
|---|---|
| `regtrack/pipeline/events.py` | Change events go to `regulation_changes`, with the region, `requirement_version_id` for date changes, `severity` (when Qwen gives one), `review_status = pending` and `sla_due_at = now + review_sla_days` (from `app_settings`). The old `auto` / `needs_check` marker needs no column: it follows from `details.summary_by` (`qwen` / `template`). "Live" files are found through `raw_ingestion_records` (a non-seed listing from an ingestion run). The detection rules are unchanged |
| `regtrack/pipeline/resolve.py` | The four automatic resolvers run on `quality_flags` with the v4B entity names (`document` = file, `regulation`), reading `documents`, `regulations`, `document_parts` and `raw_ingestion_records`. The evidence checks are unchanged |
| `regtrack/pipeline/alerts.py` | **new.** Alerts used to be computed by the portal on every page view and never stored. Now each enabled `alert_rules` row is checked at the end of every run, and each match is stored **once** in `alert_events`. A change-based alert closes when its change is reviewed; a date alert closes when the rule version is replaced or its date has passed. Conditions and scope are the portal's: high_impact, new_document, draft_published, draft_finalised, date_changed, domain (changes in the last 30 days), due_within (open versions with a date in the coming N days); the rule's vehicle category or ALL, otherwise all in-scope categories; only regulations the portal lists |
| `db/migrations/0010_monitoring_v4b.sql` | **new.** (1) `alert_events.regulation_change_id` and `requirement_version_id` (what triggered the alert) with a unique index, so a match is stored once and can be closed. (2) `refresh_regulation_fields()` also stores the **rule-based impact** in `regulations.impact_level` (`impact_basis = 'rules'`), the portal's rule word for word: High = technical and (obligation still to come, revision needing re-approval, or published in the last 12 months); Medium = other technical; Low = administrative. A value the team set (`impact_basis = 'team'`) is never overwritten |
| `regtrack/pipeline/runner.py` | `post_run` ends with the alert check, after the change events it reacts to |
| `tests/test_pipeline_v4b.py` | 5 new tests (below) |

## Tests

| Test | Shows |
|---|---|
| changes from live files | the wheel-rim chain arriving through a live MoRTH crawl: a `new_document` per notification; `implementation_date_changed` with its rule version (Sr.8(d): 2021-09-21 → 2022-09-21 → 2023-06-22); all pending, template summary, deadline 1–2 days; a second run writes 0 |
| seed-only files | the same files from the seed import: no change events |
| impact | S.O. 1406(E)-2021 is medium (technical, old, dates passed); published 10 days ago it becomes high; a team-set value stays; a second refresh writes 0 |
| alerts | a new-document rule and a due-within rule: only the in-scope notification raises an alert (the two extensions are tagged E-cart / E-rickshaw); stored once; closed when the change is reviewed and when the date passes |
| flags | a placeholder-date warning on a file is resolved with the content date as evidence |

| | Result |
|---|---|
| pytest (`DATABASE_URL` = `regtrack_dev`) | **108 passed, 2 skipped** (MinIO not running) |
| ruff | clean |

## Real runs on `regtrack_dev`

**Comparison with the old code (one transaction, rolled back):**

| Check | Result |
|---|---|
| change events | 140 copied; `emit_events` added exactly the 2 expected (below), nothing duplicated |
| automatic flag resolution | 0 further resolutions, the same as the old code had already reached |
| impact, stored vs. the portal's per-view rule, all 488 portal regulations | **0 differ** (66 high, 312 medium, 110 low) |
| alerts, stored vs. the portal's live evaluation, per rule (uncapped) | **identical**: high-impact changes 22 regulations, new draft notifications 28, due within 60 days 0, two-wheeler braking 0 |

**A bug found by the comparison and fixed:** in the first version of 0010, 11 regulations without a `nature` came out "medium" instead of "low". In SQL, `nature = 'technical'` on an empty value is unknown, so the "not technical" branch was skipped. The rule now uses `coalesce`. 0010 was then re-applied on `regtrack_dev` (it exists nowhere else), and the comparison above is after the fix.

**`post_run` for real, twice:**

| | First run | Second run |
|---|---|---|
| regulation fields (impact filled for all 2,068) | 2,068 | 0 |
| change events | 2 | 0 |
| alerts new / closed | 53 / 35 | 0 / 0 |
| chunk filters, references, flags | 0 | 0 |

- **New change events:**
  - 143 `draft_published` for draft G.S.R. 760(E)-2026;
  - 144 `new_document` for the job notice.

  Both are pending, with a review deadline of 20 Oct 2026.
- **Alerts:**
  - High-impact changes: 9 open, 15 closed;
  - New draft notifications: 9 open, 20 closed.

  Alerts on changes that were already reviewed close at once. The new draft raised one alert of each kind; the out-of-scope job notice raised none.

## Open issues

1. **Change-event ids have gaps** (141–142 were used by the rolled-back comparison). Harmless: ids are never reused.
2. **The portal still computes impact and alerts itself** from the old tables. In phase 7 it reads `regulations.impact_level` and `alert_events` instead, so both have one definition.
3. **`notify_team_id`** is stored on each rule, but nothing is sent (no e-mail or Teams yet). The open `alert_events` are what a notification would send.
4. **Still on the old tables:** the API and portal (phase 7) and `report.py`, the regression measurements (phase 8).
