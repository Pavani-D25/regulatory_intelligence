-- 0017: Malaysia (region 'MY' exists since 0007). Authorities, sources (crawler: regtrack/sources/malaysia.py),
-- vehicle-category scope, the Malaysian document classes and the client's regulatory register (17 rows, from
-- source/Thailand_Malaysia_Automotive_Regulatory_Register, Malaysia rows). Sources checked live on 2026-10-22:
-- all five pages return 200 with content, no captcha, no login.
-- Malaysia uses UNECE category meanings (like Thailand): in scope L1, L3, M1, N1 (+ ALL), see
-- IN_SCOPE_CATEGORIES_BY_COUNTRY in regtrack/models/enums.py.

INSERT INTO regulatory_authorities (region_id, code, name, website_url)
  SELECT r.id, a.code, a.name, a.url
  FROM (VALUES
    ('JPJ',    'Road Transport Department (JPJ)',            'https://www.jpj.gov.my/'),
    ('DOE_MY', 'Department of Environment (DOE/JAS)',        'https://www.doe.gov.my/'),
    ('MITI',   'Ministry of Investment, Trade and Industry', 'https://www.miti.gov.my/'),
    ('DSM',    'Department of Standards Malaysia',           'https://www.jsm.gov.my/')
  ) AS a(code, name, url)
  CROSS JOIN (SELECT id FROM regions WHERE code = 'MY') r
ON CONFLICT (code) DO NOTHING;

INSERT INTO sources (region_id, authority_id, code, name, base_url, is_active, sync_frequency_minutes)
  SELECT r.id, au.id, s.code, s.name, s.url, true, 360
  FROM (VALUES
    ('MY_JPJ_VTA',       'JPJ Vehicle Type Approval procedure',   'https://www.jpj.gov.my/en/vehicle-type-approval-process-vta/', 'JPJ'),
    ('MY_JPJ_CTA',       'JPJ Component Type Approval',           'https://www.jpj.gov.my/en/component-type-approval-cta/', 'JPJ'),
    ('MY_JPJ_AED',       'JPJ Automotive Engineering Division',   'https://www.jpj.gov.my/en/jpj-service-information/automotive-engineering-division/', 'JPJ'),
    ('MY_DOE_EMISSION',  'DOE emission control from motor vehicles', 'https://www.doe.gov.my/en/emission-control-from-motor-vehicles/', 'DOE_MY'),
    ('MY_DOE_VTA_GUIDE', 'DOE gas and noise emission VTA guidelines', 'https://www.doe.gov.my/en/motor-vehicle-type-approval-guidelines-for-gas-and-noise-emissions/', 'DOE_MY')
  ) AS s(code, name, url, authority_code)
  JOIN (SELECT id FROM regions WHERE code = 'MY') r ON true
  JOIN regulatory_authorities au ON au.code = s.authority_code
ON CONFLICT (code) DO NOTHING;

INSERT INTO vehicle_categories (region_id, code, label, un_codes)
  SELECT (SELECT id FROM regions WHERE code = 'MY'), code, label, un_codes
  FROM (VALUES
    ('L1',  'Two-wheeled moped (<=50 cm3 or <=50 km/h)', ARRAY['L1']),
    ('L3',  'Motorcycle (>50 cm3 or >50 km/h)',           ARRAY['L3']),
    ('M1',  'Passenger car, <=8 seats plus driver',       ARRAY['M1']),
    ('N1',  'Light goods vehicle, GVW <=3.5 t',            ARRAY['N1']),
    ('ALL', 'All motor vehicles',                          ARRAY['L1','L3','M1','N1'])
  ) AS v(code, label, un_codes)
ON CONFLICT (region_id, code) DO NOTHING;

INSERT INTO region_scope (region_id, vehicle_category_id)
  SELECT vc.region_id, vc.id FROM vehicle_categories vc
  WHERE vc.region_id = (SELECT id FROM regions WHERE code = 'MY')
ON CONFLICT DO NOTHING;

INSERT INTO document_classes (region_id, code, doc_type, doc_role, sub_type)
  SELECT (SELECT id FROM regions WHERE code = 'MY'), c.code, c.doc_type, c.doc_role, c.sub_type
  FROM (VALUES
    ('MY_GUIDELINE', 'PROCEDURE',  'BASE', 'GUIDELINE'),
    ('MY_FORM',      'REFERENCE',  'BASE', 'FORM'),
    ('OFF_TOPIC',    'OFF_TOPIC',  NULL,   NULL),
    ('OTHER',        'UNKNOWN',    NULL,   NULL)
  ) AS c(code, doc_type, doc_role, sub_type)
ON CONFLICT DO NOTHING;

INSERT INTO client_requirements (region_id, code, topic, requirement_text, applies_to, authority, source_url, source_name, client_status, caution)
  SELECT (SELECT id FROM regions WHERE code = 'MY'), v.code, v.topic, v.requirement_text, v.applies_to, v.authority,
         v.source_url, v.source_name, v.client_status, v.caution
  FROM (VALUES
 ('MY-01','Vehicle Type Approval (VTA)','New vehicle model VTA before registration','New vehicle models; category-specific assessment','Road Transport Department (JPJ)','https://www.jpj.gov.my/en/vehicle-type-approval-process-vta/','VTA procedure and application documents','Applicable to new models before registration','Confirm current document set, testing route and category-specific requirements'),
 ('MY-02','Component Type Approval (CTA)','Mandatory component approval for components listed by JPJ / relevant import controls','Listed components, including relevant tyres, braking components, belts, seats, glazing, lamps and child restraints','JPJ','https://www.jpj.gov.my/en/component-type-approval-cta/','CTA component list and application guidance','Applicable only to listed components / regulated supply routes','Use current JPJ list; do not treat all components as requiring CTA'),
 ('MY-03','Exhaust emissions — petrol vehicles','Type-approval emission requirements under Environmental Quality (Control of Emissions from Petrol Engines) Regulations 1996 and subsequent amendments','New vehicle models and categories within DOE regulations/guidance','Department of Environment (DOE/JAS)','https://www.doe.gov.my/en/emission-control-from-motor-vehicles/','DOE emission control page and current legal schedules','Regulation applies; exact current limits and test procedure must be checked','DOE webpage cites historical schedules; verify amendments/current standard before sign-off'),
 ('MY-04','Exhaust emissions — diesel vehicles','Type-approval emission requirements under Environmental Quality (Control of Emissions from Diesel Engines) Regulations 1996 and subsequent amendments','New vehicle models and categories within DOE regulations/guidance','DOE/JAS','https://www.doe.gov.my/en/emission-control-from-motor-vehicles/','DOE emission control page and current legal schedules','Regulation applies; exact current limits and test procedure must be checked','Do not assume the same stage applies to every category or model year'),
 ('MY-05','In-use diesel smoke emissions','Enforcement limits and smoke testing for diesel vehicles','In-use diesel vehicles covered by enforcement regime','DOE/JAS','https://www.doe.gov.my/en/emission-control-from-motor-vehicles/','DOE guidance on diesel smoke enforcement','Applicable to in-use enforcement; distinct from new-model type approval','Keep separate from OEM new-vehicle certification limits'),
 ('MY-06','Vehicle exhaust gas and noise emission VTA','DOE emission/noise certificates as part of applicable VTA process','Vehicle categories subject to DOE gas/noise approval; motorcycle routes may differ','DOE/JAS','https://www.doe.gov.my/en/motor-vehicle-type-approval-guidelines-for-gas-and-noise-emissions/','Motor vehicle type approval guidelines for gas and noise emissions','Applicable where required for the vehicle approval route','Confirm latest guideline revision and whether motorcycle-specific guidance applies'),
 ('MY-07','Vehicle noise','Gas/noise emission type-approval requirements and relevant UN/national rules','Vehicle categories covered by DOE / JPJ requirements','DOE/JAS / JPJ','https://www.doe.gov.my/en/motor-vehicle-type-approval-guidelines-for-gas-and-noise-emissions/','DOE gas and noise VTA guidance','Verify category and current limits','Record test method, limits and any separate motorcycle requirements'),
 ('MY-08','UN Regulations implemented nationally','Only UN Regulations adopted/gazetted by Malaysia and applicable to the vehicle category','Vehicle category and specific regulation dependent','JPJ Automotive Engineering Division','https://www.jpj.gov.my/en/jpj-service-information/automotive-engineering-division/','JPJ implementation framework and current VTA schedules','Applicable regulation-by-regulation; not every UN R is automatically applicable','Use current national implementation list, amendments and transition dates'),
 ('MY-09','Braking systems / replacement brake linings','Relevant vehicle UN Regulation and/or component approval requirement','Vehicle systems and regulated replacement components as applicable','JPJ','https://www.jpj.gov.my/en/component-type-approval-cta/','JPJ CTA list and VTA schedule','Applicable by vehicle/component scope','Check system-level VTA and component CTA separately'),
 ('MY-10','Tyres and retreaded tyres','Applicable UN Regulations / Malaysian Standards and CTA requirements','Tyre types and vehicle categories listed by JPJ','JPJ / Department of Standards Malaysia','https://www.jpj.gov.my/en/component-type-approval-cta/','JPJ CTA list','Applicable to listed tyre/component types','Confirm current referenced MS/UN Regulation revisions'),
 ('MY-11','Lighting and light-signalling devices','Applicable nationally implemented UN Regulations and component approval rules','Vehicle class and lamp type dependent','JPJ','https://www.jpj.gov.my/en/component-type-approval-cta/','JPJ CTA list and vehicle category VTA schedule','Applicable where listed/adopted','Confirm each regulation''s national adoption and series of amendments'),
 ('MY-12','Safety glazing / mirrors / indirect vision','Applicable UN Regulations and/or component approval requirements','Vehicle and component category dependent','JPJ','https://www.jpj.gov.my/en/component-type-approval-cta/','JPJ CTA list and VTA schedule','Applicable where listed/adopted','Check glazing and mirror fitment/installation rules'),
 ('MY-13','Seat belts, seats and child restraints','Applicable UN Regulations and component approval requirements','Vehicle seating configuration and listed components','JPJ','https://www.jpj.gov.my/en/component-type-approval-cta/','JPJ CTA list','Applicable by vehicle/component scope','Include belt, anchorage, seat strength and CRS requirements as relevant'),
 ('MY-14','Electric vehicle / REESS safety','Relevant nationally implemented UN Regulation(s), including R100 where adopted and applicable','BEV/PHEV/other electrified vehicle scope depends on current JPJ schedule','JPJ','https://www.jpj.gov.my/en/jpj-service-information/automotive-engineering-division/','Current national UN Regulation implementation list','Verify exact regulation and category before marking mandatory','Do not rely solely on international UN status; confirm Malaysian adoption'),
 ('MY-15','EMC / electrical-electronic vehicle systems','Relevant nationally implemented UN Regulation(s), including R10 where adopted and applicable','Vehicle and system scope under current VTA schedule','JPJ','https://www.jpj.gov.my/en/jpj-service-information/automotive-engineering-division/','Current national UN Regulation implementation list','Verify exact regulation and category before marking mandatory','Check current amendment series and transition provisions'),
 ('MY-16','Vehicle dimensions, mass, construction and identity','Road Transport Act 1987, subsidiary rules and VTA specifications','New models and relevant vehicle classes','JPJ','https://www.jpj.gov.my/en/vehicle-type-approval-process-vta/','VTA process and road transport legislation','Applicable to VTA/registration','Capture vehicle class, dimensions, weights, construction and identification'),
 ('MY-17','CO2 / fuel consumption / energy-efficient vehicle recognition','Requirements relevant to Energy Efficient Vehicle (EEV) recognition or incentives, where pursued','Models seeking applicable EEV status/incentives; not automatically universal VTA requirements','JPJ / MITI','https://www.jpj.gov.my/en/jpj-service-information/automotive-engineering-division/','JPJ Automotive Engineering Division; current programme criteria','Programme-specific; distinguish from baseline homologation','Confirm current criteria and any tax/incentive conditions')
  ) AS v(code, topic, requirement_text, applies_to, authority, source_url, source_name, client_status, caution)
ON CONFLICT DO NOTHING;
