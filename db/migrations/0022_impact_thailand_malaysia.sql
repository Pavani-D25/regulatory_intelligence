-- 0022: impact calibration for Thailand and Malaysia. The rule-based impact (0010) counted a document as
-- technical only if India's classifier marked it so or it was an AIS / TAP standard, so every Thai TIS standard and
-- every Malaysian regulation scored 'low'. Technical now also: a mandatory TIS standard; a Malaysian emission
-- regulation (P.U.(A)); a Malaysian document that is the source of in-force obligations naming standards (the JPJ
-- CTA component list). High / medium / low then follow the same rule as India's. India is unchanged: the new
-- conditions only match TH / MY document classes. Only the impact block differs from 0010's function.

CREATE OR REPLACE FUNCTION refresh_regulation_fields(cc TEXT) RETURNS INTEGER
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

  -- impact (rule-based): High = technical and (an obligation still to come, a revision needing re-approval, or
  -- published in the last 12 months); Medium = other technical; Low = administrative / procedural.
  -- "Technical" now also covers Thailand's and Malaysia's technical documents (0022); India's definition is unchanged.
  WITH imp AS (
    SELECT g.id, CASE
             WHEN NOT (coalesce(g.nature, '') = 'technical' OR g.local_class LIKE 'AIS\_%' OR g.local_class LIKE 'TAP\_%'
                       -- Thailand: a mandatory TIS standard; Malaysia: an emission regulation (P.U.(A)), or a
                       -- document that is the source of in-force component obligations with standards (JPJ CTA list)
                       OR g.local_class IN ('TIS_STANDARD', 'MY_SUBSIDIARY_LEGISLATION')
                       OR (g.local_class LIKE 'MY\_%' AND EXISTS (
                             SELECT 1 FROM requirement_versions v WHERE v.source_regulation_id = g.id
                             AND v.valid_to IS NULL AND NOT v.is_draft AND cardinality(v.standard_refs) > 0))) THEN 'low'
             WHEN EXISTS (SELECT 1 FROM requirement_versions v WHERE v.source_regulation_id = g.id
                          AND v.valid_to IS NULL AND NOT v.is_draft AND v.implementation_date >= current_date)
               OR EXISTS (SELECT 1 FROM regulation_relations r WHERE r.from_regulation_id = g.id AND r.requires_reapproval)
               OR g.published_date >= current_date - 365 THEN 'high'
             ELSE 'medium' END AS level
    FROM regulations g WHERE g.region_id = rid AND g.impact_basis IS DISTINCT FROM 'team')
  UPDATE regulations g SET impact_level = imp.level, impact_basis = 'rules' FROM imp
   WHERE imp.id = g.id AND (g.impact_level IS DISTINCT FROM imp.level OR g.impact_basis IS DISTINCT FROM 'rules');
  GET DIAGNOSTICS k = ROW_COUNT; n := n + k;
  RETURN n;
END $$;
