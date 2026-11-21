-- 0026: sign-in to the portal (regtrack/auth.py). A user signs in with email + password; the password is kept only as a
-- salted scrypt hash. A session is a random token handed to the browser in an HttpOnly cookie; only its sha256 is
-- stored here, so a copy of this table cannot be used to sign in. Roles stay those of users.role (viewer, editor, admin).
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS user_sessions (
    token_hash   CHAR(64)    PRIMARY KEY,
    user_id      INTEGER     NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at   TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS user_sessions_user ON user_sessions (user_id);
