"""Multi-country isolation (migration 0005): with COUNTRY=IN no Thai row reaches India's pipeline or screens, and
?country=TH shows the Thai rows. Runs on the separate regtrack_test database; the rows it adds are removed again."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.db

WORD = "zyxquokka"  # appears only in this test's chunks, so search hits are ours


@pytest.fixture()
def two_countries(migrated, monkeypatch):
    """An India and a Thai file (stage 'downloaded'), regulation and chunk (v4B), committed so the API can see them."""
    from regtrack import config
    from regtrack.db import connect

    dsn = migrated[0]
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.delenv("REGTRACK_COUNTRY", raising=False)  # default country: IN
    config.get_settings.cache_clear()
    ids: dict[str, dict[str, int]] = {}
    with connect(dsn=dsn) as conn:
        for cc, cid, dc in (("IN", "TEST-IN-0001", "AIS_STANDARD"), ("TH", "TEST-TH-0001", "TIS_STANDARD")):
            rid = conn.execute("SELECT id FROM regions WHERE code=%s", (cc,)).fetchone()["id"]
            # Thailand has no vehicle categories seeded yet (multi-country rollout): a test one, removed afterwards
            conn.execute("INSERT INTO vehicle_categories (region_id, code, label, un_codes) "
                         "VALUES (%s, 'M1', 'test passenger car', '{M1}') ON CONFLICT DO NOTHING", (rid,))
            fid = conn.execute("INSERT INTO documents (region_id, checksum_sha256, storage_path, file_ext, stage) "
                               "VALUES (%s, %s, %s, 'pdf', 'downloaded') RETURNING id",
                               (rid, cc.lower() * 32, f"test/{cc}.pdf")).fetchone()["id"]
            reg = conn.execute(
                "INSERT INTO regulations (region_id, external_code, local_class, legal_status, published_date, in_scope, "
                "nature, title) VALUES (%s, %s, (SELECT code FROM document_classes WHERE region_id=%s "
                "ORDER BY (code=%s) DESC, code LIMIT 1), 'final', current_date, true, 'technical', %s) RETURNING id",
                (rid, cid, rid, dc, f"{cc} test brake standard")).fetchone()["id"]
            conn.execute("INSERT INTO regulation_vehicle_categories SELECT %s, id FROM vehicle_categories "
                         "WHERE region_id=%s AND code='M1'", (reg, rid))
            conn.execute("INSERT INTO document_chunks (document_id, regulation_id, chunk_index, content, region_id, "
                         "in_scope, is_current, vehicle_category_ids) VALUES (%s, %s, 0, %s, %s, true, true, "
                         "ARRAY(SELECT id FROM vehicle_categories WHERE region_id=%s AND code='M1'))",
                         (fid, reg, f"{WORD} braking requirement for {cc}", rid, rid))
            ids[cc] = {"file": fid, "reg": reg}
        conn.commit()
    yield ids
    with connect(dsn=dsn) as conn:
        conn.execute("DELETE FROM regulations WHERE id = ANY(%s)", ([v["reg"] for v in ids.values()],))  # + chunks, links
        conn.execute("DELETE FROM documents WHERE id = ANY(%s)", ([v["file"] for v in ids.values()],))
        conn.execute("DELETE FROM vehicle_categories WHERE label='test passenger car'")
        conn.commit()
    config.get_settings.cache_clear()


@pytest.fixture()
def client(two_countries):
    from fastapi.testclient import TestClient

    from regtrack.api.app import app

    return TestClient(app)


def test_pipeline_does_not_pick_thai_files(two_countries, monkeypatch):
    from regtrack.db import connect
    from regtrack.pipeline import runner
    from regtrack.pipeline import stages as S

    th, india = two_countries["TH"]["file"], two_countries["IN"]["file"]
    with connect() as conn:
        picked = {f["id"] for f in runner._files(conn, "downloaded", None)}
    assert india in picked and th not in picked
    seen = []
    monkeypatch.setattr(S, "stage_text", lambda conn, f: seen.append(f["id"]))  # no real text extraction
    out = runner.run_stage("text", workers=1)
    assert seen == [india] and out["files"] == 1
    with connect() as conn:
        f = conn.execute("SELECT stage, stage_error FROM documents WHERE id=%s", (th,)).fetchone()
    assert f["stage"] == "downloaded" and f["stage_error"] is None


def test_api_shows_only_the_current_country(client):
    def ids(params=None):
        r = client.get("/documents", params={"q": "TEST-", **(params or {})})
        assert r.status_code == 200
        return {d["canonical_id"] for d in r.json()["documents"]}

    assert ids() == {"TEST-IN-0001"}
    assert ids({"country": "TH"}) == {"TEST-TH-0001"}
    assert client.get("/documents/TEST-TH-0001").status_code == 404
    assert client.get("/documents/TEST-TH-0001", params={"country": "TH"}).status_code == 200
    assert client.get("/documents", params={"country": "x'; --"}).status_code == 400


def test_dashboard_counts_exclude_other_countries(client):
    assert client.get("/meta").json()["stats"]["documents"] == 1
    assert client.get("/meta", params={"country": "TH"}).json()["stats"]["documents"] == 1
    india = client.get("/portal/summary").json()
    assert india["kpis"]["tracked"] == 1 and [r["canonical_id"] for r in india["latest"]] == ["TEST-IN-0001"]
    thai = client.get("/portal/summary", params={"country": "TH"}).json()
    assert [r["canonical_id"] for r in thai["latest"]] == ["TEST-TH-0001"]
    regs = client.get("/portal/regulations").json()["rows"]
    assert [r["canonical_id"] for r in regs] == ["TEST-IN-0001"]


def test_search_stays_in_country(client, monkeypatch):
    from regtrack import llm

    def offline(_texts):
        raise llm.LLMUnavailable("test: keyword search")

    monkeypatch.setattr(llm, "embed", offline)
    hits = client.get("/search", params={"q": WORD}).json()["results"]
    assert {h["canonical_id"] for h in hits} == {"TEST-IN-0001"}
    hits = client.get("/search", params={"q": WORD, "country": "TH"}).json()["results"]
    assert {h["canonical_id"] for h in hits} == {"TEST-TH-0001"}


def test_admin_lists_only_india_sources(client):
    india = {s["code"] for s in client.get("/portal/admin").json()["sources"]}
    assert india == {"ARAI_AIS", "MORTH_API", "EGAZETTE", "INDIACODE", "ARAI_TAP", "LOCAL_SEED"}
    thai = {s["code"] for s in client.get("/portal/admin", params={"country": "TH"}).json()["sources"]}
    assert len(thai) == 8 and all(c.startswith("TH_") for c in thai)
    assert client.get("/portal/meta").json()["sources_total"] == 4  # India's crawlers
