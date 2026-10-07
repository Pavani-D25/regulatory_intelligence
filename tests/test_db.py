"""DB tests (Phase 1/2/7/9 checks). Skipped automatically when PostgreSQL is not reachable."""

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
    assert conn.execute("SELECT count(*) AS n FROM vehicle_category WHERE in_scope").fetchone()["n"] == 5
    assert conn.execute("SELECT count(*) AS n FROM source").fetchone()["n"] == 6
    assert conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()


def _doc(conn, cid, fam=None, current=False, **kw):
    return conn.execute(
        "INSERT INTO document (canonical_id, doc_class, status, family_key, is_current, doc_date, vehicle_categories, in_scope) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (cid, kw.get("doc_class", "AIS_STANDARD"), kw.get("status", "final"), fam, current, kw.get("doc_date"),
         kw.get("cats", []), kw.get("in_scope"))).fetchone()["id"]


def test_one_current_per_family(conn):
    _doc(conn, "AIS-999", "AIS-999", True)
    with pytest.raises(psycopg.errors.UniqueViolation):
        _doc(conn, "AIS-999(Rev.1)", "AIS-999", True)


def test_design_query_scooter(conn):
    so = _doc(conn, "SO-1406(E)-2021", doc_class="NOTIFICATION_ORDER", doc_date=date(2021, 3, 22))
    conn.execute(
        """INSERT INTO mandate (legal_basis, mandate_key, subject, standard_refs, vehicle_categories, conditions,
                                implementation_date, is_draft, source_doc_id, valid_from)
           VALUES ('SO-1365(E)-2004 Table Sr.43(b)', 'SO-1365(E)-2004 Table Sr.43(b)', 'Light alloy wheel rims',
                   ARRAY['IS 16192(Part 1):2014'], ARRAY['L1','L2','L5'], %s, DATE '2023-12-22', false, %s, DATE '2021-03-22'),
                  ('x', 'x', 'big engines only', ARRAY['AIS-999'], ARRAY['L2'], %s, DATE '2020-01-01', false, %s, DATE '2020-01-01')""",
        (Jsonb({}), so, Jsonb({"engine_cc": {"lte": 50}}), so))
    rows = conn.execute(
        """SELECT legal_basis, subject, standard_refs, implementation_date FROM mandate
           WHERE NOT is_draft AND vehicle_categories && ARRAY['L2','ALL']
             AND (conditions->'engine_cc'->>'lte' IS NULL OR (conditions->'engine_cc'->>'lte')::int >= 110)
             AND implementation_date <= DATE '2026-01-01'
             AND valid_from <= DATE '2026-01-01' AND (valid_to IS NULL OR valid_to > DATE '2026-01-01')""").fetchall()
    assert [r["legal_basis"] for r in rows] == ["SO-1365(E)-2004 Table Sr.43(b)"]


def test_category_and_version_views(conn):
    _doc(conn, "AIS-998", "AIS-998", False, cats=["L2"], in_scope=True)
    _doc(conn, "AIS-998(Rev.1)", "AIS-998", True, cats=["L2"], in_scope=True)
    n = conn.execute("SELECT count(*) AS n FROM document WHERE vehicle_categories && ARRAY['L2','ALL'] AND in_scope").fetchone()["n"]
    assert n == 2
    cur = conn.execute("SELECT canonical_id FROM document WHERE family_key='AIS-998' AND is_current").fetchone()
    assert cur["canonical_id"] == "AIS-998(Rev.1)"


def test_mandate_versioning_wheel_rim_chain(conn):
    """Replaying S.O. 1406 -> 359 -> 3896 -> 3800 gives 4 versions of Sr.8(d) with one open row."""
    from pathlib import Path

    from regtrack.pipeline import mandates as M
    from regtrack.pipeline.extract import operative_text
    from regtrack.pipeline.text import english_text, extract

    fx = Path(__file__).parent / "fixtures"
    chain = [("so_1406_2021_wheel_rim.pdf", "SO-1406(E)-2021", date(2021, 3, 22)),
             ("so_359_2022_wheel_rim_extension.pdf", "SO-359(E)-2022", date(2022, 1, 27)),
             ("so_3896_2022_wheel_rim_extension.pdf", "SO-3896(E)-2022", date(2022, 8, 12))]
    for name, cid, d in chain:
        did = _doc(conn, cid, doc_class="NOTIFICATION_ORDER", doc_date=d)
        doc = conn.execute("SELECT * FROM document WHERE id=%s", (did,)).fetchone()
        M.mandates_for_document(conn, doc, operative_text(english_text(extract(fx / name, "pdf").pages)))
    rows = conn.execute("SELECT implementation_date, valid_to FROM mandate WHERE mandate_key='SO-1365(E)-2004 Table Sr.8(d)' "
                        "ORDER BY id").fetchall()
    assert [r["implementation_date"] for r in rows] == [date(2021, 9, 21), date(2022, 9, 21), date(2023, 6, 22)]
    assert sum(1 for r in rows if r["valid_to"] is None) == 1
    # re-running a document adds nothing
    doc = conn.execute("SELECT * FROM document WHERE canonical_id='SO-3896(E)-2022'").fetchone()
    before = conn.execute("SELECT count(*) AS n FROM mandate").fetchone()["n"]
    M.mandates_for_document(conn, doc, operative_text(english_text(extract(fx / chain[2][0], "pdf").pages)))
    assert conn.execute("SELECT count(*) AS n FROM mandate").fetchone()["n"] == before
