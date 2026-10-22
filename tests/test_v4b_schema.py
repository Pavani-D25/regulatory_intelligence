"""The v4B tables (docs/SCHEMA_V4B.md; migration 0007, old tables dropped by 0011) exist and enforce their rules.
Runs on regtrack_test; every test rolls back. The data copy itself is checked on a copy of the live database."""

from __future__ import annotations

import psycopg
import pytest

pytestmark = pytest.mark.db

V4B_TABLES = {
    "regions", "regulatory_authorities", "sources", "domains", "systems", "vehicle_categories", "region_scope",
    "region_terms", "document_classes", "teams", "users", "app_settings",
    "ingestion_runs", "raw_ingestion_records", "documents",
    "regulations", "regulation_authorities", "regulation_domains", "regulation_systems",
    "regulation_vehicle_categories", "document_parts", "regulation_relations",
    "document_chunks",
    "compliance_requirements", "requirement_versions", "impact_assessments",
    "regulation_changes", "quality_flags", "alert_rules", "alert_events", "regulation_watches",
    "report_templates", "reports", "report_schedules",
    "assistant_conversations", "assistant_messages", "assistant_message_citations",
    "client_requirements", "client_requirement_regulations",
}


def _id(conn, sql, args=()):
    return conn.execute(sql, args).fetchone()["id"]


@pytest.fixture()
def base(conn):
    """One region, class, regulation and file to hang test rows on."""
    region = _id(conn, "SELECT id FROM regions WHERE code='IN'")
    reg = _id(conn, "INSERT INTO regulations (region_id, external_code, local_class, legal_status) "
                    "VALUES (%s, 'GSR-9001(E)-2026', 'NOTIFICATION_FINAL', 'final') RETURNING id", (region,))
    doc = _id(conn, "INSERT INTO documents (region_id, checksum_sha256, storage_path) VALUES (%s, %s, 'x') RETURNING id",
              (region, "a" * 64))
    return {"region": region, "reg": reg, "doc": doc}


def test_v4b_tables_exist_and_old_ones_are_gone(conn, migrated):
    assert "applied migration/0007_v4b_schema.sql" in migrated[1]
    assert "applied migration/0011_drop_old_tables.sql" in migrated[1]
    have = {r["table_name"] for r in conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public'")}
    assert V4B_TABLES <= have
    assert not ({"document", "file_object", "mandate", "chunk", "source", "quality_flag", "country"} & have)
    assert have - V4B_TABLES == {"schema_migrations"}                         # nothing else left behind


def test_old_tables_drop_needs_verification(conn):
    """0011 refuses to drop old tables that hold data unless the switch-over was verified."""
    sql = open(__import__("pathlib").Path(__file__).parent.parent / "db" / "migrations" / "0011_drop_old_tables.sql",
               encoding="utf-8").read()
    guard = sql[sql.index("DO $$"):sql.index("END $$;") + len("END $$;")]
    conn.execute("CREATE TEMP TABLE document (id int)")      # stands in for the old table, with one row
    conn.execute("INSERT INTO document VALUES (1)")
    with pytest.raises(psycopg.errors.RaiseException):
        conn.execute(guard)
    conn.rollback()
    conn.execute("CREATE TEMP TABLE document (id int)")
    conn.execute("INSERT INTO document VALUES (1)")
    conn.execute("INSERT INTO app_settings VALUES ('v4b_switch_verified', 'true') ON CONFLICT (key) DO UPDATE SET value='true'")
    conn.execute(guard)                                       # verified: passes


def test_reference_rows(conn):
    regions = {r["code"] for r in conn.execute("SELECT code FROM regions")}
    assert regions == {"IN", "TH", "MY", "UN", "EU"}
    assert conn.execute("SELECT count(*) AS n FROM sources").fetchone()["n"] == 23  # + 7 Malaysian (0017, 0019), + TH_LOCAL, MY_LOCAL (0020)
    assert conn.execute("SELECT name FROM teams WHERE code='REG_AFFAIRS'").fetchone()["name"] == "Regulatory Affairs Team"
    l2 = conn.execute("""SELECT un_codes FROM vehicle_categories vc JOIN regions r ON r.id = vc.region_id
                         WHERE r.code='IN' AND vc.code='L2'""").fetchone()
    assert l2["un_codes"] == ["L3"]
    scope = {r["code"] for r in conn.execute("""SELECT vc.code FROM region_scope s JOIN vehicle_categories vc
                                                ON vc.id = s.vehicle_category_id JOIN regions r ON r.id = vc.region_id
                                                WHERE r.code='IN'""")}
    assert scope == {"L1", "L2", "M1", "N1", "ALL"}
    th_scope = {r["code"] for r in conn.execute("""SELECT vc.code FROM region_scope s JOIN vehicle_categories vc
                                                   ON vc.id = s.vehicle_category_id JOIN regions r ON r.id = vc.region_id
                                                   WHERE r.code='TH'""")}
    assert th_scope == {"L1", "L3", "M1", "N1", "ALL"}  # ALL since 0021, like India
    assert conn.execute("SELECT count(*) AS n FROM domains WHERE code='NUMBER_PLATES'").fetchone()["n"] == 1
    assert conn.execute("SELECT count(*) AS n FROM report_templates").fetchone()["n"] == 3


def test_regulation_rules(conn, base):
    with pytest.raises(psycopg.errors.UniqueViolation):     # one code per region
        conn.execute("INSERT INTO regulations (region_id, external_code, local_class, legal_status) "
                     "VALUES (%s, 'GSR-9001(E)-2026', 'NOTIFICATION_FINAL', 'final')", (base["region"],))


def test_unknown_local_class_is_refused(conn, base):
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute("INSERT INTO regulations (region_id, external_code, local_class, legal_status) "
                     "VALUES (%s, 'X-1', 'NO_SUCH_CLASS', 'final')", (base["region"],))


def test_file_stored_once(conn, base):
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute("INSERT INTO documents (region_id, checksum_sha256, storage_path) VALUES (%s, %s, 'y')",
                     (base["region"], "a" * 64))


def test_one_primary_authority(conn, base):
    a1, a2 = [r["id"] for r in conn.execute("SELECT id FROM regulatory_authorities ORDER BY id LIMIT 2")]
    conn.execute("INSERT INTO regulation_authorities VALUES (%s, %s, 'primary')", (base["reg"], a1))
    conn.execute("INSERT INTO regulation_authorities VALUES (%s, %s, 'co_issuer')", (base["reg"], a2))
    conn.execute("SAVEPOINT s")
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute("UPDATE regulation_authorities SET role='primary' WHERE authority_id=%s", (a2,))
    conn.execute("ROLLBACK TO SAVEPOINT s")


def test_citation_and_watch_checks(conn, base):
    conv = _id(conn, "INSERT INTO assistant_conversations DEFAULT VALUES RETURNING id")
    msg = _id(conn, "INSERT INTO assistant_messages (conversation_id, role, content) VALUES (%s, 'assistant', 'x') "
                    "RETURNING id", (conv,))
    conn.execute("SAVEPOINT s")
    with pytest.raises(psycopg.errors.CheckViolation):      # a citation must point at something
        conn.execute("INSERT INTO assistant_message_citations (message_id) VALUES (%s)", (msg,))
    conn.execute("ROLLBACK TO SAVEPOINT s")
    team = _id(conn, "SELECT id FROM teams WHERE code='REG_AFFAIRS'")
    conn.execute("INSERT INTO regulation_watches (regulation_id, watcher_team_id) VALUES (%s, %s)", (base["reg"], team))
    conn.execute("SAVEPOINT t")
    with pytest.raises(psycopg.errors.CheckViolation):      # exactly one watcher: user or team
        conn.execute("INSERT INTO regulation_watches (regulation_id) VALUES (%s)", (base["reg"],))
    conn.execute("ROLLBACK TO SAVEPOINT t")


def test_requirement_versions_keep_history(conn, base):
    req = _id(conn, "INSERT INTO compliance_requirements (region_id, requirement_code) VALUES (%s, 'K Sr.1') RETURNING id",
              (base["region"],))
    v1 = _id(conn, """INSERT INTO requirement_versions (requirement_id, source_regulation_id, legal_basis, is_draft,
                      implementation_date, valid_from) VALUES (%s, %s, 'K Sr.1', false, DATE '2022-09-21', DATE '2022-01-27')
                      RETURNING id""", (req, base["reg"]))
    v2 = _id(conn, """INSERT INTO requirement_versions (requirement_id, source_regulation_id, legal_basis, is_draft,
                      implementation_date, valid_from) VALUES (%s, %s, 'K Sr.1', false, DATE '2023-06-22', DATE '2022-08-12')
                      RETURNING id""", (req, base["reg"]))
    conn.execute("UPDATE requirement_versions SET valid_to = DATE '2022-08-12', superseded_by = %s WHERE id = %s", (v2, v1))
    on = conn.execute("""SELECT implementation_date FROM requirement_versions WHERE requirement_id = %s
                         AND valid_from <= DATE '2022-05-01' AND (valid_to IS NULL OR valid_to > DATE '2022-05-01')""",
                      (req,)).fetchone()
    assert str(on["implementation_date"]) == "2022-09-21"
    conn.execute("SAVEPOINT s")
    with pytest.raises(psycopg.errors.CheckViolation):      # a version cannot end before it starts
        conn.execute("UPDATE requirement_versions SET valid_to = DATE '2020-01-01' WHERE id = %s", (v2,))
    conn.execute("ROLLBACK TO SAVEPOINT s")
