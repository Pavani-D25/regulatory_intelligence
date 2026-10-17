# v4B phase 3: text, classify and extract on the v4B tables

**Date:** 18 October 2026 · **Branch:** `v4-schema` · **Plan:** `docs/SCHEMA_V4B.md` §4 · **Tested on:** `regtrack_test`, `regtrack_dev`

## Approach

The classification and extraction logic (rules, patterns, identity, Qwen prompts) is **unchanged**. Only the database reads and writes moved.

They now go through one new module, `regtrack/pipeline/repo.py`. It reads the v4B tables and hands the pipeline the same record shapes it already used (`canonical_id`, `doc_class`, `issuer`, `vehicle_categories[]`…). When it writes, it translates those back into v4B columns and link tables. One place holds the whole mapping, so the logic code needed only small call-site changes.

| The pipeline says | Stored in v4B as |
|---|---|
| file (`sha256`, `ext`, `pdf_meta`, `first_seen_at`…) | `documents` (`checksum_sha256`, `file_ext`, `metadata`, `downloaded_at`…) |
| document `canonical_id`, `doc_class`, `status` | `regulations.external_code`, `local_class`, `legal_status` |
| `official_title`, `subject`, `doc_date(_precision)` | `title`, `summary`, `published_date(_precision)` |
| `issuer` ("AISC/ARAI") | `authority_id` → `regulatory_authorities` (code `AISC_ARAI`, same rule as 0007), plus a `primary` row in `regulation_authorities` |
| `vehicle_categories[]` | rows in `regulation_vehicle_categories` (region's own codes) |
| `domains[]` (first = main topic) | rows in `regulation_domains`, the first with `is_primary` |
| document in a file, pages, English range | `document_parts` (`language_pages = {"en":[from,to]}`; role `hindi_only` ↔ `other_language_only`) |
| listings of a file | `raw_ingestion_records` + `sources` |
| warnings | `quality_flags` with v4B entity names: `document` (a file), `regulation`, `requirement_version` |

Writes still compare before writing: equal values write nothing. For the arrays, vehicle types compare as sets and topics compare as a set plus the main topic.

## What was built

| File | Change |
|---|---|
| `regtrack/pipeline/repo.py` | **new**. The adapter above, plus `listings_of_file/_document`, `parts_of_file`, `attach` / `detach`, `retire_document` and `mark_listings_classified` |
| `regtrack/pipeline/dbutil.py` | `set_stage` → `documents`, and the file's listings follow (`processed` / `failed`). `add_flag` / `resolve_flags` → `quality_flags`; an unknown entity name now raises an error instead of writing a bad row |
| `regtrack/pipeline/stages.py` | text and classify, `write_documents` / `write_ais`, best copies, TAP copies, amendment gaps and retiring stale documents all on the v4B tables. After classification, each listing gets the verdict and its main regulation |
| `regtrack/pipeline/extract.py` | `stage_extract`, `listing_subject`, `extract_document` (base-standard lookup, issuer from source/folder, flags) and `enrich_pending` (Qwen catch-up) |
| `regtrack/pipeline/runner.py` | picks files from `documents`; the link order uses `document_parts` / `regulations`; `post_run` calls the new 0008 function |
| `regtrack/pipeline/link.py` | only the warning entity names (`regulation`, `requirement_version`); the rest moves in phase 4 |
| `db/migrations/0008_v4b_regulation_fields.sql` | **new, function only, no table changes.** `refresh_regulation_fields(cc)` is the v4B twin of 0006's `refresh_universal_fields`: doc_type / doc_role from `document_classes` or what the regulation amends, local name, language, and legal_force from open `requirement_versions` |
| `tests/test_pipeline_v4b.py` | **new**, 6 tests (below) |
| `tests/test_country.py` | the "pipeline does not pick Thai files" test now uses `documents` rows; the API tests in that file stay on the old tables until phase 7 |

## Tests

| Test | Shows |
|---|---|
| notification through text → classify → extract | `SO-1406(E)-2021` read from content; MoRTH authority + primary link; vehicle-type and topic rows match; listing marked `processed` with verdict and regulation; 0008 fills doc_type `REGULATION`, legal_force `MANDATORY`, local_type `S.O.`, and a second call returns 0 |
| second pass writes nothing | classify + extract again on the same file: only the 2 stage updates (classified → parsed) |
| AIS file with an embedded amendment | split into `AIS_STANDARD` + `AIS_AMENDMENT` parts, each with `amends` and issuer AISC/ARAI |
| adapter round trip | same values → no write; topic order changes the main topic; issuer change moves the primary authority (still exactly one) |
| flag entity names | old name `file_object` is rejected; duplicates are not raised twice |
| storage | storing copies; the fixture stays |

| | Result |
|---|---|
| pytest | **95 passed, 2 skipped** (MinIO not running) |
| ruff | clean |

## Real run on `regtrack_dev`

**0008 against the existing data:** the function was run in a rolled-back transaction over all 2,066 copied regulations and changed **0 rows**. The new definition agrees exactly with 0006.

**Text → classify → extract** of the two files the phase-2 crawl downloaded (via `runner.run_stage`):

| | File 4972 | File 4974 |
|---|---|---|
| file | 4 pages, text layer, 2 Hindi + 2 English pages | 5 scanned pages, Windows OCR |
| regulation | 2125 `GSR-760(E)-2026`, `NOTIFICATION_DRAFT`, draft, 21 Aug 2026 | 2126 `DOC-11c77c52f8c06036`, `CIRCULAR_OM`, 12 Oct 2026 |
| authority | MORTH | MORTH |
| vehicle types / topics | ALL / SAFETY_EQUIPMENT (main), TYPE_APPROVAL | none / none (`in_scope = false`) |
| summary | Amends CMVR Rule 2, 125, 126 | RT-25035/80/2025-RS (file number) |
| part | pages 1–4, English 3–4, best copy | pages 1–5, best copy |
| 0008 fields | REGULATION · AMENDMENT · INFORMATIVE · G.S.R. · en | GUIDANCE · BASE · INFORMATIVE · en |
| listings | both MoRTH listings → `processed`, verdict true, regulation 2125 | `processed`, verdict true, regulation 2126 |
| Qwen | `llm_pending` (LLM not configured) | `llm_pending` |

**Nothing else changed:** row fingerprints of regulations, parts, the three link tables, quality flags, listings and stored files were identical before and after the run, except for the two new files.

**Idempotent:** both files were sent back to classify + extract, and their regulations, parts, links and listings came out identical (including `updated_at`). The flag count was unchanged, and 0008 changed 4 rows on its first call and 0 on its second.

## Open issues

1. **The job advertisement (4974) is not `OFF_TOPIC`.** The classifier scores it automotive: 3 road-safety keywords, and the issuer is MoRTH. That rule is unchanged by this phase; the old tables would give the same answer. Fixing it means a classification rule ("Application for the post of…" / "Advertisement … consultants" → `OFF_TOPIC`), which is a separate decision.
2. **Draft G.S.R. 760(E)-2026 has no comment period or title yet.** The deterministic rules did not find them in the English pages; Qwen (`llm_pending`) fills these once `LLM_BASE_URL` is set.
3. **Not runnable end to end on this branch yet.** Link, mandates, chunk/embed, events, flag resolution, report, API and portal still use the old tables (phases 4–7), and so does `post_run` apart from the 0008 call. The live system on `multi-country` is unaffected.
4. **`title_native`.** 0007 put the official-language title in `title_native` when an English title existed. The pipeline writes only `title`, which is correct for today's data (no English-title step exists in the code). A future translation step should write both.
