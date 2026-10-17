# Adopting the "Regulatory Intelligence ERD v4" schema

**Status:** analysis and proposal. **D1 decided on 17 Oct 2026: option B.** The target schema and migration plan are in `docs/SCHEMA_V4B.md`. Other decisions pending (§9). Nothing is implemented.
**Date:** 17 October 2026
**Input:** `Regulatory Intelligence ERD v4.html`, an interactive schema diagram (provided by the user from the Downloads folder; read at the user's request, not copied into the repository).
**Related:**
- `docs/DB_DESIGN.md`: the current design, authoritative today.
- `docs/MULTI_COUNTRY_SCHEMA.md` and `docs/CLASSIFICATION_DESIGN.md`: the multi-country work, migration 0006, applied.
- `docs/PIPELINE_WALKTHROUGH.md`: how the current pipeline fills the database.

**Request:** make the project follow the v4 database design.

---

## 1. What v4 is

An interactive diagram of a planned PostgreSQL + pgvector database (the same technology RegTrack uses):

- **28 tables, 45 foreign keys.**
- **10 phases:** Core, Classification, Impact, Change Monitor, Compliance, Alerts, Reports, Admin, Users, Assistant.
- **2 sample rows per table:** a real Thai standard (TIS 683-2562, inner tubes for motorcycles and mopeds), a real Thai review-queue record (TIS 1040-2541), and mock records (UNECE R155-2026 cybersecurity, India BNCAP-VT-27).
- **7 tables new in v4:** `regulation_authorities`, `users`, `regulation_watches`, `assistant_conversations`, `assistant_messages`, `assistant_message_citations`, `report_schedules`.
- **6 columns new in v4:** `regulation_changes.severity`, `regulation_changes.reviewed_at`, `alert_events.resolved_at`, and `raw_ingestion_records.classification_method` / `_verdict` / `_confidence`.
- **1 inferred table:** `document_chunks` is drawn from inference, because it is defined in `schema_v3.md`, which the diagram's author did not have.
- **6 review notes** at the bottom of the diagram (§5.1).

None of v4's tables exist in the RegTrack repository or database today.

**v4 tables by lane:**

| Lane | Tables |
|---|---|
| 1 | `regions`, `regulatory_authorities`, `impact_assessments`, `assistant_conversations`, `assistant_messages`, `assistant_message_citations` |
| 2 | `sources`, `regulation_authorities`, `raw_ingestion_records`, `ingestion_runs`, `documents`, `document_chunks` |
| 3 | `regulations`, `alert_events`, `alert_rules` |
| 4 | `regulation_changes`, `compliance_requirements`, `regulation_domains`, `regulation_systems`, `regulation_watches` |
| 5 | `teams`, `users`, `domains`, `systems`, `report_templates`, `reports`, `report_schedules`, `app_settings` |

---

## 2. The main difference

**v4 is designed around the portal: what users see and do. RegTrack is designed around the evidence: the files, what each document legally says, and how rules change over time.**

- v4's centre is one table, `regulations`. One regulation is **one row**, holding its title, status, impact, summary, recommended action, effective date, and classification result.
- RegTrack's centre is a chain: **file** (`file_object`) → **document** (`document`, with page ranges in `document_file`) → **links between documents** (`doc_relation`) → **rules with their history** (`mandate`).

This difference decides what each design can and cannot answer (§4).

---

## 3. Table-by-table mapping

| v4 table | Closest RegTrack table | Comment |
|---|---|---|
| `regions` | `country` | Same idea. v4 also has Europe, for UNECE and EU rules (RegTrack added the pseudo-country `UN` in 0006). |
| `regulatory_authorities` | text in `document.issuer` | **v4 better:** authorities as a proper list. |
| `regulation_authorities` | none | v4: several authorities per regulation, with a role (primary, co-issuer). |
| `sources` | `source` | **v4 better:** per-source `config` and `field_mapping` JSON, `scraper_key`, `sync_frequency_minutes`. |
| `ingestion_runs` | `crawl_run` | Same. |
| `raw_ingestion_records` | `file_sighting` | Similar. v4 adds the classification verdict, its confidence, and a `needs_review` queue. |
| `documents` | `file_object` + `document_file` | v4: one row per file of a regulation. **No required fingerprint, no page ranges.** |
| `regulations` | `document` + `document_review` | v4 stores portal opinions (impact, recommended action, detected change) on the regulation row. |
| `regulation_changes` | `change_event` | **v4 richer:** a before/after `diff`, severity, reviewing team, SLA due date. |
| `compliance_requirements` | `mandate` + `compliance_item` | v4 merges them and **loses the version history** (§4). |
| `domains` + `regulation_domains` | `domain` + `document.domains` array | v4 cleaner: a proper link table. |
| `systems` + `regulation_systems` | none | **New:** links rules to product systems (ADAS ECU, connectivity). |
| `impact_assessments` | calculated in the portal | v4 stores an exposure score per region and topic. |
| `teams`, `users`, `regulation_watches` | none (owners are free text) | **v4 better:** real people and teams; "watch this rule". |
| `alert_rules`, `alert_events` | `alert_rule` (events calculated on the fly) | v4 keeps a history of alerts sent, and whether they were resolved. |
| `report_templates`, `reports`, `report_schedules` | `report_log` | v4 richer: templates, stored reports, recurring schedules. |
| `assistant_conversations`, `assistant_messages`, `assistant_message_citations` | none (Ask AI keeps no history) | **v4 better:** chat history, with the sources each answer cited. |
| `document_chunks` | `chunk` | v4's definition is inferred, not specified. |
| `app_settings` | `app_setting` | Same (v4 stores values as JSON). |
| — | `doc_relation` | **Missing in v4:** links between documents (amends, extends a date, corrects, finalises a draft…). |
| — | `mandate` versions (`valid_from`, `valid_to`, `superseded_by`) | **Missing in v4:** rule history. |
| — | `document.family_key`, `version_seq`, `is_current` | **Missing in v4:** version families (AIS-038 → Rev.1 → Rev.2). |
| — | `vehicle_category`, `country_scope` | **Missing in v4:** vehicle types. |
| — | `quality_flag` | **Missing in v4:** only a `needs_review` status. |
| — | `local_class`, `vocab_term`, document language, year offset | **Missing in v4:** little support for local languages and calendars. |
| — | `requirement`, `requirement_document` (0005) | **Missing in v4:** the client's own requirement register. |

---

## 4. Assessment

### 4.1 What v4 does better (worth keeping in any outcome)

1. **Real users and teams:** owners, reviewers and watchers are people, not free text, so "who reviewed this, and when?" can be answered.
2. **Product systems** (ADAS ECU, connectivity…): engineers think in systems, so this makes impact clearer to them.
3. **Change details:** before → after difference, severity, review deadline (SLA), reviewer.
4. **Authorities as a list**, with one primary authority per regulation.
5. **AI assistant history with citations**, so an answer can be checked later.
6. **Report templates and schedules** (for example, the compliance gap report every month to the Compliance Team).
7. **Settings per source:** adding a website becomes partly configuration instead of code.
8. **Europe / UNECE as a region.**

### 4.2 What v4 is missing (risks)

Each item is a capability RegTrack has today, shown with a case from the current data:

| # | Today RegTrack can… | v4 as drawn can't, because… | Evidence in the current data |
|---|---|---|---|
| 1 | show **rules for a vehicle** ("my scooter"), one of the four views required by `CLAUDE.md` | no vehicle types (L1, L2, M1, N1) anywhere | 488 documents in scope by vehicle type; India's L2 = UNECE L3 |
| 2 | say **what rule applied on any date** | one `effective_date` per regulation; compliance requirements have only a `due_date`, so each change overwrites the last | the wheel-rim deadline (S.O. 1365(E) Table Sr.8(b)) has 4 versions: 2021, 2022, Jun 2023, Dec 2023 |
| 3 | show **which notice changed which** | no links between documents (`regulation_changes` records that a regulation changed, not which document changed it) | 5,172 links, e.g. S.O. 3896(E) extends dates in S.O. 1365(E) rows 8, 43, Table A 6, Table B 2 |
| 4 | split **one PDF into several documents** | no page ranges: one file = one regulation | 478 amendment parts split out of consolidated AIS files |
| 5 | catch **websites naming the wrong document** | the regulation code comes from the source's fields (`field_mapping`) | 33 title/content mismatches, e.g. a listing says GSR 954(E), the PDF is GSR 953(E) |
| 6 | store **each file once, by fingerprint, never changed** | `documents.checksum_sha256` optional (empty in both samples); files named by title; duplicates only prevented per (source, URL) | 2,274 seed files gave 2,018 unique; one PDF can have several sightings (file 1012 has 3) |
| 7 | track **version families** and the current version | no family or current-version fields | AIS revisions and amendments; 338 current documents |
| 8 | keep **warnings that settle themselves**, with evidence | only `processing_status = needs_review` | 1,383 quality flags; 114 resolved with recorded evidence |
| 9 | resume processing per file | processing status only on the raw record | `file_object.stage`: 1,632 chunked, 512 done |
| 10 | support **local languages and calendars** | only `title` + `raw_attributes.title_native` | Thai Buddhist years; Hindi/English pages; Thai and Malay clue words |

**Search vectors:** v4 uses `vector(1536)` on `documents.text_embedding`, `regulations.summary_embedding` and `document_chunks.embedding`.
- 1536 matches OpenAI-style embedding models; the project's local LM Studio setup uses 768 (`EMBED_DIM`).
- A single vector for a whole document (some files have 800+ pages) does not work well for search.

**Status mixes two things:** `regulations.status` mixes legal state (`proposed`) with workflow state (`tracked`, `under_review`). A final regulation can still be under review by the team, so these should be separate fields.

---

## 5. Problems inside v4

### 5.1 The diagram's own review notes (agreed)

1. `regulation_changes.reviewed_by` and `reports.approved_by` should point to `users`, but are not defined. Add `reviewed_by_user_id` and `reports.approved_by_user_id`.
2. `regulation_authorities` needs a composite primary key, and a partial unique index so that each regulation has only one `primary` authority. `regulations.authority_id` must equal that primary row.
3. `assistant_message_citations` has no key, and both targets can be empty. Add an `id`, a `CHECK (regulation_id IS NOT NULL OR document_chunk_id IS NOT NULL)`, and the retrieval `score`.
4. The review queue (`raw_ingestion_records`) records the AI's verdict but not the human decision. Add `reviewed_by_user_id`, `reviewed_at`, `review_decision`.
5. IDs inside `report_schedules.recipients` (JSON) are not checked. Move them to a link table if recipients become editable.
6. `document_chunks` is inferred. The real definition is in `schema_v3.md`.

### 5.2 Additional problems

7. **The same facts are stored twice:**
   - `regulations.domain_id` and `regulation_domains` (one topic vs many);
   - `regulations.authority_id` and `regulation_authorities`;
   - `documents.file_size_bytes` / `original_url` and the same values in `documents.metadata`.

   These copies will drift apart.
8. **`regulations.source_id` is optional**, while `documents.source_id` is required, so a regulation's origin is not always known.
9. **Impact is stored per region and topic only** (`impact_assessments`), not per product, system or vehicle type, so "how much does this affect our scooters?" cannot be stored.

### 5.3 Missing specification

- The diagram is not a full specification. Allowed values (CHECK lists), all constraints, indexes and defaults are only partly shown.
- `schema_v3.md` (referenced) and the v4 specification text are needed to build it exactly.

---

## 6. What switching to v4 involves

| Part | Change |
|---|---|
| Database | New migrations create the v4 tables; the current 25 tables are retired. |
| Pipeline (`regtrack/pipeline/`: classify, extract, link, mandates, chunk, search) | Rewritten to write v4's tables. |
| Crawlers (`regtrack/sources/`) | Adapted to `sources.config` / `field_mapping` and `raw_ingestion_records`. |
| API and portal (`regtrack/api/`, `dashboard/`) | All queries rewritten. The portal gains v4's new features: users, teams, watches, assistant history, report schedules. |
| Data | 2,066 documents moved into v4's tables, or rebuilt from the stored originals. |
| Tests | Mostly rewritten (76 today). |
| Project documents | `CLAUDE.md` and `docs/DB_DESIGN.md` updated to make v4 authoritative; the CLAUDE.md regression table re-measured. |

**Effort:** several weeks, in phases.

**Safety, whichever option is chosen:**
- The original PDFs (`data\raw`, 2,144 files) and the page text (`data\text`) are unaffected.
- The current database stays as a backup until the new one is proven: `data\snapshots\regtrack_2026-10-17.dump`, after 0006.
- Work happens on a branch; nothing is merged without approval.

---

## 7. Options

| Option | What you get | What is lost | Effort |
|---|---|---|---|
| **A. v4 exactly as drawn** | v4's structure and portal features | everything in §4.2: vehicle view, rule history, document links, file splitting, title checks, write-once storage, quality flags, local-language support | large |
| **B. v4 as the base, plus additions** (recommended if v4 is required) | v4's structure and portal features, **and** everything RegTrack does today | nothing | large, slightly more than A |
| **C. Keep RegTrack, add v4's portal tables** | the same capabilities as B, with today's table names | nothing | medium |

### 7.1 The additions for option B

Named in v4's style. Each one keeps a capability from §4.2:

| Addition | Keeps (§4.2 #) |
|---|---|
| `vehicle_categories` (per region, with the UNECE equivalent) + `regulation_vehicle_categories` + region scope | 1 |
| `requirement_versions` (`valid_from`, `valid_to`, `superseded_by`, implementation date) under `compliance_requirements` | 2 |
| `regulation_relations` (from, to, type, evidence sentence, unresolved target reference) | 3 |
| `document_parts` (regulation ↔ document, page range, role, best copy) | 4 |
| identity read from content, with the listing kept as a claim in `raw_ingestion_records` / `document_sightings`; mismatches become quality flags | 5 |
| `documents.checksum_sha256` required and unique, storage path by fingerprint, + `document_sightings` | 6 |
| `regulations.family_key`, `version_seq`, `is_current` (one current per family) | 7 |
| `quality_flags` | 8 |
| processing stage per document file | 9 |
| language fields, the region's year offset, and a per-region word list | 10 |
| `vector(768)` instead of `vector(1536)` (or configurable); vectors on chunks only | search |
| separate legal status (draft / final / superseded / withdrawn) and workflow status | status |
| the fixes in §5.1 and §5.2 | v4's own issues |

---

## 8. Recommendation

- **If following v4 is required: option B.** It follows v4's structure and adds about 6 tables and a few columns, so nothing RegTrack does today is lost.
- **Option A is not recommended.** It removes the vehicle view, which `CLAUDE.md` requires, and the rule history, which is the main value for compliance.
- **Option C gives the same capabilities with less work** if the v4 table names are not themselves a requirement.

---

## 9. Decisions and inputs needed

| # | Question | Notes |
|---|---|---|
| D1 | Option A, B or C? | Recommendation: B (or C if v4's names are not required) |
| D2 | Where does v4 come from, and who owns it? | Decides whether changes to v4 (the additions) need someone else's approval |
| D3 | Provide `schema_v3.md` and the v4 specification text | Needed to build from the real definitions, not from the diagram |
| D4 | Should the portal gain v4's new features (users, teams, watches, assistant history, report schedules)? | Changes the scope of the portal work |
| D5 | Move the existing 2,066 documents, or rebuild from the stored originals? | Moving is faster; rebuilding re-checks everything |
| D6 | Embedding size: 768 (current local model) or 1536 (as in v4)? | Changing later means re-embedding all chunks |
| D7 | Update `CLAUDE.md` and `docs/DB_DESIGN.md` to make v4 authoritative? | Required for options A and B |

---

## 10. Next steps (after the decisions)

1. Write the **final table list** for the chosen option: every table and column, its source (v4 / RegTrack / new), and its constraints.
2. Write the **mapping and data-move plan**: which current table and column goes where.
3. Get approval of steps 1–2.
4. Build in phases, on a branch, each phase tested before the next:
   1. Database: new migrations, on a copy first.
   2. Ingestion: sources, runs, raw records, documents.
   3. Classification and extraction: regulations, authorities, domains, systems.
   4. Links, rule history, compliance.
   5. Search and assistant.
   6. Alerts, reports, users and teams.
   7. Portal.
5. Measure against the regression numbers, then switch over. The old database stays as a backup.
