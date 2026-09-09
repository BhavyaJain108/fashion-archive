"""Tests for the auth repository — the only module allowed to write SQL.

Each test here targets a defect in the system this replaces:

- plaintext session tokens as the primary key (`user_system/models.py:150`)
- local-time `expires_at` compared against SQLite's UTC `CURRENT_TIMESTAMP`
  (`models.py:238` vs `models.py:277`)
- no case handling on usernames, so `Bhavya` and `bhavya` were two accounts
- email tokens that could be replayed indefinitely
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from auth import repository as repo
from auth.tokens import hash_token, new_token

pytestmark = pytest.mark.db


def make_user(conn, email="archivist@example.com", display_name="Archivist"):
    return repo.create_user(
        conn, email=email, password_hash="$argon2id$fake", display_name=display_name
    )


class TestCreateUser:
    def test_returns_user_with_generated_uuid(self, conn):
        user = make_user(conn)
        assert user.id is not None
        assert user.email == "archivist@example.com"
        assert user.display_name == "Archivist"

    def test_new_user_starts_unverified(self, conn):
        """Login must be refused until the address is proven reachable."""
        assert make_user(conn).email_verified_at is None

    def test_new_user_is_active(self, conn):
        assert make_user(conn).is_active is True

    def test_duplicate_email_is_rejected(self, conn):
        make_user(conn)
        with pytest.raises(repo.EmailAlreadyExists):
            make_user(conn)

    def test_duplicate_email_differing_only_by_case_is_rejected(self, conn):
        """citext. Otherwise Bhavya@x.com and bhavya@x.com are two accounts and
        password reset becomes ambiguous."""
        make_user(conn, email="Archivist@Example.com")
        with pytest.raises(repo.EmailAlreadyExists):
            make_user(conn, email="archivist@example.com")


class TestGetUser:
    def test_by_email_is_case_insensitive(self, conn):
        created = make_user(conn, email="Archivist@Example.com")
        found = repo.get_user_by_email(conn, "ARCHIVIST@EXAMPLE.COM")
        assert found is not None and found.id == created.id

    def test_by_email_returns_none_when_absent(self, conn):
        assert repo.get_user_by_email(conn, "nobody@example.com") is None

    def test_by_id_round_trips(self, conn):
        created = make_user(conn)
        assert repo.get_user_by_id(conn, created.id).email == created.email

    def test_inactive_user_is_not_returned(self, conn):
        user = make_user(conn)
        repo.deactivate_user(conn, user.id)
        assert repo.get_user_by_email(conn, user.email) is None


class TestEmailVerification:
    def test_mark_verified_sets_timestamp(self, conn):
        user = make_user(conn)
        repo.mark_email_verified(conn, user.id)
        assert repo.get_user_by_id(conn, user.id).email_verified_at is not None

    def test_verified_timestamp_is_timezone_aware(self, conn):
        """timestamptz throughout. The old system mixed naive local time with
        SQLite's UTC CURRENT_TIMESTAMP, so expiry was wrong by the UTC offset."""
        user = make_user(conn)
        repo.mark_email_verified(conn, user.id)
        assert repo.get_user_by_id(conn, user.id).email_verified_at.tzinfo is not None


class TestSessions:
    def test_session_lookup_returns_the_user(self, conn):
        user = make_user(conn)
        token = new_token()
        repo.create_session(conn, user_id=user.id, token=token, ttl=timedelta(days=30))
        assert repo.get_session_user(conn, token).id == user.id

    def test_plaintext_token_is_never_stored(self, conn):
        """A database read must not yield anything replayable as a session."""
        user = make_user(conn)
        token = new_token()
        repo.create_session(conn, user_id=user.id, token=token, ttl=timedelta(days=30))

        stored = conn.execute("SELECT token_hash FROM sessions").fetchall()
        assert len(stored) == 1
        assert bytes(stored[0][0]) == hash_token(token)
        assert token.encode() not in bytes(stored[0][0])

    def test_unknown_token_returns_none(self, conn):
        assert repo.get_session_user(conn, new_token()) is None

    def test_expired_session_returns_none(self, conn):
        user = make_user(conn)
        token = new_token()
        repo.create_session(conn, user_id=user.id, token=token, ttl=timedelta(seconds=-1))
        assert repo.get_session_user(conn, token) is None

    def test_delete_session_revokes_it(self, conn):
        user = make_user(conn)
        token = new_token()
        repo.create_session(conn, user_id=user.id, token=token, ttl=timedelta(days=30))
        repo.delete_session(conn, token)
        assert repo.get_session_user(conn, token) is None

    def test_delete_all_sessions_revokes_every_device(self, conn):
        """Password reset must not leave an attacker's existing session alive."""
        user = make_user(conn)
        tokens = [new_token() for _ in range(3)]
        for token in tokens:
            repo.create_session(conn, user_id=user.id, token=token, ttl=timedelta(days=30))

        repo.delete_all_sessions(conn, user.id)
        assert all(repo.get_session_user(conn, t) is None for t in tokens)

    def test_touch_session_extends_expiry(self, conn):
        """Rolling expiry is what keeps an active user logged in."""
        user = make_user(conn)
        token = new_token()
        repo.create_session(conn, user_id=user.id, token=token, ttl=timedelta(days=1))
        before = conn.execute("SELECT expires_at FROM sessions").fetchone()[0]

        repo.touch_session(conn, token, ttl=timedelta(days=30))
        after = conn.execute("SELECT expires_at FROM sessions").fetchone()[0]
        assert after > before

    def test_refresh_extends_a_stale_session(self, conn):
        """Rolling expiry: an active user is never logged out mid-use.

        Note Postgres now() is the *transaction* start time, so a refresh cannot
        be observed as "a bit later" inside one transaction. The session is put
        an hour from expiry instead, and the refresh must push it out to the
        full 30-day TTL.
        """
        user = make_user(conn)
        token = new_token()
        repo.create_session(conn, user_id=user.id, token=token, ttl=timedelta(days=30))
        conn.execute(
            "UPDATE sessions SET last_used_at = now() - interval '2 days', "
            "expires_at = now() + interval '1 hour'"
        )
        before = conn.execute("SELECT expires_at FROM sessions").fetchone()[0]

        repo.refresh_session_if_stale(
            conn, token, ttl=timedelta(days=30), refresh_after=timedelta(days=1)
        )
        after = conn.execute("SELECT expires_at FROM sessions").fetchone()[0]
        assert after > before

    def test_refresh_leaves_a_fresh_session_alone(self, conn):
        """Without this guard, a page firing ten API calls writes to the
        database ten times for no benefit."""
        user = make_user(conn)
        token = new_token()
        repo.create_session(conn, user_id=user.id, token=token, ttl=timedelta(days=30))
        conn.execute("UPDATE sessions SET expires_at = now() + interval '1 hour'")
        before = conn.execute("SELECT expires_at FROM sessions").fetchone()[0]

        repo.refresh_session_if_stale(
            conn, token, ttl=timedelta(days=30), refresh_after=timedelta(days=1)
        )
        after = conn.execute("SELECT expires_at FROM sessions").fetchone()[0]
        assert after == before

    def test_refresh_of_an_unknown_token_is_harmless(self, conn):
        repo.refresh_session_if_stale(
            conn, new_token(), ttl=timedelta(days=30), refresh_after=timedelta(days=1)
        )

    def test_deleting_a_user_deletes_their_sessions(self, conn):
        user = make_user(conn)
        token = new_token()
        repo.create_session(conn, user_id=user.id, token=token, ttl=timedelta(days=30))
        repo.delete_user(conn, user.id)
        assert conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0


class TestEmailTokens:
    def test_consume_returns_the_user(self, conn):
        user = make_user(conn)
        token = new_token()
        repo.create_email_token(
            conn, user_id=user.id, token=token, purpose="verify", ttl=timedelta(hours=24)
        )
        assert repo.consume_email_token(conn, token, purpose="verify") == user.id

    def test_plaintext_token_is_never_stored(self, conn):
        user = make_user(conn)
        token = new_token()
        repo.create_email_token(
            conn, user_id=user.id, token=token, purpose="verify", ttl=timedelta(hours=24)
        )
        stored = conn.execute("SELECT token_hash FROM email_tokens").fetchone()[0]
        assert bytes(stored) == hash_token(token)

    def test_token_cannot_be_used_twice(self, conn):
        """A verification link in an inbox is long-lived; single use limits the
        damage if that inbox is later compromised."""
        user = make_user(conn)
        token = new_token()
        repo.create_email_token(
            conn, user_id=user.id, token=token, purpose="verify", ttl=timedelta(hours=24)
        )
        assert repo.consume_email_token(conn, token, purpose="verify") == user.id
        assert repo.consume_email_token(conn, token, purpose="verify") is None

    def test_expired_token_is_rejected(self, conn):
        user = make_user(conn)
        token = new_token()
        repo.create_email_token(
            conn, user_id=user.id, token=token, purpose="verify", ttl=timedelta(seconds=-1)
        )
        assert repo.consume_email_token(conn, token, purpose="verify") is None

    def test_verify_token_cannot_be_used_as_a_reset_token(self, conn):
        """Otherwise a signup link doubles as a password-change link."""
        user = make_user(conn)
        token = new_token()
        repo.create_email_token(
            conn, user_id=user.id, token=token, purpose="verify", ttl=timedelta(hours=24)
        )
        assert repo.consume_email_token(conn, token, purpose="reset") is None

    def test_unknown_token_returns_none(self, conn):
        assert repo.consume_email_token(conn, new_token(), purpose="verify") is None

    def test_invalid_purpose_is_rejected_by_the_database(self, conn):
        """The CHECK constraint is the backstop if a caller ever bypasses the
        Purpose type — an unrecognised purpose must not become a usable token."""
        user = make_user(conn)
        with pytest.raises(psycopg.errors.CheckViolation):
            repo.create_email_token(
                conn,
                user_id=user.id,
                token=new_token(),
                purpose="something-else",
                ttl=timedelta(hours=1),
            )


class TestPasswordChange:
    def test_set_password_hash_replaces_it(self, conn):
        user = make_user(conn)
        repo.set_password_hash(conn, user.id, "$argon2id$new")
        assert repo.get_user_by_id(conn, user.id).password_hash == "$argon2id$new"


class TestLastLogin:
    def test_starts_null(self, conn):
        assert make_user(conn).last_login_at is None

    def test_update_sets_it(self, conn):
        user = make_user(conn)
        repo.update_last_login(conn, user.id)
        recorded = repo.get_user_by_id(conn, user.id).last_login_at
        assert recorded is not None
        assert abs((datetime.now(timezone.utc) - recorded).total_seconds()) < 60
