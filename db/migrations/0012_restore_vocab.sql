-- 0012: restore reference/vocab data that never made it into the v4B tables.
-- Found while validating the dashboard: regions had only 'TH' (added directly by seed/0002_thailand.sql),
-- and vehicle_categories / domains were empty, because migration 0007's copy from the pre-v4B tables
-- (vehicle_category, domain, source) ran against those tables with 0 rows (they were already empty by then,
-- although seed/0001_vocab.sql had populated them 2026-10-12 - the rows did not survive to 2026-10-19).
-- This repopulates the same rows 0007 intended to copy, as literal values, idempotently.

INSERT INTO regions (code, slug, name, timezone, languages, year_offset, currency) VALUES
 ('IN', 'india', 'India', 'Asia/Kolkata', ARRAY['en','hi'], 0, 'INR'),
 ('MY', 'malaysia', 'Malaysia', 'Asia/Kuala_Lumpur', ARRAY['ms','en'], 0, 'MYR'),
 ('UN', 'unece', 'UNECE (international regulations)', 'Europe/Zurich', ARRAY['en','fr','ru'], 0, NULL)
ON CONFLICT (code) DO NOTHING;

INSERT INTO domains (code, name) VALUES
 ('SAFETY_EQUIPMENT', 'Safety equipment'),
 ('BRAKING', 'Braking'),
 ('LIGHTING', 'Lighting and signalling'),
 ('EMISSION', 'Emissions'),
 ('FUEL_EFFICIENCY', 'Fuel consumption / CO2'),
 ('EV_ALT_FUEL', 'EV and alternative fuels'),
 ('BATTERY', 'Traction battery'),
 ('CHARGING', 'Charging'),
 ('CYBERSECURITY', 'Cybersecurity and software updates'),
 ('TRACKING_ITS', 'Tracking / ITS'),
 ('TYPE_APPROVAL', 'Type approval and CoP'),
 ('DIMENSIONS_WEIGHTS', 'Dimensions and weights'),
 ('REGISTRATION', 'Registration'),
 ('HSRP', 'High security registration plates'),
 ('LICENSING', 'Driving licence'),
 ('PERMIT', 'Permits'),
 ('FEES', 'Fees and charges'),
 ('FITNESS_PUC', 'Fitness and inspection'),
 ('RECALL_SCRAPPAGE', 'Recall and scrappage')
ON CONFLICT (code) DO NOTHING;

INSERT INTO vehicle_categories (region_id, code, label, un_codes)
  SELECT r.id, v.code, v.label, v.un_codes
  FROM (VALUES
   ('IN', 'L1', 'Two-wheeler, low speed (max design speed <= 45 km/h)', ARRAY['L1']),
   ('IN', 'L2', 'Two-wheeler (max design speed > 45 km/h)', ARRAY['L3']),
   ('IN', 'L3', 'Two-wheeler (L3 category)', ARRAY['L3']),
   ('IN', 'L4', 'Two-wheeler with side car (L4 category)', ARRAY['L4']),
   ('IN', 'L5', 'Three-wheeler', ARRAY['L5']),
   ('IN', 'L6', 'Light quadricycle (L6)', ARRAY['L6']),
   ('IN', 'L7', 'Heavy quadricycle (L7)', ARRAY['L7']),
   ('IN', 'QUADRICYCLE', 'Quadricycle (unspecified)', ARRAY['L6','L7']),
   ('IN', 'M1', 'Passenger vehicle, <= 8 seats plus driver', ARRAY['M1']),
   ('IN', 'M2', 'Passenger vehicle, > 8 seats, GVW <= 5 t', ARRAY['M2']),
   ('IN', 'M3', 'Passenger vehicle, > 8 seats, GVW > 5 t', ARRAY['M3']),
   ('IN', 'N1', 'Goods vehicle, GVW <= 3.5 t', ARRAY['N1']),
   ('IN', 'N2', 'Goods vehicle, 3.5 t < GVW <= 12 t', ARRAY['N2']),
   ('IN', 'N3', 'Goods vehicle, GVW > 12 t', ARRAY['N3']),
   ('IN', 'O',  'Trailer (O1-O4)', ARRAY['O1','O2','O3','O4']),
   ('IN', 'T',  'Agricultural tractor (T1-T5)', ARRAY['T']),
   ('IN', 'CEV', 'Construction equipment vehicle', '{}'::TEXT[]),
   ('IN', 'E_RICKSHAW', 'E-rickshaw', ARRAY['L5']),
   ('IN', 'E_CART', 'E-cart', ARRAY['L5']),
   ('IN', 'ALL', 'All motor vehicles', ARRAY['ALL']),
   ('UN', 'L1', 'Two-wheeled moped (<= 50 cm3 and <= 50 km/h)', ARRAY['L1']),
   ('UN', 'L2', 'Three-wheeled moped (<= 50 cm3 and <= 50 km/h)', ARRAY['L2']),
   ('UN', 'L3', 'Motorcycle (two wheels, > 50 cm3 or > 50 km/h)', ARRAY['L3']),
   ('UN', 'L4', 'Motorcycle with sidecar', ARRAY['L4']),
   ('UN', 'L5', 'Motor tricycle (three symmetric wheels)', ARRAY['L5']),
   ('UN', 'L6', 'Light quadricycle', ARRAY['L6']),
   ('UN', 'L7', 'Quadricycle', ARRAY['L7']),
   ('UN', 'M1', 'Passenger vehicle, <= 8 seats plus driver', ARRAY['M1']),
   ('UN', 'M2', 'Passenger vehicle, > 8 seats, max. mass <= 5 t', ARRAY['M2']),
   ('UN', 'M3', 'Passenger vehicle, > 8 seats, max. mass > 5 t', ARRAY['M3']),
   ('UN', 'N1', 'Goods vehicle, max. mass <= 3.5 t', ARRAY['N1']),
   ('UN', 'N2', 'Goods vehicle, 3.5 t < max. mass <= 12 t', ARRAY['N2']),
   ('UN', 'N3', 'Goods vehicle, max. mass > 12 t', ARRAY['N3']),
   ('UN', 'O1', 'Trailer, max. mass <= 0.75 t', ARRAY['O1']),
   ('UN', 'O2', 'Trailer, 0.75 t < max. mass <= 3.5 t', ARRAY['O2']),
   ('UN', 'O3', 'Trailer, 3.5 t < max. mass <= 10 t', ARRAY['O3']),
   ('UN', 'O4', 'Trailer, max. mass > 10 t', ARRAY['O4']),
   ('UN', 'T',  'Agricultural or forestry tractor', ARRAY['T']),
   ('UN', 'ALL', 'All motor vehicles', ARRAY['ALL'])
  ) AS v(region, code, label, un_codes)
  JOIN regions r ON r.code = v.region
ON CONFLICT (region_id, code) DO NOTHING;

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
    ('UN', 'UNECE',            'UNECE World Forum for Harmonization of Vehicle Regulations (WP.29)', 'https://unece.org')
  ) AS a(region, code, name, url)
  JOIN regions r ON r.code = a.region
ON CONFLICT (code) DO NOTHING;

INSERT INTO sources (region_id, authority_id, code, name, base_url, scraper_key, is_active, sync_frequency_minutes)
  SELECT r.id, au.id, s.code, s.name, s.base_url, s.scraper_key, s.is_active, s.sync_minutes
  FROM (VALUES
    ('ARAI_AIS',  'ARAI - AIS standards list',                              'https://hmr.araiindia.com',   'arai',      TRUE,  360, 'AISC_ARAI'),
    ('MORTH_API', 'MoRTH - notifications, orders, guidelines (JSON API)',   'https://morth.gov.in',        'morth',     TRUE,  360, 'MORTH'),
    ('EGAZETTE',  'e-Gazette of India',                                    'https://egazette.gov.in',     'egazette',  TRUE,  360, NULL),
    ('INDIACODE', 'India Code - CMVR subordinate legislation',             'https://www.indiacode.nic.in','indiacode', TRUE, 1440, NULL),
    ('ARAI_TAP',  'ARAI - CMVR-TAP documents',                             'https://www.araiindia.com',   NULL,        TRUE, 1440, 'AISC_ARAI'),
    ('LOCAL_SEED','Seed corpus D:\Regulatory_Documents (one-time import)', NULL,                           NULL,        TRUE,    0, NULL)
  ) AS s(code, name, base_url, scraper_key, is_active, sync_minutes, authority_code)
  JOIN regions r ON r.code = 'IN'
  LEFT JOIN regulatory_authorities au ON au.code = s.authority_code
ON CONFLICT (code) DO NOTHING;
