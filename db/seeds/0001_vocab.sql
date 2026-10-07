-- Lookup seeds. Labels follow CMVR Rule 2 / AIS-053 category definitions in short form.
-- Synonyms are the plain words found in the corpus profile; extend them as the ETL logs unmapped words.

INSERT INTO vehicle_category (code, label, synonyms, in_scope) VALUES
 ('L1', 'Two-wheeler, low speed (max design speed ≤ 45 km/h)', ARRAY['moped','mopeds','low speed two wheeler','category L1'], TRUE),
 ('L2', 'Two-wheeler (max design speed > 45 km/h)', ARRAY['motor cycle','motorcycle','motor cycles','scooter','scooters','two wheeler','two-wheeler','two wheeled','category L2'], TRUE),
 ('L3', 'Two-wheeler (L3 category)', ARRAY['category L3'], FALSE),
 ('L4', 'Two-wheeler with side car (L4 category)', ARRAY['side car','category L4'], FALSE),
 ('L5', 'Three-wheeler', ARRAY['three wheeler','three-wheeler','auto rickshaw','category L5'], FALSE),
 ('L6', 'Light quadricycle (L6)', ARRAY['light quadricycle'], FALSE),
 ('L7', 'Heavy quadricycle (L7)', ARRAY['heavy quadricycle'], FALSE),
 ('QUADRICYCLE', 'Quadricycle (unspecified)', ARRAY['quadricycle','quadricycles'], FALSE),
 ('M1', 'Passenger vehicle, ≤ 8 seats plus driver', ARRAY['passenger car','passenger cars','car','cars','four wheeler','four-wheeler','motor car','category M1'], TRUE),
 ('M2', 'Passenger vehicle, > 8 seats, GVW ≤ 5 t', ARRAY['mini bus','category M2'], FALSE),
 ('M3', 'Passenger vehicle, > 8 seats, GVW > 5 t', ARRAY['bus','buses','coach','category M3'], FALSE),
 ('N1', 'Goods vehicle, GVW ≤ 3.5 t', ARRAY['light goods vehicle','light commercial vehicle','LCV','category N1'], TRUE),
 ('N2', 'Goods vehicle, 3.5 t < GVW ≤ 12 t', ARRAY['medium goods vehicle','category N2'], FALSE),
 ('N3', 'Goods vehicle, GVW > 12 t', ARRAY['heavy goods vehicle','truck','trucks','category N3'], FALSE),
 ('O',  'Trailer (O1–O4)', ARRAY['trailer','trailers','semi-trailer'], FALSE),
 ('T',  'Agricultural tractor (T1–T5)', ARRAY['agricultural tractor','tractor','tractors'], FALSE),
 ('CEV', 'Construction equipment vehicle', ARRAY['construction equipment vehicle','CEV'], FALSE),
 ('E_RICKSHAW', 'E-rickshaw', ARRAY['e-rickshaw','e rickshaw','battery operated rickshaw'], FALSE),
 ('E_CART', 'E-cart', ARRAY['e-cart','e cart'], FALSE),
 ('ALL', 'All motor vehicles', ARRAY['all motor vehicles','every motor vehicle','all categories'], TRUE)
ON CONFLICT (code) DO NOTHING;

INSERT INTO domain (code, label, keywords) VALUES
 ('safety_equipment', 'Safety equipment', ARRAY['airbag','seat belt','helmet','tyre','reflector','under-run','speed governor','speed limiting']),
 ('braking', 'Braking', ARRAY['anti-lock','ABS','combined braking','CBS','braking system']),
 ('lighting', 'Lighting and signalling', ARRAY['lamp','headlamp','lighting','light signalling','AHO']),
 ('emission', 'Emissions', ARRAY['mass emission','Bharat Stage','BS-VI','BS-IV','smoke','evaporative','PUC']),
 ('fuel_efficiency', 'Fuel consumption / CO2', ARRAY['fuel consumption','fuel efficiency','CAFE','CO2']),
 ('ev_alt_fuel', 'EV and alternative fuels', ARRAY['battery operated','electric vehicle','hybrid','CNG','LPG','ethanol','flex fuel','hydrogen','bio-diesel']),
 ('battery', 'Traction battery', ARRAY['traction battery','REESS','battery pack']),
 ('charging', 'Charging', ARRAY['charging','charger','charging station']),
 ('cybersecurity', 'Cybersecurity and software updates', ARRAY['cyber security','software update']),
 ('tracking_its', 'Tracking / ITS', ARRAY['vehicle location tracking','AIS-140','panic button','emergency button','FASTag']),
 ('type_approval', 'Type approval and CoP', ARRAY['type approval','conformity of production','testing agency','rule 126']),
 ('dimensions_weights', 'Dimensions and weights', ARRAY['gross vehicle weight','axle weight','overall length','overall width']),
 ('registration', 'Registration', ARRAY['registration mark','certificate of registration','registering authority','BH series']),
 ('hsrp', 'High security registration plates', ARRAY['high security registration','HSRP']),
 ('licensing', 'Driving licence', ARRAY['driving licence','learner','driving training']),
 ('permit', 'Permits', ARRAY['permit','tourist vehicle','national permit']),
 ('fees', 'Fees and charges', ARRAY['fees','fee','rupees']),
 ('fitness_puc', 'Fitness and inspection', ARRAY['fitness certificate','automated testing station','inspection and certification']),
 ('recall_scrappage', 'Recall and scrappage', ARRAY['recall','scrapping','end-of-life'])
ON CONFLICT (code) DO NOTHING;

INSERT INTO source (code, name, base_url, schedule_hours) VALUES
 ('ARAI_AIS',  'ARAI – AIS standards list', 'https://hmr.araiindia.com', 6),
 ('MORTH_API', 'MoRTH – notifications, orders, guidelines (JSON API)', 'https://morth.gov.in', 6),
 ('EGAZETTE',  'e-Gazette of India', 'https://egazette.gov.in', 6),
 ('INDIACODE', 'India Code – CMVR subordinate legislation', 'https://www.indiacode.nic.in', 24),
 ('ARAI_TAP',  'ARAI – CMVR-TAP documents', 'https://www.araiindia.com', 24),
 ('LOCAL_SEED','Seed corpus D:\Regulatory_Documents (one-time import)', NULL, 0)
ON CONFLICT (code) DO NOTHING;
