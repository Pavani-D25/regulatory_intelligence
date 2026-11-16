-- 0025: the impact KPIs (regtrack/kpi.py) a team sets for a regulation. Each of the eight criteria is scored
-- 0-5 (0 = not applicable); the portal computes every criterion from the data and a row here replaces that
-- criterion's computed score. Deleting a row returns the criterion to its computed score.
CREATE TABLE IF NOT EXISTS regulation_kpi_scores (
    regulation_id BIGINT      NOT NULL REFERENCES regulations (id) ON DELETE CASCADE,
    criterion     TEXT        NOT NULL CHECK (criterion IN (
                      'regulatory', 'functional_safety', 'cybersecurity', 'protocol_interface',
                      'architecture', 'verification', 'exposure', 'urgency')),
    score         SMALLINT    NOT NULL CHECK (score BETWEEN 0 AND 5),
    note          TEXT,
    team_id       INTEGER     REFERENCES teams (id) ON DELETE SET NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (regulation_id, criterion)
);
