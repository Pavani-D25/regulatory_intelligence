-- 0024: what a scheduled report covers, like reports.parameters for a generated one. Today
-- {"segment": "4W/PV/M1/transport"} (regtrack/segments.py); {} = every in-scope vehicle category, as before.
ALTER TABLE report_schedules ADD COLUMN IF NOT EXISTS parameters JSONB NOT NULL DEFAULT '{}'::jsonb;
