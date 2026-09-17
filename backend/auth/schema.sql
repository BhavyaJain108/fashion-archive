-- Auth schema. Applied idempotently on boot by migrate.py.
--
-- Every timestamp is timestamptz. The system this replaces wrote naive local
-- time into expires_at and compared it against SQLite's UTC CURRENT_TIMESTAMP,
-- so sessions expired wrong by the local UTC offset. Storing an instant rather
-- than a wall-clock reading makes that class of bug unrepresentable.

CREATE EXTENSION IF NOT EXISTS citext;

-- citext on email: 'Bhavya@x.com' and 'bhavya@x.com' must be one account,
-- otherwise a Google sign-in could not find the account an email signup made.
CREATE TABLE IF NOT EXISTS users (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email             citext UNIQUE NOT NULL,
    password_hash     text,
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

-- Sign-in moved to Google and Apple. Accounts made before that keep their row
-- (and a now-unused password hash); new ones have none.
ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL;
DROP TABLE IF EXISTS email_tokens;

-- One row per provider account. (provider, subject) is the provider's stable
-- id for a person; email can change on their side and is kept only for display.
CREATE TABLE IF NOT EXISTS oauth_identities (
    provider   text NOT NULL CHECK (provider IN ('google', 'apple')),
    subject    text NOT NULL,
    user_id    uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    email      citext,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (provider, subject)
);

CREATE INDEX IF NOT EXISTS idx_oauth_identities_user_id ON oauth_identities (user_id);

-- One row per sign-in in progress, deleted when the provider sends the user
-- back. Held here rather than in a cookie because Apple returns with a
-- cross-site POST, which does not carry SameSite=Lax cookies.
CREATE TABLE IF NOT EXISTS oauth_states (
    state_hash    bytea PRIMARY KEY,
    provider      text NOT NULL,
    nonce         text NOT NULL,
    code_verifier text,
    expires_at    timestamptz NOT NULL
);
