-- 0015: `subject_source` (where a regulation's subject line came from when its content gave none: the ARAI listing or
-- another listing) is provenance, so it belongs in regulations.extraction next to the model and confidence
-- (CLAUDE.md rule 8), not in regulations.data, whose shape is the Pydantic model of the doc_class (rule 6). Extraction
-- wrote it into data, which the models forbid: 401 schema_violation flags, each with this one error. Data move only;
-- no table changes. Extraction now writes extraction.subject_source (regtrack/pipeline/extract.py).

-- the schema_violation flags whose only error was this key: settled, with the evidence
UPDATE quality_flags q
   SET resolved_at = now(),
       details = q.details || jsonb_build_object(
         'resolution', 'subject_source moved from data to extraction (migration 0015); data matches its model',
         'evidence', jsonb_build_object('subject_source', g.data->'subject_source'))
  FROM regulations g
 WHERE q.rule = 'schema_violation' AND q.entity = 'regulation' AND q.entity_id = g.id AND q.resolved_at IS NULL
   AND g.data ? 'subject_source'
   AND jsonb_array_length(coalesce(q.details->'errors', '[]')) = 1
   AND q.details->'errors'->>0 LIKE '%''subject_source'' was unexpected%';

UPDATE regulations
   SET extraction = coalesce(extraction, '{}'::jsonb) || jsonb_build_object('subject_source', data->'subject_source'),
       data = data - 'subject_source'
 WHERE data ? 'subject_source';
