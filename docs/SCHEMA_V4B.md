# Target schema: v4 + RegTrack additions ("option B")

**Status:** plan for approval. Nothing is implemented. Decision **D1 = option B** taken on 17 October 2026 (`docs/V4_SCHEMA_ADOPTION.md`).
**Purpose:**
- the complete target table list: every table and column, where it comes from, and its rules;
- how today's data moves into it;
- the order of work.

**Legend for the "from" column:**

| Tag | Meaning |
|---|---|
| **v4** | as in the ERD v4 diagram |
| **v4 fix** | v4, changed to fix a problem listed in `V4_SCHEMA_ADOPTION.md` §5 |
| **B** | added to keep a capability RegTrack has today (`V4_SCHEMA_ADOPTION.md` §4.2) |
| **MC** | added for multi-country support (from migrations 0005 and 0006) |

---

## 0. Assumptions and open inputs

| # | Item | Status |
|---|---|---|
| D1 | Option B | **decided** |
| D2 | Origin and owner of ERD v4 | **open**: decides who approves the additions to v4 |
| D3 | `schema_v3.md` and the v4 specification text | **open**: this plan is built from the diagram; where the diagram shows no type or allowed values, this plan sets them. To check against the spec when it arrives. |
| D4 | Portal gains v4's features (users, teams, watches, assistant history, report schedules) | **assumed yes**; the tables are in this plan, the screens are a later phase (§4, phase 7) |
| D5 | Existing data is moved, not rebuilt | **assumed**; the mapping is in §3 |
| D6 | Search vectors: 768 numbers (`EMBED_DIM`) | **assumed**; v4 shows 1536 |
| D7 | `CLAUDE.md` and `docs/DB_DESIGN.md` updated to make this schema authoritative | **assumed**, after approval of this plan |

---

## 1. Design rules

These come from `CLAUDE.md` and the v4 review, and apply to every table:

1. **Surrogate integer `id`** on every entity table, as in v4. Natural codes (`IN`, `MORTH_API`, `SO-3896(E)-2022`) are `UNIQUE` columns.
2. **Region on everything filterable**: `region_id` replaces today's text `country` column. The single country filter (`regtrack/country.py`) keeps working through `regions.code`.
3. **Originals are write-once**: a file is identified by its SHA-256, which is required and unique, and is stored at `STORAGE_DIR/<sha[:2]>/<sha>.<ext>`.
4. **Identity comes from content**: a website's listing is a claim (`raw_ingestion_records`). The regulation's code is read from the document text.
5. **History is never overwritten**: a rule change closes the old version and adds a new one (`requirement_versions`).
6. **One fact, one place**: no column duplicates a link table or another column (fixes v4 §5.2).
7. **Legal state and team workflow are separate fields.**
8. **Vectors only on text pieces** (`document_chunks`), `vector(768)`.
9. **Lists that differ per country are rows, not code**: vehicle categories, scope, words, document classes.

---

## 2. Tables

40 tables in 8 groups:

| Group | Tables | Count |
|---|---|---|
| Reference | `regions`, `regulatory_authorities`, `sources`, `domains`, `systems`, `vehicle_categories`, `region_scope`, `region_terms`, `document_classes`, `teams`, `users`, `app_settings` | 12 |
| Ingestion | `ingestion_runs`, `raw_ingestion_records`, `documents` | 3 |
| Regulations | `regulations`, `regulation_authorities`, `regulation_domains`, `regulation_systems`, `regulation_vehicle_categories`, `document_parts`, `regulation_relations` | 7 |
| Search | `document_chunks` | 1 |
| Compliance | `compliance_requirements`, `requirement_versions`, `impact_assessments` | 3 |
| Monitoring | `regulation_changes`, `quality_flags`, `alert_rules`, `alert_events`, `regulation_watches` | 5 |
| Reports and assistant | `report_templates`, `reports`, `report_schedules`, `assistant_conversations`, `assistant_messages`, `assistant_message_citations` | 6 |
| Client register | `client_requirements`, `client_requirement_regulations` | 2 |
| Housekeeping | `schema_migrations` | 1 |

**Versus v4's 28 tables:**
- **All 28 are kept.**
- **6 are added to keep RegTrack's capabilities (B):** `vehicle_categories`, `regulation_vehicle_categories`, `document_parts`, `regulation_relations`, `requirement_versions`, `quality_flags`.
- **4 are added for multi-country (MC):** `region_scope`, `region_terms`, `document_classes`, plus the client register pair.
- **2 of today's tables are folded into v4's:** `document_review` into `regulations`, and `compliance_item` into `compliance_requirements`.

### 2.1 Reference

#### `regions` (v4 + MC)
One row = one country or region (IN, TH, MY, EU, UN).

| Column | Type | From | Rule / meaning |
|---|---|---|---|
| id | int | v4 | PK |
| code | varchar(10) | v4 | UNIQUE. `IN`, `TH`, `MY`, `EU`, `UN` |
| slug | varchar(50) | v4 | UNIQUE |
| name | varchar(100) | v4 | |
| timezone | varchar(50) | v4 | e.g. `Asia/Kolkata`; used by the scheduler |
| metadata | jsonb | v4 | free settings |
| is_active | bool | v4 | default true |
| languages | text[] | MC | first = language the pipeline reads, e.g. `{en,hi}`, `{th,en}` |
| year_offset | int | MC | local year − offset = CE year (TH 543) |
| currency | varchar(3) | MC | `INR`, `THB`, `MYR` |
| created_at, updated_at | timestamptz | v4 | |

#### `regulatory_authorities` (v4)
One row = one issuing body (MoRTH, ARAI, BIS, TISI, DLT, JPJ, UNECE…).

| Column | Type | From | Rule / meaning |
|---|---|---|---|
| id | int | v4 | PK |
| region_id | int | v4 | FK `regions`, nullable (supranational) |
| code | varchar(20) | v4 | UNIQUE. `MORTH`, `ARAI`, `TISI` |
| name | varchar(150) | v4 | |
| website_url | varchar(500) | v4 | |

#### `sources` (v4 + B)
One row = one website or folder that is read.

| Column | Type | From | Rule / meaning |
|---|---|---|---|
| id | int | v4 | PK |
| region_id | int | v4 | FK `regions`, NOT NULL |
| authority_id | int | v4 | FK `regulatory_authorities`, nullable |
| code | varchar(30) | B | UNIQUE. `MORTH_API`, `ARAI_AIS`, `LOCAL_SEED` (used by the CLI and the logs) |
| name | varchar(150) | v4 | UNIQUE with region_id |
| base_url | varchar(500) | v4 | |
| scraper_key | varchar(50) | v4 | which reading program: `morth`, `arai`, `tisi_api`; NULL = no program (seed folder) |
| config | jsonb | v4 | program settings (URLs, filters, keywords) |
| field_mapping | jsonb | v4 | how listing fields map to claims (title, date, code) |
| is_active | bool | v4 | |
| sync_frequency_minutes | int | v4 | 0 = never automatically (today `schedule_hours` × 60) |
| last_synced_at | timestamptz | v4 | |
| last_sync_status | varchar(20) | v4 | `success`, `warning`, `failed` |

#### `domains` (v4)
One row = one topic (braking, emissions, number plates…).

| Column | Type | From | Rule / meaning |
|---|---|---|---|
| id | int | v4 | PK |
| code | varchar(30) | v4 | UNIQUE. `BRAKING`, `NUMBER_PLATES` |
| name | varchar(100) | v4 | |
| description | text | v4 | |

Keywords move to `region_terms` (kind `domain`).

#### `systems` (v4)
One row = one product system (`ADAS_ECU`, `CONNECTIVITY`…). Columns: `id` PK, `code` UNIQUE, `name`.

#### `vehicle_categories` (B)
One row = one vehicle type of one region, with its UNECE meaning.

| Column | Type | From | Rule / meaning |
|---|---|---|---|
| id | int | B | PK |
| region_id | int | B | FK `regions`; region `UN` holds the UNECE categories |
| code | varchar(20) | B | UNIQUE with region_id. `L2`, `M1`, `E_RICKSHAW`, `รย.1` |
| label | varchar(150) | B | |
| un_codes | text[] | B | UNECE equivalents, e.g. India L2 → `{L3}` |

#### `region_scope` (MC)
One row = one vehicle category a region tracks. PK (`region_id`, `vehicle_category_id`), both FK.

#### `region_terms` (MC)
One row = one word with a meaning, in one language (today's `vocab_term`).

| Column | Type | From | Rule / meaning |
|---|---|---|---|
| id | int | MC | PK |
| kind | varchar(20) | MC | `vehicle_category`, `domain`, `doc_type`, `doc_role`, `status` |
| code | varchar(50) | MC | the meaning (category code, domain code…) |
| region_id | int | MC | FK, nullable = every region |
| language | varchar(5) | MC | `en`, `th`, `ms`, `hi` |
| term | text | MC | UNIQUE NULLS NOT DISTINCT (kind, code, region_id, language, term) |

#### `document_classes` (MC)
One row = one local document class and its common meaning (today's `local_class`).
- PK (`region_id`, `code`).
- `doc_type` NOT NULL.
- `doc_role` nullable (NULL = decided per regulation).
- `sub_type`.
- The allowed values are the lists in `docs/CLASSIFICATION_DESIGN.md` §3.

#### `teams` (v4)
Columns: `id` PK, `code` UNIQUE, `name`.

#### `users` (v4)
Columns: `id` PK, `email` UNIQUE, `name`, `team_id` FK nullable, `role`, `is_active`, `created_at`.

#### `app_settings` (v4)
Columns: `key` PK, `value` jsonb.

### 2.2 Ingestion

#### `ingestion_runs` (v4 + B)
One row = one visit to a source (today's `crawl_run`).

| Column | Type | From | Rule / meaning |
|---|---|---|---|
| id | bigint | v4 | PK |
| source_id | int | v4 | FK, NOT NULL |
| started_at, finished_at | timestamptz | v4 | |
| documents_found | int | v4 | rows seen |
| changes_found | int | v4 | new files |
| status | varchar(20) | v4 | CHECK `running`, `success`, `warning`, `failed` |
| error_message | text | v4 | |
| stats | jsonb | B | full counts: seen, known, new_listings, new_files, errors, skipped, gone |
| log | text | B | error notes |

#### `raw_ingestion_records` (v4 + v4 fix + B)
One row = one time a source listed an item: **the claim** (today's `file_sighting`).

| Column | Type | From | Rule / meaning |
|---|---|---|---|
| id | bigint | v4 | PK |
| source_id | int | v4 | FK, NOT NULL |
| ingestion_run_id | bigint | B | FK `ingestion_runs`, nullable |
| document_id | bigint | B | FK `documents` (the file it led to), nullable until downloaded |
| external_ref | varchar(500) | v4 | the source's own key; UNIQUE (source_id, external_ref, document_id) |
| source_url | varchar(1000) | B | download link |
| listing_title | text | B | title as listed (a claim) |
| listing_date | date | B | date as listed (a claim) |
| listing_category | text | B | |
| payload | jsonb | v4 | the full original listing |
| processing_status | varchar(20) | v4 | CHECK `new`, `downloaded`, `processed`, `needs_review`, `skipped`, `failed` |
| classification_method | varchar(30) | v4 | `rules`, `category`, `keyword_llm`, `llm` |
| classification_verdict | bool | v4 | relevant (vehicle regulation) or not |
| classification_confidence | numeric(4,3) | v4 | |
| regulation_id | bigint | v4 | FK, nullable: the main regulation it was promoted to |
| reviewed_by_user_id | int | v4 fix | FK `users`, nullable |
| reviewed_at | timestamptz | v4 fix | |
| review_decision | varchar(20) | v4 fix | `promoted`, `rejected` |
| first_seen_at, last_seen_at, gone_at | timestamptz | B | today's `seen_at`, `last_seen_at`, `gone_at` |

#### `documents` (v4 + B)
One row = one stored file (today's `file_object`).

| Column | Type | From | Rule / meaning |
|---|---|---|---|
| id | bigint | v4 | PK |
| region_id | int | B | FK |
| checksum_sha256 | char(64) | v4 → **required** | **NOT NULL UNIQUE**: one row per file content |
| storage_path | varchar(500) | v4 | `…/data/raw/<sha[:2]>/<sha>.<ext>` |
| file_name | varchar(255) | v4 | name as first downloaded (information only) |
| original_url | varchar(1000) | v4 | first download URL (all URLs are in `raw_ingestion_records`) |
| file_ext, mime_type | varchar | v4 | |
| file_size_bytes | bigint | v4 | |
| download_status | varchar(30) | v4 | |
| downloaded_at | timestamptz | v4 | |
| metadata | jsonb | v4 | PDF metadata only; **no copies of size or URL** (v4 fix) |
| page_count | int | B | |
| text_layer | bool | B | |
| scanned_pages | int[] | B | |
| ocr_engine | varchar(30) | B | |
| ocr_confidence | numeric(4,3) | B | |
| language_mix | jsonb | B | share of each language |
| stage | varchar(20) | B | the processing queue: CHECK `downloaded`, `text`, `classified`, `parsed`, `linked`, `chunked`, `embedded`, `done`, `failed` |
| stage_error | text | B | |

**Removed from v4:**
- `regulation_id`: replaced by `document_parts`, because one file can hold several regulations.
- `source_id`: a file can come from several sources; they are in `raw_ingestion_records`.
- `extracted_text`: page text stays in `data/text/<sha>.jsonl`.
- `text_embedding`: vectors are on chunks only.

### 2.3 Regulations

#### `regulations` (v4 + v4 fix + B + MC)
One row = one regulation (today's `document`, plus today's `document_review`).

| Column | Type | From | Rule / meaning |
|---|---|---|---|
| id | bigint | v4 | PK |
| region_id | int | v4 | FK, NOT NULL |
| external_code | varchar(80) | v4 | the ID **read from the content**: `SO-3896(E)-2022`; **UNIQUE (region_id, external_code)** (v4's (source_id, external_code) dropped: the same regulation comes from several sources) |
| authority_id | int | v4 | FK `regulatory_authorities`, nullable; must equal the `primary` row in `regulation_authorities` |
| title | varchar(500) | v4 | English title |
| title_native | text | MC | title in the official language, when not English (v4 had it in `raw_attributes`) |
| summary | text | v4 | one-line subject |
| local_class | varchar(40) | B | the region's own class (today's `doc_class`); FK (region_id, local_class) → `document_classes` |
| doc_type | varchar(20) | MC | `LAW`, `REGULATION`, `TECHNICAL_STANDARD`, `PROCEDURE`, `GUIDANCE`, `REFERENCE`, `OFF_TOPIC`, `UNKNOWN` |
| doc_role | varchar(20) | MC | `BASE`, `AMENDMENT`, `CORRIGENDUM`, `EXTENSION`, `EXEMPTION`, `REPEAL`, `CONSOLIDATION`, `ANNEX`, `INTERPRETATION` |
| legal_force | varchar(20) | MC | `MANDATORY`, `VOLUNTARY`, `INFORMATIVE`, `UNKNOWN` |
| legal_status | varchar(20) | v4 fix | `draft`, `final`, `superseded`, `withdrawn` (v4's `proposed` = `draft`) |
| workflow_status | varchar(20) | v4 fix | `tracked`, `under_review`, `impact_analysis`, `action_required` (team-set or derived) |
| impact_level | varchar(10) | v4 | `high`, `medium`, `low` |
| impact_basis | varchar(10) | B | `rules` or `team` |
| owner_team_id | int | B | FK `teams` (today's free-text review owner) |
| review_note | text | B | today's `document_review.note` |
| recommended_action | text | v4 | |
| detected_change | text | v4 | |
| local_type | varchar(30) | MC | `S.O.`, `G.S.R.`, `AIS`, `กฎกระทรวง` |
| series, number | varchar | B | as read |
| year | int | B | CE year |
| part, revision, amendment_no, corrigendum_no | | B | for standards |
| family_key | varchar(80) | B | all versions of the same thing |
| version_seq | int | B | |
| is_current | bool | B | **one current per (region_id, family_key)**: partial unique index |
| published_date | date | v4 | date of issue (today's `doc_date`) |
| published_date_precision | varchar(5) | B | `day`, `month`, `year` |
| effective_date | date | v4 | when it takes effect, if stated |
| nature | varchar(15) | B | `technical`, `administrative`, `procedural` |
| usage | text[] | B | private / transport |
| powertrains | text[] | B | |
| in_scope | bool | B | derived from `region_scope` |
| language | varchar(5) | MC | language of the text that was read |
| relevance | jsonb | B | automotive score and reason |
| data | jsonb | B | details for this class, validated against its Pydantic model |
| extraction | jsonb | B | who filled `data`, confidence, AI pending |
| raw_attributes | jsonb | v4 | attributes from the source |
| source_url | varchar(1000) | v4 | main public link |
| classification_method | varchar(30) | v4 | `rules`, `llm` |
| classification_confidence | numeric(4,3) | v4 | |
| first_detected_at | timestamptz | v4 | |
| created_at, updated_at | timestamptz | B | |

**Removed from v4:**
- `source_id`: sources are in `raw_ingestion_records`, and one regulation can come from several.
- `domain_id`: duplicated `regulation_domains`; a "primary" flag on the link replaces it.
- `summary_embedding`: vectors are on chunks only.
- `status`: split into `legal_status` and `workflow_status`.

#### `regulation_authorities` (v4 fix)
- PK (`regulation_id`, `authority_id`).
- `role`: `primary` or `co_issuer`.
- Partial unique index on (`regulation_id`) WHERE role = `primary`.

#### `regulation_domains` (v4 + B)
- PK (`regulation_id`, `domain_id`).
- `is_primary` bool, with one primary per regulation (partial unique).

#### `regulation_systems` (v4)
PK (`regulation_id`, `system_id`).

#### `regulation_vehicle_categories` (B)
- PK (`regulation_id`, `vehicle_category_id`).
- The UNECE meaning comes through `vehicle_categories.un_codes`.

#### `document_parts` (B)
One row = one regulation's pages inside one file (today's `document_file`).

| Column | Type | From | Rule / meaning |
|---|---|---|---|
| regulation_id | bigint | B | FK, PK part |
| document_id | bigint | B | FK, PK part |
| page_from | int | B | PK part |
| page_to | int | B | |
| language_pages | jsonb | B | `{"hi":[1,1],"en":[2,2]}` |
| part_label | varchar(60) | B | |
| role | varchar(25) | v4 + B | `main` (v4: `standard` / `regulation`), `consolidated_segment`, `annex_table`, `historical_copy`, `other_language_only`, `translation` |
| is_best_copy | bool | B | one best copy per regulation |

#### `regulation_relations` (B)
One row = one link between regulations (today's `doc_relation`).

| Column | Type | From | Rule / meaning |
|---|---|---|---|
| id | bigint | B | PK |
| from_regulation_id | bigint | B | FK, NOT NULL |
| to_regulation_id | bigint | B | FK, nullable until the target arrives |
| to_ref | varchar(120) | B | the target's code; CHECK one of the two is set |
| type | varchar(20) | B | `amends`, `corrects`, `revises`, `supersedes`, `finalises`, `extends_date`, `exempts`, `mandates`, `inserts_row`, `substitutes_row`, `omits_row`, `annex_of`, `part_of`, `interprets`, `references`, `same_as`, `adopts`, `equivalent_to`, `repeals` |
| details | jsonb | B | rows, old and new dates |
| evidence | text | B | the exact sentence |
| page | int | B | |
| confidence | numeric(3,2) | B | |
| method | varchar(10) | B | `regex`, `file_no`, `llm`, `manual` |
| requires_reapproval | bool | B | |

### 2.4 Search

#### `document_chunks` (v4, completed from the inferred version)
One row = one clause-sized piece of text.

| Column | Type | From | Rule / meaning |
|---|---|---|---|
| id | bigint | v4 | PK |
| document_id | bigint | v4 | FK `documents` (the file) |
| regulation_id | bigint | B | FK `regulations`; UNIQUE (regulation_id, chunk_index) |
| chunk_index | int | v4 | |
| clause_no, heading | text | B | |
| page_from, page_to | int | B | |
| language | varchar(5) | B | |
| is_boilerplate | bool | B | |
| content | text | v4 | |
| embedding | vector(768) | v4 (size D6) | HNSW index |
| tsv | tsvector | MC | keyword index per language |
| region_id, doc_type, legal_status, is_current, in_scope, year, vehicle_category_ids, domain_ids | | B | filter copies of the regulation, for fast search |

### 2.5 Compliance

#### `compliance_requirements` (v4 + v4 fix + B)
One row = one rule a region imposes, across all its versions (today's `mandate_key`, plus today's `compliance_item`).

| Column | Type | From | Rule / meaning |
|---|---|---|---|
| id | bigint | v4 | PK |
| region_id | int | B | FK, NOT NULL |
| requirement_code | varchar(120) | v4 | e.g. `SO-1365(E)-2004 Table Sr.8(b)`; UNIQUE (region_id, requirement_code) |
| regulation_id | bigint | v4 → **nullable** | the legal basis document, if stored (the 2004 master notice is not) |
| domain_id | int | v4 → **nullable** | |
| owner_team_id | int | v4 → **nullable** | unassigned until the team picks it up |
| owner_user_id | int | v4 fix | FK `users` |
| status | varchar(20) | v4 | `open`, `in_progress`, `compliant`, `not_applicable` |
| due_date | date | v4 | team override; default = the current version's implementation date |
| evidence_links | jsonb | v4 | |
| note | text | B | |
| updated_at | timestamptz | B | |

#### `requirement_versions` (B)
One row = one version of a rule (today's `mandate`). Never updated in place.

| Column | Type | From | Rule / meaning |
|---|---|---|---|
| id | bigint | B | PK |
| requirement_id | bigint | B | FK `compliance_requirements` |
| source_regulation_id | bigint | B | FK: the notice that wrote this version |
| legal_basis | text | B | |
| subject | text | B | |
| standard_refs | text[] | B | `IS 9436:2018` |
| standard_regulation_ids | bigint[] | B | those standards, if stored |
| vehicle_category_ids | int[] | B | who it applies to |
| conditions | jsonb | B | e.g. `{"engine_cc":{"lte":50}}` |
| model_scope | varchar(25) | B | `new_models`, `existing_models`, `all`, `registered_vehicles` |
| usage, powertrains | text[] | B | |
| date_of_notification, effective_date, implementation_date | date | B | |
| implementation_rule | text | B | |
| is_draft | bool | B | |
| valid_from, valid_to | date | B | the period this version was the law; CHECK valid_to ≥ valid_from |
| superseded_by | bigint | B | FK self |
| recorded_at | timestamptz | B | |

#### `impact_assessments` (v4 + v4 fix)
v4 columns, plus `vehicle_category_id` and `system_id` (both nullable), so impact can be stored per product dimension. The unique key becomes (region_id, domain_id, vehicle_category_id, system_id), with NULLs not distinct.

### 2.6 Monitoring

#### `regulation_changes` (v4 + v4 fix + B)
One row = one detected change (today's `change_event`).

| Column | Type | From | Rule / meaning |
|---|---|---|---|
| id | bigint | v4 | PK |
| region_id | int | B | FK, NOT NULL |
| regulation_id | bigint | v4 → **nullable** | 15 of today's events point to retired documents |
| requirement_version_id | bigint | B | FK, for date changes |
| change_type | varchar(30) | v4 | `new_document`, `new_amendment`, `new_revision`, `corrigendum`, `draft_published`, `draft_finalised`, `implementation_date_changed`, `mandate_superseded`, `file_reissued`, `listing_removed` |
| severity | varchar(10) | v4 | |
| detected_at | timestamptz | v4 | |
| summary | text | v4 | |
| diff | jsonb | v4 | before / after |
| details | jsonb | B | who wrote the summary, etc. |
| review_status | varchar(20) | v4 | `pending`, `reviewed`; today's `auto` / `needs_check` / `confirmed` map to pending / pending / reviewed |
| reviewed_by_team_id | int | v4 | FK |
| reviewed_by_user_id | int | v4 fix | FK |
| reviewed_at | timestamptz | v4 | |
| sla_due_at | timestamptz | v4 | detected_at + `review_sla_days` |

#### `quality_flags` (B)
One row = one warning (today's `quality_flag`).
- Columns: `id`, `entity` (`document`, `regulation`, `requirement_version`), `entity_id`, `rule`, `details`, `created_at`, `resolved_at`.
- Partial index on open flags.

#### `alert_rules` (v4 + B)
- v4 columns: `scope_region_id`, `scope_domain_id`, `condition` jsonb, `is_enabled`, `notify_team_id`.
- Plus `scope_vehicle_category_id` (B), because today's alerts can be scoped to a vehicle type.

#### `alert_events` (v4)
As in v4: `rule_id`, `regulation_id` nullable, `triggered_at`, `message`, `is_resolved`, `resolved_at`.

#### `regulation_watches` (v4 + v4 fix)
- As in v4.
- Plus CHECK exactly one of `watcher_user_id` / `watcher_team_id`.
- Plus UNIQUE (regulation_id, watcher_user_id, watcher_team_id), with NULLs not distinct.

### 2.7 Reports and assistant

| Table | Changes from v4 |
|---|---|
| `report_templates` | as in v4 |
| `reports` | + `approved_by_user_id` FK (v4 fix) |
| `report_schedules` | as in v4 (recipients in JSON for now, v4 note 5) |
| `assistant_conversations` | as in v4 |
| `assistant_messages` | as in v4 |
| `assistant_message_citations` | + `id` PK, + `score`, + CHECK one target is set (v4 fix); `document_chunk_id` points to `document_chunks` |

### 2.8 Client register (MC, from migration 0005)

- **`client_requirements`**: today's `requirement`, with `region_id` instead of `country`.
- **`client_requirement_regulations`**: today's `requirement_document`, with `regulation_id` instead of `document_id`.

---

## 3. How today's data moves

Every row of today's database has a destination; nothing is dropped. Counts as of 17 October 2026.

| Today (rows) | Becomes | Notes |
|---|---|---|
| `country` (4) | `regions` | + `EU` row |
| `source` (14) | `sources` + `regulatory_authorities` | `schedule_hours` × 60 → `sync_frequency_minutes`; the issuing body becomes an authority row |
| `vehicle_category` (39) | `vehicle_categories` | region via code |
| `country_scope` (5) | `region_scope` | |
| `domain` (19) | `domains` + `region_terms` | keywords → terms |
| `vocab_term` (144) | `region_terms` | |
| `local_class` (35) | `document_classes` | |
| `app_setting` (4) | `app_settings` | values → JSON |
| `crawl_run` (31) | `ingestion_runs` | `ok` / `partial` / `failed` → `success` / `warning` / `failed` |
| `file_sighting` (5,970) | `raw_ingestion_records` | `source_item_id` → `external_ref`; `seen_at` → `first_seen_at` |
| `file_object` (2,144) | `documents` | `sha256` → `checksum_sha256`; same file paths, nothing moves on disk |
| `document` (2,066) | `regulations` | `canonical_id` → `external_code`; `doc_class` → `local_class`; `status` → `legal_status`; `issuer` → `authority_id` + `regulation_authorities`; `domains[]` → `regulation_domains`; `vehicle_categories[]` → `regulation_vehicle_categories`; `official_title` → `title` |
| `document_review` (0) | `regulations` | `workflow_status`, `impact_level`, owner, note |
| `document_file` (2,552) | `document_parts` | `english_page_*` kept in `language_pages` |
| `doc_relation` (5,172) | `regulation_relations` | `method` `qwen` → `llm` |
| `mandate` (178) | `compliance_requirements` (one per `mandate_key`) + `requirement_versions` (178) | ids kept, so `superseded_by` stays valid |
| `compliance_item` (0) | `compliance_requirements` | status values lower-case |
| `chunk` (148,342) | `document_chunks` | embeddings are empty today, so there is nothing to convert |
| `change_event` (140) | `regulation_changes` | `review_status` mapped; `sla_due_at` computed |
| `quality_flag` (1,383) | `quality_flags` | entity `document` → `regulation`, `mandate` → `requirement_version` |
| `alert_rule` (4) | `alert_rules` | `scope` code → `scope_vehicle_category_id`; `condition` + `param` → `condition` JSON |
| `report_log` (0) | `reports` | |
| `requirement` (15), `requirement_document` (0) | `client_requirements`, `client_requirement_regulations` | |
| — | `teams`, `users`, `systems`, `impact_assessments`, `alert_events`, `regulation_watches`, `report_templates`, `report_schedules`, `assistant_*` | start empty, or seeded with the portal's defaults (report templates, default team "Regulatory Affairs Team") |

**How the move is done:**
- One migration (`0007_v4_schema.sql`) creates the new tables **next to** the old ones and copies the data across.
- The old tables are dropped only in a later migration, after the code has switched and the checks pass.
- **Checks:**
  - every count above matches;
  - every regulation keeps its files, pages, links, rule versions and pieces;
  - the "rules for a vehicle on a date" answers are identical before and after, for a fixed list of cases (the wheel-rim history included).
- **Backup before applying:** `regtrack.cli snapshot-export`.

---

## 4. Order of work

Each phase ends with tests, ruff, a phase report in `reports/`, and a commit on a branch. Nothing is merged without approval.

| Phase | Work | Result |
|---|---|---|
| 0 | Approve this plan; answer D2, D3 | |
| 1 | Migration 0007: create the v4B tables next to the old ones, copy the data, run the checks (on a copy first) | both schemas present, data identical |
| 2 | Ingestion code → `sources`, `ingestion_runs`, `raw_ingestion_records`, `documents` | crawls and the seed import write v4B |
| 3 | Classification and extraction → `regulations`, authorities, domains, vehicle categories, `document_parts` | |
| 4 | Linking → `regulation_relations`, `compliance_requirements`, `requirement_versions` | |
| 5 | Search → `document_chunks`; Ask AI writes `assistant_*` | |
| 6 | Monitoring → `regulation_changes`, `quality_flags`, `alert_events` | |
| 7 | API and portal on v4B, plus new screens: users and teams, watches, assistant history, report schedules | |
| 8 | Regression check against the `CLAUDE.md` numbers; migration 0008 drops the old tables; `CLAUDE.md` and `docs/DB_DESIGN.md` updated | switch-over complete |

**Safety throughout:**
- The original PDFs and page text are never touched.
- The old tables stay until phase 8.
- A backup is taken before every migration.

---

## 5. To decide while reviewing

1. Is anything in §2 named or shaped differently in the v4 specification text (D3)?
2. Are the extra review fields on `regulations` (`workflow_status`, `impact_basis`, `owner_team_id`, `review_note`) acceptable, or should the team's review stay in a separate table?
3. Should vehicle categories on rule versions be integer IDs (`vehicle_category_ids`, as planned) or codes, as today?
4. Seed values for `teams`, `systems` and `report_templates`: use the ones in the v4 diagram (Cybersecurity, Compliance, Regulatory Affairs, ADAS ECU, Connectivity, Executive Summary, Compliance Gap)?
