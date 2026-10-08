"""Read API used by the dashboard (runs against the main database; skipped when it is not reachable)."""

from __future__ import annotations

import pytest

from regtrack.db import is_reachable

pytestmark = [pytest.mark.db, pytest.mark.skipif(not is_reachable()[0], reason="PostgreSQL not reachable")]


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from regtrack.api.app import app

    return TestClient(app)


def test_meta_and_cors(client):
    r = client.get("/meta", headers={"Origin": "http://localhost:5173"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    body = r.json()
    assert {"stats", "years", "doc_classes", "domains", "categories"} <= body.keys()


def test_families_and_document_files(client):
    fams = client.get("/families", params={"q": "AIS-0"}).json()["families"]
    assert fams and all("current" in f for f in fams)
    docs = client.get("/documents", params={"doc_class": "NOTIFICATION_FINAL", "limit": 1}).json()["documents"]
    d = client.get(f"/documents/{docs[0]['canonical_id']}").json()
    assert "ai_pending" in d and d["files"]
    f = client.get(f"/files/{d['files'][0]['sha256']}")
    assert f.status_code == 200 and "inline" in f.headers["content-disposition"]
    assert "attachment" in client.get(f"/files/{d['files'][0]['sha256']}?download=true").headers["content-disposition"]


def test_vehicle_and_unknown_file(client):
    r = client.get("/vehicles/applicable", params={"category": "L2", "engine_cc": 110, "powertrain": "petrol", "on": "2026-01-01"})
    assert r.status_code == 200 and r.json()["in_scope_category"]
    assert client.get("/files/" + "0" * 64).status_code == 404
