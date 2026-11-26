-- 0027: WTO ePing, Thailand's TBT notifications (regtrack/sources/thailand_eping.py). The ePing search
-- (https://eping.wto.org/en/Search/Index, Area: TBT, Notifying Member: Thailand) reads a public JSON API; each
-- notification's official English text is the WTO document (docs.wto.org). Only the vehicle-related ones are
-- downloaded. WTO_TBT_NOTIFICATION: a notification of a draft technical regulation / standard, or its addendum
-- (adopted, published, entry into force), revision or corrigendum; its identity is the WTO symbol (G/TBT/N/THA/797).

INSERT INTO sources (region_id, authority_id, code, name, base_url, is_active, sync_frequency_minutes)
  SELECT r.id, NULL, 'TH_EPING_TBT', 'WTO ePing: TBT notifications of Thailand',
         'https://eping.wto.org/en/Search/Index', true, 360
  FROM regions r WHERE r.code = 'TH'
ON CONFLICT (code) DO NOTHING;

INSERT INTO document_classes (region_id, code, doc_type, doc_role, sub_type)
  SELECT (SELECT id FROM regions WHERE code = 'TH'), 'WTO_TBT_NOTIFICATION', 'REGULATION', NULL, NULL
ON CONFLICT DO NOTHING;
