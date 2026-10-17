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


# ====================================================================== phase 4: link
WHEEL_RIM = ["so_1406_2021_wheel_rim.pdf", "so_359_2022_wheel_rim_extension.pdf", "so_3896_2022_wheel_rim_extension.pdf"]


def link_chain(conn) -> list[int]:
    from regtrack.pipeline import link as L
    from regtrack.pipeline import repo

    fids = [add_seed_file(conn, n) for n in WHEEL_RIM]
    for fid in fids:
        run_all(conn, fid)
    for fid in fids:  # in date order, as the runner does
        L.stage_link(conn, repo.get_file(conn, fid))
    return fids


def test_wheel_rim_chain_links_and_versions(v4):
    from regtrack.pipeline import repo

    conn = v4
    fids = link_chain(conn)
    assert {repo.get_file(conn, f)["stage"] for f in fids} == {"linked"}
    ids = {repo.find_document(conn, c)["id"]: c for c in ("SO-1406(E)-2021", "SO-359(E)-2022", "SO-3896(E)-2022")}
    rels = conn.execute("SELECT from_regulation_id, type, to_regulation_id, to_ref FROM regulation_relations "
                        "WHERE from_regulation_id = ANY(%s)", (list(ids),)).fetchall()
    # the extensions change the 2004 master table, which is not stored: the link keeps its code
    ext = [r for r in rels if r["type"] == "extends_date"]
    assert ext and all(r["to_regulation_id"] is None and r["to_ref"] == "SO-1365(E)-2004" for r in ext)
    vers = conn.execute("""SELECT v.implementation_date, v.valid_to, v.source_regulation_id FROM requirement_versions v
                           JOIN compliance_requirements c ON c.id=v.requirement_id
                           WHERE c.requirement_code='SO-1365(E)-2004 Table Sr.8(d)' ORDER BY v.id""").fetchall()
    assert [v["implementation_date"].isoformat() for v in vers] == ["2021-09-21", "2022-09-21", "2023-06-22"]
    assert [ids[v["source_regulation_id"]] for v in vers] == ["SO-1406(E)-2021", "SO-359(E)-2022", "SO-3896(E)-2022"]
    assert sum(v["valid_to"] is None for v in vers) == 1
    # the master-table family: newest notification is current
    cur = conn.execute("SELECT external_code FROM regulations WHERE family_key='SO-1365-MASTER' AND is_current").fetchall()
    assert [r["external_code"] for r in cur] == ["SO-3896(E)-2022"]


def test_relink_writes_nothing(v4):
    from regtrack.pipeline import link as L
    from regtrack.pipeline import repo

    conn = v4
    fids = link_chain(conn)
    before = writes(conn)
    for fid in fids:
        conn.execute("UPDATE documents SET stage='parsed' WHERE id=%s", (fid,))
    for fid in fids:
        L.stage_link(conn, repo.get_file(conn, fid))
    assert writes(conn) - before == 2 * len(fids)  # only parsed -> linked again; no relation, version or rule row


def test_reference_resolves_when_target_arrives(v4):
    from regtrack.pipeline import link as L
    from regtrack.pipeline import repo
    from regtrack.pipeline.dbutil import add_flag

    conn = v4
    final = repo.insert_document(conn, "GSR-9001(E)-2030", {"doc_class": "NOTIFICATION_FINAL", "status": "final"})
    assert L.add_relation(conn, final, "finalises", to_cid="GSR-8001(E)-2029")
    assert not L.add_relation(conn, final, "finalises", to_cid="GSR-8001(E)-2029")  # no duplicate
    add_flag(conn, "regulation", final, "unresolved_reference", {"draft": "GSR-8001(E)-2029"})
    draft = repo.insert_document(conn, "GSR-8001(E)-2029", {"doc_class": "NOTIFICATION_DRAFT", "status": "draft"})
    assert L.resolve_refs(conn) >= 1
    r = conn.execute("SELECT to_regulation_id FROM regulation_relations WHERE from_regulation_id=%s", (final,)).fetchone()
    assert r["to_regulation_id"] == draft
    assert conn.execute("SELECT resolved_at FROM quality_flags WHERE entity='regulation' AND entity_id=%s",
                        (final,)).fetchone()["resolved_at"] is not None


def test_ais_family_current_and_superseded(v4):
    from regtrack.pipeline import link as L
    from regtrack.pipeline import repo

    conn = v4
    r1 = repo.insert_document(conn, "AIS-990(Rev.1)", {"doc_class": "AIS_STANDARD", "status": "final",
                                                       "family_key": "AIS-990", "revision": 1})
    r2 = repo.insert_document(conn, "AIS-990(Rev.2)", {"doc_class": "AIS_STANDARD", "status": "final",
                                                       "family_key": "AIS-990", "revision": 2})
    L.recompute_family(conn, "AIS-990")
    g = {r["id"]: r for r in conn.execute("SELECT id, is_current, legal_status, version_seq FROM regulations "
                                          "WHERE family_key='AIS-990'")}
    assert g[r2]["is_current"] and not g[r1]["is_current"]
    assert g[r1]["legal_status"] == "superseded" and g[r2]["legal_status"] == "final"
    assert (g[r1]["version_seq"], g[r2]["version_seq"]) == (1, 2)
    before = writes(conn)
    L.recompute_family(conn, "AIS-990")
    assert writes(conn) == before


def test_final_closes_its_drafts_versions(v4):
    from datetime import date

    from regtrack.pipeline import mandates as M
    from regtrack.pipeline import repo

    conn = v4
    draft = repo.insert_document(conn, "GSR-8002(E)-2029", {"doc_class": "NOTIFICATION_DRAFT", "status": "draft"})
    final = repo.insert_document(conn, "GSR-9002(E)-2030", {"doc_class": "NOTIFICATION_FINAL", "status": "final"})
    base = {"legal_basis": "CMVR Rule 999", "subject": "test", "source_doc_id": draft, "vehicle_categories": ["M1"],
            "conditions": {}, "model_scope": "all"}
    d_id, _ = M.supersede(conn, "CMVR Rule 999 :: test", base, date(2029, 1, 1), True)
    f_id, _ = M.supersede(conn, "CMVR Rule 999 :: test", {**base, "source_doc_id": final}, date(2030, 1, 1), False)
    assert M.finalise_drafts(conn, final, draft, date(2030, 1, 1)) == 1
    v = conn.execute("SELECT valid_to, superseded_by FROM requirement_versions WHERE id=%s", (d_id,)).fetchone()
    assert v["valid_to"] == date(2030, 1, 1) and v["superseded_by"] == f_id
    assert M.open_versions(conn, "CMVR Rule 999 :: test")[0]["vehicle_categories"] == ["M1"]


# ====================================================================== phase 5: chunks, search, assistant history
def chunked(conn) -> tuple[int, int]:
    """The S.O. 1406(E)-2021 file through text ... link -> chunk; returns (file id, regulation id)."""
    from regtrack.pipeline import chunk as C
    from regtrack.pipeline import link as L
    from regtrack.pipeline import repo

    fid = add_seed_file(conn, "so_1406_2021_wheel_rim.pdf")
    run_all(conn, fid)
    L.stage_link(conn, repo.get_file(conn, fid))
    conn.execute("SELECT refresh_regulation_fields('IN')")
    C.stage_chunk(conn, repo.get_file(conn, fid))
    return fid, repo.find_document(conn, "SO-1406(E)-2021")["id"]


def test_chunks_carry_the_regulation_filters(v4):
    from regtrack.pipeline import chunk as C
    from regtrack.pipeline import repo

    conn = v4
    fid, rid = chunked(conn)
    assert repo.get_file(conn, fid)["stage"] == "chunked"
    rows = conn.execute("SELECT * FROM document_chunks WHERE regulation_id=%s ORDER BY chunk_index", (rid,)).fetchall()
    assert rows and [r["chunk_index"] for r in rows] == list(range(len(rows)))
    g = conn.execute("SELECT region_id, doc_type, legal_status, extract(year FROM published_date)::int AS y "
                     "FROM regulations WHERE id=%s", (rid,)).fetchone()
    cats = [r["vehicle_category_id"] for r in conn.execute(
        "SELECT vehicle_category_id FROM regulation_vehicle_categories WHERE regulation_id=%s ORDER BY 1", (rid,))]
    for r in rows:
        assert r["document_id"] == fid and r["region_id"] == g["region_id"] and r["year"] == g["y"] == 2021
        assert r["doc_type"] == g["doc_type"] == "REGULATION" and r["legal_status"] == "final"
        assert r["vehicle_category_ids"] == cats and r["language"] == "en"
        assert r["tsv"]  # filled by the database (migration 0009)
    # chunking again writes nothing; a changed regulation reaches its chunks through the sync, once
    before = writes(conn)
    conn.execute("UPDATE documents SET stage='linked' WHERE id=%s", (fid,))
    C.stage_chunk(conn, repo.get_file(conn, fid))
    assert writes(conn) - before == 2
    assert C.sync_chunk_filters(conn) == 0
    conn.execute("UPDATE regulations SET legal_status='superseded' WHERE id=%s", (rid,))
    assert C.sync_chunk_filters(conn) == len(rows)
    assert C.sync_chunk_filters(conn) == 0


def test_search_keyword_and_vector(v4, monkeypatch):
    from regtrack import llm
    from regtrack.pipeline import chunk as C
    from regtrack.pipeline.search import search

    conn = v4
    fid, rid = chunked(conn)

    def offline(_texts):
        raise llm.LLMUnavailable("test")

    monkeypatch.setattr(llm, "embed", offline)
    r = search(conn, "wheel rims", in_scope=None)
    assert r["mode"].startswith("text") and r["results"]
    top = r["results"][0]
    assert top["canonical_id"] == "SO-1406(E)-2021" and top["regulation_id"] == rid and top["doc_date"].year == 2021
    # it applies to ALL vehicles, so any category finds it; without ALL (and without L1) an L1 search does not
    assert any(h["regulation_id"] == rid for h in search(conn, "wheel rims", category="L1", in_scope=None)["results"])
    conn.execute("DELETE FROM regulation_vehicle_categories l USING vehicle_categories vc WHERE vc.id=l.vehicle_category_id "
                 "AND l.regulation_id=%s AND vc.code IN ('ALL','L1')", (rid,))
    assert C.sync_chunk_filters(conn) > 0
    assert all(h["regulation_id"] != rid for h in search(conn, "wheel rims", category="L1", in_scope=None)["results"])
    assert any(h["regulation_id"] == rid for h in search(conn, "wheel rims", category="N3", in_scope=None)["results"])
    # embeddings: every chunk gets a vector, the file moves to done, and vector search answers
    monkeypatch.setattr(llm, "embed", lambda texts: [[0.1] * 768 for _ in texts])
    monkeypatch.setattr(conn, "commit", lambda: None)  # keep the test inside its transaction
    assert C.embed_pending(conn) >= 1
    assert C.advance_embedded(conn) >= 1
    assert conn.execute("SELECT stage FROM documents WHERE id=%s", (fid,)).fetchone()["stage"] == "done"
    v = search(conn, "wheel rims", in_scope=None)
    assert v["mode"] == "vector" and v["results"] and v["results"][0]["score"] is not None


def test_assistant_history(v4):
    from regtrack.assistant import conversation, record_exchange

    conn = v4
    fid, rid = chunked(conn)
    chunk = conn.execute("SELECT id FROM document_chunks WHERE regulation_id=%s LIMIT 1", (rid,)).fetchone()["id"]
    cid = record_exchange(conn, "wheel rims?", "See [1].", [{"id": chunk, "regulation_id": rid, "score": 0.42}])
    assert record_exchange(conn, "and L2?", "No.", [], conversation_id=cid) == cid
    assert record_exchange(conn, "new", "x", [], conversation_id=-1) != cid  # unknown id: a new conversation
    msgs = conversation(conn, cid)
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert msgs[1]["citations"][0]["canonical_id"] == "SO-1406(E)-2021" and float(msgs[1]["citations"][0]["score"]) == 0.42


# ====================================================================== phase 6: changes, flags, impact, alerts
def make_live(conn, fid: int) -> None:
    """Pretend the file came from a live MoRTH crawl (not only the seed import): change events are emitted for it."""
    from regtrack.sources.common import source_id

    sid = source_id(conn, "MORTH_API")
    run = conn.execute("INSERT INTO ingestion_runs (source_id, status) VALUES (%s,'success') RETURNING id",
                       (sid,)).fetchone()["id"]
    conn.execute("DELETE FROM raw_ingestion_records WHERE document_id=%s", (fid,))
    conn.execute("INSERT INTO raw_ingestion_records (source_id, ingestion_run_id, document_id, external_ref, "
                 "processing_status) VALUES (%s,%s,%s,%s,'processed')", (sid, run, fid, f"test-live-{fid}"))


def live_chain(conn) -> list[int]:
    from regtrack.pipeline import link as L
    from regtrack.pipeline import repo

    fids = [add_seed_file(conn, n) for n in WHEEL_RIM]
    for fid in fids:
        make_live(conn, fid)
        run_all(conn, fid)
    for fid in fids:
        L.stage_link(conn, repo.get_file(conn, fid))
    conn.execute("SELECT refresh_regulation_fields('IN')")
    return fids


def test_changes_from_live_files(v4):
    from regtrack.pipeline import events as E

    conn = v4
    live_chain(conn)
    n = E.emit_events(conn)
    rows = conn.execute("""SELECT e.*, g.external_code FROM regulation_changes e LEFT JOIN regulations g ON g.id=e.regulation_id
                           ORDER BY e.id""").fetchall()
    assert n == len(rows) and rows
    assert {r["external_code"] for r in rows if r["change_type"] == "new_document"} == \
        {"SO-1406(E)-2021", "SO-359(E)-2022", "SO-3896(E)-2022"}
    dates = [r for r in rows if r["change_type"] == "implementation_date_changed"]
    assert dates and all(r["requirement_version_id"] for r in dates)
    sr8d = [r for r in dates if r["details"]["key"] == "SO-1365(E)-2004 Table Sr.8(d)"]
    assert {(r["details"]["old"], r["details"]["new"]) for r in sr8d} == {("2021-09-21", "2022-09-21"),
                                                                       ("2022-09-21", "2023-06-22")}
    for r in rows:
        assert r["review_status"] == "pending" and r["details"]["summary_by"] == "template" and r["region_id"]
        assert (r["sla_due_at"] - r["detected_at"]).days in (1, 2)
    assert E.emit_events(conn) == 0  # written once


def test_seed_only_files_emit_no_changes(v4):
    from regtrack.pipeline import events as E

    conn = v4
    link_chain(conn)  # seed listings only
    assert E.emit_events(conn) == 0


def test_rule_based_impact_and_team_value(v4):
    conn = v4
    fids = link_chain(conn)
    imp = lambda c: conn.execute("SELECT impact_level, impact_basis FROM regulations WHERE external_code=%s",  # noqa: E731
                                 (c,)).fetchone()
    conn.execute("SELECT refresh_regulation_fields('IN')")
    # technical, published years ago, all dates in the past, no re-approval: medium
    assert dict(imp("SO-1406(E)-2021")) == {"impact_level": "medium", "impact_basis": "rules"}
    conn.execute("UPDATE regulations SET published_date=current_date - 10 WHERE external_code='SO-1406(E)-2021'")
    conn.execute("UPDATE regulations SET impact_level='low', impact_basis='team' WHERE external_code='SO-359(E)-2022'")
    conn.execute("SELECT refresh_regulation_fields('IN')")
    assert imp("SO-1406(E)-2021")["impact_level"] == "high"  # published in the last 12 months
    assert dict(imp("SO-359(E)-2022")) == {"impact_level": "low", "impact_basis": "team"}  # the team's value stays
    assert conn.execute("SELECT refresh_regulation_fields('IN') AS n").fetchone()["n"] == 0
    assert fids


def test_alerts_stored_once_and_closed(v4):
    from regtrack.pipeline import alerts as A
    from regtrack.pipeline import events as E

    conn = v4
    live_chain(conn)
    E.emit_events(conn)
    team = conn.execute("SELECT id FROM teams ORDER BY id LIMIT 1").fetchone()["id"]
    conn.execute("UPDATE alert_rules SET is_enabled=false")
    new_doc = conn.execute("INSERT INTO alert_rules (name, condition, notify_team_id) VALUES "
                           "('test new documents', '{\"type\": \"new_document\"}', %s) RETURNING id", (team,)).fetchone()["id"]
    due = conn.execute("INSERT INTO alert_rules (name, condition, notify_team_id) VALUES "
                       "('test due', '{\"type\": \"due_within\", \"param\": \"30\"}', %s) RETURNING id", (team,)).fetchone()["id"]
    # an open rule version due in 10 days
    v = conn.execute("""SELECT v.id FROM requirement_versions v WHERE v.valid_to IS NULL AND NOT v.is_draft
                        AND v.vehicle_category_ids <> '{}' LIMIT 1""").fetchone()["id"]
    conn.execute("UPDATE requirement_versions SET implementation_date=current_date + 10 WHERE id=%s", (v,))
    got = A.evaluate_rules(conn)
    # only S.O. 1406(E)-2021 is in scope; the two extensions are tagged E-cart / E-rickshaw
    assert got[new_doc] == 1 and got[due] >= 1
    assert sum(A.evaluate_rules(conn).values()) == 0  # stored once
    ev = conn.execute("SELECT * FROM alert_events WHERE rule_id=%s ORDER BY id", (new_doc,)).fetchall()
    assert all(e["regulation_change_id"] and e["regulation_id"] and not e["is_resolved"] for e in ev)
    assert A.close_settled(conn) == 0
    conn.execute("UPDATE regulation_changes SET review_status='reviewed' WHERE id=%s", (ev[0]["regulation_change_id"],))
    conn.execute("UPDATE requirement_versions SET implementation_date=current_date - 1 WHERE id=%s", (v,))
    assert A.close_settled(conn) == 2
    assert conn.execute("SELECT is_resolved FROM alert_events WHERE requirement_version_id=%s AND rule_id=%s",
                        (v, due)).fetchone()["is_resolved"]


def test_flags_resolved_on_v4b(v4):
    from regtrack.pipeline import resolve as RS
    from regtrack.pipeline.dbutil import add_flag

    conn = v4
    fid = link_chain(conn)[0]
    add_flag(conn, "document", fid, "placeholder_listing_date", {"date": "2021-01-01"})
    out = RS.resolve_all(conn)
    assert out["placeholder_listing_date"] >= 1
    q = conn.execute("SELECT resolved_at, details FROM quality_flags WHERE entity='document' AND entity_id=%s "
                     "AND rule='placeholder_listing_date'", (fid,)).fetchone()
    assert q["resolved_at"] and q["details"]["evidence"]["content_date"] == "2021-03-22"
