# Database schema for every country

**Status:** proposal, for decision. Nothing in this file is implemented yet. The migration in §5 is a sketch, not applied.
**Date:** 16 October 2026
**Goal:** the database should work for **any** country (India, Thailand and Malaysia first, others later) without adding country-specific tables or columns each time.
**Related:**
- `docs/CLASSIFICATION_DESIGN.md`: the four country-neutral classification fields used here.
- `docs/DB_DESIGN.md`: the current, India-first design, authoritative until this is accepted.
- Migrations `0001`–`0005`: what exists today.

---

## 1. Principles

1. **Universal core, local detail.** Every table holds the same kind of facts for every country. What only one country has (Indian G.S.R. numbers, Thai Buddhist years, Malaysian P.U.(A) series) goes into *local* fields or `data` JSONB, never into new tables.
2. **Vocabularies are data, not code.** Lists that differ by country (vehicle categories, synonyms, keywords, scope) live in lookup tables keyed by country and language, so adding a country means **adding rows, not changing the schema**.
3. **Store what the document says, plus a common meaning.** A Thai document's own category or date stays as written; a mapped, comparable value sits next to it.
4. **Any language.** No column, index or default assumes English or Hindi.
5. **Country on everything that can be filtered alone.** Tables that are queried or keyed without a document (mandates, compliance items, alerts, events) carry `country` themselves.
6. **Nothing breaks for India.** New columns are added next to old ones. Old ones are removed only after the code no longer uses them, in a later migration.

---

## 2. Audit of today's schema

✅ = already country-neutral · ⚠️ = works, but assumes India · ❌ = will be wrong for other countries

| Table / item | Today | Status | Problem | Proposal (§4) |
|---|---|---|---|---|
| `country` | code, name, year_offset, language (0005) | ⚠️ | one language only (Malaysia and India use two); no time zone or currency | add `languages[]`, `timezone`, `currency` |
| `vehicle_category` | one global list; India's meaning of codes; English synonyms; global `in_scope` | ❌ | **India's `L2` (motorcycle > 45 km/h) is UNECE's `L3`**; UNECE `L2` is a three-wheeled moped. Thailand and Malaysia use UNECE meanings and their own registration classes (Thai รย. classes). Synonyms are English only. `in_scope` is India's client scope. | per-country categories with a mapping to UNECE; synonyms per language; scope per country |
| `domain` | 19 topics; English, India-specific keywords (Bharat Stage, HSRP, FASTag, rupees, BH series) | ⚠️ | topic codes are mostly universal; keywords are not | keep the codes; keywords per country and language; `hsrp` becomes a universal `number_plates` (D7) |
| `source` | has `country` (0005) | ✅ | | optional: `language`, `access` (api / html / browser) |
| `crawl_run`, `file_sighting` | | ✅ | | none |
| `file_object` | has `country`; `language_mix` keys `en`, `hi`, `hi_legacy_font` | ⚠️ | language keys are India's | `language_mix` becomes `{lang: share}` for any language; India's legacy-font flag moves under a `notes` key |
| `document.canonical_id` | `UNIQUE` across all countries | ⚠️ | two countries could have the same ID format | unique per `(country, canonical_id)` |
| `document` identity fields | `series`, `number`, `year`, `part`, `revision`, `amendment_no`, `corrigendum_no` | ✅ | general enough (G.S.R., P.U.(A), มอก. all fit `series`) | keep; `year` is always the CE year |
| `document` classification | `doc_class` (India list) | ❌ | see `CLASSIFICATION_DESIGN.md` | add `doc_type`, `doc_role`, `legal_force`, `sub_type`, `local_type` |
| `document` titles and dates | `official_title`, `subject`, `doc_date` | ⚠️ | a Thai title is in Thai, and users need English; Thai law separates issue date and effective date | add `language`, `title_en`, `effective_date` |
| `document.vehicle_categories` | India's codes | ❌ | not comparable across countries (see `vehicle_category`) | keep local codes; add `vehicle_categories_un` (UNECE meaning) |
| `document.in_scope` | uses India's scope | ⚠️ | each country or client tracks different categories | computed from the country's scope (`country_scope`) |
| `document_one_current` index | `(family_key)` | ⚠️ | two countries could share a family key | `(country, family_key)` |
| `document_file` | `english_page_from/to`; role `hindi_only` | ❌ | "English pages" makes no sense for a Thai-only document | add `language_pages JSONB` (`{"th":[1,4],"en":[5,8]}`); role `other_language_only`, `translation` |
| `doc_relation` | types: amends … references; method `regex`, `file_no`, `qwen` | ⚠️ | no way to say "this TIS adopts UN R 13H"; method names one model | add types `adopts`, `equivalent_to`, `repeals`; method `llm`, `manual` |
| `mandate` | no country; `mandate_key` global | ❌ | `compliance_item` is keyed by `mandate_key` alone, so two countries could collide | add `country`; key `(country, mandate_key)`; add `vehicle_categories_un` |
| `chunk` | `language` default `'en'`; full-text index with the **English** dictionary; `vector(768)` | ❌ | English stemming fails on Thai (no spaces between words) and Malay; the embedding model must handle all languages | add `country`, `doc_type`; real `language`; a `tsv` column filled per language; one **multilingual** embedding model |
| `change_event` | no country (found through `document_id`) | ⚠️ | events whose document was retired have no country | add `country` |
| `quality_flag` | | ✅ | | none |
| `document_review` | | ✅ | follows the document | none |
| `compliance_item` | primary key `mandate_key` | ❌ | collides across countries | primary key `(country, mandate_key)` |
| `alert_rule` | `scope` = 'All categories' / L1 / L2 / M1 / N1 | ❌ | India's categories hard-coded in the values | add `country`; scope refers to `country_scope` |
| `report_log` | `scope` text | ⚠️ | | add `country` |
| `app_setting` | global key/value | ✅ | | per-country values use keys like `TH.default_owner` (no change needed) |
| `requirement`, `requirement_document` (0005) | have `country` | ✅ | | none |

**Code that also assumes India** (to change with the schema, not part of the migration):

| Where | Assumption |
|---|---|
| `scheduler.py` | `timezone="Asia/Kolkata"` → use `country.timezone` |
| `api/portal.py` | `CATEGORIES = ["L1","L2","M1","N1"]` → use `country_scope` |
| `validators.py` | `IN_SCOPE_CATEGORIES` constant → use `country_scope` |
| `pipeline/text.py` | `english_text()`, `is_english` → "pages in the language(s) this country's rules read" |
| `pipeline/extract.py` | prompt "Indian vehicle-regulation documents" and the category list in `llm_model_for` → per country |
| `pipeline/search.py` | `to_tsvector('english', …)` → the chunk's `tsv` column |
| `vocab.py` | reads English synonyms and keywords → reads `vocab_term` for the country and language |

---

## 3. The key problem: vehicle categories

The same code means different vehicles:

| Code | UNECE meaning (followed by Thailand, Malaysia and most countries) | India's meaning today (CMVR / AIS-053, as seeded) |
|---|---|---|
| `L1` | two wheels, ≤ 50 cm³ and ≤ 50 km/h (moped) | two-wheeler ≤ 45 km/h |
| `L2` | **three wheels**, ≤ 50 cm³ and ≤ 50 km/h | **two-wheeler > 45 km/h (motorcycle)** |
| `L3` | **two wheels**, > 50 cm³ or > 50 km/h (**motorcycle**) | (rarely used) |
| `L5` | three wheels, symmetric | three-wheeler (auto rickshaw) |

Countries also have **their own registration classes**:

| Country | Local class | Meaning | Closest UNECE |
|---|---|---|---|
| India | `E_RICKSHAW`, `E_CART` | battery-operated three-wheelers | `L5` |
| Thailand | รย.1 | private car up to 7 seats | `M1` |
| Thailand | รย.3 | private pickup / light truck | `N1` |
| Thailand | รย.12 | private motorcycle | `L3` |
| Malaysia | JPJ classes (car, motorcycle, goods vehicle…) | | `M1`, `L3`, `N1`… |

The Thai and Malaysian classes above are examples to confirm from real DLT and JPJ documents.

**Proposal:**
- **Each country keeps its own codes**, exactly as its documents use them. India stays as it is today.
- **Every local code maps to UNECE codes**, in one mapping table.
- **Documents and mandates store both**: `vehicle_categories` (local, as written) and `vehicle_categories_un` (UNECE, for comparing countries).
- **Scope is per country**: India tracks L1, L2, M1, N1 in *India's* meaning. Thailand would track whatever the client chooses (for example รย.1, รย.3, รย.12).

---

## 4. Target schema

New and changed parts only; everything else stays as in `0001`–`0005`.

### 4.1 Countries and their settings

```
country            code PK · name · year_offset · language (primary) · languages[] · timezone · currency
country_scope      country · vehicle_category        → what each country tracks (replaces global in_scope)
```

| country | languages | timezone | currency | year_offset |
|---|---|---|---|---|
| IN | en, hi | Asia/Kolkata | INR | 0 |
| TH | th, en | Asia/Bangkok | THB | 543 |
| MY | ms, en | Asia/Kuala_Lumpur | MYR | 0 |
| UN (international, UNECE regulations) | en, fr, ru | Europe/Zurich | – | 0 |

### 4.2 Vocabularies

```
vehicle_category   country · code · label · un_codes[] · is_international      PK (country, code)
                   (UNECE codes themselves are rows with country = 'UN')
vocab_term         kind (vehicle_category | domain | doc_type | doc_role | status)
                   · code · country (NULL = all) · language · term
                   → every synonym and keyword, in any language
domain             code · label            (universal topics; keywords move to vocab_term)
```

`vocab_term` examples:

| kind | code | country | language | term |
|---|---|---|---|---|
| vehicle_category | L2 | IN | en | motor cycle |
| vehicle_category | รย.12 | TH | th | รถจักรยานยนต์ส่วนบุคคล |
| doc_role | AMENDMENT | TH | th | แก้ไขเพิ่มเติม |
| doc_role | AMENDMENT | MY | ms | (Pindaan) |
| domain | emission | IN | en | Bharat Stage |
| domain | emission | TH | th | มลพิษ |

### 4.3 Documents

New columns on `document`:

| Column | Meaning |
|---|---|
| `doc_type`, `doc_role`, `legal_force`, `sub_type`, `local_type` | country-neutral classification (`CLASSIFICATION_DESIGN.md`) |
| `language` | language of the official text (`en`, `th`, `ms`…) |
| `title_en` | English title when the official title is in another language |
| `effective_date` | when it takes effect, if the text says so (`doc_date` stays the date of issue) |
| `vehicle_categories_un` | the UNECE meaning of `vehicle_categories` |

Changed:
- `canonical_id` is unique per `(country, canonical_id)`.
- The "one current version" index becomes `(country, family_key)`.

`document_file`:
- add `language_pages JSONB`, for example `{"hi":[1,1],"en":[2,2]}`;
- new roles `other_language_only`, `translation` (`hindi_only` stays for existing rows).

### 4.4 Relations and mandates

- `doc_relation.type`: add `adopts` (a national standard takes over an international one, e.g. TIS → UN R), `equivalent_to`, `repeals`.
- `doc_relation.method`: add `llm`, `manual`.
- `mandate`: add `country`, `vehicle_categories_un`; index `(country, mandate_key, valid_from)`.

### 4.5 Search

`chunk`:
- add `country`, `doc_type`; `language` holds the real language;
- add `tsv tsvector`, filled by the pipeline per language: the `english` dictionary for `en`; Thai text split into words by a Thai word segmenter (for example PyThaiNLP) and indexed with `simple`; Malay with `simple`;
- **one multilingual embedding model** for all countries. Its dimension decides `vector(N)` (decision D3).

### 4.6 Operations and portal

- `change_event`: add `country`. This also removes today's special case for events whose document was retired.
- `compliance_item`: add `country`; primary key `(country, mandate_key)`.
- `alert_rule`: add `country`; `scope` = 'All' or a category from that country's scope.
- `report_log`: add `country`.

---

## 5. Migration sketch: `0006_universal_schema.sql`

**Not applied. For review only.** It only adds things and fills them from existing data: no India row is deleted, and India's existing values are not changed.

```sql
-- 0006: make the schema country-neutral (proposal). Adds columns and lookups; existing India values are kept.

-- countries ------------------------------------------------------------------------------------------
ALTER TABLE country
  ADD COLUMN languages TEXT[] NOT NULL DEFAULT '{}',
  ADD COLUMN timezone  TEXT   NOT NULL DEFAULT 'UTC',
  ADD COLUMN currency  TEXT;
UPDATE country SET languages = ARRAY['en','hi'], timezone = 'Asia/Kolkata', currency = 'INR' WHERE code = 'IN';
UPDATE country SET languages = ARRAY['th','en'], timezone = 'Asia/Bangkok', currency = 'THB' WHERE code = 'TH';
INSERT INTO country (code, name, year_offset, language, languages, timezone, currency) VALUES
  ('MY', 'Malaysia', 0, 'ms', ARRAY['ms','en'], 'Asia/Kuala_Lumpur', 'MYR'),
  ('UN', 'UNECE (international regulations)', 0, 'en', ARRAY['en','fr','ru'], 'Europe/Zurich', NULL)
ON CONFLICT (code) DO NOTHING;

-- vehicle categories per country, mapped to UNECE ---------------------------------------------------
ALTER TABLE vehicle_category
  ADD COLUMN country  TEXT NOT NULL DEFAULT 'IN' REFERENCES country(code),
  ADD COLUMN un_codes TEXT[] NOT NULL DEFAULT '{}';
-- India's meaning -> UNECE meaning (to confirm against AIS-053 / CMVR Rule 2)
UPDATE vehicle_category SET un_codes = CASE code
  WHEN 'L1' THEN ARRAY['L1'] WHEN 'L2' THEN ARRAY['L3'] WHEN 'L3' THEN ARRAY['L3'] WHEN 'L4' THEN ARRAY['L4']
  WHEN 'L5' THEN ARRAY['L5'] WHEN 'L6' THEN ARRAY['L6'] WHEN 'L7' THEN ARRAY['L7']
  WHEN 'QUADRICYCLE' THEN ARRAY['L6','L7'] WHEN 'E_RICKSHAW' THEN ARRAY['L5'] WHEN 'E_CART' THEN ARRAY['L5']
  WHEN 'O' THEN ARRAY['O1','O2','O3','O4'] WHEN 'T' THEN ARRAY['T1','T2','T3','T4','T5']
  WHEN 'ALL' THEN ARRAY['ALL'] ELSE ARRAY[code] END;          -- M1..N3 mean the same; CEV maps to itself
-- the PK moves from (code) to (country, code): needs the foreign keys that point at vehicle_category.code
-- reviewed first (today: none; categories are stored as text arrays) -> done in the same migration
ALTER TABLE vehicle_category DROP CONSTRAINT vehicle_category_pkey, ADD PRIMARY KEY (country, code);

CREATE TABLE country_scope (
  country           TEXT NOT NULL REFERENCES country(code),
  vehicle_category  TEXT NOT NULL,
  PRIMARY KEY (country, vehicle_category)
);
INSERT INTO country_scope SELECT 'IN', code FROM vehicle_category WHERE country = 'IN' AND in_scope;

-- synonyms and keywords in any language ----------------------------------------------------------------
CREATE TABLE vocab_term (
  id        SERIAL PRIMARY KEY,
  kind      TEXT NOT NULL CHECK (kind IN ('vehicle_category','domain','doc_type','doc_role','status')),
  code      TEXT NOT NULL,
  country   TEXT REFERENCES country(code),          -- NULL = any country
  language  TEXT NOT NULL,
  term      TEXT NOT NULL,
  UNIQUE NULLS NOT DISTINCT (kind, code, country, language, term)
);
INSERT INTO vocab_term (kind, code, country, language, term)
  SELECT 'vehicle_category', code, 'IN', 'en', unnest(synonyms) FROM vehicle_category WHERE country = 'IN';
INSERT INTO vocab_term (kind, code, country, language, term)
  SELECT 'domain', code, 'IN', 'en', unnest(keywords) FROM domain;

-- documents -------------------------------------------------------------------------------------------
ALTER TABLE document
  ADD COLUMN doc_type     TEXT CHECK (doc_type IN ('LAW','REGULATION','TECHNICAL_STANDARD','PROCEDURE','GUIDANCE',
                                                    'REFERENCE','OFF_TOPIC','UNKNOWN')),
  ADD COLUMN doc_role     TEXT CHECK (doc_role IN ('BASE','AMENDMENT','CORRIGENDUM','EXTENSION','EXEMPTION','REPEAL',
                                                    'CONSOLIDATION','ANNEX','INTERPRETATION')),
  ADD COLUMN legal_force  TEXT NOT NULL DEFAULT 'UNKNOWN'
                          CHECK (legal_force IN ('MANDATORY','VOLUNTARY','INFORMATIVE','UNKNOWN')),
  ADD COLUMN sub_type     TEXT,
  ADD COLUMN local_type   TEXT,
  ADD COLUMN language     TEXT,
  ADD COLUMN title_en     TEXT,
  ADD COLUMN effective_date DATE,
  ADD COLUMN vehicle_categories_un TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE document DROP CONSTRAINT document_canonical_id_key,
                     ADD CONSTRAINT document_country_canonical_key UNIQUE (country, canonical_id);
DROP INDEX document_one_current;
CREATE UNIQUE INDEX document_one_current ON document (country, family_key) WHERE is_current AND family_key IS NOT NULL;
CREATE INDEX document_type_idx ON document (country, doc_type, doc_role);
CREATE INDEX document_cat_un_idx ON document USING gin (vehicle_categories_un);
-- India: doc_type / doc_role from the mapping in CLASSIFICATION_DESIGN.md §5.1, written by the pipeline
-- (a Python backfill, so the mapping has one definition); language = 'en' for India's English-text documents.

ALTER TABLE document_file ADD COLUMN language_pages JSONB;
ALTER TABLE document_file DROP CONSTRAINT document_file_role_check,
  ADD CONSTRAINT document_file_role_check CHECK (role IN ('main','consolidated_segment','annex_table','historical_copy',
                                                         'hindi_only','other_language_only','translation'));

-- relations and mandates ------------------------------------------------------------------------------
ALTER TABLE doc_relation DROP CONSTRAINT doc_relation_method_check,
  ADD CONSTRAINT doc_relation_method_check CHECK (method IN ('regex','file_no','qwen','llm','manual'));
ALTER TABLE mandate
  ADD COLUMN country TEXT NOT NULL DEFAULT 'IN' REFERENCES country(code),
  ADD COLUMN vehicle_categories_un TEXT[] NOT NULL DEFAULT '{}';
UPDATE mandate m SET country = d.country FROM document d WHERE d.id = m.source_doc_id AND m.country <> d.country;
CREATE INDEX mandate_country_key_idx ON mandate (country, mandate_key, valid_from);

-- search ------------------------------------------------------------------------------------------------
ALTER TABLE chunk
  ADD COLUMN country  TEXT NOT NULL DEFAULT 'IN' REFERENCES country(code),
  ADD COLUMN doc_type TEXT,
  ADD COLUMN tsv      tsvector;                      -- filled by the pipeline per language
CREATE INDEX chunk_tsv_idx ON chunk USING gin (tsv);
CREATE INDEX chunk_country_idx ON chunk (country, in_scope, is_current);
-- the existing english full-text index (0003) stays until search.py uses tsv

-- operations and portal ---------------------------------------------------------------------------------
ALTER TABLE change_event ADD COLUMN country TEXT NOT NULL DEFAULT 'IN' REFERENCES country(code);
UPDATE change_event e SET country = d.country FROM document d WHERE d.id = e.document_id AND e.country <> d.country;
ALTER TABLE compliance_item ADD COLUMN country TEXT NOT NULL DEFAULT 'IN' REFERENCES country(code);
ALTER TABLE compliance_item DROP CONSTRAINT compliance_item_pkey, ADD PRIMARY KEY (country, mandate_key);
ALTER TABLE alert_rule  ADD COLUMN country TEXT NOT NULL DEFAULT 'IN' REFERENCES country(code);
ALTER TABLE report_log  ADD COLUMN country TEXT NOT NULL DEFAULT 'IN' REFERENCES country(code);
```

**Before this is applied:**
- the constraint names were checked against the live database on 16 Oct 2026 (PostgreSQL 16.15): `document_canonical_id_key`, `document_file_role_check`, `doc_relation_method_check`, `vehicle_category_pkey` and `compliance_item_pkey` all exist, and no foreign key points at `vehicle_category`. Check them again just before applying;
- it is tested on a copy (`regtrack_test`), twice, to prove it is idempotent;
- all India counts before and after must be equal.

**Later migration (`0007`, after the code has moved):** drop what is no longer used: `vehicle_category.in_scope`, the English-only full-text index, and `english_page_from/to` once `language_pages` replaces them.

---

## 6. Adding a new country afterwards

With this schema, a new country (for example Vietnam) needs **no schema change**:

| Step | Where |
|---|---|
| 1 | a `country` row (languages, time zone, currency, year offset) |
| 2 | `source` rows for its websites, and a crawler module per website |
| 3 | `vehicle_category` rows for its local classes, with `un_codes` |
| 4 | `country_scope` rows: what the client tracks there |
| 5 | `vocab_term` rows: synonyms, keywords and classification clue words in its language |
| 6 | a classification profile in `regtrack/pipeline/countries/<cc>.py`: identity formats and rules |
| 7 | `local_class` values and their `data` shapes (Pydantic models), if its documents need new fields |

---

## 7. Decisions needed

| # | Question | Recommendation |
|---|---|---|
| D1 | Keep India's own category codes (L2 = motorcycle) and add UNECE codes next to them, or re-code India's data to UNECE (L2 → L3)? | **Keep India's codes, add `vehicle_categories_un`.** Re-coding would change India's existing data and every screen. |
| D2 | Should `vocab_term` replace the `synonyms` and `keywords` columns? | Yes; the old columns stay until `0007` |
| D3 | Which multilingual embedding model, and therefore which `vector(N)`? | Pick one that handles Thai, Malay, English and Hindi and runs in LM Studio. Test 2–3 candidates on real Thai and Malay text before fixing `N`. Changing `N` later means re-embedding everything. |
| D4 | Thai word splitting for keyword search: PyThaiNLP in the pipeline, or a Postgres extension? | PyThaiNLP in the pipeline (no database extension to install or maintain) |
| D5 | Add `UN` as a pseudo-country for UNECE regulations? | Yes |
| D6 | Unique `canonical_id` per country (`UNIQUE (country, canonical_id)`), or keep it globally unique with country prefixes? | Per country; the `TH-`/`MY-` prefixes in `CLASSIFICATION_DESIGN.md` then become optional |
| D7 | Rename the India-specific topic `hsrp` to the universal `number_plates`? | Yes, with HSRP kept as an India keyword |
| D8 | Is the scope per **country** enough, or per **client** (several clients tracking different categories in the same country)? | Per country now. Add a `client` level only when a second client exists. |

**Open points to verify:**
- India's category meanings against AIS-053 / CMVR Rule 2 (especially `L1` and `L2`).
- Thai รย. classes and JPJ classes against official DLT and JPJ documents.
