-- Auth schema. Applied idempotently on boot by migrate.py.
--
-- Every timestamp is timestamptz. The system this replaces wrote naive local
-- time into expires_at and compared it against SQLite's UTC CURRENT_TIMESTAMP,
-- so sessions expired wrong by the local UTC offset. Storing an instant rather
-- than a wall-clock reading makes that class of bug unrepresentable.

CREATE EXTENSION IF NOT EXISTS citext;

-- citext on email: 'Bhavya@x.com' and 'bhavya@x.com' must be one account,
-- otherwise password reset is ambiguous about which one it is resetting.
CREATE TABLE IF NOT EXISTS users (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email             citext UNIQUE NOT NULL,
    password_hash     text NOT NULL,
    display_name      text NOT NULL,
    email_verified_at timestamptz,
    created_at        timestamptz NOT NULL DEFAULT now(),
    last_login_at     timestamptz,
    is_active         boolean NOT NULL DEFAULT true
);

-- token_hash, never the token. A read of this table yields nothing replayable.
CREATE TABLE IF NOT EXISTS sessions (
    token_hash   bytea PRIMARY KEY,
    user_id      uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at   timestamptz NOT NULL DEFAULT now(),
    expires_at   timestamptz NOT NULL,
    last_used_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions (user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions (expires_at);

-- consumed_at enforces single use; the CHECK stops a verify link from being
-- redeemed as a password-reset link.
CREATE TABLE IF NOT EXISTS email_tokens (
    token_hash  bytea PRIMARY KEY,
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    purpose     text NOT NULL CHECK (purpose IN ('verify', 'reset')),
    created_at  timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz NOT NULL,
    consumed_at timestamptz
);

CREATE INDEX IF NOT EXISTS idx_email_tokens_user_id ON email_tokens (user_id);
