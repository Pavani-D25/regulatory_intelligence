-- 0020: documents people saved by hand (regtrack/sources/local_import.py, <IMPORT_DIR>/TH and /MY), for sources the
-- crawlers may not reach (DLT refuses connections from outside Thailand; the Council of State law search and the
-- Royal Gazette use captchas). Same pipeline as crawled files: write-once originals, identity from content.
-- TH_ACT: a Thai Act (พระราชบัญญัติ), e.g. the Motor Vehicle Act B.E. 2522.

INSERT INTO sources (region_id, authority_id, code, name, base_url, is_active, sync_frequency_minutes)
  SELECT r.id, NULL, s.code, s.name, NULL, true, 360
  FROM (VALUES ('TH', 'TH_LOCAL', 'Thailand: documents saved by hand'),
               ('MY', 'MY_LOCAL', 'Malaysia: documents saved by hand')) AS s(cc, code, name)
  JOIN regions r ON r.code = s.cc
ON CONFLICT (code) DO NOTHING;

INSERT INTO document_classes (region_id, code, doc_type, doc_role, sub_type)
  SELECT (SELECT id FROM regions WHERE code = 'TH'), 'TH_ACT', 'LAW', NULL, NULL
ON CONFLICT DO NOTHING;
