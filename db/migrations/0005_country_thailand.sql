-- 0005: make RegTrack multi-country and add Thailand (approach A).
-- Existing India rows are not rewritten: every new country column defaults to 'IN'.
-- Thai-only details (Buddhist-era year, mandatory status, effective-date wording, scope, HS codes)
-- go in document.data, so no India column changes meaning.

-- countries and how they write years
CREATE TABLE country (
  code         TEXT PRIMARY KEY,                 -- 'IN', 'TH'
  name         TEXT NOT NULL,
  year_offset  INT  NOT NULL DEFAULT 0,          -- local year - year_offset = CE year (Thailand: 543)
  language     TEXT NOT NULL
);
INSERT INTO country (code, name, year_offset, language) VALUES
 ('IN', 'India', 0, 'en'),
 ('TH', 'Thailand', 543, 'th');

-- every source, document and file says which country it belongs to (existing rows become 'IN')
ALTER TABLE source      ADD COLUMN country TEXT NOT NULL DEFAULT 'IN' REFERENCES country(code);
ALTER TABLE document    ADD COLUMN country TEXT NOT NULL DEFAULT 'IN' REFERENCES country(code);
ALTER TABLE file_object ADD COLUMN country TEXT NOT NULL DEFAULT 'IN' REFERENCES country(code);
CREATE INDEX document_country_idx    ON document (country, doc_class);
CREATE INDEX file_object_country_idx ON file_object (country, stage);

-- the 8 Thai sources (schedule_hours 0 = not scheduled yet; turned on when each Thai crawler exists)
INSERT INTO source (country, code, name, base_url, schedule_hours) VALUES
 ('TH', 'TH_TISI_MANDATORY', 'TISI mandatory-standards list', 'https://www.tisi.go.th/website/standardlist/comp_thai/th', 0),
 ('TH', 'TH_TISI_DB',        'TISI standards database',       'https://appdb.tisi.go.th/tis_dev/p3_tis/p3tis.php', 0),
 ('TH', 'TH_TISI_PORTAL',    'TISI search portal',            'https://a.tisi.go.th/t/', 0),
 ('TH', 'TH_TISI_NEWS',      'TISI Euro 6 news',              'https://pr.tisi.go.th/news-25-12-68/', 0),
 ('TH', 'TH_DLT',            'Department of Land Transport',  'https://www.dlt.go.th/', 0),
 ('TH', 'TH_GAZETTE',        'Royal Gazette',                 'https://ratchakitcha.soc.go.th/', 0),
 ('TH', 'TH_INDUSTRY',       'Ministry of Industry',          'https://www.industry.go.th/', 0),
 ('TH', 'TH_PCD',            'Pollution Control Department',  'https://www.pcd.go.th/', 0)
ON CONFLICT (code) DO NOTHING;

-- the client's register rows (Thailand: 15 rows, copied from the client sheet)
CREATE TABLE requirement (
  id                SERIAL PRIMARY KEY,
  country           TEXT NOT NULL REFERENCES country(code),
  code              TEXT UNIQUE NOT NULL,        -- 'TH-03'
  topic             TEXT NOT NULL,               -- client's regulatory area
  requirement_text  TEXT,
  applies_to        TEXT,
  authority         TEXT,
  source_url        TEXT,
  source_name       TEXT,
  client_status     TEXT,
  caution           TEXT
);

-- which documents answer which register row
CREATE TABLE requirement_document (
  requirement_id  INT NOT NULL REFERENCES requirement(id) ON DELETE CASCADE,
  document_id     BIGINT NOT NULL REFERENCES document(id) ON DELETE CASCADE,
  role            TEXT NOT NULL DEFAULT 'candidate'
                  CHECK (role IN ('primary','supporting','candidate','rejected')),
  matched_by      TEXT,                          -- 'keywords: ห้ามล้อ, รถยนต์' or 'manual'
  note            TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (requirement_id, document_id)
);

INSERT INTO requirement (country, code, topic, requirement_text, applies_to, authority, source_url, source_name, client_status, caution) VALUES
 ('TH','TH-01','Vehicle homologation / product conformity','New vehicle model approval; applicable mandatory TIS and certification route','All vehicle categories; exact standard depends on vehicle class and powertrain','Thai Industrial Standards Institute (TISI)','https://www.tisi.go.th/','Mandatory TIS catalogue and product certification','Applicable framework; identify each model-specific mandatory TIS','Check current mandatory-standard list and effective date before design freeze'),
 ('TH','TH-02','Vehicle registration / road-use requirements','Vehicle specifications and registration requirements','Vehicles intended for Thai road registration','Department of Land Transport (DLT)','https://www.dlt.go.th/','Vehicle registration and technical requirements','Applicable; model/category-specific','Confirm latest ministerial regulations and vehicle-class requirements'),
 ('TH','TH-03','Exhaust emissions — light-duty petrol vehicles','Euro 6-related mandatory standard implementation for small petrol vehicles reported from 1 Jan 2025','Small/light-duty petrol vehicles within the relevant TIS scope','TISI','https://pr.tisi.go.th/news-25-12-68/','TISI announcement on Euro 6 implementation','Reported effective from 1 Jan 2025; confirm exact TIS and vehicle scope','Do not generalise to diesel, hybrid, heavy-duty or all vehicle classes'),
 ('TH','TH-04','Exhaust emissions — buses and trucks with petrol engines','Euro 6-related mandatory standard implementation reported from 1 Jan 2026','Petrol-engine buses and trucks within the relevant TIS scope','TISI','https://pr.tisi.go.th/news-25-12-68/','TISI announcement on Euro 6 implementation','Reported effective from 1 Jan 2026; confirm exact TIS and vehicle scope','Verify vehicle class, engine type, approval date and transition provisions'),
 ('TH','TH-05','Other exhaust-emission categories','Applicable mandatory emission TIS and test procedures','Diesel, hybrid, other vehicle classes and engines as specified by current TIS notifications','TISI / Ministry of Industry / Royal Gazette','https://www.tisi.go.th/','TIS catalogue and legal notifications','Exact standard and effective date must be established per category','Do not assume Euro 6 applies uniformly across all Thai vehicle categories'),
 ('TH','TH-06','Vehicle noise','Applicable mandatory noise standards, where prescribed for vehicle/component category','Vehicle categories covered by current mandatory TIS / DLT rules','TISI / DLT','https://www.tisi.go.th/','TIS catalogue and DLT regulations','Verify by category','Capture stationary/pass-by method and limit only from current applicable standard'),
 ('TH','TH-07','Vehicle dimensions, mass and construction','National technical specifications and road-use limits','All relevant vehicle classes; special rules may apply to commercial vehicles','DLT / Royal Gazette','https://www.dlt.go.th/','DLT rules and official legal notifications','Applicable; vehicle-class-specific','Record dimensions, axle loads, gross vehicle weight and any special-use conditions'),
 ('TH','TH-08','Lighting and light-signalling devices','Applicable mandatory TIS requirements for lamps and related components','Vehicles/components within the scope of mandatory TIS','TISI','https://www.tisi.go.th/','TIS catalogue','Verify current mandatory standard and vehicle scope','Include installation, marking and photometric requirements where prescribed'),
 ('TH','TH-09','Tyres and wheels','Applicable mandatory TIS and vehicle fitment requirements','Vehicle classes and tyre/component types within the scope of current rules','TISI / DLT','https://www.tisi.go.th/','TIS catalogue and DLT rules','Verify by tyre type and vehicle category','Include load/speed ratings and fitment requirements where applicable'),
 ('TH','TH-10','Braking systems','Applicable national mandatory standards and vehicle technical requirements','Vehicle class-specific','TISI / DLT','https://www.tisi.go.th/','TIS catalogue and DLT regulations','Verify current applicable standard','Distinguish vehicle system approval from component certification'),
 ('TH','TH-11','Seat belts, seats and occupant protection','Applicable mandatory TIS / vehicle requirements','Vehicle category and seating configuration dependent','TISI / DLT','https://www.tisi.go.th/','TIS catalogue and DLT regulations','Verify current mandatory standards','Include seat-belt anchorage and child-restraint requirements where applicable'),
 ('TH','TH-12','Safety glazing / mirrors / indirect vision','Applicable mandatory component and installation standards','Vehicle/component categories within mandatory-standard scope','TISI / DLT','https://www.tisi.go.th/','TIS catalogue and DLT rules','Verify by component and vehicle category','Capture marking, performance and installation requirements'),
 ('TH','TH-13','Electric vehicle high-voltage safety','Applicable EV and traction-battery standards, where mandated','BEV/PHEV/HEV as specified in current TIS and approval rules','TISI / DLT / Ministry of Industry','https://www.tisi.go.th/','TIS catalogue and EV-related notifications','Model/powertrain-specific; confirm current mandatory scope','Include electrical safety, REESS/battery and charging interfaces only where legally required'),
 ('TH','TH-14','Vehicle EMC / radio equipment','Applicable vehicle/component EMC and radio approvals where required','Vehicles with relevant electrical/electronic or radio equipment','TISI / relevant Thai telecom regulator','https://www.tisi.go.th/','TIS and applicable equipment approval rules','Confirm vehicle vs component/radio-equipment scope','Keep vehicle EMC separate from telecom/radio equipment approval'),
 ('TH','TH-15','Fuel consumption / CO2 / energy-efficiency incentives or rules',NULL,NULL,NULL,'https://www.industry.go.th/',NULL,NULL,NULL)
ON CONFLICT (code) DO NOTHING;
