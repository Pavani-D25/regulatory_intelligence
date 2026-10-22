-- 0019: Malaysia's legal texts (phase MY-2). JPJ publishes the Road Transport Act 1987 (Akta 333) and Akta 334, DOE
-- the vehicle emission regulations (P.U.(A) 543/96, 429/96, 488/2000, 464/2003), as public PDFs shown in viewer widgets
-- on their own pages (checked 2026-10-22: no login, no captcha). The AGC Laws of Malaysia portal is not used: its
-- document links carry signed per-link tokens (CLAUDE.md rule 2); the Federal Gazette site did not answer.

INSERT INTO sources (region_id, authority_id, code, name, base_url, is_active, sync_frequency_minutes)
  SELECT r.id, au.id, s.code, s.name, s.url, true, 360
  FROM (VALUES
    ('MY_JPJ_ACTS', 'JPJ acts (Akta 333, Akta 334)',        'https://www.jpj.gov.my/akta-333/', 'JPJ'),
    ('MY_DOE_REGS', 'DOE vehicle emission regulations',      'https://www.doe.gov.my/en/environmental-quality-control-of-emissions-from-petrol-engines-regulations-1996-p-u-a-543-96/', 'DOE_MY')
  ) AS s(code, name, url, authority_code)
  JOIN (SELECT id FROM regions WHERE code = 'MY') r ON true
  JOIN regulatory_authorities au ON au.code = s.authority_code
ON CONFLICT (code) DO NOTHING;

INSERT INTO document_classes (region_id, code, doc_type, doc_role, sub_type)
  SELECT (SELECT id FROM regions WHERE code = 'MY'), c.code, c.doc_type, c.doc_role, c.sub_type
  FROM (VALUES
    ('MY_ACT',                    'LAW',        NULL, NULL),
    ('MY_SUBSIDIARY_LEGISLATION', 'REGULATION', NULL, NULL)
  ) AS c(code, doc_type, doc_role, sub_type)
ON CONFLICT DO NOTHING;
