"""Portal sign-in: password hashing, sessions and the roles a request needs (migration 0026).

A password is kept only as a salted scrypt hash. Signing in creates a session: a random token sent to the browser in an
HttpOnly cookie (COOKIE), valid for SESSION_HOURS; only its sha256 is stored. Roles are users.role:

    viewer  reads everything            editor  also changes data (reviews, compliance, KPI scores, alerts...)
    admin   also manages users, teams, settings and source syncs

AUTH_REQUIRED=false in .env turns sign-in off (tests do this); every request is then an admin.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from contextvars import ContextVar

from regtrack.db import connect

COOKIE = "regtrack_session"
SESSION_HOURS = 12
ROLES = ("viewer", "editor", "admin")
RANK = {r: i for i, r in enumerate(ROLES)}
MIN_PASSWORD = 10

# the signed-in user of the current request (set by the API middleware)
USER: ContextVar[dict | None] = ContextVar("regtrack_user", default=None)
ANONYMOUS_ADMIN = {"id": None, "email": "", "name": "Sign-in disabled", "role": "admin"}

_N, _R, _P = 2**14, 8, 1  # scrypt cost


def required() -> bool:
    return (os.getenv("AUTH_REQUIRED") or "true").strip().lower() not in ("0", "false", "no", "off")


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    key = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${base64.b64encode(salt).decode()}${base64.b64encode(key).decode()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored or not stored.startswith("scrypt$"):
        return False
    _, n, r, p, salt, key = stored.split("$")
    got = hashlib.scrypt(
        password.encode("utf-8"),
        salt=base64.b64decode(salt),
        n=int(n),
        r=int(r),
        p=int(p),
        dklen=len(base64.b64decode(key)),
    )
    return hmac.compare_digest(got, base64.b64decode(key))


def password_problem(password: str) -> str | None:
    if len(password or "") < MIN_PASSWORD:
        return f"the password needs at least {MIN_PASSWORD} characters"
    return None


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# failed sign-ins per email: 5 within 15 minutes locks that email for the rest of the window (in memory, per process)
_FAILS: dict[str, list[float]] = {}
LOCK_AFTER, LOCK_WINDOW = 5, 15 * 60


def locked(email: str) -> bool:
    now = time.time()
    recent = [t for t in _FAILS.get(email, []) if now - t < LOCK_WINDOW]
    _FAILS[email] = recent
    return len(recent) >= LOCK_AFTER


def sign_in(email: str, password: str) -> tuple[dict, str] | None:
    """(user, session token) for a correct email + password of an active user; None otherwise."""
    email = (email or "").strip().lower()
    with connect() as conn:
        u = conn.execute(
            "SELECT id, email, name, role, is_active, password_hash FROM users WHERE email=%s", (email,)
        ).fetchone()
        if not u or not u["is_active"] or not verify_password(password or "", u["password_hash"]):
            _FAILS.setdefault(email, []).append(time.time())
            return None
        _FAILS.pop(email, None)
        token = secrets.token_urlsafe(32)
        conn.execute(
            "INSERT INTO user_sessions (token_hash, user_id, expires_at) "
            "VALUES (%s, %s, now() + make_interval(hours => %s))",
            (_token_hash(token), u["id"], SESSION_HOURS),
        )
        conn.execute("UPDATE users SET last_login_at=now() WHERE id=%s", (u["id"],))
        conn.execute("DELETE FROM user_sessions WHERE expires_at < now()")
        conn.commit()
    return {k: u[k] for k in ("id", "email", "name", "role")}, token


def user_for(token: str | None) -> dict | None:
    """The active user a session token belongs to, if it has not expired."""
    if not token:
        return None
    with connect() as conn:
        u = conn.execute(
            """SELECT u.id, u.email, u.name, u.role FROM user_sessions s JOIN users u ON u.id = s.user_id
               WHERE s.token_hash=%s AND s.expires_at > now() AND u.is_active""",
            (_token_hash(token),),
        ).fetchone()
        if u:
            conn.execute("UPDATE user_sessions SET last_seen_at=now() WHERE token_hash=%s", (_token_hash(token),))
            conn.commit()
    return dict(u) if u else None


def sign_out(token: str | None) -> None:
    if token:
        with connect() as conn:
            conn.execute("DELETE FROM user_sessions WHERE token_hash=%s", (_token_hash(token),))
            conn.commit()


def end_sessions(user_id: int) -> None:
    """Sign a user out everywhere (after a password change or deactivation)."""
    with connect() as conn:
        conn.execute("DELETE FROM user_sessions WHERE user_id=%s", (user_id,))
        conn.commit()


def set_password(user_id: int, password: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE users SET password_hash=%s WHERE id=%s", (hash_password(password), user_id))
        conn.commit()
    end_sessions(user_id)


# ---------------------------------------------------------------- what a request needs
# paths anyone may call; everything else needs a signed-in user
PUBLIC = {"/health", "/auth/login", "/auth/logout"}
# writes that need an admin (user and team management, settings, source syncs); other writes need an editor
ADMIN_PREFIXES = ("/portal/users", "/portal/teams", "/portal/settings", "/portal/admin/sync")


def needed_role(method: str, path: str) -> str | None:
    """The lowest role a request needs; None for a public path."""
    if path in PUBLIC or method == "OPTIONS":
        return None
    if method in ("GET", "HEAD"):
        return "viewer"
    if path in ("/portal/ask", "/auth/password") or path.startswith(
        "/portal/watches"
    ):  # a question, or one's own watch list
        return "viewer"
    return "admin" if path.startswith(ADMIN_PREFIXES) else "editor"


def allows(user: dict, role: str) -> bool:
    return RANK.get(user.get("role") or "viewer", 0) >= RANK[role]
