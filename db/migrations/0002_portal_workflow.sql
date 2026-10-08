-- Portal workflow tables (approved portal design v2): what the team enters on top of the regulatory data.
-- The regulatory tables stay as they are; these only hold review status, compliance tracking, alert rules,
-- generated-report history and settings.

-- review status of a regulation (document) set by the team; absent = status derived from the data
CREATE TABLE document_review (
  document_id  BIGINT PRIMARY KEY REFERENCES document(id) ON DELETE CASCADE,
  status       TEXT NOT NULL CHECK (status IN ('Action Required','Under Review','Impact Analysis','Tracked')),
  impact       TEXT CHECK (impact IN ('High','Medium','Low')),       -- team override of the computed impact
  owner        TEXT,
  note         TEXT,
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- compliance tracking per requirement (a requirement = an open mandate slot, identified by mandate_key)
CREATE TABLE compliance_item (
  mandate_key  TEXT PRIMARY KEY,
  owner        TEXT,
  evidence     TEXT,
  status       TEXT NOT NULL DEFAULT 'Open' CHECK (status IN ('Open','In Progress','Compliant','Not Applicable')),
  due_date     DATE,
  note         TEXT,
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- alert rules evaluated against change events and upcoming implementation dates
CREATE TABLE alert_rule (
  id           BIGSERIAL PRIMARY KEY,
  name         TEXT NOT NULL,
  scope        TEXT NOT NULL DEFAULT 'All categories',   -- 'All categories' | 'L1' | 'L2' | 'M1' | 'N1'
  condition    TEXT NOT NULL CHECK (condition IN ('high_impact','new_document','draft_published','draft_finalised',
                                                  'date_changed','due_within','domain')),
  param        TEXT,                                      -- days for due_within, domain code for domain
  enabled      BOOLEAN NOT NULL DEFAULT TRUE,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- history of generated reports (the files are produced on demand from current data)
CREATE TABLE report_log (
  id           BIGSERIAL PRIMARY KEY,
  kind         TEXT NOT NULL,
  scope        TEXT,
  generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  owner        TEXT,
  rows         INT
);

-- portal settings (default owner, review SLA, ...)
CREATE TABLE app_setting (
  key    TEXT PRIMARY KEY,
  value  TEXT NOT NULL
);

INSERT INTO app_setting (key, value) VALUES
  ('default_owner', 'Regulatory Affairs Team'),
  ('review_sla_days', '2'),
  ('high_impact_rule', 'in-scope technical with an upcoming or changed obligation'),
  ('auto_sync', 'true'),
  ('auto_compliance_task', 'true')
ON CONFLICT (key) DO NOTHING;

INSERT INTO alert_rule (name, scope, condition, param) VALUES
  ('High-impact changes', 'All categories', 'high_impact', NULL),
  ('Implementation dates within 60 days', 'All categories', 'due_within', '60'),
  ('New draft notifications', 'All categories', 'draft_published', NULL),
  ('Two-wheeler braking changes', 'L2', 'domain', 'braking');

CREATE INDEX change_event_review_idx ON change_event (review_status);
