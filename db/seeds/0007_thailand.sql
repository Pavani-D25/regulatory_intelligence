-- Renumbered from 0002 to 0007 (found during the Thailand-parity work, phase TH-1): this seed inserts into
-- regions/regulatory_authorities/sources/client_requirements, which migration 0007 creates - numbered 0002 it ran
-- before those tables existed on any database that migrates from scratch (regtrack/migrate.py orders a seed right
-- after the migration of the same number, so 0002 ran next to 0002_portal_workflow.sql, long before 0007). On the
-- already-migrated dev database this had already been papered over by running it out of band after 0007 existed;
-- a fresh `migrate` (e.g. the test suite's throwaway database) failed outright. All inserts below are
-- ON CONFLICT DO NOTHING, so re-running this file under its new name is a harmless no-op wherever the old
-- seed/0002_thailand.sql key is already recorded in schema_migrations.
--
-- Thailand region, authorities, sources and the client's regulatory register (15 rows), sourced from
-- source/Thailand_Malaysia_Automotive_Regulatory_Register (1).xlsx ("Applicable Requirements" + "Official
-- Websites" sheets, Thailand rows only). Cross-checked against the live sites on 2026-10-19:
--   - https://www.tisi.go.th/            reachable, confirmed the official TISI entry page.
--   - https://pr.tisi.go.th/news-25-12-68/  reachable; content confirms Euro 6 mandatory for small petrol
--     passenger vehicles from 1 Jan 2025, and for petrol-engine buses/trucks from 1 Jan 2026 (TH-03/TH-04 below
--     match exactly - note it is petrol engines specifically, not all engine types).
--   - https://www.dlt.go.th/             did not load when checked (connection reset); kept as-is as the
--     DLT (Department of Land Transport) is a well-known Thai government domain - re-verify before relying on it.
-- Everything else in this file (exact TIS numbers, current limits, test procedures) is explicitly marked
-- 'verify' in client_status/caution below, per the workbook's own "Read Me" sheet: a row applies at the
-- regulatory-area level, not every limit within it, and must be confirmed with TISI/DLT before sign-off.

INSERT INTO regions (code, slug, name, timezone, languages, year_offset, currency) VALUES
 ('TH', 'thailand', 'Thailand', 'Asia/Bangkok', ARRAY['th','en'], 543, 'THB')
ON CONFLICT (code) DO NOTHING;

INSERT INTO regulatory_authorities (region_id, code, name, website_url)
  SELECT r.id, a.code, a.name, a.url
  FROM (VALUES
    ('TISI',          'Thai Industrial Standards Institute (TISI)', 'https://www.tisi.go.th/'),
    ('DLT',           'Department of Land Transport (DLT)',         'https://www.dlt.go.th/'),
    ('MOI_TH',         'Ministry of Industry',                       'https://www.industry.go.th/'),
    ('ROYAL_GAZETTE',  'Royal Gazette',                              'https://ratchakitcha.soc.go.th/'),
    ('PCD',            'Pollution Control Department (PCD)',         'https://www.pcd.go.th/')
  ) AS a(code, name, url)
  CROSS JOIN (SELECT id FROM regions WHERE code = 'TH') r
ON CONFLICT (code) DO NOTHING;

-- Thai crawlers do not exist yet (discovery-only sources, same approach as the original 0005 migration):
-- is_active = false until each source has a working scraper.
INSERT INTO sources (region_id, authority_id, code, name, base_url, is_active, sync_frequency_minutes)
  SELECT r.id, au.id, s.code, s.name, s.url, false, 360
  FROM (VALUES
    ('TH_TISI_MANDATORY', 'TISI mandatory-standards list', 'https://www.tisi.go.th/website/standardlist/comp_thai/th', 'TISI'),
    ('TH_TISI_DB',        'TISI standards database',       'https://appdb.tisi.go.th/tis_dev/p3_tis/p3tis.php',       'TISI'),
    ('TH_TISI_PORTAL',    'TISI search portal',            'https://a.tisi.go.th/t/',                                 'TISI'),
    ('TH_TISI_NEWS',      'TISI Euro 6 news',              'https://pr.tisi.go.th/news-25-12-68/',                    'TISI'),
    ('TH_DLT',            'Department of Land Transport',  'https://www.dlt.go.th/',                                  'DLT'),
    ('TH_GAZETTE',        'Royal Gazette',                 'https://ratchakitcha.soc.go.th/',                         'ROYAL_GAZETTE'),
    ('TH_INDUSTRY',       'Ministry of Industry',          'https://www.industry.go.th/',                             'MOI_TH'),
    ('TH_PCD',            'Pollution Control Department',  'https://www.pcd.go.th/',                                  'PCD')
  ) AS s(code, name, url, authority_code)
  JOIN (SELECT id FROM regions WHERE code = 'TH') r ON true
  JOIN regulatory_authorities au ON au.code = s.authority_code
ON CONFLICT (code) DO NOTHING;

INSERT INTO client_requirements (region_id, code, topic, requirement_text, applies_to, authority, source_url, source_name, client_status, caution)
  SELECT (SELECT id FROM regions WHERE code = 'TH'), v.code, v.topic, v.requirement_text, v.applies_to, v.authority,
         v.source_url, v.source_name, v.client_status, v.caution
  FROM (VALUES
 ('TH-01','Vehicle homologation / product conformity','New vehicle model approval; applicable mandatory TIS and certification route','All vehicle categories; exact standard depends on vehicle class and powertrain','Thai Industrial Standards Institute (TISI)','https://www.tisi.go.th/','Mandatory TIS catalogue and product certification','Applicable framework; identify each model-specific mandatory TIS','Check current mandatory-standard list and effective date before design freeze'),
 ('TH-02','Vehicle registration / road-use requirements','Vehicle specifications and registration requirements','Vehicles intended for Thai road registration','Department of Land Transport (DLT)','https://www.dlt.go.th/','Vehicle registration and technical requirements','Applicable; model/category-specific','Confirm latest ministerial regulations and vehicle-class requirements'),
 ('TH-03','Exhaust emissions — light-duty petrol vehicles','Euro 6-related mandatory standard implementation for small petrol vehicles reported from 1 Jan 2025','Small/light-duty petrol vehicles within the relevant TIS scope','TISI','https://pr.tisi.go.th/news-25-12-68/','TISI announcement on Euro 6 implementation','Confirmed effective from 1 Jan 2025 (verified against TISI announcement, checked 2026-10-19)','Do not generalise to diesel, hybrid, heavy-duty or all vehicle classes'),
 ('TH-04','Exhaust emissions — buses and trucks with petrol engines','Euro 6-related mandatory standard implementation reported from 1 Jan 2026','Petrol-engine buses and trucks within the relevant TIS scope','TISI','https://pr.tisi.go.th/news-25-12-68/','TISI announcement on Euro 6 implementation','Confirmed effective from 1 Jan 2026 (verified against TISI announcement, checked 2026-10-19)','Verify vehicle class, engine type, approval date and transition provisions'),
 ('TH-05','Other exhaust-emission categories','Applicable mandatory emission TIS and test procedures','Diesel, hybrid, other vehicle classes and engines as specified by current TIS notifications','TISI / Ministry of Industry / Royal Gazette','https://www.tisi.go.th/','TIS catalogue and legal notifications','Exact standard and effective date must be established per category','Do not assume Euro 6 applies uniformly across all Thai vehicle categories'),
 ('TH-06','Vehicle noise','Applicable mandatory noise standards, where prescribed for vehicle/component category','Vehicle categories covered by current mandatory TIS / DLT rules','TISI / DLT','https://www.tisi.go.th/','TIS catalogue and DLT regulations','Verify by category','Capture stationary/pass-by method and limit only from current applicable standard'),
 ('TH-07','Vehicle dimensions, mass and construction','National technical specifications and road-use limits','All relevant vehicle classes; special rules may apply to commercial vehicles','DLT / Royal Gazette','https://www.dlt.go.th/','DLT rules and official legal notifications','Applicable; vehicle-class-specific','Record dimensions, axle loads, gross vehicle weight and any special-use conditions'),
 ('TH-08','Lighting and light-signalling devices','Applicable mandatory TIS requirements for lamps and related components','Vehicles/components within the scope of mandatory TIS','TISI','https://www.tisi.go.th/','TIS catalogue','Verify current mandatory standard and vehicle scope','Include installation, marking and photometric requirements where prescribed'),
 ('TH-09','Tyres and wheels','Applicable mandatory TIS and vehicle fitment requirements','Vehicle classes and tyre/component types within the scope of current rules','TISI / DLT','https://www.tisi.go.th/','TIS catalogue and DLT rules','Verify by tyre type and vehicle category','Include load/speed ratings and fitment requirements where applicable'),
 ('TH-10','Braking systems','Applicable national mandatory standards and vehicle technical requirements','Vehicle class-specific','TISI / DLT','https://www.tisi.go.th/','TIS catalogue and DLT regulations','Verify current applicable standard','Distinguish vehicle system approval from component certification'),
 ('TH-11','Seat belts, seats and occupant protection','Applicable mandatory TIS / vehicle requirements','Vehicle category and seating configuration dependent','TISI / DLT','https://www.tisi.go.th/','TIS catalogue and DLT regulations','Verify current mandatory standards','Include seat-belt anchorage and child-restraint requirements where applicable'),
 ('TH-12','Safety glazing / mirrors / indirect vision','Applicable mandatory component and installation standards','Vehicle/component categories within mandatory-standard scope','TISI / DLT','https://www.tisi.go.th/','TIS catalogue and DLT rules','Verify by component and vehicle category','Capture marking, performance and installation requirements'),
 ('TH-13','Electric vehicle high-voltage safety','Applicable EV and traction-battery standards, where mandated','BEV/PHEV/HEV as specified in current TIS and approval rules','TISI / DLT / Ministry of Industry','https://www.tisi.go.th/','TIS catalogue and EV-related notifications','Model/powertrain-specific; confirm current mandatory scope','Include electrical safety, REESS/battery and charging interfaces only where legally required'),
 ('TH-14','Vehicle EMC / radio equipment','Applicable vehicle/component EMC and radio approvals where required','Vehicles with relevant electrical/electronic or radio equipment','TISI / relevant Thai telecom regulator','https://www.tisi.go.th/','TIS and applicable equipment approval rules','Confirm vehicle vs component/radio-equipment scope','Keep vehicle EMC separate from telecom/radio equipment approval'),
 ('TH-15','Fuel consumption / CO2 / energy-efficiency incentives or rules','Applicable requirements affecting vehicle approval, labelling, tax or incentives','Powertrain and vehicle categories specified by current policy','TISI / DLT / relevant government agencies','https://www.industry.go.th/','Official ministry notifications and programme criteria','Not a universal homologation requirement; verify programme and vehicle scope','Separate mandatory compliance from tax/incentive eligibility')
  ) AS v(code, topic, requirement_text, applies_to, authority, source_url, source_name, client_status, caution)
ON CONFLICT (code) DO NOTHING;
