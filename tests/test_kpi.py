"""Impact KPIs (regtrack/kpi.py): weights, computed scores, team scores over them, the API."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from regtrack import kpi

SCOPE = ["L1", "L2", "M1", "N1"]
TODAY = date(2026, 11, 16)


def row(**kw) -> dict:
    base = {
        "doc_class": "NOTIFICATION_FINAL",
        "doc_status": "final",
        "nature": "technical",
        "domains": [],
        "vehicle_categories": [],
        "next_obligation": None,
        "reapproval": False,
        "open_mandates": 0,
    }
    return {**base, **kw}


def test_weights_total_100_and_bands():
    assert sum(kpi.WEIGHTS.values()) == 100 and len(kpi.CRITERIA) == 8
    all_five = {k: (5, "") for k in kpi.KEYS}
    assert kpi.combine(all_five) == {**kpi.combine(all_five), "score": 100, "band": "High"}
    assert kpi.combine({k: (0, "") for k in kpi.KEYS})["band"] == "Low"


def test_computed_scores_follow_the_data():
    braking = row(domains=["braking"], vehicle_categories=["L2"], next_obligation=TODAY + timedelta(days=100))
    a = kpi.auto_scores(braking, SCOPE, TODAY)
    assert a["regulatory"][0] == 5 and a["functional_safety"][0] == 5 and a["urgency"][0] == 5
    assert a["exposure"][0] == 2 and a["cybersecurity"][0] == 0
    fees = row(nature="administrative", domains=["fees"], vehicle_categories=["ALL"])
    f = kpi.auto_scores(fees, SCOPE, TODAY)
    assert f["regulatory"][0] == 1 and f["functional_safety"][0] == 0 and f["exposure"][0] == 5
    assert kpi.auto_scores(row(doc_class="AIS_DRAFT", doc_status="draft"), SCOPE, TODAY)["regulatory"][0] == 2
    cyber = kpi.auto_scores(row(domains=["cybersecurity"]), SCOPE, TODAY)
    assert cyber["cybersecurity"][0] == 5 and cyber["protocol_interface"][0] == 3


def test_team_score_replaces_the_computed_one():
    auto = kpi.auto_scores(row(domains=["fees"], nature="administrative"), SCOPE, TODAY)
    before = kpi.combine(auto)
    after = kpi.combine(auto, {"cybersecurity": {"score": 5, "note": "OTA update path affected"}})
    c = next(x for x in after["criteria"] if x["key"] == "cybersecurity")
    assert c["basis"] == "team" and c["reason"] == "OTA update path affected"
    assert after["score"] == before["score"] + 15
    bases = {x["key"]: x["basis"] for x in before["criteria"]}
    assert bases["regulatory"] == "data" and bases["architecture"] == "estimate"


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from regtrack.api.app import app

    return TestClient(app)


def test_kpi_api_score_and_team_override(client):
    rows = client.get("/portal/regulations").json()["rows"]
    assert all(0 <= r["kpi_score"] <= 100 and r["kpi_band"] in ("High", "Medium", "Low") for r in rows)
    cid = rows[0]["canonical_id"]
    d = client.get(f"/portal/regulations/{cid}/detail").json()
    assert [c["key"] for c in d["kpi"]] == kpi.KEYS and sum(c["points"] for c in d["kpi"]) == pytest.approx(
        d["kpi_score"], abs=1
    )
    try:
        set_ = client.post(
            f"/portal/regulations/{cid}/kpi", json={"criterion": "architecture", "score": 5, "note": "pytest"}
        ).json()
        arch = next(c for c in set_["kpi"] if c["key"] == "architecture")
        assert arch == {**arch, "score": 5, "basis": "team", "reason": "pytest"}
    finally:
        cleared = client.post(f"/portal/regulations/{cid}/kpi", json={"criterion": "architecture", "score": None})
    assert next(c for c in cleared.json()["kpi"] if c["key"] == "architecture")["basis"] == "estimate"
    assert client.post(f"/portal/regulations/{cid}/kpi", json={"criterion": "colour", "score": 3}).status_code == 400
    assert client.post(f"/portal/regulations/{cid}/kpi", json={"criterion": "urgency", "score": 9}).status_code == 400
