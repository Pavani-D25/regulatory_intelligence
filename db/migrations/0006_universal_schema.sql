-- 0006: make the schema country-neutral (design: docs/MULTI_COUNTRY_SCHEMA.md, docs/CLASSIFICATION_DESIGN.md).
-- Adds columns, lookups and keys, and fills them from existing data. No India row is deleted, and India's own
-- values (doc_class, vehicle_categories, dates, mandates) are not changed. One deliberate rename: topic 'hsrp'
-- becomes the universal 'number_plates'.
-- Runs after seed 0001 (regtrack/migrate.py orders files by number), so seeded rows exist on a fresh database too.

-- ============================================================ countries
ALTER TABLE country
  ADD COLUMN languages TEXT[] NOT NULL DEFAULT '{}',      -- first = language of the official texts the pipeline reads
  ADD COLUMN timezone  TEXT   NOT NULL DEFAULT 'UTC',
  ADD COLUMN currency  TEXT;
UPDATE country SET languages = ARRAY['en','hi'], timezone = 'Asia/Kolkata', currency = 'INR' WHERE code = 'IN';
UPDATE country SET languages = ARRAY['th','en'], timezone = 'Asia/Bangkok', currency = 'THB' WHERE code = 'TH';
INSERT INTO country (code, name, year_offset, language, languages, timezone, currency) VALUES
  ('MY', 'Malaysia', 0, 'ms', ARRAY['ms','en'], 'Asia/Kuala_Lumpur', 'MYR'),
  ('UN', 'UNECE (international regulations)', 0, 'en', ARRAY['en','fr','ru'], 'Europe/Zurich', NULL)
ON CONFLICT (code) DO NOTHING;

-- ============================================================ vehicle categories: local codes + UNECE meaning
-- India's codes keep India's meaning (India L2 = motorcycle = UNECE L3). Each local code maps to UNECE codes.
-- A country that uses UNECE codes unchanged needs no rows of its own: lookups fall back to country 'UN'.
ALTER TABLE vehicle_category
  ADD COLUMN country  TEXT   NOT NULL DEFAULT 'IN' REFERENCES country(code),
  ADD COLUMN un_codes TEXT[] NOT NULL DEFAULT '{}';
UPDATE vehicle_category SET un_codes = CASE code
    WHEN 'L2'          THEN ARRAY['L3']                       -- India: two-wheeler > 45 km/h (motorcycle)
    WHEN 'QUADRICYCLE' THEN ARRAY['L6','L7']
    WHEN 'E_RICKSHAW'  THEN ARRAY['L5']
    WHEN 'E_CART'      THEN ARRAY['L5']
    WHEN 'O'           THEN ARRAY['O1','O2','O3','O4']
    WHEN 'CEV'         THEN '{}'::TEXT[]                      -- construction equipment: no UNECE category
    ELSE ARRAY[code] END                                       -- L1, L3-L7, M1-M3, N1-N3, T, ALL: same meaning
  WHERE country = 'IN';
ALTER TABLE vehicle_category DROP CONSTRAINT vehicle_category_pkey, ADD PRIMARY KEY (country, code);

INSERT INTO vehicle_category (country, code, label, un_codes, in_scope) VALUES
 ('UN', 'L1', 'Two-wheeled moped (≤ 50 cm³ and ≤ 50 km/h)', ARRAY['L1'], FALSE),
 ('UN', 'L2', 'Three-wheeled moped (≤ 50 cm³ and ≤ 50 km/h)', ARRAY['L2'], FALSE),
 ('UN', 'L3', 'Motorcycle (two wheels, > 50 cm³ or > 50 km/h)', ARRAY['L3'], FALSE),
 ('UN', 'L4', 'Motorcycle with sidecar', ARRAY['L4'], FALSE),
 ('UN', 'L5', 'Motor tricycle (three symmetric wheels)', ARRAY['L5'], FALSE),
 ('UN', 'L6', 'Light quadricycle', ARRAY['L6'], FALSE),
 ('UN', 'L7', 'Quadricycle', ARRAY['L7'], FALSE),
 ('UN', 'M1', 'Passenger vehicle, ≤ 8 seats plus driver', ARRAY['M1'], FALSE),
 ('UN', 'M2', 'Passenger vehicle, > 8 seats, max. mass ≤ 5 t', ARRAY['M2'], FALSE),
 ('UN', 'M3', 'Passenger vehicle, > 8 seats, max. mass > 5 t', ARRAY['M3'], FALSE),
 ('UN', 'N1', 'Goods vehicle, max. mass ≤ 3.5 t', ARRAY['N1'], FALSE),
 ('UN', 'N2', 'Goods vehicle, 3.5 t < max. mass ≤ 12 t', ARRAY['N2'], FALSE),
 ('UN', 'N3', 'Goods vehicle, max. mass > 12 t', ARRAY['N3'], FALSE),
 ('UN', 'O1', 'Trailer, max. mass ≤ 0.75 t', ARRAY['O1'], FALSE),
 ('UN', 'O2', 'Trailer, 0.75 t < max. mass ≤ 3.5 t', ARRAY['O2'], FALSE),
 ('UN', 'O3', 'Trailer, 3.5 t < max. mass ≤ 10 t', ARRAY['O3'], FALSE),
 ('UN', 'O4', 'Trailer, max. mass > 10 t', ARRAY['O4'], FALSE),
 ('UN', 'T',  'Agricultural or forestry tractor', ARRAY['T'], FALSE),
 ('UN', 'ALL', 'All motor vehicles', ARRAY['ALL'], FALSE)
ON CONFLICT (country, code) DO NOTHING;

-- a country's local codes -> UNECE codes (sorted, without duplicates; unknown codes are left out)
CREATE FUNCTION un_vehicle_categories(cc TEXT, codes TEXT[]) RETURNS TEXT[]
LANGUAGE sql STABLE AS $$
  SELECT coalesce(array_agg(DISTINCT x.u ORDER BY x.u), '{}')
  FROM unnest(codes) AS c(code)
  CROSS JOIN LATERAL (SELECT v.un_codes FROM vehicle_category v
                      WHERE v.code = c.code AND v.country IN (cc, 'UN')
                      ORDER BY v.country = 'UN' LIMIT 1) m
  CROSS JOIN LATERAL unnest(m.un_codes) AS x(u)
$$;

-- what each country tracks (replaces the global vehicle_category.in_scope, which stays until 0007)
CREATE TABLE country_scope (
  country           TEXT NOT NULL REFERENCES country(code),
  vehicle_category  TEXT NOT NULL,
  PRIMARY KEY (country, vehicle_category)
);
INSERT INTO country_scope (country, vehicle_category)
  SELECT 'IN', code FROM vehicle_category WHERE country = 'IN' AND in_scope
ON CONFLICT DO NOTHING;

-- ============================================================ topics: 'hsrp' becomes the universal 'number_plates'
UPDATE domain SET code = 'number_plates', label = 'Number plates (incl. high security registration plates)'
  WHERE code = 'hsrp' AND NOT EXISTS (SELECT 1 FROM domain WHERE code = 'number_plates');
UPDATE document   SET domains = array_replace(domains, 'hsrp', 'number_plates') WHERE 'hsrp' = ANY(domains);
UPDATE chunk      SET domains = array_replace(domains, 'hsrp', 'number_plates') WHERE 'hsrp' = ANY(domains);
UPDATE alert_rule SET param = 'number_plates' WHERE condition = 'domain' AND param = 'hsrp';

-- ============================================================ words in any language
-- synonyms, topic keywords and classification clue words, per country (NULL = every country) and language
CREATE TABLE vocab_term (
  id        SERIAL PRIMARY KEY,
  kind      TEXT NOT NULL CHECK (kind IN ('vehicle_category','domain','doc_type','doc_role','status')),
  code      TEXT NOT NULL,
  country   TEXT REFERENCES country(code),
  language  TEXT NOT NULL,
  term      TEXT NOT NULL,
  UNIQUE NULLS NOT DISTINCT (kind, code, country, language, term)
);
INSERT INTO vocab_term (kind, code, country, language, term)
  SELECT 'vehicle_category', code, 'IN', 'en', unnest(synonyms) FROM vehicle_category WHERE country = 'IN'
ON CONFLICT DO NOTHING;
INSERT INTO vocab_term (kind, code, country, language, term)
  SELECT 'domain', code, 'IN', 'en', unnest(keywords) FROM domain
ON CONFLICT DO NOTHING;

-- ============================================================ country-neutral classification
-- local_class: each country's own classes (doc_class values) and what they mean everywhere.
-- doc_role NULL = decided from the document: AMENDMENT when it amends another document, else BASE.
CREATE TABLE local_class (
  country   TEXT NOT NULL REFERENCES country(code),
  code      TEXT NOT NULL,
  doc_type  TEXT NOT NULL CHECK (doc_type IN ('LAW','REGULATION','TECHNICAL_STANDARD','PROCEDURE','GUIDANCE',
                                              'REFERENCE','OFF_TOPIC','UNKNOWN')),
  doc_role  TEXT CHECK (doc_role IN ('BASE','AMENDMENT','CORRIGENDUM','EXTENSION','EXEMPTION','REPEAL',
                                     'CONSOLIDATION','ANNEX','INTERPRETATION')),
  sub_type  TEXT,
  PRIMARY KEY (country, code)
);
INSERT INTO local_class (country, code, doc_type, doc_role, sub_type) VALUES
 ('IN', 'AIS_STANDARD',             'TECHNICAL_STANDARD', 'BASE',           NULL),
 ('IN', 'AIS_AMENDMENT',            'TECHNICAL_STANDARD', 'AMENDMENT',      NULL),
 ('IN', 'AIS_CORRIGENDUM',          'TECHNICAL_STANDARD', 'CORRIGENDUM',    NULL),
 ('IN', 'AIS_DRAFT',                'TECHNICAL_STANDARD', NULL,             NULL),
 ('IN', 'AIS_FORM_TABLE',           'TECHNICAL_STANDARD', 'ANNEX',          NULL),
 ('IN', 'AIS_INTERPRETATION',       'GUIDANCE',           'INTERPRETATION', 'MANUAL'),
 ('IN', 'SAFETY_STANDARD_LEGACY',   'TECHNICAL_STANDARD', 'BASE',           NULL),
 ('IN', 'TAP_DOCUMENT',             'PROCEDURE',          'BASE',           NULL),
 ('IN', 'TAP_AMENDMENT',            'PROCEDURE',          'AMENDMENT',      NULL),
 ('IN', 'NOTIFICATION_DRAFT',       'REGULATION',         NULL,             NULL),
 ('IN', 'NOTIFICATION_FINAL',       'REGULATION',         NULL,             NULL),
 ('IN', 'NOTIFICATION_ORDER',       'REGULATION',         NULL,             NULL),
 ('IN', 'NOTIFICATION_CORRIGENDUM', 'REGULATION',         'CORRIGENDUM',    NULL),
 ('IN', 'NOTIFICATION_EXEMPTION',   'REGULATION',         'EXEMPTION',      NULL),
 ('IN', 'NOTIFICATION_EXTENSION',   'REGULATION',         'EXTENSION',      NULL),
 ('IN', 'CIRCULAR_OM',              'GUIDANCE',           'BASE',           'CIRCULAR'),
 ('IN', 'GUIDELINE_POLICY',         'GUIDANCE',           'BASE',           'GUIDELINE'),
 ('IN', 'ACT',                      'LAW',                NULL,             NULL),
 ('IN', 'CONSOLIDATED_RULES',       'REGULATION',         'CONSOLIDATION',  NULL),
 ('IN', 'BIS_REGULATION',           'REGULATION',         'BASE',           NULL),
 ('IN', 'BIS_CATALOGUE',            'REFERENCE',          'BASE',           'CATALOGUE'),
 ('IN', 'ENERGY_STANDARD',          'REGULATION',         NULL,             NULL),
 ('IN', 'FUEL_ORDER',               'REGULATION',         NULL,             NULL),
 ('IN', 'APPROVED_LIST',            'REFERENCE',          'BASE',           'LIST'),
 ('IN', 'FORM_TEMPLATE',            'REFERENCE',          'BASE',           'FORM'),
 ('IN', 'REPORT',                   'REFERENCE',          'BASE',           'REPORT'),
 ('IN', 'OFF_TOPIC',                'OFF_TOPIC',          NULL,             NULL),
 ('IN', 'OTHER',                    'UNKNOWN',            NULL,             NULL),
 ('TH', 'TIS_STANDARD',             'TECHNICAL_STANDARD', NULL,             NULL),
 ('TH', 'MINISTERIAL_REGULATION',   'REGULATION',         NULL,             NULL),
 ('TH', 'DLT_NOTIFICATION',         'REGULATION',         NULL,             NULL),
 ('TH', 'GAZETTE_NOTICE',           'REGULATION',         NULL,             NULL),
 ('TH', 'NEWS',                     'REFERENCE',          'BASE',           'NEWS'),
 ('TH', 'OFF_TOPIC',                'OFF_TOPIC',          NULL,             NULL),
 ('TH', 'OTHER',                    'UNKNOWN',            NULL,             NULL)
ON CONFLICT (country, code) DO NOTHING;

-- ============================================================ new columns
ALTER TABLE document
  ADD COLUMN doc_type       TEXT CHECK (doc_type IN ('LAW','REGULATION','TECHNICAL_STANDARD','PROCEDURE','GUIDANCE',
                                                     'REFERENCE','OFF_TOPIC','UNKNOWN')),
  ADD COLUMN doc_role       TEXT CHECK (doc_role IN ('BASE','AMENDMENT','CORRIGENDUM','EXTENSION','EXEMPTION','REPEAL',
                                                     'CONSOLIDATION','ANNEX','INTERPRETATION')),
  ADD COLUMN legal_force    TEXT NOT NULL DEFAULT 'UNKNOWN'
                            CHECK (legal_force IN ('MANDATORY','VOLUNTARY','INFORMATIVE','UNKNOWN')),
  ADD COLUMN sub_type       TEXT,
  ADD COLUMN local_type     TEXT,                    -- official local name: S.O., G.S.R., AIS, กฎกระทรวง, P.U.(A)…
  ADD COLUMN language       TEXT,                    -- language of the official text the pipeline reads
  ADD COLUMN title_en       TEXT,                    -- English title when the official title is in another language
  ADD COLUMN effective_date DATE,                    -- when it takes effect, if stated (doc_date = date of issue)
  ADD COLUMN vehicle_categories_un TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE document DROP CONSTRAINT document_canonical_id_key,
                     ADD CONSTRAINT document_country_canonical_key UNIQUE (country, canonical_id);
DROP INDEX document_one_current;
CREATE UNIQUE INDEX document_one_current ON document (country, family_key) WHERE is_current AND family_key IS NOT NULL;
CREATE INDEX document_type_idx   ON document (country, doc_type, doc_role);
CREATE INDEX document_cat_un_idx ON document USING gin (vehicle_categories_un);

ALTER TABLE document_file ADD COLUMN language_pages JSONB;      -- {"hi":[1,1],"en":[2,2]}
UPDATE document_file SET language_pages = jsonb_build_object('en', jsonb_build_array(english_page_from, english_page_to))
  WHERE english_page_from IS NOT NULL;
ALTER TABLE document_file DROP CONSTRAINT document_file_role_check,
  ADD CONSTRAINT document_file_role_check CHECK (role IN ('main','consolidated_segment','annex_table','historical_copy',
                                                         'hindi_only','other_language_only','translation'));

ALTER TABLE doc_relation DROP CONSTRAINT doc_relation_method_check,
  ADD CONSTRAINT doc_relation_method_check CHECK (method IN ('regex','file_no','qwen','llm','manual'));

-- country defaults to 'IN' only so that rows written by today's code stay valid; refresh_universal_fields()
-- sets it from the document, so a Thai or Malaysian row always ends up with its document's country
ALTER TABLE mandate
  ADD COLUMN country TEXT NOT NULL DEFAULT 'IN' REFERENCES country(code),
  ADD COLUMN vehicle_categories_un TEXT[] NOT NULL DEFAULT '{}';
CREATE INDEX mandate_country_key_idx ON mandate (country, mandate_key, valid_from);
CREATE INDEX mandate_cat_un_idx ON mandate USING gin (vehicle_categories_un);

ALTER TABLE chunk
  ADD COLUMN country  TEXT NOT NULL DEFAULT 'IN' REFERENCES country(code),
  ADD COLUMN doc_type TEXT,
  ADD COLUMN tsv      tsvector;                      -- full-text vector per language, filled by the pipeline
CREATE INDEX chunk_tsv_idx     ON chunk USING gin (tsv);
CREATE INDEX chunk_country_idx ON chunk (country, in_scope, is_current);
-- the English-only full-text index from 0003 stays until search uses tsv (to be dropped in 0007)

ALTER TABLE change_event ADD COLUMN country TEXT NOT NULL DEFAULT 'IN' REFERENCES country(code);
CREATE INDEX change_event_country_idx ON change_event (country, detected_at DESC);

ALTER TABLE compliance_item ADD COLUMN country TEXT NOT NULL DEFAULT 'IN' REFERENCES country(code);
ALTER TABLE compliance_item DROP CONSTRAINT compliance_item_pkey, ADD PRIMARY KEY (country, mandate_key);

ALTER TABLE alert_rule ADD COLUMN country TEXT NOT NULL DEFAULT 'IN' REFERENCES country(code);
ALTER TABLE report_log ADD COLUMN country TEXT NOT NULL DEFAULT 'IN' REFERENCES country(code);

-- ============================================================ derived fields: one definition, used here and by the pipeline
-- Fills the country-neutral fields of one country from its local data. Only rows whose values change are written,
-- so a second run returns 0 (CLAUDE.md rule 7). Called at the end of every pipeline run (runner.post_run).
CREATE FUNCTION refresh_universal_fields(cc TEXT) RETURNS INTEGER
LANGUAGE plpgsql AS $$
DECLARE
  n INTEGER := 0;
  k INTEGER;
BEGIN
  -- classification, local name, language, UNECE categories
  WITH calc AS (
    SELECT d.id, lc.doc_type, lc.sub_type,
           CASE WHEN lc.doc_type IS NULL OR lc.doc_type IN ('OFF_TOPIC','UNKNOWN') THEN NULL
                ELSE coalesce(lc.doc_role,
                              -- it amends something: a saved relation, or what extraction read from the text
                              -- (the amended document is often not in the database, so no relation exists)
                              CASE WHEN EXISTS (SELECT 1 FROM doc_relation r WHERE r.from_doc = d.id
                                                AND r.type IN ('amends','substitutes_row','inserts_row','omits_row'))
                                     OR jsonb_array_length(coalesce(d.data->'amends_targets', '[]')) > 0
                                     OR jsonb_array_length(coalesce(d.data->'amends_notification', '[]')) > 0
                                   THEN 'AMENDMENT' ELSE 'BASE' END) END AS doc_role,
           coalesce(d.local_type, d.series) AS local_type,
           coalesce(d.language, c.language) AS language,
           un_vehicle_categories(d.country, d.vehicle_categories) AS un
    FROM document d
    JOIN country c ON c.code = d.country
    LEFT JOIN local_class lc ON lc.country = d.country AND lc.code = d.doc_class
    WHERE d.country = cc)
  UPDATE document d
     SET doc_type = calc.doc_type, sub_type = calc.sub_type, doc_role = calc.doc_role,
         local_type = calc.local_type, language = calc.language, vehicle_categories_un = calc.un
    FROM calc
   WHERE calc.id = d.id
     AND (d.doc_type IS DISTINCT FROM calc.doc_type OR d.sub_type IS DISTINCT FROM calc.sub_type
          OR d.doc_role IS DISTINCT FROM calc.doc_role OR d.local_type IS DISTINCT FROM calc.local_type
          OR d.language IS DISTINCT FROM calc.language OR d.vehicle_categories_un IS DISTINCT FROM calc.un);
  GET DIAGNOSTICS k = ROW_COUNT; n := n + k;

  -- must anyone comply? (same rule everywhere; a standard is mandatory while an open mandate cites it)
  WITH lf AS (
    SELECT d.id, CASE
             WHEN d.doc_type IS NULL OR d.doc_type IN ('OFF_TOPIC','UNKNOWN') THEN 'UNKNOWN'
             WHEN d.status = 'draft' THEN 'INFORMATIVE'
             WHEN d.doc_type IN ('GUIDANCE','REFERENCE') THEN 'INFORMATIVE'
             WHEN d.doc_type IN ('LAW','REGULATION') THEN 'MANDATORY'
             WHEN EXISTS (SELECT 1 FROM mandate m
                          WHERE m.country = d.country AND m.valid_to IS NULL AND NOT m.is_draft
                            AND (d.id = ANY(m.standard_doc_ids) OR d.canonical_id = ANY(m.standard_refs)
                                 OR d.family_key = ANY(m.standard_refs))) THEN 'MANDATORY'
             ELSE 'VOLUNTARY' END AS force
    FROM document d WHERE d.country = cc)
  UPDATE document d SET legal_force = lf.force FROM lf
   WHERE lf.id = d.id AND d.legal_force IS DISTINCT FROM lf.force;
  GET DIAGNOSTICS k = ROW_COUNT; n := n + k;

  -- rows that carry their own country follow their document
  UPDATE mandate m SET country = d.country FROM document d
   WHERE d.id = m.source_doc_id AND d.country = cc AND m.country <> d.country;
  GET DIAGNOSTICS k = ROW_COUNT; n := n + k;
  UPDATE mandate m SET vehicle_categories_un = un_vehicle_categories(m.country, m.vehicle_categories)
   WHERE m.country = cc AND m.vehicle_categories_un IS DISTINCT FROM un_vehicle_categories(m.country, m.vehicle_categories);
  GET DIAGNOSTICS k = ROW_COUNT; n := n + k;
  UPDATE chunk c SET country = d.country, doc_type = d.doc_type FROM document d
   WHERE d.id = c.document_id AND d.country = cc
     AND (c.country <> d.country OR c.doc_type IS DISTINCT FROM d.doc_type);
  GET DIAGNOSTICS k = ROW_COUNT; n := n + k;
  UPDATE change_event e SET country = d.country FROM document d
   WHERE d.id = e.document_id AND d.country = cc AND e.country <> d.country;
  GET DIAGNOSTICS k = ROW_COUNT; n := n + k;
  RETURN n;
END $$;

-- ============================================================ fill for existing data
UPDATE document SET local_type = 'AIS'                  -- AIS documents whose series was not read
 WHERE country = 'IN' AND local_type IS NULL AND series IS NULL AND doc_class LIKE 'AIS%';
SELECT refresh_universal_fields(code) FROM country ORDER BY code;
