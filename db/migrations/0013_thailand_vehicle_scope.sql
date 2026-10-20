-- 0013: Thailand's vehicle-category scope (phase TH-1 of the Thailand-parity plan).
-- Thailand uses UNECE category meanings directly (unlike India, whose own L2 = UNECE L3), so its codes are
-- self-mapping. The in-scope set itself (L1, L3, M1, N1, ALL - the functional equivalents of India's L1/L2/M1/N1)
-- is in regtrack/models/enums.py (IN_SCOPE_CATEGORIES_BY_COUNTRY); this migration only adds the label rows the
-- portal reads via load_vocab(). L3 is used rather than L2 because Thailand's own L2 already means something
-- different (three-wheeled moped) under UNECE numbering - reusing it here would misrepresent the category.

INSERT INTO vehicle_categories (region_id, code, label, un_codes)
  SELECT (SELECT id FROM regions WHERE code = 'TH'), code, label, un_codes
  FROM (VALUES
    ('L1', 'Two-wheeled moped (<=50 cm3 or <=50 km/h)', ARRAY['L1']),
    ('L3', 'Motorcycle (>50 cm3 or >50 km/h)',           ARRAY['L3']),
    ('M1', 'Passenger car, <=8 seats plus driver',       ARRAY['M1']),
    ('N1', 'Light goods vehicle, GVW <=3.5 t',            ARRAY['N1'])
  ) AS v(code, label, un_codes)
ON CONFLICT (region_id, code) DO NOTHING;

INSERT INTO region_scope (region_id, vehicle_category_id)
  SELECT vc.region_id, vc.id FROM vehicle_categories vc
  WHERE vc.region_id = (SELECT id FROM regions WHERE code = 'TH')
ON CONFLICT DO NOTHING;
