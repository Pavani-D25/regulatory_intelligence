"""Portal sign-in (regtrack/auth.py, migration 0026): mandatory, roles, sessions, passwords."""

from __future__ import annotations

import pytest

from regtrack import auth

PASSWORD = "correct-horse-battery"


def test_password_hash_and_rules():
    h = auth.hash_password(PASSWORD)
    assert h.startswith("scrypt$") and PASSWORD not in h
    assert auth.verify_password(PASSWORD, h) and not auth.verify_password("wrong-password", h)
    assert auth.hash_password(PASSWORD) != h  # salted
    assert auth.password_problem("short") and auth.password_problem(PASSWORD) is None


def test_needed_role():
    assert auth.needed_role("GET", "/health") is None and auth.needed_role("POST", "/auth/login") is None
    assert auth.needed_role("GET", "/portal/regulations") == "viewer"
    assert auth.needed_role("POST", "/portal/ask") == "viewer"
    assert auth.needed_role("PUT", "/portal/compliance/x") == "editor"
    assert auth.needed_role("POST", "/portal/users") == "admin"
    assert auth.needed_role("POST", "/portal/admin/sync") == "admin"


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from regtrack.api.app import app
    from regtrack.db import connect

    monkeypatch.setenv("AUTH_REQUIRED", "true")
    emails = {"viewer": "pytest-viewer@example.test", "admin": "pytest-admin@example.test"}
    with connect() as conn:
        conn.execute("DELETE FROM users WHERE email = ANY(%s)", (list(emails.values()),))
        for role, email in emails.items():
            conn.execute(
                "INSERT INTO users (email, name, role, password_hash) VALUES (%s,%s,%s,%s)",
                (email, f"pytest {role}", role, auth.hash_password(PASSWORD)),
            )
        conn.commit()
    auth._FAILS.clear()
    yield TestClient(app), emails
    with connect() as conn:
        conn.execute("DELETE FROM users WHERE email = ANY(%s)", (list(emails.values()),))
        conn.commit()


def test_sign_in_is_mandatory(client):
    c, emails = client
    assert c.get("/health").status_code == 200
    for path in ("/portal/summary", "/portal/regulations", "/documents", "/auth/me"):
        assert c.get(path).status_code == 401, path
    assert c.post("/auth/login", json={"email": emails["viewer"], "password": "wrong-password"}).status_code == 401
    r = c.post("/auth/login", json={"email": emails["viewer"].upper(), "password": PASSWORD})
    assert r.status_code == 200 and r.json()["user"]["role"] == "viewer"
    assert "httponly" in r.headers["set-cookie"].lower()
    assert c.get("/portal/summary").status_code == 200
    assert c.get("/auth/me").json()["user"]["email"] == emails["viewer"]
    c.post("/auth/logout")
    assert c.get("/portal/summary").status_code == 401


def test_roles(client):
    c, emails = client
    c.post("/auth/login", json={"email": emails["viewer"], "password": PASSWORD})
    rows = c.get("/portal/regulations").json()["rows"]
    cid = rows[0]["canonical_id"]
    r = c.post(f"/portal/regulations/{cid}/kpi", json={"criterion": "architecture", "score": 3})
    assert r.status_code == 403  # a viewer reads but does not change
    assert c.post("/portal/users", json={"email": "x@example.test", "name": "x"}).status_code == 403
    c.post("/auth/logout")
    c.post("/auth/login", json={"email": emails["admin"], "password": PASSWORD})
    assert c.get("/portal/team").status_code == 200


def test_lockout_and_password_change(client):
    c, emails = client
    for _ in range(auth.LOCK_AFTER):
        c.post("/auth/login", json={"email": emails["viewer"], "password": "wrong-password"})
    assert c.post("/auth/login", json={"email": emails["viewer"], "password": PASSWORD}).status_code == 429
    auth._FAILS.clear()
    c.post("/auth/login", json={"email": emails["admin"], "password": PASSWORD})
    new = "another-long-password"
    assert c.post("/auth/password", json={"current": "wrong-password", "new": new}).status_code == 400
    assert c.post("/auth/password", json={"current": PASSWORD, "new": new}).status_code == 200
    assert c.get("/portal/summary").status_code == 401  # signed out everywhere after the change
    assert c.post("/auth/login", json={"email": emails["admin"], "password": new}).status_code == 200
