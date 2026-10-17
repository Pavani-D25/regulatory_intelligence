"""Phase 3 of the v4B move: text, classify and extract read and write the v4B tables (documents, regulations,
document_parts, raw_ingestion_records, quality_flags and the regulation link tables). One small notification from the
seed corpus goes through all three stages on regtrack_test; a second pass over the same file must write nothing."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

pytestmark = pytest.mark.db
FX = Path(__file__).parent / "fixtures"


def writes(conn) -> int:
    """Rows inserted, updated or deleted so far in this transaction (all tables)."""
    return conn.execute("SELECT coalesce(sum(n_tup_ins + n_tup_upd + n_tup_del), 0)::int AS n "
                        "FROM pg_stat_xact_user_tables").fetchone()["n"]


@pytest.fixture()
def v4(migrated, tmp_path, monkeypatch):
    from regtrack import config
    from regtrack.db import connect

    monkeypatch.setenv("DATABASE_URL", migrated[0])
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "raw"))
    monkeypatch.setenv("TEXT_DIR", str(tmp_path / "text"))
    monkeypatch.setenv("LLM_BASE_URL", "")  # no Qwen: extraction stays deterministic and marks llm_pending
    monkeypatch.delenv("REGTRACK_COUNTRY", raising=False)
    config.get_settings.cache_clear()
    conn = connect(dsn=migrated[0])
    yield conn
    conn.rollback()
    conn.close()
    config.get_settings.cache_clear()


def add_seed_file(conn, name: str, folder: str = "05_MoRTH_Gazette_Notifications") -> int:
    from regtrack.db import Jsonb
    from regtrack.sources.common import source_id, store_document
    from regtrack.storage import store_file

    sha, path, _ = store_file(FX / name)
    fid, _ = store_document(conn, conn.execute("SELECT id FROM regions WHERE code='IN'").fetchone()["id"], sha,
                            str(path), name, None, "pdf", "application/pdf", path.stat().st_size)
    conn.execute("INSERT INTO raw_ingestion_records (source_id, document_id, external_ref, listing_title, payload, "
                 "processing_status) VALUES (%s,%s,%s,%s,%s,'downloaded')",
                 (source_id(conn, "LOCAL_SEED"), fid, f"test-log.csv:{name}", name,
                  Jsonb({"folder": folder, "file_name": name})))
    return fid


def run_all(conn, fid: int) -> None:
    from regtrack.pipeline import extract as X
    from regtrack.pipeline import repo
    from regtrack.pipeline import stages as S

    S.stage_text(conn, repo.get_file(conn, fid), allow_ocr=False)
    S.stage_classify(conn, repo.get_file(conn, fid))
    X.stage_extract(conn, repo.get_file(conn, fid), use_llm=False)


def test_notification_goes_through_text_classify_extract(v4):
    from regtrack.pipeline import repo

    conn = v4
    fid = add_seed_file(conn, "so_1406_2021_wheel_rim.pdf")
    run_all(conn, fid)

    f = repo.get_file(conn, fid)
    assert f["stage"] == "parsed" and f["page_count"] and f["text_layer"] is True and f["country"] == "IN"
    parts = repo.parts_of_file(conn, fid)
    assert len(parts) == 1 and parts[0]["is_best_copy"] and parts[0]["role"] == "main"
    doc = repo.get_document(conn, parts[0]["document_id"])
    assert doc["canonical_id"] == "SO-1406(E)-2021" and doc["doc_class"].startswith("NOTIFICATION")
    assert doc["doc_date"] and doc["doc_date"].year == 2021 and doc["issuer"] == "MoRTH"
    assert doc["vehicle_categories"] and doc["extraction"]["llm_pending"] is True
    # the linked rows behind the legacy view
    g = conn.execute("SELECT g.external_code, a.code FROM regulations g JOIN regulatory_authorities a "
                     "ON a.id=g.authority_id WHERE g.id=%s", (doc["id"],)).fetchone()
    assert g["code"] == "MORTH"
    assert conn.execute("SELECT count(*) AS n FROM regulation_authorities WHERE regulation_id=%s AND role='primary'",
                        (doc["id"],)).fetchone()["n"] == 1
    n_cat = conn.execute("SELECT count(*) AS n FROM regulation_vehicle_categories WHERE regulation_id=%s",
                         (doc["id"],)).fetchone()["n"]
    assert n_cat == len(doc["vehicle_categories"])
    if doc["domains"]:
        prim = conn.execute("SELECT lower(d.code) AS c FROM regulation_domains l JOIN domains d ON d.id=l.domain_id "
                            "WHERE l.regulation_id=%s AND l.is_primary", (doc["id"],)).fetchall()
        assert [r["c"] for r in prim] == doc["domains"][:1]
    # the listing records the verdict and the regulation it led to
    rec = conn.execute("SELECT processing_status, classification_verdict, regulation_id FROM raw_ingestion_records "
                       "WHERE document_id=%s", (fid,)).fetchone()
    assert rec["processing_status"] == "processed" and rec["classification_verdict"] is True
    assert rec["regulation_id"] == doc["id"]
    # derived fields (migration 0008), and a second call has nothing to do
    assert conn.execute("SELECT refresh_regulation_fields('IN') AS n").fetchone()["n"] >= 1
    assert conn.execute("SELECT refresh_regulation_fields('IN') AS n").fetchone()["n"] == 0
    g = conn.execute("SELECT doc_type, doc_role, legal_force, local_type FROM regulations WHERE id=%s",
                     (doc["id"],)).fetchone()
    assert g["doc_type"] == "REGULATION" and g["legal_force"] == "MANDATORY" and g["local_type"] == "S.O."


def test_second_pass_writes_nothing(v4):
    from regtrack.pipeline import extract as X
    from regtrack.pipeline import repo
    from regtrack.pipeline import stages as S

    conn = v4
    fid = add_seed_file(conn, "draft_notification.pdf")
    run_all(conn, fid)
    conn.execute("SELECT refresh_regulation_fields('IN')")
    before = writes(conn)
    S.stage_classify(conn, repo.get_file(conn, fid))  # back through classify and extract, same content
    X.stage_extract(conn, repo.get_file(conn, fid), use_llm=False)
    conn.execute("SELECT refresh_regulation_fields('IN')")
    # set_stage moves the file classified -> parsed again: exactly those two updates (and the listing stays processed)
    assert writes(conn) - before == 2


def test_ais_with_amendments_split_into_parts(v4):
    from regtrack.pipeline import repo

    conn = v4
    fid = add_seed_file(conn, "ais_with_amendment.pdf", "07_AIS_Published_Standards")
    run_all(conn, fid)
    parts = repo.parts_of_file(conn, fid)
    docs = [repo.get_document(conn, p["document_id"]) for p in parts]
    classes = {d["doc_class"] for d in docs}
    assert "AIS_STANDARD" in classes and "AIS_AMENDMENT" in classes
    for d in docs:
        assert d["canonical_id"].startswith("AIS-") and d["issuer"] == "AISC/ARAI"
    amd = [d for d in docs if d["doc_class"] == "AIS_AMENDMENT"]
    assert all(d["data"].get("amends") for d in amd)


def test_repo_round_trip_and_links(v4):
    from regtrack.pipeline import repo

    conn = v4
    did = repo.insert_document(conn, "TEST-REPO-1", {"doc_class": "CIRCULAR_OM", "status": "final",
                                                     "issuer": "MoPNG", "vehicle_categories": ["M1", "N1"],
                                                     "domains": ["emission", "fuel_efficiency"], "data": {"x": 1}})
    d = repo.get_document(conn, did)
    assert d["issuer"] == "MoPNG" and d["vehicle_categories"] == ["M1", "N1"] and d["domains"][0] == "emission"
    assert not repo.update_document(conn, did, {"vehicle_categories": ["N1", "M1"], "domains": ["emission", "fuel_efficiency"],
                                                "issuer": "MoPNG", "data": {"x": 1}})  # same values: no write
    assert repo.update_document(conn, did, {"domains": ["fuel_efficiency", "emission"], "issuer": "BIS", "vehicle_categories": []})
    d = repo.get_document(conn, did)
    assert d["domains"] == ["fuel_efficiency", "emission"] and d["issuer"] == "BIS" and d["vehicle_categories"] == []
    assert conn.execute("SELECT count(*) AS n FROM regulation_authorities WHERE regulation_id=%s",
                        (did,)).fetchone()["n"] == 1


def test_flags_use_v4b_entity_names(v4):
    from regtrack.pipeline.dbutil import add_flag

    with pytest.raises(ValueError):
        add_flag(v4, "file_object", 1, "X", {})
    assert add_flag(v4, "regulation", 1, "TEST_RULE", {"a": 1})
    assert not add_flag(v4, "regulation", 1, "TEST_RULE", {"a": 1})


def test_stage_files_are_copies_not_moves(tmp_path):
    """The fixtures stay where they are: store_file copies (write-once storage never takes the original)."""
    src = tmp_path / "a.pdf"
    shutil.copy(FX / "draft_notification.pdf", src)
    from regtrack.storage import store_file

    store_file(src, root=tmp_path / "raw")
    assert src.exists()
