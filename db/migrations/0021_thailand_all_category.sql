-- 0021: 'ALL' for Thailand (a motor-vehicle law naming no category applies to all motor vehicles, CLAUDE.md);
-- IN_SCOPE_CATEGORIES_BY_COUNTRY["TH"] already lists it, but there was no vehicle_categories row to store it in.
INSERT INTO vehicle_categories (region_id, code, label, un_codes)
  SELECT (SELECT id FROM regions WHERE code = 'TH'), 'ALL', 'All motor vehicles', ARRAY['L1','L3','M1','N1']
ON CONFLICT (region_id, code) DO NOTHING;
INSERT INTO region_scope (region_id, vehicle_category_id)
  SELECT vc.region_id, vc.id FROM vehicle_categories vc
  WHERE vc.region_id = (SELECT id FROM regions WHERE code = 'TH') AND vc.code = 'ALL'
ON CONFLICT DO NOTHING;
