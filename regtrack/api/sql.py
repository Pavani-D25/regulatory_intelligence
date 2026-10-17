"""The v4B tables in the shape the API returns (docs/SCHEMA_V4B.md), one definition each.

The dashboard was built on the first schema: a regulation is a "document" with canonical_id, doc_class, status,
issuer, vehicle_categories[] and domains[]; a rule version is a "mandate" with mandate_key and category codes; a change
has event_type and review_status auto / needs_check / confirmed; a source run is ok / partial / failed. These derived
tables translate v4B into that shape so the endpoints and the dashboard keep their contract. Each takes the country
(region code) it shows.
"""

from __future__ import annotations

from regtrack import country
from regtrack.pipeline import repo
from regtrack.pipeline.mandates import version_sql

RUN_STATUS = "CASE {c} WHEN 'success' THEN 'ok' WHEN 'warning' THEN 'partial' ELSE {c} END"
# a change's review state as the portal knows it: reviewed -> confirmed; otherwise auto when Qwen wrote the summary,
# needs_check when it is a template
REVIEW = ("CASE WHEN {e}.review_status = 'reviewed' THEN 'confirmed' "
          "WHEN {e}.details->>'summary_by' = 'qwen' THEN 'auto' ELSE 'needs_check' END")


def docs(cc: str | None = None) -> str:
    """Regulations as documents (same columns as pipeline/repo.py)."""
    return f"({repo.REG_SQL} WHERE {country.region_sql('g', cc)})"


def mandates(cc: str | None = None) -> str:
    """Rule versions as mandates: the columns of the old mandate table (mandate_key, source_doc_id, standard_doc_ids,
    vehicle_categories as codes and their UNECE codes, country)."""
    return f"""(SELECT m.id, m.legal_basis, m.mandate_key, m.subject, m.standard_refs, m.standard_doc_ids,
                       m.vehicle_categories, m.conditions, m.model_scope, m.usage, m.powertrains, m.date_of_notification,
                       m.effective_date, m.implementation_date, m.implementation_rule, m.is_draft, m.source_doc_id,
                       m.valid_from, m.valid_to, m.superseded_by, m.recorded_at, rg.code AS country,
                       coalesce((SELECT array_agg(DISTINCT u ORDER BY u) FROM vehicle_categories vc, unnest(vc.un_codes) u
                                 WHERE vc.id = ANY(m.vehicle_category_ids)), '{{}}') AS vehicle_categories_un
                FROM ({version_sql(cc)}) m
                JOIN compliance_requirements cr ON cr.id = m.requirement_id JOIN regions rg ON rg.id = cr.region_id)"""


def changes(cc: str | None = None) -> str:
    """regulation_changes as change events (review_status as in REVIEW)."""
    return f"""(SELECT e.id, e.change_type AS event_type, e.regulation_id AS document_id,
                       e.requirement_version_id AS mandate_id, e.detected_at, e.summary, initcap(e.severity) AS impact,
                       coalesce(e.details, '{{}}'::jsonb) - 'legacy_review_status'
                         || CASE WHEN e.reviewed_at IS NOT NULL
                                 THEN jsonb_build_object('reviewed_at', e.reviewed_at) ELSE '{{}}'::jsonb END AS details,
                       {REVIEW.format(e='e')} AS review_status,
                       e.reviewed_at, e.sla_due_at, rg.code AS country
                FROM regulation_changes e JOIN regions rg ON rg.id = e.region_id
                WHERE {country.region_sql('e', cc)})"""


def sources(cc: str | None = None) -> str:
    """sources with the old names: schedule_hours, last_run_at, last_status (ok / partial / failed)."""
    return f"""(SELECT s.id, s.code, s.name, s.base_url, s.sync_frequency_minutes / 60 AS schedule_hours,
                       s.last_synced_at AS last_run_at, {RUN_STATUS.format(c='s.last_sync_status')} AS last_status,
                       s.is_active, rg.code AS country
                FROM sources s JOIN regions rg ON rg.id = s.region_id WHERE {country.region_sql('s', cc)})"""


def runs(cc: str | None = None) -> str:
    """ingestion_runs as crawl runs (status ok / partial / failed / running)."""
    return f"""(SELECT r.id, r.source_id, r.started_at, r.finished_at, {RUN_STATUS.format(c='r.status')} AS status,
                       r.stats, r.log
                FROM ingestion_runs r JOIN sources s ON s.id = r.source_id WHERE {country.region_sql('s', cc)})"""


def settings(conn) -> dict[str, str]:
    """app_settings as text values (JSON numbers, booleans and strings), as the portal used them."""
    return {r["key"]: r["v"] for r in conn.execute("SELECT key, value #>> '{}' AS v FROM app_settings")}


def put_setting(conn, key: str, value: str) -> None:
    conn.execute("""INSERT INTO app_settings (key, value)
                    VALUES (%s, CASE WHEN %s ~ '^-?[0-9]+(\\.[0-9]+)?$' OR %s IN ('true','false') THEN %s::jsonb
                                     ELSE to_jsonb(%s::text) END)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""", (key, value, value, value, value))
