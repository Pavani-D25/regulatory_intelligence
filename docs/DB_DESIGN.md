# RegTrack India — Database Design (v3, full-corpus evidence)

> Built from **every file** in `D:\Regulatory_Documents`:
> - 2,274 files, about 3.3 GB, including all 15 folders and the download logs
> - text extracted with PyMuPDF, and every document profiled automatically by script (no hand reading)
>
> v2 was based on 49 documents. Every number below comes from the full run.
>
> Scope of the app: India; L1/L2 (two-wheelers); M1 (cars, private and commercial use); N1 (light goods).
> This file replaces `ETL_SPEC.md` §2.

> **Tables since the v4B switch-over (October 2026, migrations 0007–0011).** The design decisions, vocabularies and
> `data` shapes in this file still hold. The tables of §4 were moved into the v4B schema (`docs/SCHEMA_V4B.md`, which
> is authoritative for table and column names) and dropped by migration 0011. §4 is kept as the record of the first
> schema. Where this file says:
>
> | Here (first schema) | v4B |
> |---|---|
> | `file_object` (a stored file, `stage`) | `documents` |
> | `file_sighting` (a listing) | `raw_ingestion_records` |
> | `document` (`canonical_id`, `doc_class`, `status`, `doc_date`, `official_title`, `subject`, `issuer`) | `regulations` (`external_code`, `local_class`, `legal_status`, `published_date`, `title`, `summary`, `authority_id`) |
> | `document.vehicle_categories[]`, `domains[]`, `issuer` | `regulation_vehicle_categories`, `regulation_domains`, `regulation_authorities` |
> | `document_file` | `document_parts` |
> | `doc_relation` | `regulation_relations` |
> | `mandate` (`mandate_key`) | `requirement_versions` under `compliance_requirements` (`requirement_code`) |
> | `chunk` | `document_chunks` |
> | `change_event`, `quality_flag`, `crawl_run`, `source` | `regulation_changes`, `quality_flags`, `ingestion_runs`, `sources` |
> | `country`, `vehicle_category`, `domain`, `local_class` | `regions`, `vehicle_categories`, `domains`, `document_classes` |
>
> The pipeline keeps the first schema's names for a regulation in code (`canonical_id`, `doc_class`, …); the mapping
> lives in `regtrack/pipeline/repo.py` and `regtrack/api/sql.py`.

---

## 0. Corpus profile (measured)

| Measure | Value |
|---|---|
| Files / unique by SHA-256 | 2,274 / **2,016** (256 extra byte-copies in 237 groups) |
| Pages | ≈ 57,600 |
| File types | 2,191 PDF · 79 DOCX (73 = AIS-007 Rev.5 tables) · 7 CSV · 1 HTM · 1 DOC |
| **Scans (no text layer)** | **251 files / 1,742 pages**, mostly MoRTH Gazette (181 of 591 in folder 05); spread across 1989–2025, so not only "old" files |
| Notifications (G.S.R./S.O. detected) | 879 files → about 325 distinct primary IDs; 145 IDs have more than one file, and 137 of those have **different bytes** |
| Notifications with Hindi in legacy Kruti Dev font (extracts as gibberish) | 300 of 879 |
| Gazette section found | Part II-3(i) (G.S.R. = rules): 530 · 3(ii) (S.O. = orders): 138 · not found (scans): 211 |
| Official short title "Central Motor Vehicles (Nth Amendment) Rules, YYYY" | 305 |
| File no. (`RT-11xxx/…`) | 499; this is the key that links a draft to its final |
| Finals that cite their draft | 225: **121 drafts present in the corpus**, 104 missing (link must allow a target we haven't collected yet) |
| **Same G.S.R./S.O. number in different years** | 20 cases, e.g. G.S.R. 659(E) 2016 and 2022; G.S.R. 683(E) 2016 and 2022; G.S.R. 412(E) 2015 and 2016 → **the year must be part of the ID** |
| MoRTH listing title vs PDF content | 265 agree, **6 disagree** (e.g. listing "G.S.R. 904(E)" is actually G.S.R. 903(E); "S.O. 3504" is S.O. 3604); 14 listings have a placeholder date of 1 Jan |
| AIS files (ARAI folder 07) | 358 files → 195 AIS codes, 59 codes with more than one file (Parts, Revisions) |
| AIS files with embedded amendments | **210** (up to 10 amendments in one file, e.g. AIS-037 Amd 1–11, AIS-113 Amd 1–10); 15 with corrigenda |
| Amendment header formats | `AMENDMENT NO. 2  10 April 2015 TO AIS 021/2004` · `Amendment No. 4 (MM/YYYY) To AIS-xxx` · no date at all → three regex variants |
| AIS structure markers | cover "AUTOMOTIVE INDUSTRY STANDARD" 581 · Scope clause 489 · status chart 266 · transitional provisions 133 |
| **AIS copies in MoRTH folder 06** | 314: 123 identical to ARAI's, **191 different = earlier versions, drafts ("Finalized Draft AIS-138", "Last date for comments …")**, each with a MoRTH publish date → this is the version history |
| S.O. 1365(E) master table chain | 35 notifications cite it, e.g. S.O. 411/2016 · 3291/2017 · 2211/2018 · 6108/2018 · 5419/2021 · 4143, 4144, 4567/2022; date-extension chains like wheel rim S.O. 1406 → 359 → 3896 → 3800 |
| Off-topic noise in India Code folder 02 | 92 files with no automotive content; 23 state-level files (GST, state MV tax, pollution schemes); file names are meaningless (`110.pdf`, `A1939-40.pdf`) |
| Vehicle category in notifications | explicit L1/L2/M1/N1 only: 65 · mixed with other categories: 185 · only out-of-scope (tractor, bus, trailer, e-rickshaw…): 235 · **no category word at all: 385** (fees, permits, licensing, or "all motor vehicles") |
| Topics per notification | 0 topics: 406 (scans/Hindi) · 1: 205 · 2 or more: 259 → topic is a **list**, not one value |
| Numeric conditions in notifications | cc 44 · kW 45 · GVW 49 · seats 33 · km/h 50 |
| CMVR-TAP-115/116 | 1 logical document (Issue 4) split into **102 files** (Parts 1–15, chapters) + an HTML amendment record |
| Other classes | 90 Parivahan forms · 45 reports/yearbooks · 14 BIS conformity regulations + 505-row IS catalogue CSV · 5 ARAI approved lists · 20 battery/e-waste rules · 12 ELV/scrappage · 8 fuel-quality orders · 5 Acts / consolidated CMVR texts |

---

## 1. Findings → design decisions

| # | Finding | Decision |
|---|---|---|
| 1 | One file contains several legal documents (210 AIS files with embedded amendments; TAP is 102 files for one document) | `file_object` ⟂ `document`, joined by `document_file` with page range and `part_label` |
| 2 | One document exists as many files (137 IDs with different bytes; 123 AIS byte-copies across ARAI/MoRTH) | Identity = `canonical_id`, never the hash |
| 3 | G.S.R./S.O. numbers restart every year | `canonical_id = 'GSR-659(E)-2022'` (series-number-year) |
| 4 | Listing titles/dates are sometimes wrong | `file_sighting.listing_*` stores the source's *claim*; the document fields come from the content; a mismatch creates a `quality_flag(title_file_mismatch)` |
| 5 | Amendments, corrigenda and revisions have legal meaning (AIS-000) | `doc_relation` types + `requires_reapproval` |
| 6 | AIS standards have *families* with many versions (Part, Rev, Amd), and MoRTH keeps old versions | New `family_key` + `version_seq` + `is_current` on `document` |
| 7 | Mandatory dates come from notifications (S.O. 1365 table, Rule 124(4) table, rule text), are extended repeatedly, and differ between draft and final | Temporal `mandate` table, with `extends_date` and `finalises` relations |
| 8 | 251 scans and 300 Kruti-Dev Hindi files | OCR stage; English page range on `document_file`; Hindi never embedded |
| 9 | Applicability is mostly *implicit* (385 notifications name no category) and often *outside scope* | `applicability` JSON (with "all motor vehicles" = `ALL`) + computed `in_scope`; out-of-scope documents are kept but filtered |
| 10 | Many notifications are administrative (fees, permits, licences), not vehicle design | `nature` = technical / administrative / procedural; the vendor view shows technical by default |
| 11 | Noise (92 non-automotive files) | `relevance` stage: `doc_class = OFF_TOPIC`, file kept, no chunks, no mandates |
| 12 | Topics overlap | `domains TEXT[]` |
| 13 | AIS-007 has 72 DOCX tables (specification forms) | Child documents `AIS_FORM_TABLE` linked by `annex_of` |
| 14 | Drafts often missing from the corpus (104) | `doc_relation.to_doc` nullable + `to_ref` text; auto-resolved when the target arrives |

---

## 2. Layers

```
OBJECT STORAGE (write-once, sha256 keys)
      │
file_object ──< file_sighting (where/when seen, listing claims)
      │
document_file (page ranges, part labels, english pages)
      │
document  ── family_key / version ──  doc_relation (amends, revises, corrects, finalises,
   │  (JSONB data per doc_class)                     extends_date, supersedes, annex_of, references…)
   ├── mandate   (who · which standard · from when · legal basis · valid_from/valid_to)
   └── chunk     (clause-level text + filter metadata + embedding)
```

---

## 3. Controlled vocabularies

- **doc_class** (measured classes):
  - AIS: `AIS_STANDARD`, `AIS_AMENDMENT`, `AIS_CORRIGENDUM`, `AIS_DRAFT`, `AIS_FORM_TABLE`, `AIS_INTERPRETATION`, `SAFETY_STANDARD_LEGACY`
  - TAP: `TAP_DOCUMENT`, `TAP_AMENDMENT`
  - Notifications: `NOTIFICATION_DRAFT`, `NOTIFICATION_FINAL`, `NOTIFICATION_ORDER` (S.O.), `NOTIFICATION_CORRIGENDUM`, `NOTIFICATION_EXEMPTION`, `NOTIFICATION_EXTENSION`
  - Other official documents: `CIRCULAR_OM`, `GUIDELINE_POLICY`, `ACT`, `CONSOLIDATED_RULES`, `BIS_REGULATION`, `BIS_CATALOGUE`, `ENERGY_STANDARD`, `FUEL_ORDER`, `APPROVED_LIST`, `FORM_TEMPLATE`, `REPORT`
  - Catch-all: `OFF_TOPIC`, `OTHER`
- **relation_type**: `amends`, `corrects`, `revises`, `supersedes`, `finalises`, `extends_date`, `exempts`, `mandates`, `inserts_row`, `substitutes_row`, `omits_row`, `annex_of`, `part_of`, `interprets`, `references`, `same_as`
- **vehicle_category**: `L1 L2 L3 L4 L5 L6 L7 M1 M2 M3 N1 N2 N3 O1–O4 T1–T5 CEV QUADRICYCLE E_RICKSHAW E_CART ALL`
  - each has `synonyms` (measured words: two-wheeler, motor cycle, scooter, moped, car, four-wheeler, bus, truck, trailer, agricultural tractor, ambulance, caravan…)
  - each has `in_scope` (L1, L2, M1, N1, ALL)
- **nature**: `technical` (type approval, equipment, emissions), `administrative` (registration, licence, permit, fees), `procedural` (testing, CoP, accreditation)
- **domain** (multi-valued, measured frequency in notifications):
  - safety_equipment 145 · type_approval 130 · ev_alt_fuel 122 · registration 113 · fees 78 · permit 76 · emission 75 · licensing 63 · dimensions_weights 51 · recall_scrappage 43 · fitness_puc 24 · tracking_its 23 · hsrp 10
  - plus lighting, braking, cybersecurity, charging, battery
- **usage**: `private`, `transport`, `all` · **powertrain**: `petrol diesel cng lpg ethanol_flex biodiesel hydrogen lng methanol hybrid bev all`

---

## 4. Schema (PostgreSQL 16 + pgvector) — first schema, replaced by v4B (see the note at the top)

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- lookups
CREATE TABLE vehicle_category (code TEXT PRIMARY KEY, label TEXT, synonyms TEXT[], in_scope BOOLEAN);
CREATE TABLE domain (code TEXT PRIMARY KEY, label TEXT, keywords TEXT[]);

-- ingestion
CREATE TABLE source (id SERIAL PRIMARY KEY, code TEXT UNIQUE,      -- ARAI_AIS | MORTH_API | INDIACODE | EGAZETTE | ARAI_TAP | BIS | PARIVAHAN
                     name TEXT, base_url TEXT, schedule_hours INT DEFAULT 6,
                     last_run_at TIMESTAMPTZ, last_status TEXT);
CREATE TABLE crawl_run (id BIGSERIAL PRIMARY KEY, source_id INT REFERENCES source(id),
                        started_at TIMESTAMPTZ DEFAULT now(), finished_at TIMESTAMPTZ,
                        status TEXT, stats JSONB, log TEXT);

CREATE TABLE file_object (
  id BIGSERIAL PRIMARY KEY,
  sha256 CHAR(64) UNIQUE NOT NULL,
  storage_path TEXT NOT NULL,
  mime TEXT, ext TEXT, size_bytes BIGINT, page_count INT,
  text_layer BOOLEAN,                      -- false for the 251 scans
  scanned_pages INT[],                     -- mixed files: only some pages scanned
  ocr_engine TEXT, ocr_confidence NUMERIC(4,3),
  language_mix JSONB,                      -- {"en":0.58,"hi":0.42,"hi_legacy_font":true}
  pdf_meta JSONB,                          -- producer/creator/creationDate
  stage TEXT DEFAULT 'downloaded',         -- downloaded|text|classified|parsed|linked|chunked|embedded|done|failed
  stage_error TEXT,
  first_seen_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE file_sighting (               -- one row per (source listing row, file)
  id BIGSERIAL PRIMARY KEY,
  file_id BIGINT REFERENCES file_object(id),
  source_id INT REFERENCES source(id), crawl_run_id BIGINT REFERENCES crawl_run(id),
  source_url TEXT, source_item_id TEXT,    -- India Code item UUID, MoRTH file id, ARAI SR
  listing_title TEXT, listing_date DATE, listing_category TEXT,   -- CLAIMS, not truth
  listing_raw JSONB,
  seen_at TIMESTAMPTZ DEFAULT now(), last_seen_at TIMESTAMPTZ, gone_at TIMESTAMPTZ
);

-- the regulatory object
CREATE TABLE document (
  id BIGSERIAL PRIMARY KEY,
  canonical_id TEXT UNIQUE NOT NULL,       -- 'GSR-659(E)-2022' | 'SO-1365(E)-2004' | 'AIS-038(Rev.2)' | 'AIS-038(Rev.2)/Amd.4'
                                           -- 'AIS-007(Rev.5)/Table-1B' | 'TAP-115/116(Issue.4)' | 'FORM-20'
  doc_class TEXT NOT NULL,
  series TEXT, number TEXT, year INT,      -- year is part of the identity of GSR/SO
  part TEXT, revision INT, amendment_no INT, corrigendum_no INT,
  family_key TEXT,                         -- 'AIS-038' | 'AIS-004(Part3)' | 'CMVR-Rule-124' | 'SO-1365-MASTER'
  version_seq INT,                         -- order inside the family (base, amd1, amd2, rev1 …)
  is_current BOOLEAN,
  official_title TEXT, subject TEXT,
  issuer TEXT,                             -- MoRTH | AISC/ARAI | MoEFCC | MoPNG | MoP/BEE | BIS | Law Ministry
  status TEXT NOT NULL,                    -- draft | final | superseded | withdrawn
  doc_date DATE, doc_date_precision TEXT,  -- day | month | year
  nature TEXT,                             -- technical | administrative | procedural
  vehicle_categories TEXT[] DEFAULT '{}',
  usage TEXT[] DEFAULT '{}', powertrains TEXT[] DEFAULT '{}', domains TEXT[] DEFAULT '{}',
  in_scope BOOLEAN,                        -- computed from categories ∩ vehicle_category.in_scope
  relevance JSONB,                         -- {"automotive":true,"score":0.93,"reason":"CMVR rule amendment"}
  data JSONB NOT NULL DEFAULT '{}',        -- shape per doc_class (§5), validated by JSON Schema
  extraction JSONB,                        -- {"model":"qwen3.8-27b","prompt":"notif_v3","confidence":{…},"needs_check":[…]}
  created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON document USING gin (data jsonb_path_ops);
CREATE INDEX ON document USING gin (vehicle_categories);
CREATE INDEX ON document USING gin (domains);
CREATE INDEX ON document (doc_class, doc_date);
CREATE INDEX ON document (family_key, version_seq);
CREATE INDEX ON document USING gin (official_title gin_trgm_ops);

CREATE TABLE document_file (
  document_id BIGINT REFERENCES document(id),
  file_id BIGINT REFERENCES file_object(id),
  page_from INT, page_to INT,
  english_page_from INT, english_page_to INT,
  part_label TEXT,                         -- 'Part-03/Chapter-04' (TAP) | 'Amendment 3 segment'
  role TEXT DEFAULT 'main',                -- main | consolidated_segment | annex_table | historical_copy | hindi_only
  is_best_copy BOOLEAN DEFAULT FALSE,      -- best text layer / newest of several byte-different copies
  PRIMARY KEY (document_id, file_id, page_from)
);

CREATE TABLE doc_relation (
  id BIGSERIAL PRIMARY KEY,
  from_doc BIGINT REFERENCES document(id),
  to_doc BIGINT REFERENCES document(id),   -- NULL until the target is collected (104 drafts missing today)
  to_ref TEXT,                             -- 'GSR-673(E)-2021' | 'IS 14664:2010' | 'UN R136'
  type TEXT NOT NULL,
  requires_reapproval BOOLEAN,
  details JSONB,                           -- {"rows":["26(b)"]} | {"scope":"hindi_only"} | {"old_date":"2021-04-01","new_date":"2022-04-01"}
  evidence TEXT, page INT, confidence NUMERIC(3,2),
  method TEXT                              -- regex | file_no | qwen
);
CREATE INDEX ON doc_relation(from_doc); CREATE INDEX ON doc_relation(to_doc);
CREATE INDEX ON doc_relation(type); CREATE INDEX ON doc_relation(to_ref);

CREATE TABLE mandate (
  id BIGSERIAL PRIMARY KEY,
  legal_basis TEXT NOT NULL,               -- 'SO-1365(E)-2004 Table Sr.26(b)' | 'CMVR Rule 124(4) Sl.23' | 'CMVR Rule 138(3)'
  mandate_key TEXT NOT NULL,               -- stable key for the slot, so later notifications version the same row
  subject TEXT,
  standard_refs TEXT[], standard_doc_ids BIGINT[],
  vehicle_categories TEXT[],
  conditions JSONB,                        -- {"engine_cc":{"lte":125},"power_kw":{"lte":11},"gvw_kg":{"gt":3500},"seats":{"lte":9}}
  model_scope TEXT,                        -- new_models | existing_models | all | registered_vehicles
  usage TEXT[], powertrains TEXT[],
  date_of_notification DATE, effective_date DATE, implementation_date DATE,
  implementation_rule TEXT,
  is_draft BOOLEAN NOT NULL,
  source_doc_id BIGINT REFERENCES document(id),
  valid_from DATE, valid_to DATE,
  superseded_by BIGINT REFERENCES mandate(id),
  recorded_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON mandate USING gin (vehicle_categories);
CREATE INDEX ON mandate (mandate_key, valid_from);
CREATE INDEX ON mandate (implementation_date);

CREATE TABLE chunk (
  id BIGSERIAL PRIMARY KEY,
  document_id BIGINT REFERENCES document(id), file_id BIGINT REFERENCES file_object(id),
  chunk_index INT, clause_no TEXT, heading TEXT, page_from INT, page_to INT,
  language TEXT DEFAULT 'en', is_boilerplate BOOLEAN DEFAULT FALSE,
  content TEXT NOT NULL,
  doc_class TEXT, family_key TEXT, vehicle_categories TEXT[], domains TEXT[],
  doc_year INT, status TEXT, is_current BOOLEAN, in_scope BOOLEAN,
  embedding vector(768),                   -- set to the LM Studio embedding model's dimension
  UNIQUE (document_id, chunk_index)
);
CREATE INDEX ON chunk USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON chunk USING gin (vehicle_categories);

CREATE TABLE change_event (
  id BIGSERIAL PRIMARY KEY, detected_at TIMESTAMPTZ DEFAULT now(),
  event_type TEXT,   -- new_document | new_amendment | new_revision | corrigendum | draft_published | draft_finalised
                     -- | implementation_date_changed | mandate_superseded | file_reissued | listing_removed
  document_id BIGINT REFERENCES document(id), mandate_id BIGINT REFERENCES mandate(id),
  summary TEXT, impact TEXT, details JSONB, review_status TEXT DEFAULT 'auto'
);
CREATE TABLE quality_flag (
  id BIGSERIAL PRIMARY KEY, entity TEXT, entity_id BIGINT,
  rule TEXT,         -- title_file_mismatch | placeholder_listing_date | low_ocr_confidence | unresolved_reference
                     -- | amendment_gap | draft_final_date_mismatch | duplicate_identity_diff_header | off_topic
  details JSONB, created_at TIMESTAMPTZ DEFAULT now(), resolved_at TIMESTAMPTZ
);
```

---

## 5. `document.data` shapes (one JSON Schema per doc_class)

**AIS_STANDARD**
```json
{ "title": "…", "cover_month": "2020-09", "parts": [], "based_on": ["UN R100"],
  "scope_text": "…", "applicability": {"categories":["L"], "raw":"vehicles of category L as defined in Rule 2(u)"},
  "transitional_text": "…", "deemed_compliance": ["AIS-038(Rev.1)"],
  "contents": [{"clause":"1","title":"Scope","page":"1/80"}],
  "annexes": [{"id":"8J","title":"…"}],
  "status_chart": [{"amendment":1,"date":"2021-05"}] }
```

**AIS_AMENDMENT / AIS_CORRIGENDUM**
```json
{ "amends": "AIS-038(Rev.2)", "amendment_no": 4, "issued": "2024-08", "issued_precision": "month",
  "header_format": "no_date|month_year|full_date",
  "instructions": [{"action":"substitute","clause":"5.1.1"},{"action":"add","clauses":["2.54","2.55"],"after":"2.53"}] }
```

**AIS_DRAFT** (MoRTH folder 06)
```json
{ "draft_of": "AIS-138(Part1)", "comments_until": "2015-08-31", "finalized_draft": true }
```

**NOTIFICATION_*** (G.S.R./S.O.)
```json
{ "series":"G.S.R.","number":"888(E)","date":"2022-12-19",
  "gazette":{"part":"II","section":"3","sub_section":"(i)"},
  "file_no":"RT-11036/60/2022-MVL","signatory":"…","powers":["MV Act s.110"],
  "official_title":"Central Motor Vehicles (Twenty-fifth Amendment) Rules, 2022",
  "commencement":"date of publication",
  "draft_ref":{"canonical_id":"GSR-659(E)-2022","date":"2022-08-25"},
  "comment_period_days":30,
  "amends_targets":["CMVR Rule 124(4)","SO-1365(E)-2004 Table"],
  "provisions":[{"action":"insert_row","target":"Rule 124(4) Table after Sl.22","subject":"Traction battery",
                 "standards":["AIS-156","AIS-038(Rev.2)"],"categories":["L","M","N"],"conditions":{},
                 "implementation":[{"model_scope":"new_models","date":"2023-03-31"}]}] }
```

**TAP_DOCUMENT**
```json
{ "doc_no":"MoRTH/CMVR/TAP-115/116","issue":4,
  "parts":[{"part":"3","chapter":"4","title":"…","file":"Part-03_Chapter04.pdf"}],
  "amendment_record":[{"amd":7,"date":"…","pages":"…"}] }
```

**CIRCULAR_OM / GUIDELINE_POLICY**: `{ "ref_no", "date", "addressees", "subject", "directions":[…], "valid_until" }`
**FORM_TEMPLATE**: `{ "form_no":"20", "rule_ref":"Rule 47", "purpose":"…" }`
**BIS_CATALOGUE** rows: `{ "is_no":"IS 14664:2010", "title":"…", "amendments":2, "reaffirmed":2020 }`

---

## 6. How the views come out

- **Vehicle** (L2, 110 cc, petrol, private):
  - `mandate` filtered by category, conditions and date
  - the standards behind each mandate, with each standard's current version and amendments
  - Export zip: the original files via `document_file`, plus a manifest.
- **Year-wise**: `doc_date`, `implementation_date`, `change_event.detected_at`.
- **Category-wise**: `vehicle_categories` + `in_scope`; administrative vs technical is filtered by `nature`.
- **Versions**: `family_key` ordered by `version_seq`, plus `doc_relation`. The older MoRTH copies appear as `historical_copy` files, each with its date.

```sql
-- everything mandatory for a 110 cc petrol scooter (L2) on 1 Jan 2026
SELECT legal_basis, subject, standard_refs, implementation_date
FROM mandate
WHERE NOT is_draft
  AND vehicle_categories && ARRAY['L2','ALL']
  AND (conditions->'engine_cc'->>'lte' IS NULL OR (conditions->'engine_cc'->>'lte')::int >= 110)
  AND implementation_date <= DATE '2026-01-01'
  AND valid_from <= DATE '2026-01-01' AND (valid_to IS NULL OR valid_to > DATE '2026-01-01');
```

---

## 7. Pipeline per file (all automatic)

| Stage | Deterministic | Qwen 3.8 27B |
|---|---|---|
| Text | PyMuPDF, docx XML; pages with < 100 chars → OCR | vision fallback for the 1,742 scan pages |
| Language | Devanagari ratio + Kruti-Dev fingerprints → English page range | — |
| Relevance | automotive keyword density, issuer, CMVR/MV Act mention | borderline files only |
| Classify | folder/source + header rules (gives the measured classes above) | `OTHER` leftovers |
| Identity | G.S.R./S.O. number + date + year from the English header (**not** the listing); AIS code/Part/Rev from cover | when the regex fails |
| Split | three AIS amendment-header variants, corrigendum headers, TAP part/chapter | — |
| Link | `file_no` equality, "draft … published vide G.S.R. X dated Y", "Amendment No N To AIS-xxx", "in S.O. 1365(E) … for serial number … substituted" | relation type when ambiguous |
| Applicability | synonym map to category codes; cc/kW/GVW/seat/speed regex | implicit scope ("all motor vehicles", out-of-scope only) |
| Mandates | table-row markers, "on and from", "new models / existing models" | main extraction of provisions → rows |
| Chunk + embed | clause numbering; boilerplate (committee lists, mastheads, status charts) flagged | — |

**Validators → `quality_flag`:**
- the listing ID differs from the content ID (6 cases today)
- a placeholder date of 1 Jan
- gaps in amendment numbering
- a draft referenced but not collected
- the same ID with different bytes but different headers
- implementation date before the notification date

---

## 8. What changed from v2

- Added to `document`:
  - `year` in the identity (G.S.R./S.O. numbers are reused across years)
  - `family_key`, `version_seq`, `is_current` (version view; MoRTH's 191 older AIS copies)
  - `nature`, `relevance`, `OFF_TOPIC` class
- Added to `document_file`: `part_label`, `role` and `is_best_copy`.
- Added to `file_sighting`: `source_item_id` and `last_seen_at`; listing fields are now claims, not identity.
- Added to `mandate`: `mandate_key`, so date-extension chains (wheel rim: 4 extensions) version a single slot.
- Added to `doc_relation`: `method`; new types `annex_of`, `part_of`, `same_as`, `omits_row`.
- New doc_classes: `AIS_DRAFT`, `CIRCULAR_OM`, `GUIDELINE_POLICY`, `CONSOLIDATED_RULES`, `BIS_REGULATION`, `FUEL_ORDER`, `FORM_TEMPLATE`.
- Profiling scripts that produced these numbers: `prof/extract.py`, `analyze.py`, `classify.py`, `ais.py`. Claude Code should rerun them as `discovery/` in the repo.
