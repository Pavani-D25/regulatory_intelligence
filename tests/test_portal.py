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
