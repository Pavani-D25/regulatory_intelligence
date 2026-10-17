-- 0007: the v4B schema (docs/SCHEMA_V4B.md): ERD v4 plus the tables that keep RegTrack's capabilities.
-- Creates every v4B table NEXT TO the existing ones and copies the data across. The existing tables are not
-- changed; the code keeps using them until it has moved (phases 2-7), and they are dropped in a later migration.
-- Ids are kept wherever a table has a direct predecessor, so links stay valid and rows can be compared 1:1.

-- =====================================================================================================
-- Reference
-- =====================================================================================================
CREATE TABLE regions (
  id           SERIAL PRIMARY KEY,
  code         VARCHAR(10)  NOT NULL UNIQUE,                 -- IN, TH, MY, EU, UN
  slug         VARCHAR(50)  NOT NULL UNIQUE,
  name         VARCHAR(100) NOT NULL,
  timezone     VARCHAR(50)  NOT NULL DEFAULT 'UTC',
  metadata     JSONB        NOT NULL DEFAULT '{}',
  is_active    BOOLEAN      NOT NULL DEFAULT TRUE,
  languages    TEXT[]       NOT NULL DEFAULT '{}',           -- first = language the pipeline reads
  year_offset  INT          NOT NULL DEFAULT 0,              -- local year - year_offset = CE year (TH 543)
  currency     VARCHAR(3),
  created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);
INSERT INTO regions (code, slug, name, timezone, languages, year_offset, currency)
  SELECT code, trim(both '-' from lower(regexp_replace(name, '[^A-Za-z]+', '-', 'g'))), name, timezone, languages,
         year_offset, currency
  FROM country
  ORDER BY CASE code WHEN 'IN' THEN 1 WHEN 'TH' THEN 2 WHEN 'MY' THEN 3 WHEN 'UN' THEN 4 ELSE 5 END, code;
INSERT INTO regions (code, slug, name, timezone, languages, year_offset, currency)
  VALUES ('EU', 'europe', 'Europe', 'Europe/Brussels', ARRAY['en'], 0, 'EUR')
ON CONFLICT (code) DO NOTHING;

CREATE TABLE regulatory_authorities (
  id           SERIAL PRIMARY KEY,
  region_id    INT REFERENCES regions(id),                     -- NULL = supranational
  code         VARCHAR(20)  NOT NULL UNIQUE,
  name         VARCHAR(150) NOT NULL,
  website_url  VARCHAR(500)
);
INSERT INTO regulatory_authorities (region_id, code, name, website_url)
  SELECT r.id, a.code, a.name, a.url
  FROM (VALUES
    ('IN', 'MORTH',            'Ministry of Road Transport and Highways',                 'https://morth.gov.in'),
    ('IN', 'AISC_ARAI',        'Automotive Industry Standards Committee / ARAI',          'https://www.araiindia.com'),
    ('IN', 'BIS',              'Bureau of Indian Standards',                              'https://www.bis.gov.in'),
    ('IN', 'MOEFCC',           'Ministry of Environment, Forest and Climate Change',      'https://moef.gov.in'),
    ('IN', 'MOPNG',            'Ministry of Petroleum and Natural Gas',                   'https://mopng.gov.in'),
    ('IN', 'MOP_BEE',          'Ministry of Power / Bureau of Energy Efficiency',         'https://beeindia.gov.in'),
    ('IN', 'MOHI',             'Ministry of Heavy Industries',                            'https://heavyindustries.gov.in'),
    ('IN', 'LAW_MINISTRY',     'Ministry of Law and Justice (Legislative Department)',    'https://legislative.gov.in'),
    ('IN', 'MOF',              'Ministry of Finance',                                     'https://finmin.gov.in'),
    ('IN', 'STATE_GOVERNMENT', 'State Government',                                        NULL),
    ('TH', 'TISI',             'Thai Industrial Standards Institute',                     'https://www.tisi.go.th'),
    ('TH', 'DLT',              'Department of Land Transport',                            'https://www.dlt.go.th'),
    ('TH', 'MOI_TH',           'Ministry of Industry (Thailand)',                         'https://www.industry.go.th'),
    ('TH', 'PCD',              'Pollution Control Department',                            'https://www.pcd.go.th'),
    ('UN', 'UNECE',            'UNECE World Forum for Harmonization of Vehicle Regulations (WP.29)', 'https://unece.org')
  ) AS a(region, code, name, url)
  JOIN regions r ON r.code = a.region
ON CONFLICT (code) DO NOTHING;
-- any other issuer found in documents (code derived the same way everywhere: upper case, non-letters -> _)
INSERT INTO regulatory_authorities (region_id, code, name)
  SELECT DISTINCT ON (2) r.id, left(upper(trim(both '_' from regexp_replace(d.issuer, '[^A-Za-z0-9]+', '_', 'g'))), 20), d.issuer
  FROM document d JOIN regions r ON r.code = d.country
  WHERE d.issuer IS NOT NULL
ON CONFLICT (code) DO NOTHING;

CREATE TABLE sources (
  id                      SERIAL PRIMARY KEY,
  region_id               INT          NOT NULL REFERENCES regions(id),
  authority_id            INT          REFERENCES regulatory_authorities(id),
  code                    VARCHAR(30)  NOT NULL UNIQUE,        -- MORTH_API, ARAI_AIS, LOCAL_SEED
  name                    VARCHAR(150) NOT NULL,
  base_url                VARCHAR(500),
  scraper_key             VARCHAR(50),                         -- reading program; NULL = none (seed folder)
  config                  JSONB        NOT NULL DEFAULT '{}',
  field_mapping           JSONB        NOT NULL DEFAULT '{}',
  is_active               BOOLEAN      NOT NULL DEFAULT TRUE,
  sync_frequency_minutes  INT          NOT NULL DEFAULT 360,   -- 0 = never automatically
  last_synced_at          TIMESTAMPTZ,
  last_sync_status        VARCHAR(20)  CHECK (last_sync_status IN ('running','success','warning','failed')),
  UNIQUE (region_id, name)
);
INSERT INTO sources (id, region_id, authority_id, code, name, base_url, scraper_key, is_active, sync_frequency_minutes,
                     last_synced_at, last_sync_status)
  SELECT s.id, r.id, a.id, s.code, s.name, s.base_url,
         CASE s.code WHEN 'MORTH_API' THEN 'morth' WHEN 'ARAI_AIS' THEN 'arai'
                     WHEN 'EGAZETTE' THEN 'egazette' WHEN 'INDIACODE' THEN 'indiacode' END,
         s.schedule_hours > 0 OR s.code = 'LOCAL_SEED',
         s.schedule_hours * 60, s.last_run_at,
         CASE s.last_status WHEN 'ok' THEN 'success' WHEN 'partial' THEN 'warning'
                            WHEN 'failed' THEN 'failed' WHEN 'running' THEN 'running' END
  FROM source s
  JOIN regions r ON r.code = s.country
  LEFT JOIN regulatory_authorities a ON a.code = CASE
         WHEN s.code = 'MORTH_API' THEN 'MORTH'
         WHEN s.code IN ('ARAI_AIS', 'ARAI_TAP') THEN 'AISC_ARAI'
         WHEN s.code LIKE 'TH_TISI%' THEN 'TISI'
         WHEN s.code = 'TH_DLT' THEN 'DLT'
         WHEN s.code = 'TH_INDUSTRY' THEN 'MOI_TH'
         WHEN s.code = 'TH_PCD' THEN 'PCD' END
  ORDER BY s.id;

CREATE TABLE domains (
  id           SERIAL PRIMARY KEY,
  code         VARCHAR(30)  NOT NULL UNIQUE,                 -- BRAKING, NUMBER_PLATES
  name         VARCHAR(100) NOT NULL,
  description  TEXT
);
INSERT INTO domains (code, name) SELECT upper(code), label FROM domain ORDER BY code;

CREATE TABLE systems (
  id           SERIAL PRIMARY KEY,
  code         VARCHAR(30)  NOT NULL UNIQUE,                 -- ADAS_ECU, CONNECTIVITY
  name         VARCHAR(100) NOT NULL,
  description  TEXT
);

CREATE TABLE vehicle_categories (
  id         SERIAL PRIMARY KEY,
  region_id  INT          NOT NULL REFERENCES regions(id),   -- region UN holds the UNECE categories
  code       VARCHAR(20)  NOT NULL,
  label      VARCHAR(150) NOT NULL,
  un_codes   TEXT[]       NOT NULL DEFAULT '{}',             -- UNECE meaning (India L2 -> {L3})
  UNIQUE (region_id, code)
);
INSERT INTO vehicle_categories (region_id, code, label, un_codes)
  SELECT r.id, v.code, v.label, v.un_codes FROM vehicle_category v JOIN regions r ON r.code = v.country
  ORDER BY r.id, v.code;

CREATE TABLE region_scope (
  region_id            INT NOT NULL REFERENCES regions(id),
  vehicle_category_id  INT NOT NULL REFERENCES vehicle_categories(id),
  PRIMARY KEY (region_id, vehicle_category_id)
);
INSERT INTO region_scope (region_id, vehicle_category_id)
  SELECT r.id, vc.id FROM country_scope cs
  JOIN regions r ON r.code = cs.country
  JOIN vehicle_categories vc ON vc.region_id = r.id AND vc.code = cs.vehicle_category;

CREATE TABLE region_terms (
  id         SERIAL PRIMARY KEY,
  kind       VARCHAR(20) NOT NULL CHECK (kind IN ('vehicle_category','domain','doc_type','doc_role','status')),
  code       VARCHAR(50) NOT NULL,
  region_id  INT         REFERENCES regions(id),             -- NULL = every region
  language   VARCHAR(5)  NOT NULL,
  term       TEXT        NOT NULL,
  UNIQUE NULLS NOT DISTINCT (kind, code, region_id, language, term)
);
INSERT INTO region_terms (kind, code, region_id, language, term)
  SELECT t.kind, CASE WHEN t.kind = 'domain' THEN upper(t.code) ELSE t.code END, r.id, t.language, t.term
  FROM vocab_term t LEFT JOIN regions r ON r.code = t.country
  ORDER BY t.id
ON CONFLICT DO NOTHING;

CREATE TABLE document_classes (
  region_id  INT         NOT NULL REFERENCES regions(id),
  code       VARCHAR(40) NOT NULL,
  doc_type   VARCHAR(20) NOT NULL CHECK (doc_type IN ('LAW','REGULATION','TECHNICAL_STANDARD','PROCEDURE','GUIDANCE',
                                                      'REFERENCE','OFF_TOPIC','UNKNOWN')),
  doc_role   VARCHAR(20) CHECK (doc_role IN ('BASE','AMENDMENT','CORRIGENDUM','EXTENSION','EXEMPTION','REPEAL',
                                             'CONSOLIDATION','ANNEX','INTERPRETATION')),
  sub_type   VARCHAR(20),
  PRIMARY KEY (region_id, code)
);
INSERT INTO document_classes (region_id, code, doc_type, doc_role, sub_type)
  SELECT r.id, lc.code, lc.doc_type, lc.doc_role, lc.sub_type FROM local_class lc JOIN regions r ON r.code = lc.country;

CREATE TABLE teams (
  id    SERIAL PRIMARY KEY,
  code  VARCHAR(30)  NOT NULL UNIQUE,
  name  VARCHAR(100) NOT NULL UNIQUE
);
-- the portal's default owner becomes the default team; free-text owners used so far become teams too
INSERT INTO teams (code, name)
  SELECT 'REG_AFFAIRS', coalesce((SELECT value FROM app_setting WHERE key = 'default_owner'), 'Regulatory Affairs Team');
INSERT INTO teams (code, name)
  SELECT DISTINCT ON (1) left(upper(trim(both '_' from regexp_replace(o.owner, '[^A-Za-z0-9]+', '_', 'g'))), 30), o.owner
  FROM (SELECT owner FROM document_review UNION SELECT owner FROM compliance_item UNION SELECT owner FROM report_log) o
  WHERE coalesce(o.owner, '') <> '' AND o.owner NOT IN (SELECT name FROM teams)
ON CONFLICT (code) DO NOTHING;

CREATE TABLE users (
  id          SERIAL PRIMARY KEY,
  email       VARCHAR(255) NOT NULL UNIQUE,
  name        VARCHAR(150) NOT NULL,
  team_id     INT          REFERENCES teams(id),
  role        VARCHAR(30)  NOT NULL DEFAULT 'viewer',
  is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
  created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE app_settings (
  key    VARCHAR(60) PRIMARY KEY,
  value  JSONB       NOT NULL
);
INSERT INTO app_settings (key, value)
  SELECT key, CASE WHEN value ~ '^-?[0-9]+(\.[0-9]+)?$' OR value IN ('true', 'false') THEN value::jsonb
                   ELSE to_jsonb(value) END
  FROM app_setting;

-- =====================================================================================================
-- Ingestion
-- =====================================================================================================
CREATE TABLE ingestion_runs (
  id               BIGSERIAL PRIMARY KEY,
  source_id        INT         NOT NULL REFERENCES sources(id),
  started_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at      TIMESTAMPTZ,
  documents_found  INT,                                        -- listing rows seen
  changes_found    INT,                                        -- new files
  status           VARCHAR(20) NOT NULL DEFAULT 'running' CHECK (status IN ('running','success','warning','failed')),
  error_message    TEXT,                                       -- first line of the log
  stats            JSONB       NOT NULL DEFAULT '{}',          -- all counts
  log              TEXT
);
INSERT INTO ingestion_runs (id, source_id, started_at, finished_at, documents_found, changes_found, status, error_message,
                            stats, log)
  SELECT id, source_id, started_at, finished_at,
         coalesce((stats->>'seen')::int, (stats->>'files')::int),
         coalesce((stats->>'new_files')::int, (stats->>'file_object_new')::int),
         CASE status WHEN 'ok' THEN 'success' WHEN 'partial' THEN 'warning' ELSE status END,
         nullif(split_part(coalesce(log, ''), E'\n', 1), ''), stats, log
  FROM crawl_run ORDER BY id;
CREATE INDEX ingestion_runs_source_idx ON ingestion_runs (source_id, started_at DESC);

-- one row per stored file, identified by its content (write-once originals)
CREATE TABLE documents (
  id               BIGSERIAL PRIMARY KEY,
  region_id        INT         NOT NULL REFERENCES regions(id),
  checksum_sha256  CHAR(64)    NOT NULL UNIQUE,
  storage_path     TEXT        NOT NULL,                       -- STORAGE_DIR/<sha[:2]>/<sha>.<ext>
  file_name        TEXT,                                       -- as first listed (information only)
  original_url     TEXT,                                       -- first download URL (all are in raw_ingestion_records)
  file_ext         VARCHAR(10),
  mime_type        VARCHAR(100),
  file_size_bytes  BIGINT,
  download_status  VARCHAR(30) NOT NULL DEFAULT 'stored',
  downloaded_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  metadata         JSONB       NOT NULL DEFAULT '{}',          -- PDF metadata only
  page_count       INT,
  text_layer       BOOLEAN,
  scanned_pages    INT[]       NOT NULL DEFAULT '{}',
  ocr_engine       VARCHAR(30),
  ocr_confidence   NUMERIC(4,3),
  language_mix     JSONB,
  stage            VARCHAR(20) NOT NULL DEFAULT 'downloaded'
                   CHECK (stage IN ('downloaded','text','classified','parsed','linked','chunked','embedded','done','failed')),
  stage_error      TEXT
);
INSERT INTO documents (id, region_id, checksum_sha256, storage_path, file_name, original_url, file_ext, mime_type,
                       file_size_bytes, download_status, downloaded_at, metadata, page_count, text_layer, scanned_pages,
                       ocr_engine, ocr_confidence, language_mix, stage, stage_error)
  SELECT f.id, r.id, f.sha256, f.storage_path, fs.fname, fu.url, f.ext, f.mime, f.size_bytes, 'stored', f.first_seen_at,
         coalesce(f.pdf_meta, '{}'), f.page_count, f.text_layer, f.scanned_pages, f.ocr_engine, f.ocr_confidence,
         f.language_mix, f.stage, f.stage_error
  FROM file_object f
  JOIN regions r ON r.code = f.country
  LEFT JOIN LATERAL (SELECT coalesce(s.listing_raw->>'file_name', s.listing_title) AS fname FROM file_sighting s
                     WHERE s.file_id = f.id ORDER BY s.id LIMIT 1) fs ON true
  LEFT JOIN LATERAL (SELECT s.source_url AS url FROM file_sighting s
                     WHERE s.file_id = f.id AND s.source_url IS NOT NULL ORDER BY s.id LIMIT 1) fu ON true
  ORDER BY f.id;
CREATE INDEX documents_stage_idx ON documents (region_id, stage);

-- =====================================================================================================
-- Regulations
-- =====================================================================================================
CREATE TABLE regulations (
  id                          BIGSERIAL PRIMARY KEY,
  region_id                   INT          NOT NULL REFERENCES regions(id),
  external_code               VARCHAR(120) NOT NULL,           -- read from the content: SO-3896(E)-2022
  authority_id                INT          REFERENCES regulatory_authorities(id),
  title                       TEXT,                            -- English title
  title_native                TEXT,                            -- official-language title, when not English
  summary                     TEXT,
  local_class                 VARCHAR(40)  NOT NULL,           -- the region's own class
  doc_type                    VARCHAR(20)  CHECK (doc_type IN ('LAW','REGULATION','TECHNICAL_STANDARD','PROCEDURE',
                                                               'GUIDANCE','REFERENCE','OFF_TOPIC','UNKNOWN')),
  doc_role                    VARCHAR(20)  CHECK (doc_role IN ('BASE','AMENDMENT','CORRIGENDUM','EXTENSION','EXEMPTION',
                                                               'REPEAL','CONSOLIDATION','ANNEX','INTERPRETATION')),
  legal_force                 VARCHAR(20)  NOT NULL DEFAULT 'UNKNOWN'
                              CHECK (legal_force IN ('MANDATORY','VOLUNTARY','INFORMATIVE','UNKNOWN')),
  legal_status                VARCHAR(20)  NOT NULL CHECK (legal_status IN ('draft','final','superseded','withdrawn')),
  workflow_status             VARCHAR(20)  CHECK (workflow_status IN ('tracked','under_review','impact_analysis',
                                                                      'action_required')),
  impact_level                VARCHAR(10)  CHECK (impact_level IN ('high','medium','low')),
  impact_basis                VARCHAR(10)  CHECK (impact_basis IN ('rules','team')),
  owner_team_id               INT          REFERENCES teams(id),
  review_note                 TEXT,
  reviewed_at                 TIMESTAMPTZ,
  recommended_action          TEXT,
  detected_change             TEXT,
  local_type                  VARCHAR(30),                     -- S.O., G.S.R., AIS, กฎกระทรวง, P.U.(A)
  series                      TEXT,
  number                      TEXT,
  year                        INT,                             -- CE year
  part                        TEXT,
  revision                    INT,
  amendment_no                INT,
  corrigendum_no              INT,
  family_key                  TEXT,
  version_seq                 INT,
  is_current                  BOOLEAN      NOT NULL DEFAULT FALSE,
  published_date              DATE,                            -- date of issue
  published_date_precision    VARCHAR(5)   CHECK (published_date_precision IN ('day','month','year')),
  effective_date              DATE,
  nature                      VARCHAR(15)  CHECK (nature IN ('technical','administrative','procedural')),
  usage                       TEXT[]       NOT NULL DEFAULT '{}',
  powertrains                 TEXT[]       NOT NULL DEFAULT '{}',
  in_scope                    BOOLEAN,
  language                    VARCHAR(5),
  relevance                   JSONB,
  data                        JSONB        NOT NULL DEFAULT '{}',
  extraction                  JSONB,
  raw_attributes              JSONB        NOT NULL DEFAULT '{}',
  source_url                  TEXT,
  classification_method       VARCHAR(30),
  classification_confidence   NUMERIC(4,3),
  first_detected_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  created_at                  TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at                  TIMESTAMPTZ  NOT NULL DEFAULT now(),
  UNIQUE (region_id, external_code),
  FOREIGN KEY (region_id, local_class) REFERENCES document_classes (region_id, code)
);
INSERT INTO regulations (id, region_id, external_code, authority_id, title, title_native, summary, local_class, doc_type,
                         doc_role, legal_force, legal_status, workflow_status, impact_level, impact_basis, owner_team_id,
                         review_note, reviewed_at, local_type, series, number, year, part, revision, amendment_no,
                         corrigendum_no, family_key, version_seq, is_current, published_date, published_date_precision,
                         effective_date, nature, usage, powertrains, in_scope, language, relevance, data, extraction,
                         source_url, classification_method, first_detected_at, created_at, updated_at)
  SELECT d.id, r.id, d.canonical_id, a.id,
         CASE WHEN d.title_en IS NOT NULL THEN d.title_en ELSE d.official_title END,
         CASE WHEN d.title_en IS NOT NULL THEN d.official_title END,
         d.subject, d.doc_class, d.doc_type, d.doc_role, d.legal_force, d.status,
         CASE WHEN rv.status IS NOT NULL THEN replace(lower(rv.status), ' ', '_') END,
         lower(rv.impact), CASE WHEN rv.impact IS NOT NULL THEN 'team' END, t.id, rv.note, rv.updated_at,
         d.local_type, d.series, d.number, d.year, d.part, d.revision, d.amendment_no, d.corrigendum_no,
         d.family_key, d.version_seq, d.is_current, d.doc_date, d.doc_date_precision, d.effective_date, d.nature,
         d.usage, d.powertrains, d.in_scope, d.language, d.relevance, d.data, d.extraction, su.url, 'rules',
         d.created_at, d.created_at, d.updated_at
  FROM document d
  JOIN regions r ON r.code = d.country
  LEFT JOIN regulatory_authorities a
         ON a.code = left(upper(trim(both '_' from regexp_replace(d.issuer, '[^A-Za-z0-9]+', '_', 'g'))), 20)
  LEFT JOIN document_review rv ON rv.document_id = d.id
  LEFT JOIN teams t ON t.name = rv.owner
  LEFT JOIN LATERAL (SELECT s.source_url AS url FROM document_file df JOIN file_sighting s ON s.file_id = df.file_id
                     WHERE df.document_id = d.id AND s.source_url IS NOT NULL
                     ORDER BY df.is_best_copy DESC, s.id LIMIT 1) su ON true
  ORDER BY d.id;
CREATE UNIQUE INDEX regulations_one_current ON regulations (region_id, family_key) WHERE is_current AND family_key IS NOT NULL;
CREATE INDEX regulations_type_idx   ON regulations (region_id, doc_type, doc_role);
CREATE INDEX regulations_class_idx  ON regulations (region_id, local_class, published_date);
CREATE INDEX regulations_family_idx ON regulations (region_id, family_key, version_seq);
CREATE INDEX regulations_data_idx   ON regulations USING gin (data jsonb_path_ops);
CREATE INDEX regulations_title_trgm ON regulations USING gin (title gin_trgm_ops);

CREATE TABLE regulation_authorities (
  regulation_id  BIGINT      NOT NULL REFERENCES regulations(id) ON DELETE CASCADE,
  authority_id   INT         NOT NULL REFERENCES regulatory_authorities(id),
  role           VARCHAR(10) NOT NULL DEFAULT 'primary' CHECK (role IN ('primary','co_issuer')),
  PRIMARY KEY (regulation_id, authority_id)
);
CREATE UNIQUE INDEX regulation_authorities_one_primary ON regulation_authorities (regulation_id) WHERE role = 'primary';
INSERT INTO regulation_authorities (regulation_id, authority_id, role)
  SELECT id, authority_id, 'primary' FROM regulations WHERE authority_id IS NOT NULL;

CREATE TABLE regulation_domains (
  regulation_id  BIGINT  NOT NULL REFERENCES regulations(id) ON DELETE CASCADE,
  domain_id      INT     NOT NULL REFERENCES domains(id),
  is_primary     BOOLEAN NOT NULL DEFAULT FALSE,
  PRIMARY KEY (regulation_id, domain_id)
);
CREATE UNIQUE INDEX regulation_domains_one_primary ON regulation_domains (regulation_id) WHERE is_primary;
INSERT INTO regulation_domains (regulation_id, domain_id, is_primary)
  SELECT DISTINCT ON (d.id, dm.id) d.id, dm.id, x.n = 1
  FROM document d CROSS JOIN LATERAL unnest(d.domains) WITH ORDINALITY AS x(code, n)
  JOIN domains dm ON dm.code = upper(x.code)
  ORDER BY d.id, dm.id, x.n;
CREATE INDEX regulation_domains_domain_idx ON regulation_domains (domain_id);

CREATE TABLE regulation_systems (
  regulation_id  BIGINT NOT NULL REFERENCES regulations(id) ON DELETE CASCADE,
  system_id      INT    NOT NULL REFERENCES systems(id),
  PRIMARY KEY (regulation_id, system_id)
);

CREATE TABLE regulation_vehicle_categories (
  regulation_id        BIGINT NOT NULL REFERENCES regulations(id) ON DELETE CASCADE,
  vehicle_category_id  INT    NOT NULL REFERENCES vehicle_categories(id),
  PRIMARY KEY (regulation_id, vehicle_category_id)
);
INSERT INTO regulation_vehicle_categories (regulation_id, vehicle_category_id)
  SELECT DISTINCT d.id, vc.id
  FROM document d JOIN regions r ON r.code = d.country
  CROSS JOIN LATERAL unnest(d.vehicle_categories) AS x(code)
  JOIN vehicle_categories vc ON vc.region_id = r.id AND vc.code = x.code;
CREATE INDEX regulation_vehicle_categories_vc_idx ON regulation_vehicle_categories (vehicle_category_id);

-- one regulation's pages inside one stored file (a file can hold several regulations)
CREATE TABLE document_parts (
  regulation_id   BIGINT      NOT NULL REFERENCES regulations(id) ON DELETE CASCADE,
  document_id     BIGINT      NOT NULL REFERENCES documents(id),
  page_from       INT         NOT NULL DEFAULT 1,
  page_to         INT,
  language_pages  JSONB,                                       -- {"hi":[1,1],"en":[2,2]}
  part_label      TEXT,
  role            VARCHAR(25) NOT NULL DEFAULT 'main'
                  CHECK (role IN ('main','consolidated_segment','annex_table','historical_copy','other_language_only',
                                  'translation')),
  is_best_copy    BOOLEAN     NOT NULL DEFAULT FALSE,
  PRIMARY KEY (regulation_id, document_id, page_from)
);
INSERT INTO document_parts (regulation_id, document_id, page_from, page_to, language_pages, part_label, role, is_best_copy)
  SELECT document_id, file_id, page_from, page_to,
         coalesce(language_pages, CASE WHEN english_page_from IS NOT NULL
                                       THEN jsonb_build_object('en', jsonb_build_array(english_page_from, english_page_to)) END),
         part_label, CASE role WHEN 'hindi_only' THEN 'other_language_only' ELSE role END, is_best_copy
  FROM document_file;
CREATE INDEX document_parts_document_idx ON document_parts (document_id);

CREATE TABLE regulation_relations (
  id                   BIGSERIAL PRIMARY KEY,
  from_regulation_id   BIGINT      NOT NULL REFERENCES regulations(id) ON DELETE CASCADE,
  to_regulation_id     BIGINT      REFERENCES regulations(id),      -- NULL until the target arrives
  to_ref               TEXT,                                         -- the target's code
  type                 VARCHAR(20) NOT NULL CHECK (type IN ('amends','corrects','revises','supersedes','finalises',
                         'extends_date','exempts','mandates','inserts_row','substitutes_row','omits_row','annex_of',
                         'part_of','interprets','references','same_as','adopts','equivalent_to','repeals')),
  details              JSONB,
  evidence             TEXT,                                         -- the exact sentence
  page                 INT,
  confidence           NUMERIC(3,2),
  method               VARCHAR(10) CHECK (method IN ('regex','file_no','llm','manual')),
  requires_reapproval  BOOLEAN,
  CHECK (to_regulation_id IS NOT NULL OR to_ref IS NOT NULL)
);
INSERT INTO regulation_relations (id, from_regulation_id, to_regulation_id, to_ref, type, details, evidence, page, confidence,
                                  method, requires_reapproval)
  SELECT id, from_doc, to_doc, to_ref, type, details, evidence, page, confidence,
         CASE method WHEN 'qwen' THEN 'llm' ELSE method END, requires_reapproval
  FROM doc_relation ORDER BY id;
CREATE INDEX regulation_relations_from_idx ON regulation_relations (from_regulation_id);
CREATE INDEX regulation_relations_to_idx   ON regulation_relations (to_regulation_id);
CREATE INDEX regulation_relations_type_idx ON regulation_relations (type);
CREATE INDEX regulation_relations_ref_idx  ON regulation_relations (to_ref) WHERE to_regulation_id IS NULL;

-- the website listings (claims), now that files and regulations exist
CREATE TABLE raw_ingestion_records (
  id                         BIGSERIAL PRIMARY KEY,
  source_id                  INT         NOT NULL REFERENCES sources(id),
  ingestion_run_id           BIGINT      REFERENCES ingestion_runs(id),
  document_id                BIGINT      REFERENCES documents(id),     -- the file it led to
  external_ref               TEXT,                                     -- the source's own key
  source_url                 TEXT,
  listing_title              TEXT,                                     -- a claim, never trusted for identity
  listing_date               DATE,
  listing_category           TEXT,
  payload                    JSONB       NOT NULL DEFAULT '{}',        -- the full original listing
  processing_status          VARCHAR(20) NOT NULL DEFAULT 'new'
                             CHECK (processing_status IN ('new','downloaded','processed','needs_review','skipped','failed')),
  classification_method      VARCHAR(30),
  classification_verdict     BOOLEAN,
  classification_confidence  NUMERIC(4,3),
  regulation_id              BIGINT      REFERENCES regulations(id),   -- main regulation it was promoted to
  reviewed_by_user_id        INT         REFERENCES users(id),
  reviewed_at                TIMESTAMPTZ,
  review_decision            VARCHAR(20) CHECK (review_decision IN ('promoted','rejected')),
  first_seen_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
  gone_at                    TIMESTAMPTZ,
  UNIQUE (source_id, external_ref, document_id)
);
INSERT INTO raw_ingestion_records (id, source_id, ingestion_run_id, document_id, external_ref, source_url, listing_title,
                                   listing_date, listing_category, payload, processing_status, classification_method,
                                   classification_verdict, regulation_id, first_seen_at, last_seen_at, gone_at)
  SELECT s.id, s.source_id, s.crawl_run_id, s.file_id, s.source_item_id, s.source_url, s.listing_title, s.listing_date,
         s.listing_category, coalesce(s.listing_raw, '{}'),
         CASE WHEN f.id IS NULL THEN 'new' WHEN f.stage = 'downloaded' THEN 'downloaded'
              WHEN f.stage = 'failed' THEN 'failed' ELSE 'processed' END,
         CASE WHEN f.stage NOT IN ('downloaded', 'text') THEN 'rules' END,
         CASE WHEN f.stage NOT IN ('downloaded', 'text')
              THEN EXISTS (SELECT 1 FROM document_file df JOIN document d ON d.id = df.document_id
                           WHERE df.file_id = s.file_id AND d.doc_class <> 'OFF_TOPIC') END,
         (SELECT df.document_id FROM document_file df WHERE df.file_id = s.file_id
          ORDER BY (df.role = 'main') DESC, df.is_best_copy DESC, df.page_from, df.document_id LIMIT 1),
         s.seen_at, s.last_seen_at, s.gone_at
  FROM file_sighting s LEFT JOIN file_object f ON f.id = s.file_id
  ORDER BY s.id;
CREATE INDEX raw_ingestion_records_document_idx ON raw_ingestion_records (document_id);
CREATE INDEX raw_ingestion_records_status_idx   ON raw_ingestion_records (processing_status);

-- =====================================================================================================
-- Search
-- =====================================================================================================
CREATE TABLE document_chunks (
  id                    BIGSERIAL PRIMARY KEY,
  document_id           BIGINT      REFERENCES documents(id),             -- the file the text came from
  regulation_id         BIGINT      NOT NULL REFERENCES regulations(id) ON DELETE CASCADE,
  chunk_index           INT         NOT NULL,
  clause_no             TEXT,
  heading               TEXT,
  page_from             INT,
  page_to               INT,
  language              VARCHAR(5)  NOT NULL DEFAULT 'en',
  is_boilerplate        BOOLEAN     NOT NULL DEFAULT FALSE,
  content               TEXT        NOT NULL,
  embedding             vector(768),
  tsv                   tsvector,
  -- filter copies of the regulation, so search needs no joins
  region_id             INT         NOT NULL REFERENCES regions(id),
  doc_type              VARCHAR(20),
  legal_status          VARCHAR(20),
  is_current            BOOLEAN,
  in_scope              BOOLEAN,
  year                  INT,
  vehicle_category_ids  INT[]       NOT NULL DEFAULT '{}',
  domain_ids            INT[]       NOT NULL DEFAULT '{}',
  UNIQUE (regulation_id, chunk_index)
);
WITH vc AS (SELECT regulation_id, array_agg(vehicle_category_id ORDER BY vehicle_category_id) AS ids
            FROM regulation_vehicle_categories GROUP BY regulation_id),
     dm AS (SELECT regulation_id, array_agg(domain_id ORDER BY domain_id) AS ids
            FROM regulation_domains GROUP BY regulation_id)
INSERT INTO document_chunks (id, document_id, regulation_id, chunk_index, clause_no, heading, page_from, page_to, language,
                             is_boilerplate, content, embedding, tsv, region_id, doc_type, legal_status, is_current,
                             in_scope, year, vehicle_category_ids, domain_ids)
  SELECT c.id, c.file_id, c.document_id, c.chunk_index, c.clause_no, c.heading, c.page_from, c.page_to, c.language,
         c.is_boilerplate, c.content, c.embedding, c.tsv, rg.id, c.doc_type, c.status, c.is_current, c.in_scope, c.doc_year,
         coalesce(vc.ids, '{}'), coalesce(dm.ids, '{}')
  FROM chunk c
  JOIN regions rg ON rg.code = c.country
  LEFT JOIN vc ON vc.regulation_id = c.document_id
  LEFT JOIN dm ON dm.regulation_id = c.document_id
  ORDER BY c.id;
CREATE INDEX document_chunks_vec_idx      ON document_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX document_chunks_tsv_idx      ON document_chunks USING gin (tsv);
CREATE INDEX document_chunks_vc_idx       ON document_chunks USING gin (vehicle_category_ids);
CREATE INDEX document_chunks_filter_idx   ON document_chunks (region_id, in_scope, is_current);
CREATE INDEX document_chunks_document_idx ON document_chunks (document_id);

-- =====================================================================================================
-- Compliance
-- =====================================================================================================
-- one rule a region imposes, across all its versions
CREATE TABLE compliance_requirements (
  id                BIGSERIAL PRIMARY KEY,
  region_id         INT         NOT NULL REFERENCES regions(id),
  requirement_code  TEXT        NOT NULL,                      -- SO-1365(E)-2004 Table Sr.8(b)
  regulation_id     BIGINT      REFERENCES regulations(id),     -- legal basis document, if stored
  domain_id         INT         REFERENCES domains(id),
  owner_team_id     INT         REFERENCES teams(id),
  owner_user_id     INT         REFERENCES users(id),
  status            VARCHAR(20) NOT NULL DEFAULT 'open' CHECK (status IN ('open','in_progress','compliant','not_applicable')),
  due_date          DATE,                                       -- team override; default = current version's date
  evidence_links    JSONB       NOT NULL DEFAULT '[]',
  note              TEXT,
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (region_id, requirement_code)
);
INSERT INTO compliance_requirements (region_id, requirement_code, regulation_id)
  SELECT k.region_id, k.mandate_key,
         (SELECT g.id FROM regulations g WHERE g.region_id = k.region_id AND position(g.external_code IN k.legal_basis) = 1
          ORDER BY length(g.external_code) DESC LIMIT 1)
  FROM (SELECT DISTINCT ON (r.id, m.mandate_key) r.id AS region_id, m.mandate_key, m.legal_basis
        FROM mandate m JOIN regions r ON r.code = m.country
        ORDER BY r.id, m.mandate_key, m.id) k
  ORDER BY k.region_id, k.mandate_key;
-- the team's tracking (compliance_item) joins its rule
INSERT INTO compliance_requirements (region_id, requirement_code, owner_team_id, status, due_date, evidence_links, note,
                                     updated_at)
  SELECT r.id, ci.mandate_key, t.id, replace(lower(ci.status), ' ', '_'), ci.due_date,
         CASE WHEN coalesce(ci.evidence, '') <> ''
              THEN jsonb_build_array(jsonb_build_object('type', 'note', 'label', ci.evidence)) ELSE '[]'::jsonb END,
         ci.note, ci.updated_at
  FROM compliance_item ci JOIN regions r ON r.code = ci.country LEFT JOIN teams t ON t.name = ci.owner
ON CONFLICT (region_id, requirement_code) DO UPDATE
  SET owner_team_id = EXCLUDED.owner_team_id, status = EXCLUDED.status, due_date = EXCLUDED.due_date,
      evidence_links = EXCLUDED.evidence_links, note = EXCLUDED.note, updated_at = EXCLUDED.updated_at;

-- one version of a rule; never updated in place (a change closes the old version and adds a new one)
CREATE TABLE requirement_versions (
  id                       BIGSERIAL PRIMARY KEY,
  requirement_id           BIGINT      NOT NULL REFERENCES compliance_requirements(id) ON DELETE CASCADE,
  source_regulation_id     BIGINT      NOT NULL REFERENCES regulations(id),   -- the notice that wrote it
  legal_basis              TEXT        NOT NULL,
  subject                  TEXT,
  standard_refs            TEXT[]      NOT NULL DEFAULT '{}',
  standard_regulation_ids  BIGINT[]    NOT NULL DEFAULT '{}',
  vehicle_category_ids     INT[]       NOT NULL DEFAULT '{}',
  conditions               JSONB       NOT NULL DEFAULT '{}',
  model_scope              VARCHAR(25) CHECK (model_scope IN ('new_models','existing_models','all','registered_vehicles')),
  usage                    TEXT[]      NOT NULL DEFAULT '{}',
  powertrains              TEXT[]      NOT NULL DEFAULT '{}',
  date_of_notification     DATE,
  effective_date           DATE,
  implementation_date      DATE,
  implementation_rule      TEXT,
  is_draft                 BOOLEAN     NOT NULL,
  valid_from               DATE,
  valid_to                 DATE,
  superseded_by            BIGINT      REFERENCES requirement_versions(id),
  recorded_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)
);
INSERT INTO requirement_versions (id, requirement_id, source_regulation_id, legal_basis, subject, standard_refs,
                                  standard_regulation_ids, vehicle_category_ids, conditions, model_scope, usage, powertrains,
                                  date_of_notification, effective_date, implementation_date, implementation_rule, is_draft,
                                  valid_from, valid_to, superseded_by, recorded_at)
  SELECT m.id, cr.id, m.source_doc_id, m.legal_basis, m.subject, m.standard_refs, m.standard_doc_ids,
         coalesce((SELECT array_agg(vc.id ORDER BY vc.id) FROM unnest(m.vehicle_categories) AS x(code)
                   JOIN vehicle_categories vc ON vc.region_id = r.id AND vc.code = x.code), '{}'),
         m.conditions, m.model_scope, m.usage, m.powertrains, m.date_of_notification, m.effective_date,
         m.implementation_date, m.implementation_rule, m.is_draft, m.valid_from, m.valid_to, m.superseded_by, m.recorded_at
  FROM mandate m
  JOIN regions r ON r.code = m.country
  JOIN compliance_requirements cr ON cr.region_id = r.id AND cr.requirement_code = m.mandate_key
  ORDER BY m.id;
CREATE INDEX requirement_versions_req_idx  ON requirement_versions (requirement_id, valid_from);
CREATE INDEX requirement_versions_src_idx  ON requirement_versions (source_regulation_id);
CREATE INDEX requirement_versions_impl_idx ON requirement_versions (implementation_date);
CREATE INDEX requirement_versions_vc_idx   ON requirement_versions USING gin (vehicle_category_ids);

CREATE TABLE impact_assessments (
  id                   SERIAL PRIMARY KEY,
  region_id            INT         NOT NULL REFERENCES regions(id),
  domain_id            INT         NOT NULL REFERENCES domains(id),
  vehicle_category_id  INT         REFERENCES vehicle_categories(id),
  system_id            INT         REFERENCES systems(id),
  exposure_score       SMALLINT    CHECK (exposure_score BETWEEN 1 AND 5),
  notes                TEXT,
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE NULLS NOT DISTINCT (region_id, domain_id, vehicle_category_id, system_id)
);

-- =====================================================================================================
-- Monitoring
-- =====================================================================================================
CREATE TABLE regulation_changes (
  id                      BIGSERIAL PRIMARY KEY,
  region_id               INT         NOT NULL REFERENCES regions(id),
  regulation_id           BIGINT      REFERENCES regulations(id),
  requirement_version_id  BIGINT      REFERENCES requirement_versions(id),
  change_type             VARCHAR(30) NOT NULL CHECK (change_type IN ('new_document','new_amendment','new_revision',
                            'corrigendum','draft_published','draft_finalised','implementation_date_changed',
                            'mandate_superseded','file_reissued','listing_removed')),
  severity                VARCHAR(10) CHECK (severity IN ('high','medium','low')),
  detected_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  summary                 TEXT,
  diff                    JSONB,
  details                 JSONB,
  review_status           VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (review_status IN ('pending','reviewed')),
  reviewed_by_team_id     INT         REFERENCES teams(id),
  reviewed_by_user_id     INT         REFERENCES users(id),
  reviewed_at             TIMESTAMPTZ,
  sla_due_at              TIMESTAMPTZ
);
INSERT INTO regulation_changes (id, region_id, regulation_id, requirement_version_id, change_type, severity, detected_at,
                                summary, details, review_status, reviewed_at, sla_due_at)
  SELECT e.id, r.id, e.document_id, e.mandate_id, e.event_type,
         CASE WHEN lower(e.impact) IN ('high','medium','low') THEN lower(e.impact) END,
         e.detected_at, e.summary,
         coalesce(e.details, '{}') || jsonb_build_object('legacy_review_status', e.review_status),
         CASE e.review_status WHEN 'confirmed' THEN 'reviewed' ELSE 'pending' END,
         (e.details->>'reviewed_at')::timestamptz,
         e.detected_at + make_interval(days => coalesce((SELECT value::int FROM app_setting WHERE key = 'review_sla_days'), 2))
  FROM change_event e JOIN regions r ON r.code = e.country
  ORDER BY e.id;
CREATE INDEX regulation_changes_time_idx   ON regulation_changes (region_id, detected_at DESC);
CREATE INDEX regulation_changes_review_idx ON regulation_changes (review_status);

CREATE TABLE quality_flags (
  id           BIGSERIAL PRIMARY KEY,
  entity       VARCHAR(30) NOT NULL CHECK (entity IN ('document','regulation','requirement_version','source')),
  entity_id    BIGINT      NOT NULL,
  rule         VARCHAR(60) NOT NULL,
  details      JSONB,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at  TIMESTAMPTZ
);
-- today's names -> v4 names: a file is now a "document", a document a "regulation", a mandate a "requirement_version"
INSERT INTO quality_flags (id, entity, entity_id, rule, details, created_at, resolved_at)
  SELECT id, CASE entity WHEN 'file_object' THEN 'document' WHEN 'file' THEN 'document'
                         WHEN 'document' THEN 'regulation' WHEN 'mandate' THEN 'requirement_version' ELSE entity END,
         entity_id, rule, details, created_at, resolved_at
  FROM quality_flag ORDER BY id;
CREATE INDEX quality_flags_open_idx   ON quality_flags (rule) WHERE resolved_at IS NULL;
CREATE INDEX quality_flags_entity_idx ON quality_flags (entity, entity_id);

CREATE TABLE alert_rules (
  id                         SERIAL PRIMARY KEY,
  name                       VARCHAR(150) NOT NULL,
  scope_region_id            INT          REFERENCES regions(id),
  scope_domain_id            INT          REFERENCES domains(id),
  scope_vehicle_category_id  INT          REFERENCES vehicle_categories(id),
  condition                  JSONB        NOT NULL,           -- {"type":"due_within","param":"60"}
  is_enabled                 BOOLEAN      NOT NULL DEFAULT TRUE,
  notify_team_id             INT          NOT NULL REFERENCES teams(id),
  created_at                 TIMESTAMPTZ  NOT NULL DEFAULT now()
);
INSERT INTO alert_rules (id, name, scope_region_id, scope_domain_id, scope_vehicle_category_id, condition, is_enabled,
                         notify_team_id, created_at)
  SELECT a.id, a.name, r.id, dm.id, vc.id,
         jsonb_build_object('type', a.condition)
           || CASE WHEN a.param IS NOT NULL AND a.condition <> 'domain' THEN jsonb_build_object('param', a.param)
                   ELSE '{}'::jsonb END,
         a.enabled, (SELECT id FROM teams WHERE code = 'REG_AFFAIRS'), a.created_at
  FROM alert_rule a
  JOIN regions r ON r.code = a.country
  LEFT JOIN domains dm ON a.condition = 'domain' AND dm.code = upper(a.param)
  LEFT JOIN vehicle_categories vc ON vc.region_id = r.id AND vc.code = a.scope
  ORDER BY a.id;

CREATE TABLE alert_events (
  id             BIGSERIAL PRIMARY KEY,
  rule_id        INT         NOT NULL REFERENCES alert_rules(id) ON DELETE CASCADE,
  regulation_id  BIGINT      REFERENCES regulations(id),
  triggered_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  message        TEXT        NOT NULL,
  is_resolved    BOOLEAN     NOT NULL DEFAULT FALSE,
  resolved_at    TIMESTAMPTZ
);
CREATE INDEX alert_events_open_idx ON alert_events (rule_id, triggered_at DESC) WHERE NOT is_resolved;

CREATE TABLE regulation_watches (
  id               BIGSERIAL PRIMARY KEY,
  regulation_id    BIGINT      NOT NULL REFERENCES regulations(id) ON DELETE CASCADE,
  watcher_user_id  INT         REFERENCES users(id),
  watcher_team_id  INT         REFERENCES teams(id),
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (num_nonnulls(watcher_user_id, watcher_team_id) = 1),
  UNIQUE NULLS NOT DISTINCT (regulation_id, watcher_user_id, watcher_team_id)
);

-- =====================================================================================================
-- Reports and assistant
-- =====================================================================================================
CREATE TABLE report_templates (
  id    SERIAL PRIMARY KEY,
  code  VARCHAR(30)  NOT NULL UNIQUE,
  name  VARCHAR(150) NOT NULL
);
INSERT INTO report_templates (code, name) VALUES
  ('EXEC_SUMMARY',   'Executive Regulatory Summary'),
  ('COMPLIANCE_GAP', 'Compliance Gap Report'),
  ('CHANGE_IMPACT',  'Change Impact Report');

CREATE TABLE reports (
  id                   BIGSERIAL PRIMARY KEY,
  template_id          INT         NOT NULL REFERENCES report_templates(id),
  scope_region_id      INT         REFERENCES regions(id),
  generated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  owner_team_id        INT         NOT NULL REFERENCES teams(id),
  status               VARCHAR(20) NOT NULL DEFAULT 'published' CHECK (status IN ('draft','review','published')),
  parameters           JSONB       NOT NULL DEFAULT '{}',
  file_path            TEXT,
  approved_by_user_id  INT         REFERENCES users(id)
);
INSERT INTO reports (template_id, scope_region_id, generated_at, owner_team_id, parameters)
  SELECT rt.id, r.id, l.generated_at, coalesce(t.id, (SELECT id FROM teams WHERE code = 'REG_AFFAIRS')),
         jsonb_build_object('scope', l.scope, 'rows', l.rows)
  FROM report_log l
  JOIN report_templates rt ON rt.name = l.kind
  JOIN regions r ON r.code = l.country
  LEFT JOIN teams t ON t.name = l.owner
  ORDER BY l.id;

CREATE TABLE report_schedules (
  id               SERIAL PRIMARY KEY,
  template_id      INT         NOT NULL REFERENCES report_templates(id),
  scope_region_id  INT         REFERENCES regions(id),
  frequency        VARCHAR(20) NOT NULL CHECK (frequency IN ('daily','weekly','monthly','quarterly')),
  recipients       JSONB       NOT NULL DEFAULT '{}',          -- {"teams":[1],"users":[2]}
  next_run_at      TIMESTAMPTZ,
  is_active        BOOLEAN     NOT NULL DEFAULT TRUE
);

CREATE TABLE assistant_conversations (
  id          BIGSERIAL PRIMARY KEY,
  user_id     INT         REFERENCES users(id),
  started_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE assistant_messages (
  id               BIGSERIAL PRIMARY KEY,
  conversation_id  BIGINT      NOT NULL REFERENCES assistant_conversations(id) ON DELETE CASCADE,
  role             VARCHAR(10) NOT NULL CHECK (role IN ('user','assistant','system')),
  content          TEXT        NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE assistant_message_citations (
  id                 BIGSERIAL PRIMARY KEY,
  message_id         BIGINT       NOT NULL REFERENCES assistant_messages(id) ON DELETE CASCADE,
  regulation_id      BIGINT       REFERENCES regulations(id),
  document_chunk_id  BIGINT       REFERENCES document_chunks(id),
  score              NUMERIC(6,4),
  CHECK (regulation_id IS NOT NULL OR document_chunk_id IS NOT NULL)
);

-- =====================================================================================================
-- Client register
-- =====================================================================================================
CREATE TABLE client_requirements (
  id                SERIAL PRIMARY KEY,
  region_id         INT  NOT NULL REFERENCES regions(id),
  code              TEXT NOT NULL UNIQUE,                      -- TH-03
  topic             TEXT NOT NULL,
  requirement_text  TEXT,
  applies_to        TEXT,
  authority         TEXT,
  source_url        TEXT,
  source_name       TEXT,
  client_status     TEXT,
  caution           TEXT
);
INSERT INTO client_requirements (id, region_id, code, topic, requirement_text, applies_to, authority, source_url, source_name,
                                 client_status, caution)
  SELECT q.id, r.id, q.code, q.topic, q.requirement_text, q.applies_to, q.authority, q.source_url, q.source_name,
         q.client_status, q.caution
  FROM requirement q JOIN regions r ON r.code = q.country ORDER BY q.id;

CREATE TABLE client_requirement_regulations (
  requirement_id  INT         NOT NULL REFERENCES client_requirements(id) ON DELETE CASCADE,
  regulation_id   BIGINT      NOT NULL REFERENCES regulations(id) ON DELETE CASCADE,
  role            VARCHAR(12) NOT NULL DEFAULT 'candidate' CHECK (role IN ('primary','supporting','candidate','rejected')),
  matched_by      TEXT,
  note            TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (requirement_id, regulation_id)
);
INSERT INTO client_requirement_regulations (requirement_id, regulation_id, role, matched_by, note, created_at)
  SELECT requirement_id, document_id, role, matched_by, note, created_at FROM requirement_document;

-- =====================================================================================================
-- Continue numbering after the copied ids
-- =====================================================================================================
SELECT setval(pg_get_serial_sequence(t, 'id'), coalesce(m, 0) + 1, false)
FROM (VALUES
  ('sources',                 (SELECT max(id) FROM sources)),
  ('ingestion_runs',          (SELECT max(id) FROM ingestion_runs)),
  ('documents',               (SELECT max(id) FROM documents)),
  ('regulations',             (SELECT max(id) FROM regulations)),
  ('regulation_relations',    (SELECT max(id) FROM regulation_relations)),
  ('raw_ingestion_records',   (SELECT max(id) FROM raw_ingestion_records)),
  ('document_chunks',         (SELECT max(id) FROM document_chunks)),
  ('requirement_versions',    (SELECT max(id) FROM requirement_versions)),
  ('regulation_changes',      (SELECT max(id) FROM regulation_changes)),
  ('quality_flags',           (SELECT max(id) FROM quality_flags)),
  ('alert_rules',             (SELECT max(id) FROM alert_rules)),
  ('client_requirements',     (SELECT max(id) FROM client_requirements))
) AS s(t, m);
