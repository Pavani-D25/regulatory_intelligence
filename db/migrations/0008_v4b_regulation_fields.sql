-- 0008: derived fields of regulations (v4B), the counterpart of refresh_universal_fields() from 0006.
-- Adds one function; no tables change. Called at the end of every pipeline run (runner.post_run).
-- Fills the country-neutral fields of one region's regulations from their local data:
--   doc_type, doc_role   from document_classes, or AMENDMENT/BASE from what the regulation amends
--   local_type, language the local series name; the region's first language when not read
--   legal_force          must anyone comply? (a standard is mandatory while an open requirement version cites it)
-- Only rows whose values change are written, so a second run returns 0 (CLAUDE.md rule 7).
-- UNECE categories need no copy here: they are read through regulation_vehicle_categories -> vehicle_categories.un_codes.

CREATE FUNCTION refresh_regulation_fields(cc TEXT) RETURNS INTEGER
LANGUAGE plpgsql AS $$
DECLARE
  n INTEGER := 0;
  k INTEGER;
  rid INTEGER;
BEGIN
  SELECT id INTO rid FROM regions WHERE code = cc;
  IF rid IS NULL THEN
    RETURN 0;
  END IF;

  WITH calc AS (
    SELECT g.id, coalesce(dc.doc_type, 'UNKNOWN') AS doc_type,
           CASE WHEN dc.doc_type IS NULL OR dc.doc_type IN ('OFF_TOPIC','UNKNOWN') THEN NULL
                ELSE coalesce(dc.doc_role,
                              -- it amends something: a saved relation, or what extraction read from the text
                              -- (the amended regulation is often not in the database, so no relation exists)
                              CASE WHEN EXISTS (SELECT 1 FROM regulation_relations r WHERE r.from_regulation_id = g.id
                                                AND r.type IN ('amends','substitutes_row','inserts_row','omits_row'))
                                     OR jsonb_array_length(coalesce(g.data->'amends_targets', '[]')) > 0
                                     OR jsonb_array_length(coalesce(g.data->'amends_notification', '[]')) > 0
                                   THEN 'AMENDMENT' ELSE 'BASE' END) END AS doc_role,
           coalesce(g.local_type, g.series) AS local_type,
           coalesce(g.language, rg.languages[1]) AS language
    FROM regulations g
    JOIN regions rg ON rg.id = g.region_id
    LEFT JOIN document_classes dc ON dc.region_id = g.region_id AND dc.code = g.local_class
    WHERE g.region_id = rid)
  UPDATE regulations g
     SET doc_type = calc.doc_type, doc_role = calc.doc_role, local_type = calc.local_type, language = calc.language
    FROM calc
   WHERE calc.id = g.id
     AND (g.doc_type IS DISTINCT FROM calc.doc_type OR g.doc_role IS DISTINCT FROM calc.doc_role
          OR g.local_type IS DISTINCT FROM calc.local_type OR g.language IS DISTINCT FROM calc.language);
  GET DIAGNOSTICS k = ROW_COUNT; n := n + k;

  WITH lf AS (
    SELECT g.id, CASE
             WHEN g.doc_type IS NULL OR g.doc_type IN ('OFF_TOPIC','UNKNOWN') THEN 'UNKNOWN'
             WHEN g.legal_status = 'draft' THEN 'INFORMATIVE'
             WHEN g.doc_type IN ('GUIDANCE','REFERENCE') THEN 'INFORMATIVE'
             WHEN g.doc_type IN ('LAW','REGULATION') THEN 'MANDATORY'
             WHEN EXISTS (SELECT 1 FROM requirement_versions v
                          JOIN compliance_requirements c ON c.id = v.requirement_id
                          WHERE c.region_id = g.region_id AND v.valid_to IS NULL AND NOT v.is_draft
                            AND (g.id = ANY(v.standard_regulation_ids) OR g.external_code = ANY(v.standard_refs)
                                 OR g.family_key = ANY(v.standard_refs))) THEN 'MANDATORY'
             ELSE 'VOLUNTARY' END AS force
    FROM regulations g WHERE g.region_id = rid)
  UPDATE regulations g SET legal_force = lf.force FROM lf
   WHERE lf.id = g.id AND g.legal_force IS DISTINCT FROM lf.force;
  GET DIAGNOSTICS k = ROW_COUNT; n := n + k;
  RETURN n;
END $$;
