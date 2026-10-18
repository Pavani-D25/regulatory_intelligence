-- 0011: the switch-over to v4B is complete; the tables of migrations 0001-0006 are dropped (docs/SCHEMA_V4B.md §4,
-- phase 8). Every one of them was copied into its v4B table by 0007:
--   file_object -> documents, file_sighting -> raw_ingestion_records, document -> regulations (+ link tables),
--   document_file -> document_parts, doc_relation -> regulation_relations, mandate -> requirement_versions
--   (+ compliance_requirements), chunk -> document_chunks, change_event -> regulation_changes,
--   quality_flag -> quality_flags, crawl_run -> ingestion_runs, source -> sources, country -> regions,
--   vehicle_category -> vehicle_categories, domain -> domains, local_class -> document_classes,
--   country_scope -> region_scope, vocab_term -> region_terms, compliance_item -> compliance_requirements,
--   document_review -> regulations (workflow fields), alert_rule -> alert_rules, report_log -> reports,
--   app_setting -> app_settings, requirement -> client_requirements,
--   requirement_document -> client_requirement_regulations
--
-- Guard: on a database that holds data, this runs only after the switch-over was verified
-- (app_settings 'v4b_switch_verified' = true, set by the phase-8 verification); a fresh database (no old rows)
-- passes straight through. Without the guard, one `migrate` would copy (0007) and drop (0011) with no check between.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM document) AND NOT EXISTS (
       SELECT 1 FROM app_settings WHERE key = 'v4b_switch_verified' AND value = 'true'::jsonb) THEN
    RAISE EXCEPTION 'v4B switch-over not verified: run the phase-8 verification before dropping the old tables';
  END IF;
END $$;

DROP FUNCTION refresh_universal_fields(TEXT);
DROP FUNCTION un_vehicle_categories(TEXT, TEXT[]);

-- one statement: PostgreSQL resolves the foreign keys among the listed tables; nothing outside this list may still
-- depend on them (no CASCADE, so an unexpected dependency stops the migration instead of dropping it silently)
DROP TABLE requirement_document, requirement, report_log, alert_rule, compliance_item, document_review, change_event,
           quality_flag, chunk, mandate, doc_relation, document_file, file_sighting, crawl_run, file_object, document,
           vocab_term, country_scope, local_class, vehicle_category, domain, source, app_setting, country;
