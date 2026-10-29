"""Phase 8 of the v4B switch-over (docs/SCHEMA_V4B.md): prove that the v4B tables hold the same data as the old ones
on a database where migrations 0007-0010 have run and 0011 (drop) has not.

    python scripts/v4b_verify.py regtrack_rehearsal --migrate            # apply up to 0010, then check
    python scripts/v4b_verify.py regtrack --mark-verified                # check; if all pass, allow 0011

Checks: row counts old vs new (25), row-by-row content fingerprints (11), the rules that apply to a vehicle on a date
(8 cases), the wheel-rim rule history. Exit code 0 only when every check passes. Only reads, except --migrate and
--mark-verified (which writes app_settings 'v4b_switch_verified').
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from regtrack.config import get_settings  # noqa: E402
from regtrack.db import connect  # noqa: E402
from regtrack.migrate import migrate  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("database", help="database name on the configured server, e.g. regtrack or regtrack_rehearsal")
ap.add_argument("--migrate", action="store_true", help="apply migrations up to 0010 first")
ap.add_argument("--mark-verified", action="store_true", help="when every check passes, allow migration 0011")
args = ap.parse_args()
DSN = get_settings().psycopg_dsn.rsplit("/", 1)[0] + "/" + args.database
if args.migrate:
    print("migrate:", migrate(DSN, until=10))

COUNTS = [  # (old query, new query, label)
    ("SELECT count(*)+1 FROM country", "SELECT count(*) FROM regions", "regions = countries + EU"),
    ("SELECT count(*) FROM source", "SELECT count(*) FROM sources", "sources"),
    ("SELECT count(*) FROM vehicle_category", "SELECT count(*) FROM vehicle_categories", "vehicle categories"),
    ("SELECT count(*) FROM country_scope", "SELECT count(*) FROM region_scope", "scope"),
    ("SELECT count(*) FROM vocab_term", "SELECT count(*) FROM region_terms", "words"),
    ("SELECT count(*) FROM local_class", "SELECT count(*) FROM document_classes", "document classes"),
    ("SELECT count(*) FROM app_setting", "SELECT count(*) FROM app_settings", "settings"),
    ("SELECT count(*) FROM crawl_run", "SELECT count(*) FROM ingestion_runs", "ingestion runs"),
    ("SELECT count(*) FROM file_object", "SELECT count(*) FROM documents", "files"),
    ("SELECT count(*) FROM file_sighting", "SELECT count(*) FROM raw_ingestion_records", "listings"),
    ("SELECT count(*) FROM document", "SELECT count(*) FROM regulations", "regulations"),
    (
        "SELECT count(*) FROM document WHERE issuer IS NOT NULL",
        "SELECT count(*) FROM regulation_authorities",
        "authorities linked",
    ),
    (
        "SELECT count(*) FROM (SELECT DISTINCT d.id, x FROM document d, unnest(d.domains) x) t",
        "SELECT count(*) FROM regulation_domains",
        "topic links",
    ),
    (
        "SELECT count(*) FROM (SELECT DISTINCT d.id, x FROM document d, unnest(d.vehicle_categories) x) t",
        "SELECT count(*) FROM regulation_vehicle_categories",
        "vehicle links",
    ),
    ("SELECT count(*) FROM document_file", "SELECT count(*) FROM document_parts", "file parts"),
    ("SELECT count(*) FROM doc_relation", "SELECT count(*) FROM regulation_relations", "relations"),
    ("SELECT count(*) FROM chunk", "SELECT count(*) FROM document_chunks", "chunks"),
    (
        "SELECT count(*) FROM (SELECT country, mandate_key FROM mandate UNION SELECT country, mandate_key FROM compliance_item) t",
        "SELECT count(*) FROM compliance_requirements",
        "rules",
    ),
    ("SELECT count(*) FROM mandate", "SELECT count(*) FROM requirement_versions", "rule versions"),
    ("SELECT count(*) FROM change_event", "SELECT count(*) FROM regulation_changes", "changes"),
    ("SELECT count(*) FROM quality_flag", "SELECT count(*) FROM quality_flags", "warnings"),
    ("SELECT count(*) FROM alert_rule", "SELECT count(*) FROM alert_rules", "alert rules"),
    ("SELECT count(*) FROM report_log", "SELECT count(*) FROM reports", "reports"),
    ("SELECT count(*) FROM requirement", "SELECT count(*) FROM client_requirements", "client requirements"),
    (
        "SELECT count(*) FROM requirement_document",
        "SELECT count(*) FROM client_requirement_regulations",
        "client links",
    ),
]

SAME = [  # row-by-row fingerprints: (old, new, label)
    (
        "SELECT md5(string_agg(concat_ws('|', id, canonical_id, doc_class, status, doc_date, family_key, version_seq, is_current,"
        " in_scope, nature, subject, official_title, doc_type, doc_role, legal_force, data::text, extraction::text), '#' ORDER BY id)) FROM document",
        "SELECT md5(string_agg(concat_ws('|', id, external_code, local_class, legal_status, published_date, family_key, version_seq,"
        " is_current, in_scope, nature, summary, title, doc_type, doc_role, legal_force, data::text, extraction::text), '#' ORDER BY id)) FROM regulations",
        "regulations",
    ),
    (
        "SELECT md5(string_agg(concat_ws('|', id, sha256, storage_path, stage, page_count, text_layer, size_bytes), '#' ORDER BY id)) FROM file_object",
        "SELECT md5(string_agg(concat_ws('|', id, checksum_sha256, storage_path, stage, page_count, text_layer, file_size_bytes), '#' ORDER BY id)) FROM documents",
        "files",
    ),
    (
        "SELECT md5(string_agg(concat_ws('|', id, file_id, source_id, source_item_id, listing_title, listing_date, last_seen_at), '#' ORDER BY id)) FROM file_sighting",
        "SELECT md5(string_agg(concat_ws('|', id, document_id, source_id, external_ref, listing_title, listing_date, last_seen_at), '#' ORDER BY id)) FROM raw_ingestion_records",
        "listings",
    ),
    (
        "SELECT md5(string_agg(concat_ws('|', document_id, file_id, page_from, page_to, is_best_copy), '#' ORDER BY document_id, file_id, page_from)) FROM document_file",
        "SELECT md5(string_agg(concat_ws('|', regulation_id, document_id, page_from, page_to, is_best_copy), '#' ORDER BY regulation_id, document_id, page_from)) FROM document_parts",
        "file parts",
    ),
    (
        "SELECT md5(string_agg(concat_ws('|', id, from_doc, to_doc, to_ref, type, details::text, evidence), '#' ORDER BY id)) FROM doc_relation",
        "SELECT md5(string_agg(concat_ws('|', id, from_regulation_id, to_regulation_id, to_ref, type, details::text, evidence), '#' ORDER BY id)) FROM regulation_relations",
        "relations",
    ),
    (
        "SELECT md5(string_agg(concat_ws('|', id, legal_basis, mandate_key, subject, standard_refs, implementation_date, valid_from, valid_to,"
        " superseded_by, source_doc_id, is_draft, conditions::text), '#' ORDER BY id)) FROM mandate",
        "SELECT md5(string_agg(concat_ws('|', v.id, v.legal_basis, c.requirement_code, v.subject, v.standard_refs, v.implementation_date, v.valid_from,"
        " v.valid_to, v.superseded_by, v.source_regulation_id, v.is_draft, v.conditions::text), '#' ORDER BY v.id)) FROM requirement_versions v"
        " JOIN compliance_requirements c ON c.id = v.requirement_id",
        "rule versions",
    ),
    (
        "SELECT md5(string_agg(concat_ws('|', id, document_id, file_id, chunk_index, md5(content), is_boilerplate), '#' ORDER BY id)) FROM chunk",
        "SELECT md5(string_agg(concat_ws('|', id, regulation_id, document_id, chunk_index, md5(content), is_boilerplate), '#' ORDER BY id)) FROM document_chunks",
        "chunks",
    ),
    (
        "SELECT md5(string_agg(concat_ws('|', id, event_type, document_id, summary, detected_at), '#' ORDER BY id)) FROM change_event",
        "SELECT md5(string_agg(concat_ws('|', id, change_type, regulation_id, summary, detected_at), '#' ORDER BY id)) FROM regulation_changes",
        "changes",
    ),
    (
        "SELECT md5(string_agg(concat_ws('|', id, entity_id, rule, details::text, resolved_at), '#' ORDER BY id)) FROM quality_flag",
        "SELECT md5(string_agg(concat_ws('|', id, entity_id, rule, details::text, resolved_at), '#' ORDER BY id)) FROM quality_flags",
        "warnings",
    ),
    # per regulation: the same vehicle codes, through the link table
    (
        "SELECT md5(string_agg(d.id || ':' || coalesce((SELECT string_agg(DISTINCT x, ',' ORDER BY x) FROM unnest(d.vehicle_categories) x), ''), '#' ORDER BY d.id)) FROM document d",
        "SELECT md5(string_agg(g.id || ':' || coalesce((SELECT string_agg(vc.code, ',' ORDER BY vc.code) FROM regulation_vehicle_categories l"
        " JOIN vehicle_categories vc ON vc.id = l.vehicle_category_id WHERE l.regulation_id = g.id), ''), '#' ORDER BY g.id)) FROM regulations g",
        "vehicle types per regulation",
    ),
    (
        "SELECT md5(string_agg(d.id || ':' || coalesce((SELECT string_agg(DISTINCT upper(x), ',' ORDER BY upper(x)) FROM unnest(d.domains) x), ''), '#' ORDER BY d.id)) FROM document d",
        "SELECT md5(string_agg(g.id || ':' || coalesce((SELECT string_agg(dm.code, ',' ORDER BY dm.code) FROM regulation_domains l"
        " JOIN domains dm ON dm.id = l.domain_id WHERE l.regulation_id = g.id), ''), '#' ORDER BY g.id)) FROM regulations g",
        "topics per regulation",
    ),
]

# "which rules applied to this vehicle on this date" - old tables vs new tables
OLD_ON = """SELECT string_agg(m.id::text, ',' ORDER BY m.id) FROM mandate m
            WHERE NOT m.is_draft AND m.vehicle_categories && ARRAY[%(cat)s, 'ALL']
              AND (m.implementation_date IS NULL OR m.implementation_date <= %(on)s::date)
              AND (m.valid_from IS NULL OR m.valid_from <= %(on)s::date) AND (m.valid_to IS NULL OR m.valid_to > %(on)s::date)"""
NEW_ON = """SELECT string_agg(v.id::text, ',' ORDER BY v.id) FROM requirement_versions v
            WHERE NOT v.is_draft
              AND EXISTS (SELECT 1 FROM vehicle_categories vc JOIN regions r ON r.id = vc.region_id
                          WHERE r.code = 'IN' AND vc.code IN (%(cat)s, 'ALL') AND vc.id = ANY(v.vehicle_category_ids))
              AND (v.implementation_date IS NULL OR v.implementation_date <= %(on)s::date)
              AND (v.valid_from IS NULL OR v.valid_from <= %(on)s::date) AND (v.valid_to IS NULL OR v.valid_to > %(on)s::date)"""
CASES = [
    ("L2", "2023-01-01"),
    ("L2", "2023-07-01"),
    ("L2", "2026-10-18"),
    ("M1", "2022-06-01"),
    ("M1", "2026-10-18"),
    ("N1", "2024-03-01"),
    ("L1", "2025-01-01"),
    ("ALL", "2025-06-01"),
]

ok = True
with connect(dsn=DSN) as c:
    one = lambda q, a=None: list(c.execute(q, a).fetchone().values())[0]  # noqa: E731
    print("\n-- counts")
    for old, new, label in COUNTS:
        o, n = one(old), one(new)
        ok &= o == n
        print(f"{'OK ' if o == n else 'BAD'} {label:28} old {o:>7}  new {n:>7}")
    print("\n-- content, row by row")
    for old, new, label in SAME:
        same = one(old) == one(new)
        ok &= same
        print(f"{'OK ' if same else 'BAD'} {label}")
    print("\n-- rules for a vehicle on a date (old answer = new answer)")
    for cat, on in CASES:
        o, n = one(OLD_ON, {"cat": cat, "on": on}), one(NEW_ON, {"cat": cat, "on": on})
        ok &= o == n
        print(f"{'OK ' if o == n else 'BAD'} {cat:4} {on}: {len((o or '').split(',')) if o else 0} rules")
    hist = c.execute("""SELECT v.id, g.external_code, v.implementation_date, v.valid_from, v.valid_to
                        FROM requirement_versions v JOIN compliance_requirements c ON c.id = v.requirement_id
                        JOIN regulations g ON g.id = v.source_regulation_id
                        WHERE c.requirement_code = 'SO-1365(E)-2004 Table Sr.8(b)' ORDER BY v.id""").fetchall()
    print("\n-- wheel-rim rule history (Sr.8(b))")
    for h in hist:
        print(
            "   ", h["id"], h["external_code"], h["implementation_date"], h["valid_from"], "->", h["valid_to"] or "open"
        )
    print("\n-- extras")
    print(
        "   authorities:",
        [
            tuple(r.values())
            for r in c.execute(
                "SELECT a.code, count(*) FROM regulation_authorities l JOIN regulatory_authorities a ON a.id = l.authority_id GROUP BY 1 ORDER BY 2 DESC"
            )
        ],
    )
    print("   teams:", [r["name"] for r in c.execute("SELECT name FROM teams")])
    print(
        "   rules with a stored legal-basis document:",
        one("SELECT count(*) FROM compliance_requirements WHERE regulation_id IS NOT NULL"),
    )
    print(
        "   last ids (regulations, documents):",
        one("SELECT last_value FROM pg_sequences WHERE sequencename = 'regulations_id_seq'"),
        one("SELECT last_value FROM pg_sequences WHERE sequencename = 'documents_id_seq'"),
    )
    c.rollback()
print()
print("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED")
if ok and args.mark_verified:
    with connect(dsn=DSN) as c:
        c.execute(
            "INSERT INTO app_settings (key, value) VALUES ('v4b_switch_verified', 'true') "
            "ON CONFLICT (key) DO UPDATE SET value = 'true'"
        )
        c.commit()
    print("marked verified: migration 0011 may now drop the old tables (python -m regtrack.cli migrate)")
sys.exit(0 if ok else 1)
