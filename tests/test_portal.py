"""Portal API (approved design v2) on the main database; writes are made on test rows and removed again."""

from __future__ import annotations

from datetime import date

import pytest

from regtrack.db import is_reachable

pytestmark = [pytest.mark.db, pytest.mark.skipif(not is_reachable()[0], reason="PostgreSQL not reachable")]


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from regtrack.api.app import app

    return TestClient(app)


def test_classify_rules():
    from regtrack.api.portal import classify_row

    base = dict(nature="technical", doc_class="NOTIFICATION_FINAL", doc_date=date(2015, 1, 1), next_obligation=None,
                reapproval=False, last_event_at=None, last_event_review=None, doc_status="final", official_title="T",
                subject=None, canonical_id="X", vehicle_categories=["M1"], issuer="MoRTH", domains=["braking"])
    assert classify_row(dict(base))["impact"] == "Medium"
    assert classify_row(dict(base, nature="administrative", doc_class="NOTIFICATION_FINAL"))["impact"] == "Low"
    up = classify_row(dict(base, next_obligation=date(2099, 1, 1)), today=date(2026, 1, 1))
    assert (up["impact"], up["status"]) == ("High", "Action Required")
    assert classify_row(dict(base, doc_class="NOTIFICATION_DRAFT"))["status"] == "Under Review"
    team = classify_row(dict(base, review_status="Tracked", review_impact="Low", next_obligation=date(2099, 1, 1)))
    assert (team["impact"], team["status"], team["impact_basis"]) == ("Low", "Tracked", "team")


def test_views_only_india_scope(client):
    s = client.get("/portal/summary").json()
    assert s["kpis"]["tracked"] > 0 and len(s["trend"]) == 12
    assert [c["code"] for c in s["by_category"]] == ["L1", "L2", "M1", "N1"]
    assert all(c["name"].startswith(c["code"]) for c in s["by_category"])
    regs = client.get("/portal/regulations").json()["rows"]
    assert regs and all(set(r["categories"]) <= {"L1", "L2", "M1", "N1", "ALL"} and r["categories"] for r in regs)
    for path in ("/portal/changes", "/portal/compliance", "/portal/impact", "/portal/reports", "/portal/alerts", "/portal/admin"):
        assert client.get(path).status_code == 200, path
    heat = client.get("/portal/impact").json()
    assert all(1 <= v <= 5 for c in heat["cells"] for v in c["scores"])


def test_drawer_and_review_roundtrip(client):
    from regtrack.db import connect

    cid = client.get("/portal/regulations").json()["rows"][0]["canonical_id"]
    d = client.get(f"/portal/regulations/{cid}/detail").json()
    assert d["summary"] and d["change"] and d["action"]
    try:
        assert client.put(f"/portal/regulations/{cid}/review", json={"status": "Tracked", "owner": "pytest"}).status_code == 200
        assert client.get(f"/portal/regulations/{cid}/detail").json()["status"] == "Tracked"
        assert client.put(f"/portal/regulations/{cid}/review", json={"status": "Bogus"}).status_code == 400
    finally:
        with connect() as conn:
            conn.execute("DELETE FROM document_review WHERE owner='pytest'")
            conn.commit()


def test_compliance_alerts_reports(client):
    from regtrack.db import connect

    rows = client.get("/portal/compliance").json()["rows"]
    assert rows
    key = rows[0]["mandate_key"]
    try:
        r = client.put(f"/portal/compliance/{key}", json={"owner": "pytest", "status": "Compliant"})
        assert r.status_code == 200
        assert client.get("/portal/compliance").json()["kpis"]["compliant_pct"] > 0
        rid = client.post("/portal/alerts", json={"name": "pytest rule", "condition": "new_document"}).json()["id"]
        assert client.patch(f"/portal/alerts/{rid}", json={"enabled": False}).status_code == 200
        assert client.delete(f"/portal/alerts/{rid}").status_code == 200
        rep = client.get("/portal/reports/executive?owner=pytest")
        assert rep.status_code == 200 and "attachment" in rep.headers["content-disposition"]
        assert client.get("/portal/reports/compliance_gap?fmt=csv&owner=pytest").text.startswith("Requirement,")
    finally:
        with connect() as conn:
            conn.execute("DELETE FROM compliance_item WHERE owner='pytest'")
            conn.execute("DELETE FROM alert_rule WHERE name='pytest rule'")
            conn.execute("DELETE FROM report_log WHERE owner='pytest'")
            conn.commit()


def test_ask_returns_cited_clauses(client):
    r = client.post("/portal/ask", json={"question": "traction battery safety"}).json()
    assert r["mode"] in ("search", "qwen") and r["sources"]
    assert any(s["canonical_id"].startswith("AIS-") for s in r["sources"])


def test_no_static_values(client):
    """Labels, suggestions, sync sources and scheduler state come from the database, not from code."""
    from regtrack.db import connect

    meta = client.get("/portal/meta").json()
    with connect() as conn:
        labels = {r["code"]: r["label"] for r in conn.execute("SELECT code, label FROM vehicle_category")}
    assert all(labels[c["code"]].startswith(c["label"].split(" ", 1)[1]) for c in meta["categories"])
    assert {"alive", "heartbeat", "auto_sync"} <= meta["scheduler"].keys()
    ctx = client.get("/portal/ask/context").json()
    assert ctx["suggestions"] and ctx["sources"] and ctx["chunks"] > 0
    adm = client.get("/portal/admin").json()
    assert set(adm["syncable"]) == {"ALL", "MORTH_API", "ARAI_AIS", "EGAZETTE", "INDIACODE"}
    assert "high_impact_rule" not in adm["settings"] and "auto_compliance_task" not in adm["settings"]
    wf = client.get("/portal/impact").json()["workflow"]
    assert [w["step"] for w in wf] == ["Detect", "Classify", "Assess", "Map", "Close"]
    assert "scheduled" not in client.get("/portal/reports").json()["kpis"]


def test_sync_all_runs_every_source_and_survives_a_failure(monkeypatch):
    from regtrack import scheduler

    calls, steps = [], []

    def fake_crawl(code):
        calls.append(code)
        if code == "ARAI_AIS":
            raise TimeoutError("site slow")
        return {"status": "ok"}

    monkeypatch.setattr(scheduler, "crawl_source", fake_crawl)
    monkeypatch.setattr(scheduler, "run_pipeline_locked", lambda: {"stage": "done"})
    res = scheduler.run_all(steps.append)
    assert calls == list(scheduler.CRAWLERS)
    assert steps == list(scheduler.CRAWLERS) + ["pipeline"]
    assert set(res["crawl"]) == set(scheduler.CRAWLERS) - {"ARAI_AIS"}
    assert "ARAI_AIS" in res["errors"] and res["pipeline"] == {"stage": "done"}


def test_sync_endpoint_offers_all(client):
    adm = client.get("/portal/admin").json()
    assert adm["syncable"][0] == "ALL"
    assert client.post("/portal/admin/sync", json={"source": "NOPE"}).status_code == 400


def test_superseded_hidden_unless_asked(client):
    cur = client.get("/portal/regulations").json()
    hist = client.get("/portal/regulations", params={"history": True}).json()
    assert all(r["doc_status"] not in ("superseded", "withdrawn") for r in cur["rows"])
    assert hist["kpis"]["records"] == cur["kpis"]["records"] + cur["kpis"]["superseded"]


def test_motor_vehicle_law_rule():
    from regtrack.pipeline.extract import motor_vehicle_law

    assert motor_vehicle_law("THE MOTOR VEHICLES ACT, 1988", "") == "in_force"
    assert motor_vehicle_law("THE CENTRAL MOTOR VEHICLES RULES, 1989", "") == "in_force"
    assert motor_vehicle_law("THE MOTOR VEHIC ES (AMENDMENT) ACT, 1969", "An Act further to amend the Motor Vehicles Act, 1939.") == "repealed"
    assert motor_vehicle_law("REGISTERED NO. DL-33004/2000", "An Act further to amend the Motor Vehicles Act, 1988.") == "in_force"
    assert motor_vehicle_law("THE CARRIAGE BY ROAD ACT, 2007", "An Act to provide for the regulation of common carriers") is None
