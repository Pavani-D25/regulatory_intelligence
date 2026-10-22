"""The country-neutral schema (docs/MULTI_COUNTRY_SCHEMA.md), as carried into v4B: every local class has a
universal meaning, categories map to UNECE, regulations get their derived fields from one SQL definition
(refresh_regulation_fields, migrations 0008/0010), and ids are unique per country. Runs on regtrack_test; every test
rolls back."""

from __future__ import annotations

from datetime import date

import psycopg
import pytest

from regtrack.models.enums import MALAYSIA_CLASSES, THAI_CLASSES, DocClass, DocRole, DocType, LegalForce

pytestmark = pytest.mark.db


def _region(conn, cc: str) -> int:
    return conn.execute("SELECT id FROM regions WHERE code=%s", (cc,)).fetchone()["id"]


def _reg(conn, cid, doc_class, cc="IN", status="final", series=None, family=None):
    return conn.execute(
        "INSERT INTO regulations (region_id, external_code, local_class, legal_status, series, family_key, published_date) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (_region(conn, cc), cid, doc_class, status, series, family, date(2022, 8, 12))).fetchone()["id"]


def _fields(conn, rid):
    return conn.execute("SELECT doc_type, doc_role, legal_force, local_type, language FROM regulations WHERE id=%s",
                        (rid,)).fetchone()


def _requirement(conn, cc, code, source, standards=(), draft=False):
    req = conn.execute("INSERT INTO compliance_requirements (region_id, requirement_code) VALUES (%s,%s) RETURNING id",
                       (_region(conn, cc), code)).fetchone()["id"]
    conn.execute("INSERT INTO requirement_versions (requirement_id, source_regulation_id, legal_basis, standard_refs, "
                 "is_draft, valid_from) VALUES (%s,%s,'x',%s,%s,DATE '2022-08-12')", (req, source, list(standards), draft))


def test_seed_runs_before_later_migrations(migrated):
    first = migrated[1]
    assert first.index("applied seed/0001_vocab.sql") < first.index("applied migration/0002_portal_workflow.sql")
    assert "applied migration/0011_drop_old_tables.sql" in first


def test_every_doc_class_has_a_meaning(conn):
    rows = {(r["cc"], r["code"]): r for r in conn.execute(
        "SELECT r.code AS cc, c.* FROM document_classes c JOIN regions r ON r.id=c.region_id")}
    for dc in DocClass:
        cc = "TH" if dc in THAI_CLASSES else "MY" if dc in MALAYSIA_CLASSES else "IN"
        assert (cc, dc.value) in rows, f"document_classes has no row for {cc} {dc.value}"
    assert {r["doc_type"] for r in rows.values()} <= {t.value for t in DocType}
    assert {r["doc_role"] for r in rows.values() if r["doc_role"]} <= {t.value for t in DocRole}


def test_vehicle_categories_map_to_unece(conn):
    un = {r["code"]: r["un_codes"] for r in conn.execute(
        "SELECT code, un_codes FROM vehicle_categories WHERE region_id=%s", (_region(conn, "IN"),))}
    assert un["L2"] == ["L3"] and un["M1"] == ["M1"]          # India L2 = motorcycle = UNECE L3
    scope = {r["code"] for r in conn.execute("""SELECT vc.code FROM region_scope s JOIN vehicle_categories vc
                                                ON vc.id=s.vehicle_category_id WHERE s.region_id=%s""",
                                             (_region(conn, "IN"),))}
    assert scope == {"L1", "L2", "M1", "N1", "ALL"}


def test_hsrp_renamed_to_number_plates(conn):
    codes = {r["code"] for r in conn.execute("SELECT code FROM domains")}
    assert "NUMBER_PLATES" in codes and "HSRP" not in codes
    assert conn.execute("SELECT count(*) AS n FROM region_terms WHERE kind='domain' AND code='NUMBER_PLATES' "
                        "AND term='HSRP'").fetchone()["n"] == 1


def test_refresh_regulation_fields(conn):
    ext = _reg(conn, "SO-9001(E)-2022", "NOTIFICATION_EXTENSION", series="S.O.")
    fin = _reg(conn, "GSR-9002(E)-2022", "NOTIFICATION_FINAL", series="G.S.R.")
    amd = _reg(conn, "GSR-9003(E)-2022", "NOTIFICATION_FINAL", series="G.S.R.")
    conn.execute("INSERT INTO regulation_relations (from_regulation_id, to_regulation_id, type, method) "
                 "VALUES (%s,%s,'amends','regex')", (amd, fin))
    said = _reg(conn, "GSR-9005(E)-2022", "NOTIFICATION_FINAL", series="G.S.R.")   # amended regulation not stored
    conn.execute("""UPDATE regulations SET data = '{"amends_notification": ["GSR-590(E)-1989"]}' WHERE id=%s""", (said,))
    drf = _reg(conn, "GSR-9004(E)-2022", "NOTIFICATION_DRAFT", status="draft", series="G.S.R.")
    ais = _reg(conn, "AIS-999", "AIS_STANDARD", family="AIS-999")
    off = _reg(conn, "DOC-x", "OFF_TOPIC")
    assert conn.execute("SELECT refresh_regulation_fields('IN') AS n").fetchone()["n"] > 0

    assert tuple(_fields(conn, ext).values()) == ("REGULATION", "EXTENSION", "MANDATORY", "S.O.", "en")
    assert _fields(conn, fin)["doc_role"] == DocRole.BASE
    assert _fields(conn, amd)["doc_role"] == DocRole.AMENDMENT          # decided from its 'amends' relation
    assert _fields(conn, said)["doc_role"] == DocRole.AMENDMENT         # decided from what extraction read
    assert _fields(conn, drf)["legal_force"] == LegalForce.INFORMATIVE   # drafts bind no one
    assert _fields(conn, ais)["legal_force"] == LegalForce.VOLUNTARY
    assert _fields(conn, off)["doc_type"] == DocType.OFF_TOPIC and _fields(conn, off)["doc_role"] is None

    # a standard becomes mandatory while an open rule version cites it
    _requirement(conn, "IN", "TEST Sr.1", fin, standards=["AIS-999"])
    conn.execute("SELECT refresh_regulation_fields('IN')")
    assert _fields(conn, ais)["legal_force"] == LegalForce.MANDATORY

    # nothing changed upstream: a second run writes nothing (CLAUDE.md rule 7)
    assert conn.execute("SELECT refresh_regulation_fields('IN') AS n").fetchone()["n"] == 0


def test_thai_rows_get_their_own_country(conn):
    th = _reg(conn, "TIS-2560-2565", "TIS_STANDARD", cc="TH")
    _requirement(conn, "TH", "TH-1", th)
    conn.execute("SELECT refresh_regulation_fields('TH')")
    assert _fields(conn, th)["doc_type"] == DocType.TECHNICAL_STANDARD and _fields(conn, th)["language"] == "th"
    assert conn.execute("SELECT refresh_regulation_fields('IN') AS n").fetchone()["n"] == 0  # India untouched
    assert conn.execute("""SELECT r.code FROM compliance_requirements c JOIN regions r ON r.id=c.region_id
                           WHERE c.requirement_code='TH-1'""").fetchone()["code"] == "TH"


def test_ids_unique_per_country(conn):
    _reg(conn, "SAME-1", "OTHER", cc="IN")
    _reg(conn, "SAME-1", "OTHER", cc="TH")                    # same id in another country is allowed
    with pytest.raises(psycopg.errors.UniqueViolation):
        _reg(conn, "SAME-1", "OTHER", cc="IN")


def test_compliance_keyed_by_country(conn):
    for cc in ("IN", "TH"):
        conn.execute("INSERT INTO compliance_requirements (region_id, requirement_code) VALUES (%s,'K')", (_region(conn, cc),))
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute("INSERT INTO compliance_requirements (region_id, requirement_code) VALUES (%s,'K')",
                     (_region(conn, "IN"),))


def test_tis_family_orders_editions_by_year(conn):
    from regtrack.pipeline.link import recompute_family

    th = _region(conn, "TH")
    ids = {}
    for cid, year in (("TIS-9999-2568", 2025), ("TIS-9999-2551", 2008)):  # the newer edition arrives first
        ids[cid] = conn.execute(
            "INSERT INTO regulations (region_id, external_code, local_class, legal_status, family_key, year) "
            "VALUES (%s,%s,'TIS_STANDARD','final','TIS-9999',%s) RETURNING id", (th, cid, year)).fetchone()["id"]
    import os
    os.environ["REGTRACK_COUNTRY"] = "TH"
    from regtrack.config import get_settings
    get_settings.cache_clear()
    try:
        recompute_family(conn, "TIS-9999")
    finally:
        os.environ.pop("REGTRACK_COUNTRY")
        get_settings.cache_clear()
    rows = {r["external_code"]: r for r in conn.execute(
        "SELECT external_code, is_current, legal_status, version_seq FROM regulations WHERE family_key='TIS-9999'")}
    assert rows["TIS-9999-2568"]["is_current"] and rows["TIS-9999-2568"]["legal_status"] == "final"
    assert not rows["TIS-9999-2551"]["is_current"] and rows["TIS-9999-2551"]["legal_status"] == "superseded"
    assert (rows["TIS-9999-2551"]["version_seq"], rows["TIS-9999-2568"]["version_seq"]) == (1, 2)
