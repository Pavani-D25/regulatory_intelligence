# RegTrack India — ETL, Database & Storage Spec (v2, based on the real sources)

> v2 replaces the first draft. The schema is now derived from what the three official sources actually publish (checked live on 6 Oct 2026), not from the UI prototype.
> Put this file in the repo root (or reference it from `CLAUDE.md`) so Claude Code builds against it.

---

## 1. What the real sources look like

### 1.1 ARAI — the master list of AIS standards

- Page: `https://www.araiindia.com/downloads/ais-downloads` (tabs **Published** / **Draft**).
- The page loads the **whole list as JSON** into the browser (Alpine.js component, client-side paging of 10 rows).
- Counts on 6 Oct 2026: **358 published, 68 drafts**.
- File hosting: `https://hmr.araiindia.com/storage/ais-details/<file>` → **285 PDF + 73 DOCX** in the published list (DOCX is not rare).
- The page's JSON calls use a bearer token embedded in the page. **Don't hard-code it in a scraper.** Either render the page with Playwright and read the list it shows, or ask ARAI / your TL whether automated access is allowed.
- `hmr.araiindia.com` itself is a members-only portal (login + captcha) — **out of scope**, never automate logins.

Fields per record (exactly as published):

| Field | Example | Notes |
|---|---|---|
| `id` | 196 | ARAI's internal id — stable key |
| `category` / `status` | Published / published, draft | |
| `code` | `AIS-038 (Rev. 2) and Amd. 1 to 4` | **Free text** — carries code, part, revision, amendments, corrigenda, draft stage, dates |
| `title` | Specific Requirements for Electric Power Train of Vehicles… | |
| `no_of_amendments` | 0 | Unreliable (356 of 358 = 0) — parse `code` instead |
| `priority_no` | 100 | Display order |
| `remarks` | "Copy re-issued on 23rd December 2024 for formatting correction in amendment 4" | Signals a **re-issue**: same code, new file |
| `document_url` | …/1787889123_AIS_156_with_Amd 1 to 5.pdf | |

Real `code` patterns the parser must handle:

```
AIS-000
AIS-001 and Amd. No.1 & Amd. No.2
AIS-001 (Part 1)(Rev. 2):2023 & Corrigendum1
AIS-007(Rev. 5) - Table 24A                 ← one standard split into many table files
AIS-037/2004 & Amd. No. 1 to 11
AIS-137 (Part 1) and Amd.1 to 4
Interpretation manual for AIS-189           ← guidance doc, not a standard
List                                        ← "List of Published AIS" PDF
Draft AIS-132/D10/May 2017 (Date of hosting on website: 26th May 2017)
Draft Amd 1 to AIS-159 (Date of hosting on website: 18th June 2021)
Draft AIS-010 (Part 5) (Rev. 2)/F 2021 (Date of hosting on website: 8th November 2021)
Revised Draft Amd 10 to AIS-137 (Part 3) (Date of hosting on website: 7th January 2025)
```

Draft titles also carry "(Last date for comments: …)".

### 1.2 Inside an AIS document (example: AIS-156 with Amd. 1 to 5)

- Cover: code, title, Parts (Part I electrical safety, Part II REESS), published by ARAI on behalf of AISC under CMVR-TSC, MoRTH; base date (Sept 2020).
- **Amendment record**: each amendment is appended with its own cover ("Amendment No. X (MM/YYYY) to AIS-156") and instructions like *"Add new clause 6.12 after clause 6.11"* or *"Clause 6.1 — substitute following text"*.
- **Scope clause (1.x)** defines applicability: *"vehicles of category L, as defined in Rule 2 (u) of CMVR … not permanently connected to the grid"*.
- **Transitional provisions (clause 9)**: compliance applies *"from the date stipulated in the notification"* → **the standard itself has no mandatory date.**
- It also says which older standards it replaces: *"vehicle complying with AIS 156 shall be deemed to comply with AIS 038 (Rev 1)"*.
- It references other AIS standards, IS standards (IS 16893, IS 17387…), UN R136, ISO 26262 and IEC standards.
- Annexes (test procedures 8A–8K…) and two committee-composition annexes (noise for search).
- Size: about 100+ pages. Other standards are much larger (AIS-175 draft: 719 pages).

### 1.3 MoRTH — Gazette notifications (and some AIS drafts)

- The site is now an Angular app; the old `morth.gov.in/en/ais` page is **blank/dead**. Behind it is a **public JSON API** (Laravel):
  `GET https://morth.gov.in/backend/api/gazettes-notifications?page=1&per_page=100&wings=&order_by=desc&search=`
  Other slugs: `acts-and-rules`, `policies-and-regulations`, `orders-and-notices`, `guidelines`, `public-notices`, `reports`, `archives`, `home-page-data` (What's New).
- Response: `page.files[]` = groups, each with `files_data[]`. On 6 Oct 2026: 902 files in 21 groups. The relevant group is **"Motor Vehicle Legislation" (577 PDFs, 1989–2026)**. The other groups are mostly about highways (NH Declaration, NH Entrustment) and are out of scope.
- File fields: `title, file, published_date, wings_division, name (group), document_type_id, file_size, page_id, is_archived, code, circular_guideline_number, link, last_date`.
- File URL = `https://morth.gov.in/backend/` + `file`.
- New AIS drafts sometimes appear only on MoRTH ("What's New"), sometimes as **.doc/.docx** (e.g. `DF_AIS_207_Trail_caravan.doc`, `DF_AIS_214_Troop_carrier.docx`).
- **Data-quality problems seen:**
  - Duplicate rows (G.S.R. 223(E) twice, draft G.S.R. 659(E) twice).
  - A file path with no extension (`…Cell001pdf`).
  - A broken temp link (`/backend//tmp/phpXZ4799`).
  - A row whose title says G.S.R. 07(E) but whose file is G.S.R. 26(E).

  → **Never trust the title alone.** Identify documents from the PDF content plus the file hash.

### 1.4 Inside a Gazette notification

Example 1: **S.O. 4143(E), 2 Sept 2022** ("Implementation of AIS-038 and AIS-156 from 1st October 2022"):

- Masthead: Gazette ID **CG-DL-E-03092022-238578**, *Extraordinary*, Part II—Section 3—Sub-section (ii), No. 3962, date.
- **Bilingual**: Hindi first, English after.
- Operative text: it **amends notification S.O. 1365(E) dated 13 Dec 2004**, *"in the Table, against serial number 26, in column (2) items (b) and (c), in column (4)"*, replacing *"twelve months from the date of notification"* with *"1st October, 2022"*.
- The AIS standards are **not named in the body**. The link is through the **row number in the S.O. 1365(E) master table**.
- Footer: file no. (RT-11036/60/2022-MVL), signatory, and a note listing the earlier amendments.

Example 2: **G.S.R. 415(E), 23 June 2025** (ABS for L2 and two helmets):

- Heading "प्रारूप नियम" = **draft rules** (with a public-comment period).
- Part II—Section 3—Sub-section (i).
- Amends **CMVR rules directly**:
  - Rule 96 sub-rule (4A): all L2 vehicles made on or after **1 Jan 2026** must have ABS conforming to **IS 14664:2010**.
  - Rule 138(4)(f): two BIS-standard helmets at purchase, within 3 months of commencement.
- References an **IS** standard, not an AIS.

What this means for the data:

1. **When** a rule applies comes from notifications, not from standards.
2. Notifications amend **CMVR rules** (rule/sub-rule) **or** rows of the **S.O. 1365(E) master table**.
3. Draft notifications come first and the final ones follow.
4. Effective dates can be absolute ("1st October, 2022") or relative ("twelve months from notification", "three months from commencement").

### 1.5 e-Gazette (egazette.gov.in)

- ASP.NET WebForms with the **session id in the URL** (`/(S(…))/default.aspx`) and `__doPostBack` navigation.
- Opening `SearchMenu.aspx` directly → error page. It only works through a browser flow (Playwright).
- **Role:** a verification and backfill source for the official copy (Gazette ID, Part/Section). MoRTH's own API already lists MoRTH's notifications with direct PDF links, so start with MoRTH.
- Reference implementation: [sushant354/egazette](https://github.com/sushant354/egazette) (Apache 2.0).

---

## 2. Data model (derived from the above)

```
                 ┌──────────────┐
  source ──< crawl_run           │
    │                            │
    └──< source_record ──< document_file ──< section_chunk (pgvector)
             │  (raw row: ARAI JSON row / MoRTH file row / e-Gazette hit)
             │
             ├── ais_document ───────> ais_standard            (AIS-156, AIS-001 Part 1 …)
             │     └──< ais_amendment (from the amendment pages inside the PDF)
             │
             └── notification ──< notification_provision ──> standard_mandate
                   (G.S.R./S.O.)     (what it changes)          (current state: which standard,
                                                                 which vehicles, from when)
  document_reference: any document → any cited code (AIS / IS / UN R / ISO / S.O. / G.S.R. / CMVR rule)
  change_event, review_task
```

### 2.1 SQL

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ================= INGESTION =================
CREATE TABLE source (
  id             SERIAL PRIMARY KEY,
  code           TEXT UNIQUE NOT NULL,      -- arai_ais | morth_api | egazette
  name           TEXT NOT NULL,
  base_url       TEXT NOT NULL,
  enabled        BOOLEAN DEFAULT TRUE,
  schedule_hours INT DEFAULT 6,
  last_run_at    TIMESTAMPTZ,
  last_status    TEXT
);

CREATE TABLE crawl_run (
  id            BIGSERIAL PRIMARY KEY,
  source_id     INT NOT NULL REFERENCES source(id),
  started_at    TIMESTAMPTZ DEFAULT now(),
  finished_at   TIMESTAMPTZ,
  status        TEXT DEFAULT 'running',     -- running|success|partial|failed
  records_seen  INT DEFAULT 0,
  records_new   INT DEFAULT 0,
  records_changed INT DEFAULT 0,
  records_gone  INT DEFAULT 0,              -- e.g. a draft removed when it is published
  files_new     INT DEFAULT 0,
  errors        INT DEFAULT 0,
  log           TEXT
);

-- One row per listing entry, exactly as the source shows it
CREATE TABLE source_record (
  id             BIGSERIAL PRIMARY KEY,
  source_id      INT NOT NULL REFERENCES source(id),
  external_id    TEXT NOT NULL,             -- ARAI id | MoRTH file path | Gazette ID
  listing        TEXT,                      -- 'published' | 'draft' | MoRTH group name
  code_raw       TEXT,                      -- ARAI 'code' string as-is
  title          TEXT,
  remarks        TEXT,
  listed_date    DATE,                      -- MoRTH published_date
  file_url       TEXT,
  raw            JSONB NOT NULL,            -- the full original row
  content_hash   CHAR(64) NOT NULL,         -- hash of raw → detects edits to the listing
  first_seen_at  TIMESTAMPTZ DEFAULT now(),
  last_seen_at   TIMESTAMPTZ DEFAULT now(),
  gone_at        TIMESTAMPTZ,               -- disappeared from the listing
  doc_kind       TEXT,                      -- ais_document | notification | list | manual | other (set by classifier)
  UNIQUE (source_id, external_id)
);

CREATE TABLE document_file (
  id              BIGSERIAL PRIMARY KEY,
  source_record_id BIGINT NOT NULL REFERENCES source_record(id),
  crawl_run_id    BIGINT REFERENCES crawl_run(id),
  file_url        TEXT NOT NULL,
  file_type       TEXT NOT NULL,            -- pdf|docx|doc|pptx|xlsx|zip
  sha256          CHAR(64) NOT NULL,
  size_bytes      BIGINT,
  storage_path    TEXT NOT NULL,            -- write-once original
  viewer_pdf_path TEXT,                     -- docx/doc → pdf for viewing
  is_current      BOOLEAN DEFAULT TRUE,     -- false when a newer hash replaces it (re-issue)
  page_count      INT,
  languages       TEXT[],                   -- {en} | {hi,en}
  text_layer      BOOLEAN,                  -- false → scanned → OCR/vision
  full_text       TEXT,
  stage           TEXT DEFAULT 'downloaded',-- downloaded|extracted|classified|parsed|embedded|error
  stage_error     TEXT,
  attempts        INT DEFAULT 0,
  fetched_at      TIMESTAMPTZ DEFAULT now(),
  UNIQUE (source_record_id, sha256)
);
CREATE INDEX ON document_file(sha256);
CREATE INDEX ON document_file(stage);

-- ================= AIS STANDARDS =================
CREATE TABLE ais_standard (                 -- the logical standard
  id          BIGSERIAL PRIMARY KEY,
  base_code   TEXT NOT NULL,                -- 'AIS-156'
  part        TEXT,                         -- '1', '2', NULL
  std_key     TEXT UNIQUE NOT NULL,         -- 'AIS-156' | 'AIS-001(Part 1)'
  title       TEXT,
  replaces    TEXT[] DEFAULT '{}',          -- from "deemed to comply with AIS 038 (Rev 1)"
  created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE ais_document (                 -- one issued file of a standard
  id                BIGSERIAL PRIMARY KEY,
  ais_standard_id   BIGINT NOT NULL REFERENCES ais_standard(id),
  source_record_id  BIGINT NOT NULL REFERENCES source_record(id),
  document_file_id  BIGINT REFERENCES document_file(id),
  doc_type          TEXT NOT NULL,          -- full_standard | amendment_only | draft_standard | draft_amendment | corrigendum | table_extract | interpretation_manual
  revision          INT,                    -- Rev. 2 → 2 (NULL = original)
  revision_year     INT,                    -- ':2023'
  amendments_included INT[] DEFAULT '{}',   -- 'Amd. 1 to 4' → {1,2,3,4}
  corrigenda_included INT[] DEFAULT '{}',
  draft_stage       TEXT,                   -- D1..D10 | DF | F | revised
  draft_amendment_no INT,                   -- 'Draft Amd 10 to …' → 10
  table_ref         TEXT,                   -- 'Table 24A' (AIS-007 Rev 5)
  hosted_on         DATE,                   -- 'Date of hosting on website'
  comments_due      DATE,                   -- 'Last date for comments'
  cover_date        TEXT,                   -- 'September 2020' (month precision)
  status            TEXT NOT NULL,          -- draft | published | superseded | withdrawn
  reissue_note      TEXT,                   -- ARAI remarks
  scope_text        TEXT,                   -- clause 1 verbatim
  transitional_text TEXT,                   -- transitional-provisions clause verbatim
  vehicle_categories TEXT[] DEFAULT '{}',   -- from the scope: {L} {M1,N1} …
  powertrain        TEXT,                   -- ICE | EV | ALL (only if the scope says so)
  parse_confidence  NUMERIC(3,2),
  llm_raw           JSONB,
  review_status     TEXT DEFAULT 'pending_review'
);

CREATE TABLE ais_amendment (                -- the amendment pages inside a standard
  id               BIGSERIAL PRIMARY KEY,
  ais_document_id  BIGINT NOT NULL REFERENCES ais_document(id),
  amendment_no     INT NOT NULL,
  issued_month     TEXT,                    -- '08/2026'
  instructions     JSONB,                   -- [{action:'add'|'substitute'|'delete', clause:'6.12', after:'6.11'}]
  page_from        INT,
  page_to          INT,
  UNIQUE (ais_document_id, amendment_no)
);

-- ================= GAZETTE NOTIFICATIONS =================
CREATE TABLE notification (
  id               BIGSERIAL PRIMARY KEY,
  source_record_id BIGINT NOT NULL REFERENCES source_record(id),
  document_file_id BIGINT REFERENCES document_file(id),
  series           TEXT NOT NULL,           -- 'G.S.R.' | 'S.O.' | 'O.M.' | other
  number           TEXT NOT NULL,           -- '415' | '4143'
  suffix           TEXT,                    -- '(E)'
  notif_date       DATE,
  gazette_id       TEXT,                    -- 'CG-DL-E-03092022-238578'
  gazette_issue_no TEXT,                    -- 'No. 3962'
  gazette_part     TEXT,                    -- 'Part II—Section 3—Sub-section (i)/(ii)'
  is_draft         BOOLEAN NOT NULL,        -- 'प्रारूप नियम' / 'draft rules'
  comment_days     INT,                     -- objections window for drafts
  file_no          TEXT,                    -- 'RT-11036/60/2022-MVL'
  signatory        TEXT,
  subject          TEXT,                    -- one-line summary
  parent_instrument TEXT,                   -- 'CMVR 1989' | 'S.O. 1365(E) 2004' | 'MV Act 1988'
  final_of_id      BIGINT REFERENCES notification(id),  -- final notification ↔ its draft
  english_page_from INT,                    -- where the English half starts
  parse_confidence NUMERIC(3,2),
  llm_raw          JSONB,
  review_status    TEXT DEFAULT 'pending_review',
  UNIQUE (series, number, suffix, notif_date)
);

CREATE TABLE notification_provision (       -- each operative change in a notification
  id               BIGSERIAL PRIMARY KEY,
  notification_id  BIGINT NOT NULL REFERENCES notification(id) ON DELETE CASCADE,
  seq              INT NOT NULL,
  action           TEXT NOT NULL,           -- insert | substitute | omit | amend_table_entry | commence
  target_kind      TEXT NOT NULL,           -- cmvr_rule | so1365_table_row | mv_act_section | other_notification
  target_ref       TEXT NOT NULL,           -- 'Rule 96(4A) proviso' | 'S.O.1365(E) Sr.26 col(4) items (b),(c)'
  old_text         TEXT,
  new_text         TEXT,                    -- verbatim English text
  effective_date   DATE,                    -- if absolute
  effective_rule   TEXT,                    -- if relative: '12 months from notification', '3 months from commencement'
  vehicle_categories TEXT[] DEFAULT '{}',
  standards_cited  TEXT[] DEFAULT '{}'      -- {'IS 14664:2010'} {'AIS-156'}
);

-- Materialised "current law": which standard applies to which vehicles from when
CREATE TABLE standard_mandate (
  id                 BIGSERIAL PRIMARY KEY,
  standard_code      TEXT NOT NULL,         -- 'AIS-156' | 'IS 14664:2010'
  ais_standard_id    BIGINT REFERENCES ais_standard(id),
  subject            TEXT,                  -- 'ABS', 'Traction battery safety'
  legal_basis        TEXT,                  -- 'CMVR Rule 96(4A)' | 'S.O. 1365(E) Sr.26'
  vehicle_categories TEXT[] DEFAULT '{}',
  applies_to         TEXT,                  -- new_types | all_models | registered_vehicles
  effective_date     DATE,
  provision_id       BIGINT NOT NULL REFERENCES notification_provision(id),
  is_draft           BOOLEAN NOT NULL,      -- proposed vs in force
  valid_from         DATE,
  valid_to           DATE,                  -- set when a later notification changes it
  superseded_by      BIGINT REFERENCES standard_mandate(id)
);

-- ================= CROSS-REFERENCES & SEARCH =================
CREATE TABLE document_reference (
  id               BIGSERIAL PRIMARY KEY,
  document_file_id BIGINT NOT NULL REFERENCES document_file(id),
  ref_kind         TEXT NOT NULL,           -- AIS | IS | UN_R | ISO | IEC | SO | GSR | CMVR_RULE | MV_ACT
  ref_code         TEXT NOT NULL,           -- normalised: 'AIS-038(Rev.1)', 'UN R136', 'Rule 2(u)'
  context          TEXT,                    -- sentence it appears in
  page             INT
);
CREATE INDEX ON document_reference(ref_kind, ref_code);

CREATE TABLE section_chunk (                -- clause-aware chunks, not fixed-size
  id               BIGSERIAL PRIMARY KEY,
  document_file_id BIGINT NOT NULL REFERENCES document_file(id),
  chunk_index      INT NOT NULL,
  part             TEXT,                    -- 'Part I'
  clause_no        TEXT,                    -- '6.12' | 'Annex 8J'
  heading          TEXT,
  from_amendment   INT,                     -- clause text that came from Amendment N
  language         TEXT DEFAULT 'en',
  page_from        INT,
  page_to          INT,
  content          TEXT NOT NULL,
  is_boilerplate   BOOLEAN DEFAULT FALSE,   -- committee lists, checklists → excluded from search
  embedding        vector(768),
  UNIQUE (document_file_id, chunk_index)
);
CREATE INDEX ON section_chunk USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON section_chunk USING gin (content gin_trgm_ops);

-- ================= CHANGES & REVIEW =================
CREATE TABLE change_event (
  id            BIGSERIAL PRIMARY KEY,
  detected_at   TIMESTAMPTZ DEFAULT now(),
  event_type    TEXT NOT NULL,   -- new_draft_ais | draft_withdrawn | ais_published | new_amendment | reissue
                                 -- | new_draft_notification | notification_finalised | effective_date_changed | listing_edited
  source_record_id BIGINT REFERENCES source_record(id),
  ais_standard_id  BIGINT REFERENCES ais_standard(id),
  notification_id  BIGINT REFERENCES notification(id),
  old_file_id   BIGINT REFERENCES document_file(id),
  new_file_id   BIGINT REFERENCES document_file(id),
  diff_text     TEXT,
  summary       TEXT,            -- Qwen
  impact        TEXT,            -- High|Medium|Low (Qwen, reviewed)
  review_status TEXT DEFAULT 'unreviewed'
);

CREATE TABLE review_task (
  id          BIGSERIAL PRIMARY KEY,
  entity_type TEXT NOT NULL,
  entity_id   BIGINT NOT NULL,
  reason      TEXT,              -- low_confidence | title_file_mismatch | duplicate | parse_failed
  status      TEXT DEFAULT 'open',
  created_at  TIMESTAMPTZ DEFAULT now(),
  resolved_by TEXT,
  resolved_at TIMESTAMPTZ
);
```

### 2.2 Why each table exists (traced to evidence)

| Table | Evidence |
|---|---|
| `source_record` + `gone_at` | ARAI drafts leave the Draft list when published; listings get edited (remarks) |
| `document_file.is_current` | ARAI re-issues the same code with a new file ("re-issued for editorial reason") |
| `ais_document` fields | Every element of the real `code` strings: Part, Rev, year, Amd. 1 to N, Corrigendum, D1/DF/F, Draft Amd N, Table 24A, hosting date, comments date |
| `ais_amendment` | AIS-156 has five dated amendment sections with add/substitute instructions |
| `scope_text`, `vehicle_categories` | Applicability is written in the scope clause ("category L, Rule 2(u) of CMVR") |
| `transitional_text`, no date column on standards | Standards say the date is "stipulated in the notification" |
| `notification` fields | Gazette ID, Part/Section, issue no., file no., signatory, draft marker, bilingual layout seen on S.O. 4143(E) and G.S.R. 415(E) |
| `notification_provision` | Notifications amend CMVR rules or rows of S.O. 1365(E), with absolute or relative dates |
| `standard_mandate` | Needed to answer "what applies to an L2 EV today, and from when" |
| `document_reference` | Standards cite AIS, IS, UN R, ISO and IEC documents; notifications cite rules and earlier notifications |
| `section_chunk.clause_no / is_boilerplate` | Clause-numbered documents; committee annexes are noise |
| `review_task` reasons | MoRTH duplicates, title/file mismatches, broken links |

---

## 3. Pipeline

```
LIST → DIFF LISTING → DOWNLOAD → HASH → STORE → EXTRACT → CLASSIFY → PARSE (rules + Qwen) → LINK → CHUNK+EMBED → EVENTS
```

1. **List**
   - ARAI: Published + Draft lists, rendered with Playwright.
   - MoRTH: the `gazettes-notifications` JSON, filtered to group = "Motor Vehicle Legislation", plus `home-page-data` for new AIS drafts.
   - e-Gazette: later, Playwright, Ministry = Road Transport and Highways.
2. **Diff listing:** upsert `source_record` and compare `content_hash`. Rows that are no longer listed get `gone_at`.
3. **Download / hash / store:** SHA-256 of each file; new hash → new `document_file`, and the old one gets `is_current = false`.
4. **Extract:**
   - PDF: PyMuPDF per page; check for a text layer and for Devanagari script.
   - DOC/DOCX: LibreOffice converts to PDF, then extract the same way.
   - For notifications, keep only the **English half** for parsing; store both halves.
5. **Classify** (rules first, Qwen as fallback): `ais_document | notification | list | manual | other`. Regex on the first page: "AUTOMOTIVE INDUSTRY STANDARD", "The Gazette of India", "G.S.R.", "S.O.".
6. **Parse**
   - **Deterministic regex** for anything with a fixed format: the ARAI `code` string, Gazette ID, `G.S.R. 415(E)`, dates, file no.
   - **Qwen** for:
     - the scope clause → vehicle categories
     - transitional provisions
     - the amendment instructions table
     - notification provisions (action / target / new text / effective date / standards cited)
     - "deemed to comply / replaces"
7. **Link**
   - draft ↔ final notification (same subject; the final cites the draft)
   - provision → `standard_mandate`, closing the previous row (`valid_to`)
   - references → known standards
8. **Chunk + embed:** split by clause numbers (`^\d+(\.\d+)*\s`) and Annex headings; mark committee/checklist pages as boilerplate.
9. **Events + review:** emit `change_event`s. Anything with confidence < 0.7, a title/file mismatch or a duplicate goes to `review_task`.

Resumable by `document_file.stage`, so the crawl keeps running while the Qwen laptop is offline.

---

## 4. Qwen 3.8 27B (LM Studio) — what it is used for

Use plain `ChatOpenAI(...).with_structured_output(Model, method="json_schema")`, not agents. Give it **only the relevant section**: cover page + scope + transitional clause + amendment pages for standards, and the English half for notifications. Never send a whole 700-page document.

```python
class AisParse(BaseModel):
    std_key: str                      # 'AIS-156'
    parts: list[str]                  # ['Part I: electrical safety', 'Part II: REESS']
    cover_date: str | None            # 'September 2020'
    scope_text: str
    vehicle_categories: list[str]     # ['L'] or ['M1','N1']
    powertrain: Literal["ICE","EV","ALL","UNSPECIFIED"]
    transitional_text: str | None
    replaces: list[str]               # ['AIS-038 (Rev 1)', 'AIS-048']
    amendments: list[AmendmentEntry]  # no, month, [{action, clause, after}]
    confidence: float

class NotificationParse(BaseModel):
    series: Literal["G.S.R.","S.O.","O.M.","OTHER"]
    number: str; suffix: str | None; notif_date: date | None
    gazette_id: str | None; gazette_part: str | None
    is_draft: bool; comment_days: int | None
    parent_instrument: str            # 'CMVR 1989' | 'S.O. 1365(E) dated 13.12.2004'
    subject: str
    provisions: list[Provision]       # action, target_kind, target_ref, new_text,
                                      # effective_date | effective_rule, vehicle_categories, standards_cited
    confidence: float
```

Things to test before relying on it:
- Can it read the Hindi half (and does that even matter, given the English half exists)?
- Does your LM Studio build accept page images (for scanned notifications from 1989–2005)?
- What context length did you set?

---

## 5. How the UI uses it later (read-only API)

| Question a user asks | Query |
|---|---|
| What applies to an L2 EV today? | `standard_mandate` where `'L2' = ANY(vehicle_categories) OR 'L' = ANY(…)`, `is_draft = false`, `valid_to IS NULL`, joined to `ais_standard` / latest `ais_document` |
| What's proposed but not yet law? | same with `is_draft = true` + open AIS drafts (`ais_document.status = 'draft'`, `comments_due >= today`) |
| What changed this week? | `change_event` ordered by `detected_at` |
| Show me the official document | `document_file.storage_path` / `viewer_pdf_path` |
| Where does a standard come from legally? | `standard_mandate.provision_id → notification` (Gazette ID, date, PDF) |
| Ask a question | embed → `section_chunk` (non-boilerplate) → Qwen answer citing clause + document |

---

## 6. Build order

1. Docker Postgres + pgvector, `schema.sql`, seed `source`
2. **MoRTH API lister** (easiest: public JSON) → `source_record` → download → `document_file`
3. ARAI lister via Playwright → `source_record`
4. Extraction (PDF, DOC/DOCX) + classifier
5. Regex parsers: ARAI `code` strings, notification headers (unit tests using the real strings in section 1)
6. Qwen parsers: `AisParse`, `NotificationParse` → review queue
7. Linking → `standard_mandate`
8. Clause chunking + embeddings
9. Change events, scheduler (6 h), read API

## 7. Open questions for the TL

- [ ] Is automated access to ARAI's list allowed (the page uses a bearer token)? Should we use Playwright or request access?
- [ ] Do we need the **S.O. 1365(E) master table** (2004 + all amendments) seeded first? Notifications reference its row numbers.
- [ ] Scope of MoRTH groups: only "Motor Vehicle Legislation", or also Acts & Rules (CMVR consolidated text)?
- [ ] History depth: everything since 1989, or from a cut-off year?
- [ ] e-Gazette in phase 1, or later as verification only?
