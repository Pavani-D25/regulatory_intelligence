"""Migration 0006: the country-neutral schema (docs/MULTI_COUNTRY_SCHEMA.md). Runs on regtrack_test; every test
rolls back."""

from __future__ import annotations

from datetime import date

import psycopg
import pytest

from regtrack.models.enums import THAI_CLASSES, DocClass, DocRole, DocType, LegalForce

pytestmark = pytest.mark.db


def _doc(conn, cid, doc_class, cc="IN", status="final", series=None, cats=(), family=None):
    return conn.execute(
        "INSERT INTO document (canonical_id, doc_class, status, series, vehicle_categories, family_key, country, doc_date) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (cid, doc_class, status, series, list(cats), family, cc, date(2022, 8, 12))).fetchone()["id"]


def _fields(conn, did):
    return conn.execute("SELECT doc_type, doc_role, legal_force, local_type, language, vehicle_categories_un "
                        "FROM document WHERE id=%s", (did,)).fetchone()


def test_seed_runs_before_later_migrations(migrated):
    first = migrated[1]
    assert first.index("applied seed/0001_vocab.sql") < first.index("applied migration/0002_portal_workflow.sql")
    assert "applied migration/0006_universal_schema.sql" in first


def test_every_doc_class_has_a_meaning(conn):
    rows = {(r["country"], r["code"]): r for r in conn.execute("SELECT * FROM local_class")}
    for dc in DocClass:
        cc = "TH" if dc in THAI_CLASSES else "IN"
        assert (cc, dc.value) in rows, f"local_class has no row for {cc} {dc.value}"
    assert {r["doc_type"] for r in rows.values()} <= {t.value for t in DocType}
    assert {r["doc_role"] for r in rows.values() if r["doc_role"]} <= {t.value for t in DocRole}


def test_vehicle_categories_map_to_unece(conn):
    un = lambda cc, codes: conn.execute("SELECT un_vehicle_categories(%s, %s) AS u", (cc, codes)).fetchone()["u"]  # noqa: E731
    assert un("IN", ["L2", "M1", "E_RICKSHAW", "CEV"]) == ["L3", "L5", "M1"]   # India L2 = motorcycle = UNECE L3
    assert un("TH", ["L2", "M1"]) == ["L2", "M1"]                               # no Thai rows: UNECE meaning
    assert un("IN", []) == []
    scope = {r["vehicle_category"] for r in conn.execute("SELECT vehicle_category FROM country_scope WHERE country='IN'")}
    assert scope == {"L1", "L2", "M1", "N1", "ALL"}


def test_hsrp_renamed_to_number_plates(conn):
    codes = {r["code"] for r in conn.execute("SELECT code FROM domain")}
    assert "number_plates" in codes and "hsrp" not in codes
    assert conn.execute("SELECT count(*) AS n FROM vocab_term WHERE kind='domain' AND code='number_plates' "
                        "AND term='HSRP'").fetchone()["n"] == 1


def test_refresh_universal_fields(conn):
    ext = _doc(conn, "SO-9001(E)-2022", "NOTIFICATION_EXTENSION", series="S.O.", cats=["L2", "M1"])
    fin = _doc(conn, "GSR-9002(E)-2022", "NOTIFICATION_FINAL", series="G.S.R.")
    amd = _doc(conn, "GSR-9003(E)-2022", "NOTIFICATION_FINAL", series="G.S.R.")
    conn.execute("INSERT INTO doc_relation (from_doc, to_doc, type, method) VALUES (%s,%s,'amends','regex')", (amd, fin))
    said = _doc(conn, "GSR-9005(E)-2022", "NOTIFICATION_FINAL", series="G.S.R.")   # amended document not in the DB
    conn.execute("""UPDATE document SET data = '{"amends_notification": ["GSR-590(E)-1989"]}' WHERE id=%s""", (said,))
    drf = _doc(conn, "GSR-9004(E)-2022", "NOTIFICATION_DRAFT", status="draft", series="G.S.R.")
    ais = _doc(conn, "AIS-999", "AIS_STANDARD", family="AIS-999")
    off = _doc(conn, "DOC-x", "OFF_TOPIC")
    assert conn.execute("SELECT refresh_universal_fields('IN') AS n").fetchone()["n"] > 0

    assert tuple(_fields(conn, ext).values()) == ("REGULATION", "EXTENSION", "MANDATORY", "S.O.", "en", ["L3", "M1"])
    assert _fields(conn, fin)["doc_role"] == DocRole.BASE
    assert _fields(conn, amd)["doc_role"] == DocRole.AMENDMENT          # decided from its 'amends' relation
    assert _fields(conn, said)["doc_role"] == DocRole.AMENDMENT         # decided from what extraction read
    assert _fields(conn, drf)["legal_force"] == LegalForce.INFORMATIVE   # drafts bind no one
    assert _fields(conn, ais)["legal_force"] == LegalForce.VOLUNTARY
    assert _fields(conn, off)["doc_type"] == DocType.OFF_TOPIC and _fields(conn, off)["doc_role"] is None

    # a standard becomes mandatory while an open mandate cites it
    conn.execute("""INSERT INTO mandate (legal_basis, mandate_key, standard_refs, vehicle_categories, is_draft,
                                         source_doc_id, valid_from)
                    VALUES ('x', 'TEST Sr.1', ARRAY['AIS-999'], ARRAY['L2'], false, %s, DATE '2022-08-12')""", (fin,))
    conn.execute("SELECT refresh_universal_fields('IN')")
    assert _fields(conn, ais)["legal_force"] == LegalForce.MANDATORY
    m = conn.execute("SELECT country, vehicle_categories_un FROM mandate WHERE mandate_key='TEST Sr.1'").fetchone()
    assert m["country"] == "IN" and m["vehicle_categories_un"] == ["L3"]

    # nothing changed upstream: a second run writes nothing (CLAUDE.md rule 7)
    assert conn.execute("SELECT refresh_universal_fields('IN') AS n").fetchone()["n"] == 0


def test_thai_rows_get_their_own_country(conn):
    th = _doc(conn, "TIS-2560-2565", "TIS_STANDARD", cc="TH")
    conn.execute("""INSERT INTO mandate (legal_basis, mandate_key, is_draft, source_doc_id) VALUES ('x', 'TH-1', false, %s)""",
                 (th,))
    conn.execute("SELECT refresh_universal_fields('TH')")
    assert _fields(conn, th)["doc_type"] == DocType.TECHNICAL_STANDARD and _fields(conn, th)["language"] == "th"
    assert conn.execute("SELECT country FROM mandate WHERE mandate_key='TH-1'").fetchone()["country"] == "TH"


def test_ids_unique_per_country(conn):
    _doc(conn, "SAME-1", "OTHER", cc="IN")
    _doc(conn, "SAME-1", "OTHER", cc="TH")                    # same id in another country is allowed
    with pytest.raises(psycopg.errors.UniqueViolation):
        _doc(conn, "SAME-1", "OTHER", cc="IN")


def test_compliance_keyed_by_country(conn):
    conn.execute("INSERT INTO compliance_item (country, mandate_key, status) VALUES ('IN','K','Open'), ('TH','K','Open')")
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute("INSERT INTO compliance_item (country, mandate_key, status) VALUES ('IN','K','Open')")
