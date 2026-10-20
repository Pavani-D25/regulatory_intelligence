"""Portal API (approved design v2) on DATABASE_URL (on branch v4-schema: regtrack_dev, the v4B tables).
Writes are made on real rows and put back exactly as they were, or on test rows that are removed again."""

from __future__ import annotations

from datetime import date

import pytest

from regtrack.db import Jsonb, is_reachable

pytestmark = [pytest.mark.db, pytest.mark.skipif(not is_reachable()[0], reason="PostgreSQL not reachable")]


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from regtrack.api.app import app

    return TestClient(app)


def test_classify_rules():
    from regtrack.api.portal import classify_row

    vocab = {"categories": ["L1", "L2", "M1", "N1"], "scope": ["L1", "L2", "M1", "N1", "ALL"],
             "cat_label": {}, "domain_label": {}}
    base = dict(nature="technical", doc_class="NOTIFICATION_FINAL", doc_date=date(2015, 1, 1), next_obligation=None,
                reapproval=False, last_event_at=None, last_event_review=None, doc_status="final", official_title="T",
                subject=None, canonical_id="X", vehicle_categories=["M1"], issuer="MoRTH", domains=["braking"])
    assert classify_row(dict(base), vocab)["impact"] == "Medium"
    assert classify_row(dict(base, nature="administrative", doc_class="NOTIFICATION_FINAL"), vocab)["impact"] == "Low"
    up = classify_row(dict(base, next_obligation=date(2099, 1, 1)), vocab, today=date(2026, 1, 1))
    assert (up["impact"], up["status"]) == ("High", "Action Required")
    assert classify_row(dict(base, doc_class="NOTIFICATION_DRAFT"), vocab)["status"] == "Under Review"
    team = classify_row(dict(base, review_status="Tracked", review_impact="Low", next_obligation=date(2099, 1, 1)), vocab)
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
    cols = "workflow_status, impact_level, impact_basis, owner_team_id, review_note, reviewed_at"
    with connect() as conn:
        saved = conn.execute(f"SELECT id, {cols} FROM regulations WHERE external_code=%s", (cid,)).fetchone()
    try:
        assert client.put(f"/portal/regulations/{cid}/review",
                          json={"status": "Tracked", "owner": "pytest", "impact": "Low"}).status_code == 200
        d = client.get(f"/portal/regulations/{cid}/detail").json()
        assert (d["status"], d["impact"], d["impact_basis"], d["owner"]) == ("Tracked", "Low", "team", "pytest")
        assert client.put(f"/portal/regulations/{cid}/review", json={"status": "Tracked", "owner": "pytest"}).status_code == 200
        assert client.get(f"/portal/regulations/{cid}/detail").json()["impact_basis"] == "rules"  # back to the rule
        assert client.put(f"/portal/regulations/{cid}/review", json={"status": "Bogus"}).status_code == 400
    finally:
        with connect() as conn:
            conn.execute(f"UPDATE regulations SET ({cols}) = (%s,%s,%s,%s,%s,%s) WHERE id=%s",
                         (*[saved[c.strip()] for c in cols.split(",")], saved["id"]))
            conn.execute("DELETE FROM teams WHERE name='pytest'")
            conn.commit()


def test_compliance_alerts_reports(client):
    from regtrack.db import connect

    rows = client.get("/portal/compliance").json()["rows"]
    assert rows
    key = rows[0]["mandate_key"]
    cols = "owner_team_id, evidence_links, status, due_date, note, updated_at"
    with connect() as conn:
        saved = conn.execute(f"SELECT id, {cols} FROM compliance_requirements WHERE requirement_code=%s", (key,)).fetchone()
    try:
        r = client.put(f"/portal/compliance/{key}", json={"owner": "pytest", "status": "Compliant"})
        assert r.status_code == 200
        assert client.get("/portal/compliance").json()["kpis"]["compliant_pct"] > 0
        row = next(r for r in client.get("/portal/compliance").json()["rows"] if r["mandate_key"] == key)
        assert (row["owner"], row["status"]) == ("pytest", "Compliant") and row["updated_at"]
        rid = client.post("/portal/alerts", json={"name": "pytest rule", "condition": "new_document", "scope": "L2"}).json()["id"]
        rule = next(r for r in client.get("/portal/alerts").json()["rules"] if r["id"] == rid)
        assert (rule["scope"], rule["condition"], rule["enabled"]) == ("L2", "new_document", True)
        assert client.patch(f"/portal/alerts/{rid}", json={"enabled": False}).status_code == 200
        assert client.delete(f"/portal/alerts/{rid}").status_code == 200
        rep = client.get("/portal/reports/executive?owner=pytest")
        assert rep.status_code == 200 and "attachment" in rep.headers["content-disposition"]
        assert client.get("/portal/reports/compliance_gap?fmt=csv&owner=pytest").text.startswith("Requirement,")
        recent = client.get("/portal/reports").json()["recent"]
        assert [r["owner"] for r in recent[:2]] == ["pytest", "pytest"] and recent[0]["kind"] == "Compliance Gap Report"
    finally:
        with connect() as conn:
            conn.execute(f"UPDATE compliance_requirements SET ({cols}) = (%s,%s,%s,%s,%s,%s) WHERE id=%s",
                         (*[Jsonb(saved[c.strip()]) if c.strip() == "evidence_links" else saved[c.strip()]
                            for c in cols.split(",")], saved["id"]))
            conn.execute("DELETE FROM alert_rules WHERE name='pytest rule'")
            conn.execute("DELETE FROM reports WHERE owner_team_id=(SELECT id FROM teams WHERE name='pytest')")
            conn.execute("DELETE FROM teams WHERE name='pytest'")
            conn.commit()


def test_ask_returns_cited_clauses(client):
    from regtrack.db import connect

    r = client.post("/portal/ask", json={"question": "traction battery safety"}).json()
    assert r["mode"] in ("search", "qwen") and r["sources"]
    assert any(s["canonical_id"].startswith("AIS-") for s in r["sources"])
    # the exchange is kept (v4B assistant tables); a follow-up continues the same conversation
    cid = r["conversation_id"]
    try:
        r2 = client.post("/portal/ask", json={"question": "and for M1?", "conversation_id": cid}).json()
        assert r2["conversation_id"] == cid
        h = client.get(f"/portal/ask/conversations/{cid}").json()["messages"]
        assert [m["role"] for m in h] == ["user", "assistant", "user", "assistant"]
        assert h[0]["content"] == "traction battery safety" and len(h[1]["citations"]) == len(r["sources"])
        assert all(c["canonical_id"] for c in h[1]["citations"])
        assert client.get("/portal/ask/conversations/999999999").status_code == 404
    finally:
        with connect() as conn:
            conn.execute("DELETE FROM assistant_conversations WHERE id=%s", (cid,))  # messages and citations cascade
            conn.commit()


def test_no_static_values(client):
    """Labels, suggestions, sync sources and scheduler state come from the database, not from code."""
    from regtrack.db import connect

    meta = client.get("/portal/meta").json()
    with connect() as conn:
        labels = {r["code"]: r["label"] for r in conn.execute(
            "SELECT code, label FROM vehicle_categories WHERE region_id=(SELECT id FROM regions WHERE code='IN')")}
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

    def fake_crawl(code, cc=None):
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


def test_reference_documents_hidden_unless_asked(client):
    cur = client.get("/portal/regulations").json()
    ref = client.get("/portal/regulations", params={"reference": True}).json()
    assert ref["kpis"]["records"] == cur["kpis"]["records"] + cur["kpis"]["reference"]
    assert all(r["doc_class"] not in ("REPORT", "OTHER", "AIS_FORM_TABLE") for r in cur["rows"])
    # the ARAI index page is reference material, not a regulation
    assert "DOC-47ed5282a0ed3ef6" not in {r["canonical_id"] for r in cur["rows"]}


def test_drafts_are_not_published_standards():
    from regtrack.db import connect

    with connect() as conn:
        bad = conn.execute("""SELECT count(*) AS n FROM regulations d JOIN document_parts p ON p.regulation_id=d.id AND p.is_best_copy
                              JOIN raw_ingestion_records fs ON fs.document_id=p.document_id
                              JOIN sources s ON s.id=fs.source_id AND s.code='ARAI_AIS'
                              WHERE d.local_class='AIS_STANDARD' AND fs.payload->>'code' ILIKE 'Draft%%'""").fetchone()["n"]
    assert bad == 0


def test_workspace_teams_watches_schedules(client, tmp_path, monkeypatch):
    """v4 workspace: teams and users, a watch on a regulation, a report schedule that the scheduler runs."""
    from datetime import datetime, timedelta

    from regtrack.api import workspace as W
    from regtrack.db import connect

    monkeypatch.setattr(W, "REPORT_DIR", tmp_path)
    cid = client.get("/portal/regulations").json()["rows"][0]["canonical_id"]
    tid = client.post("/portal/teams", json={"name": "pytest workspace"}).json()["id"]
    try:
        assert client.post("/portal/teams", json={"name": "pytest workspace"}).json()["id"] == tid  # same name, same team
        uid = client.post("/portal/users", json={"email": "PyTest@Example.com", "name": "Py Test", "team_id": tid}).json()["id"]
        assert client.post("/portal/users", json={"email": "pytest@example.com", "name": "x"}).status_code == 409
        assert client.post("/portal/users", json={"email": "not-an-email", "name": "x"}).status_code == 400
        assert client.patch(f"/portal/users/{uid}", json={"role": "editor", "is_active": False}).status_code == 200
        u = next(x for x in client.get("/portal/team").json()["users"] if x["id"] == uid)
        assert (u["email"], u["role"], u["is_active"], u["team"]) == ("pytest@example.com", "editor", False, "pytest workspace")
        assert any(t["id"] == tid for t in client.get("/portal/meta").json()["teams"])
        # watch: one team, once
        wid = client.post("/portal/watches", json={"canonical_id": cid, "team_id": tid}).json()["id"]
        assert client.post("/portal/watches", json={"canonical_id": cid, "team_id": tid}).status_code == 409
        assert client.post("/portal/watches", json={"canonical_id": cid}).status_code == 400
        assert client.post("/portal/watches", json={"canonical_id": "NO-SUCH-ID", "team_id": tid}).status_code == 404
        assert [w["team"] for w in client.get("/portal/watches", params={"canonical_id": cid}).json()["watches"]
                if w["id"] == wid] == ["pytest workspace"]
        # schedule: due a week later, the scheduler writes the report file, logs it and moves the next date
        sid = client.post("/portal/report-schedules", json={"kind": "compliance_gap", "frequency": "weekly",
                                                             "team_ids": [tid]}).json()["id"]
        assert client.post("/portal/report-schedules", json={"kind": "compliance_gap", "frequency": "hourly",
                                                             "team_ids": [tid]}).status_code == 400
        files = W.run_due_schedules(datetime.now().astimezone() + timedelta(days=8))
        assert len(files) == 1 and (tmp_path / files[0]).read_text(encoding="utf-8").startswith("<!doctype html>")
        s = next(x for x in client.get("/portal/report-schedules").json()["schedules"] if x["id"] == sid)
        assert s["teams"] == ["pytest workspace"] and s["last_run_at"] and s["kind"] == "compliance_gap"
        assert W.run_due_schedules(datetime.now().astimezone() + timedelta(days=8)) == []  # not due again yet
        assert client.patch(f"/portal/report-schedules/{sid}", json={"is_active": False}).status_code == 200
        assert client.get("/portal/ask/conversations").status_code == 200
    finally:
        with connect() as conn:
            conn.execute("DELETE FROM reports WHERE owner_team_id=%s", (tid,))
            conn.execute("DELETE FROM report_schedules WHERE recipients->'teams' @> to_jsonb(%s::int)", (tid,))
            conn.execute("DELETE FROM regulation_watches WHERE watcher_team_id=%s", (tid,))
            conn.execute("DELETE FROM users WHERE team_id=%s", (tid,))
            conn.execute("DELETE FROM teams WHERE id=%s", (tid,))
            conn.commit()
