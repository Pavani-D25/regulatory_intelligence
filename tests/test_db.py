"""DB tests (Phase 1/2/7/9 checks) on the v4B tables. Skipped automatically when PostgreSQL is not reachable."""

from __future__ import annotations

from datetime import date

import psycopg
import pytest

from regtrack.db import Jsonb

pytestmark = pytest.mark.db


def test_migrations_apply_twice(migrated):
    _, first, second = migrated
    assert any(x.startswith("applied migration/0001_init.sql") for x in first)
    assert any(x.startswith("applied seed/0001_vocab.sql") for x in first)
    assert second == ["up to date"]


def test_seed_vocab(conn):
    scope = conn.execute("""SELECT count(*) AS n FROM region_scope s JOIN regions r ON r.id=s.region_id
                            WHERE r.code='IN'""").fetchone()["n"]
    assert scope == 5
    by_country = {r["code"]: r["n"] for r in conn.execute(
        "SELECT r.code, count(*) AS n FROM sources s JOIN regions r ON r.id=s.region_id GROUP BY 1")}
    assert by_country == {"IN": 6, "TH": 8, "MY": 5}  # 0001 seed + 0005 Thai + 0017 Malaysian sources
    assert conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()


def _region(conn, cc="IN"):
    return conn.execute("SELECT id FROM regions WHERE code=%s", (cc,)).fetchone()["id"]


def _doc(conn, cid, fam=None, current=False, **kw):
    """A regulation (v4B) with its vehicle categories as link rows."""
    rid = conn.execute(
        "INSERT INTO regulations (region_id, external_code, local_class, legal_status, family_key, is_current, "
        "published_date, in_scope) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (_region(conn), cid, kw.get("doc_class", "AIS_STANDARD"), kw.get("status", "final"), fam, current,
         kw.get("doc_date"), kw.get("in_scope"))).fetchone()["id"]
    conn.execute("INSERT INTO regulation_vehicle_categories SELECT %s, id FROM vehicle_categories "
                 "WHERE region_id=%s AND code = ANY(%s)", (rid, _region(conn), kw.get("cats", [])))
    return rid


def _cat_ids(conn, codes):
    return [r["id"] for r in conn.execute("SELECT id FROM vehicle_categories WHERE region_id=%s AND code = ANY(%s) "
                                          "ORDER BY id", (_region(conn), codes))]


def test_one_current_per_family(conn):
    _doc(conn, "AIS-999", "AIS-999", True)
    with pytest.raises(psycopg.errors.UniqueViolation):
        _doc(conn, "AIS-999(Rev.1)", "AIS-999", True)


def test_design_query_scooter(conn):
    so = _doc(conn, "SO-1406(E)-2021", doc_class="NOTIFICATION_ORDER", doc_date=date(2021, 3, 22))
    for key, subject, refs, cats, cond, impl, valid in (
            ("SO-1365(E)-2004 Table Sr.43(b)", "Light alloy wheel rims", ["IS 16192(Part 1):2014"], ["L1", "L2", "L5"],
             {}, date(2023, 12, 22), date(2021, 3, 22)),
            ("x", "big engines only", ["AIS-999"], ["L2"], {"engine_cc": {"lte": 50}}, date(2020, 1, 1), date(2020, 1, 1))):
        req = conn.execute("INSERT INTO compliance_requirements (region_id, requirement_code) VALUES (%s,%s) RETURNING id",
                           (_region(conn), key)).fetchone()["id"]
        conn.execute("""INSERT INTO requirement_versions (requirement_id, source_regulation_id, legal_basis, subject,
                            standard_refs, vehicle_category_ids, conditions, implementation_date, is_draft, valid_from)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,false,%s)""",
                     (req, so, key, subject, refs, _cat_ids(conn, cats), Jsonb(cond), impl, valid))
    rows = conn.execute(
        """SELECT v.legal_basis, v.subject, v.standard_refs, v.implementation_date FROM requirement_versions v
           WHERE NOT v.is_draft AND v.vehicle_category_ids && %s::int[]
             AND (v.conditions->'engine_cc'->>'lte' IS NULL OR (v.conditions->'engine_cc'->>'lte')::int >= 110)
             AND v.implementation_date <= DATE '2026-01-01'
             AND v.valid_from <= DATE '2026-01-01' AND (v.valid_to IS NULL OR v.valid_to > DATE '2026-01-01')""",
        (_cat_ids(conn, ["L2", "ALL"]),)).fetchall()
    assert [r["legal_basis"] for r in rows] == ["SO-1365(E)-2004 Table Sr.43(b)"]


def test_category_and_version_views(conn):
    _doc(conn, "AIS-998", "AIS-998", False, cats=["L2"], in_scope=True)
    _doc(conn, "AIS-998(Rev.1)", "AIS-998", True, cats=["L2"], in_scope=True)
    n = conn.execute("""SELECT count(DISTINCT g.id) AS n FROM regulations g JOIN regulation_vehicle_categories l
                        ON l.regulation_id=g.id WHERE l.vehicle_category_id = ANY(%s) AND g.in_scope""",
                     (_cat_ids(conn, ["L2", "ALL"]),)).fetchone()["n"]
    assert n == 2
    cur = conn.execute("SELECT external_code FROM regulations WHERE family_key='AIS-998' AND is_current").fetchone()
    assert cur["external_code"] == "AIS-998(Rev.1)"


def test_mandate_versioning_wheel_rim_chain(conn):
    """Replaying S.O. 1406 -> 359 -> 3896 gives 3 versions of Sr.8(d) with one open row (v4B: one
    compliance_requirements row, its versions in requirement_versions)."""
    from pathlib import Path

    from regtrack.pipeline import mandates as M
    from regtrack.pipeline import repo
    from regtrack.pipeline.extract import operative_text
    from regtrack.pipeline.text import english_text, extract

    fx = Path(__file__).parent / "fixtures"
    chain = [("so_1406_2021_wheel_rim.pdf", "SO-1406(E)-2021", date(2021, 3, 22)),
             ("so_359_2022_wheel_rim_extension.pdf", "SO-359(E)-2022", date(2022, 1, 27)),
             ("so_3896_2022_wheel_rim_extension.pdf", "SO-3896(E)-2022", date(2022, 8, 12))]
    for name, cid, d in chain:
        did = repo.insert_document(conn, cid, {"doc_class": "NOTIFICATION_ORDER", "status": "final", "doc_date": d})
        doc = repo.get_document(conn, did)
        M.mandates_for_document(conn, doc, operative_text(english_text(extract(fx / name, "pdf").pages)))
    rows = conn.execute("SELECT v.implementation_date, v.valid_to, v.vehicle_category_ids FROM requirement_versions v "
                        "JOIN compliance_requirements c ON c.id=v.requirement_id "
                        "WHERE c.requirement_code='SO-1365(E)-2004 Table Sr.8(d)' ORDER BY v.id").fetchall()
    assert [r["implementation_date"] for r in rows] == [date(2021, 9, 21), date(2022, 9, 21), date(2023, 6, 22)]
    assert sum(1 for r in rows if r["valid_to"] is None) == 1
    assert all(r["vehicle_category_ids"] for r in rows)  # category codes stored as the region's category ids
    assert conn.execute("SELECT count(*) AS n FROM compliance_requirements "
                        "WHERE requirement_code='SO-1365(E)-2004 Table Sr.8(d)'").fetchone()["n"] == 1
    # re-running a document adds nothing
    doc = repo.find_document(conn, "SO-3896(E)-2022")
    before = conn.execute("SELECT count(*) AS n FROM requirement_versions").fetchone()["n"]
    M.mandates_for_document(conn, doc, operative_text(english_text(extract(fx / chain[2][0], "pdf").pages)))
    assert conn.execute("SELECT count(*) AS n FROM requirement_versions").fetchone()["n"] == before
