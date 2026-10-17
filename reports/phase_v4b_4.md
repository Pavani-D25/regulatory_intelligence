# v4B phase 4: linking on the v4B tables

**Date:** 18 October 2026 · **Branch:** `v4-schema` · **Plan:** `docs/SCHEMA_V4B.md` §4 · **Tested on:** `regtrack_test`, `regtrack_dev`

## What was built

The link stage connects regulations to each other, orders each family's versions, and turns notifications into dated rule versions. All of its reads and writes now use the v4B tables. As in phase 3, the logic (regex rules, table-amendment parser, version ordering) is **unchanged**; only the database access moved.

| Old | v4B |
|---|---|
| `doc_relation (from_doc, to_doc, to_ref, type…)` | `regulation_relations (from_regulation_id, to_regulation_id, to_ref, type…)` |
| `mandate` row, keyed by `mandate_key` | one `compliance_requirements` row per rule (`requirement_code` = the old key, per region), created with its first version and linked to the regulation it is based on (same rule as 0007), **plus** one `requirement_versions` row per version |
| `mandate.vehicle_categories` (codes) | `requirement_versions.vehicle_category_ids` (the region's category ids) |
| `standard_doc_ids`, `source_doc_id` | `standard_regulation_ids`, `source_regulation_id` |
| family fields on `document` | the same fields on `regulations` (`status` → `legal_status`) |

| File | Change |
|---|---|
| `regtrack/pipeline/mandates.py` | `version_sql()` returns versions under the names the parser uses (`mandate_key`, `vehicle_categories`, `standard_doc_ids`…), so the replay logic is untouched. Writes go through `requirement_id()` (finds or creates the rule) and `insert_mandate()` (translates the columns). Close/supersede, the extension lookup and `finalise_drafts` run on `requirement_versions`. Everything is limited to the current region |
| `regtrack/pipeline/link.py` | `add_relation` / `doc_by_cid` / draft-by-file-number / `resolve_refs` on `regulation_relations` and `regulations`; an amendment inherits its base standard's vehicles through `repo`; `recompute_family` on `regulations`; `stage_link` reads parts and regulations through `repo`; the unresolved-draft flag is resolved on `quality_flags` (entity `regulation`) |
| `tests/test_pipeline_v4b.py` | 5 new tests (below) |
| `tests/test_db.py` | the wheel-rim replay test now checks `requirement_versions` / `compliance_requirements` |

No schema change in this phase.

## Tests

| Test | Shows |
|---|---|
| wheel-rim chain (S.O. 1406(E)-2021 → 359(E)-2022 → 3896(E)-2022) through text → classify → extract → link | `extends_date` links keep the code `SO-1365(E)-2004` (not stored); Sr.8(d) has 3 versions (2021-09-21, 2022-09-21, 2023-06-22) from the right notifications, exactly one open; S.O. 3896(E)-2022 is the current version of the master table family |
| re-link the chain | only the 6 stage updates (parsed → linked); no relation, rule or version row |
| reference resolves later | a link to a missing draft keeps its code; when the draft arrives, `resolve_refs` fills it in and resolves the "unresolved reference" flag; no duplicate relation |
| AIS family | Rev.2 current, Rev.1 superseded, versions numbered 1, 2; a second run writes nothing |
| draft closed by its final | the draft's open version gets `valid_to` and `superseded_by` = the final's version; categories come back as codes |
| wheel-rim replay (`test_db.py`) | the same chain at mandate level: one rule, three versions with category ids, re-run adds nothing |

| | Result |
|---|---|
| pytest | **100 passed, 2 skipped** (MinIO not running) |
| ruff | clean |

## Real runs on `regtrack_dev`

**The new code agrees with the old data.** All 2,144 files that the old code had already linked were re-linked with the new code, in date order, inside one transaction that was rolled back afterwards:

| Table | Writes |
|---|---|
| `documents` | 2,144 updates (the stage marker only) |
| every other table (relations, rules, versions, regulations, link tables, flags, listings) | **0** |
| errors | 0 (52 seconds) |

**The two new files from phase 3** were linked for real (`runner.run_stage("link")`):

| | Result |
|---|---|
| draft G.S.R. 760(E)-2026 (regulation 2125) | 3 `references`: AIS-049(Rev.1) and AIS-041(Rev.1), both stored and linked by id; G.S.R. 889(E)-2020, not stored, kept as a code |
| rule versions | none: no table rows or rule obligations in the draft for the rules to read, and Qwen is off |
| job notice (2126) | no links (no references in it) |
| both files | stage `linked` |
| existing data | fingerprints of relations (5,172), rules (120), versions (178), regulations (2,066) and flags (1,383) identical before and after |
| second link pass | identical |
| `resolve_refs` / 0008 after the run | 0 / 0 |

## Open issues

1. **Draft G.S.R. 760(E)-2026 has no rule versions yet.** Its obligations are in prose, which the deterministic rules don't cover. Qwen's `provisions` (once `LLM_BASE_URL` is set) create them, as for other drafts.
2. **`compliance_requirements.domain_id` stays empty**, as in 0007. A rule's topic could be taken from its source regulation's main topic; that is a small follow-up.
3. **Still on the old tables:** `events.py` (change events), `report.py`, chunk/embed, flag resolution, API and portal (phases 5–7). The live system on `multi-country` is unaffected.
