-- RegTrack India — database schema (PostgreSQL 16 + pgvector)
-- Set vector(768) to the dimension of the embedding model loaded in LM Studio.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ===== lookups =====
CREATE TABLE vehicle_category (
  code      TEXT PRIMARY KEY,
  label     TEXT NOT NULL,
  synonyms  TEXT[] NOT NULL DEFAULT '{}',
  in_scope  BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE domain (
  code      TEXT PRIMARY KEY,
  label     TEXT NOT NULL,
  keywords  TEXT[] NOT NULL DEFAULT '{}'
);

-- ===== ingestion =====
CREATE TABLE source (
  id              SERIAL PRIMARY KEY,
  code            TEXT UNIQUE NOT NULL,
  name            TEXT NOT NULL,
  base_url        TEXT,
  schedule_hours  INT NOT NULL DEFAULT 6,
  last_run_at     TIMESTAMPTZ,
  last_status     TEXT
);

CREATE TABLE crawl_run (
  id           BIGSERIAL PRIMARY KEY,
  source_id    INT NOT NULL REFERENCES source(id),
  started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at  TIMESTAMPTZ,
  status       TEXT NOT NULL DEFAULT 'running'
               CHECK (status IN ('running','ok','partial','failed')),
  stats        JSONB NOT NULL DEFAULT '{}',
  log          TEXT
);

CREATE TABLE file_object (
  id              BIGSERIAL PRIMARY KEY,
  sha256          CHAR(64) UNIQUE NOT NULL,
  storage_path    TEXT NOT NULL,
  mime            TEXT,
  ext             TEXT,
  size_bytes      BIGINT,
  page_count      INT,
  text_layer      BOOLEAN,
  scanned_pages   INT[] NOT NULL DEFAULT '{}',
  ocr_engine      TEXT,
  ocr_confidence  NUMERIC(4,3),
  language_mix    JSONB,
  pdf_meta        JSONB,
  stage           TEXT NOT NULL DEFAULT 'downloaded'
                  CHECK (stage IN ('downloaded','text','classified','parsed','linked',
                                   'chunked','embedded','done','failed')),
  stage_error     TEXT,
  first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX file_object_stage_idx ON file_object (stage);

CREATE TABLE file_sighting (
  id                BIGSERIAL PRIMARY KEY,
  file_id           BIGINT NOT NULL REFERENCES file_object(id),
  source_id         INT NOT NULL REFERENCES source(id),
  crawl_run_id      BIGINT REFERENCES crawl_run(id),
  source_url        TEXT,
  source_item_id    TEXT,
  listing_title     TEXT,
  listing_date      DATE,
  listing_category  TEXT,
  listing_raw       JSONB,
  seen_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  gone_at           TIMESTAMPTZ,
  UNIQUE (source_id, source_item_id, file_id)
);
CREATE INDEX file_sighting_file_idx ON file_sighting (file_id);

-- ===== the regulatory object =====
CREATE TABLE document (
  id                  BIGSERIAL PRIMARY KEY,
  canonical_id        TEXT UNIQUE NOT NULL,
  doc_class           TEXT NOT NULL,
  series              TEXT,
  number              TEXT,
  year                INT,
  part                TEXT,
  revision            INT,
  amendment_no        INT,
  corrigendum_no      INT,
  family_key          TEXT,
  version_seq         INT,
  is_current          BOOLEAN NOT NULL DEFAULT FALSE,
  official_title      TEXT,
  subject             TEXT,
  issuer              TEXT,
  status              TEXT NOT NULL
                      CHECK (status IN ('draft','final','superseded','withdrawn')),
  doc_date            DATE,
  doc_date_precision  TEXT CHECK (doc_date_precision IN ('day','month','year')),
  nature              TEXT CHECK (nature IN ('technical','administrative','procedural')),
  vehicle_categories  TEXT[] NOT NULL DEFAULT '{}',
  usage               TEXT[] NOT NULL DEFAULT '{}',
  powertrains         TEXT[] NOT NULL DEFAULT '{}',
  domains             TEXT[] NOT NULL DEFAULT '{}',
  in_scope            BOOLEAN,
  relevance           JSONB,
  data                JSONB NOT NULL DEFAULT '{}',
  extraction          JSONB,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX document_data_idx     ON document USING gin (data jsonb_path_ops);
CREATE INDEX document_cat_idx      ON document USING gin (vehicle_categories);
CREATE INDEX document_domain_idx   ON document USING gin (domains);
CREATE INDEX document_class_date   ON document (doc_class, doc_date);
CREATE INDEX document_family_idx   ON document (family_key, version_seq);
CREATE INDEX document_title_trgm   ON document USING gin (official_title gin_trgm_ops);
CREATE UNIQUE INDEX document_one_current
  ON document (family_key) WHERE is_current AND family_key IS NOT NULL;

CREATE TABLE document_file (
  document_id        BIGINT NOT NULL REFERENCES document(id) ON DELETE CASCADE,
  file_id            BIGINT NOT NULL REFERENCES file_object(id),
  page_from          INT NOT NULL DEFAULT 1,
  page_to            INT,
  english_page_from  INT,
  english_page_to    INT,
  part_label         TEXT,
  role               TEXT NOT NULL DEFAULT 'main'
                     CHECK (role IN ('main','consolidated_segment','annex_table',
                                     'historical_copy','hindi_only')),
  is_best_copy       BOOLEAN NOT NULL DEFAULT FALSE,
  PRIMARY KEY (document_id, file_id, page_from)
);
CREATE INDEX document_file_file_idx ON document_file (file_id);

-- ===== meaning =====
CREATE TABLE doc_relation (
  id                   BIGSERIAL PRIMARY KEY,
  from_doc             BIGINT NOT NULL REFERENCES document(id) ON DELETE CASCADE,
  to_doc               BIGINT REFERENCES document(id),
  to_ref               TEXT,
  type                 TEXT NOT NULL,
  requires_reapproval  BOOLEAN,
  details              JSONB,
  evidence             TEXT,
  page                 INT,
  confidence           NUMERIC(3,2),
  method               TEXT CHECK (method IN ('regex','file_no','qwen')),
  CHECK (to_doc IS NOT NULL OR to_ref IS NOT NULL)
);
CREATE INDEX doc_relation_from_idx ON doc_relation (from_doc);
CREATE INDEX doc_relation_to_idx   ON doc_relation (to_doc);
CREATE INDEX doc_relation_type_idx ON doc_relation (type);
CREATE INDEX doc_relation_ref_idx  ON doc_relation (to_ref) WHERE to_doc IS NULL;

CREATE TABLE mandate (
  id                    BIGSERIAL PRIMARY KEY,
  legal_basis           TEXT NOT NULL,
  mandate_key           TEXT NOT NULL,
  subject               TEXT,
  standard_refs         TEXT[] NOT NULL DEFAULT '{}',
  standard_doc_ids      BIGINT[] NOT NULL DEFAULT '{}',
  vehicle_categories    TEXT[] NOT NULL DEFAULT '{}',
  conditions            JSONB NOT NULL DEFAULT '{}',
  model_scope           TEXT CHECK (model_scope IN ('new_models','existing_models',
                                                    'all','registered_vehicles')),
  usage                 TEXT[] NOT NULL DEFAULT '{}',
  powertrains           TEXT[] NOT NULL DEFAULT '{}',
  date_of_notification  DATE,
  effective_date        DATE,
  implementation_date   DATE,
  implementation_rule   TEXT,
  is_draft              BOOLEAN NOT NULL,
  source_doc_id         BIGINT NOT NULL REFERENCES document(id),
  valid_from            DATE,
  valid_to              DATE,
  superseded_by         BIGINT REFERENCES mandate(id),
  recorded_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)
);
CREATE INDEX mandate_cat_idx  ON mandate USING gin (vehicle_categories);
CREATE INDEX mandate_key_idx  ON mandate (mandate_key, valid_from);
CREATE INDEX mandate_impl_idx ON mandate (implementation_date);

CREATE TABLE chunk (
  id                  BIGSERIAL PRIMARY KEY,
  document_id         BIGINT NOT NULL REFERENCES document(id) ON DELETE CASCADE,
  file_id             BIGINT REFERENCES file_object(id),
  chunk_index         INT NOT NULL,
  clause_no           TEXT,
  heading             TEXT,
  page_from           INT,
  page_to             INT,
  language            TEXT NOT NULL DEFAULT 'en',
  is_boilerplate      BOOLEAN NOT NULL DEFAULT FALSE,
  content             TEXT NOT NULL,
  doc_class           TEXT,
  family_key          TEXT,
  vehicle_categories  TEXT[] NOT NULL DEFAULT '{}',
  domains             TEXT[] NOT NULL DEFAULT '{}',
  doc_year            INT,
  status              TEXT,
  is_current          BOOLEAN,
  in_scope            BOOLEAN,
  embedding           vector(768),
  UNIQUE (document_id, chunk_index)
);
CREATE INDEX chunk_vec_idx ON chunk USING hnsw (embedding vector_cosine_ops);
CREATE INDEX chunk_cat_idx ON chunk USING gin (vehicle_categories);

-- ===== operations =====
CREATE TABLE change_event (
  id             BIGSERIAL PRIMARY KEY,
  detected_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  event_type     TEXT NOT NULL,
  document_id    BIGINT REFERENCES document(id),
  mandate_id     BIGINT REFERENCES mandate(id),
  summary        TEXT,
  impact         TEXT,
  details        JSONB,
  review_status  TEXT NOT NULL DEFAULT 'auto'
                 CHECK (review_status IN ('auto','needs_check','confirmed'))
);
CREATE INDEX change_event_time_idx ON change_event (detected_at DESC);

CREATE TABLE quality_flag (
  id           BIGSERIAL PRIMARY KEY,
  entity       TEXT NOT NULL,
  entity_id    BIGINT NOT NULL,
  rule         TEXT NOT NULL,
  details      JSONB,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at  TIMESTAMPTZ
);
CREATE INDEX quality_flag_open_idx ON quality_flag (rule) WHERE resolved_at IS NULL;
