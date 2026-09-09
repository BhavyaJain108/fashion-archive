"""Tests for the connection pool and the transaction boundary.

The commit boundary is worth testing directly because it is invisible when it
works and silent when it does not: a transaction that commits on error leaves
half-written state, and one that never commits loses writes without an error.
Neither shows up in a repository test.
"""

from __future__ import annotations

import pytest
from auth import db as auth_db
from auth import repository as repo

pytestmark = pytest.mark.db


@pytest.fixture
def pool(schema_applied):
    """A pool against the test database, torn down after each test."""
    auth_db.close_pool()
    auth_db.init_pool(schema_applied, max_size=3)
    yield
    with auth_db.transaction() as conn:
        conn.execute("TRUNCATE users CASCADE")
    auth_db.close_pool()


class TestInitPool:
    def test_missing_url_raises_rather_than_deferring(self, monkeypatch):
        """Fail at boot, not on the first login in production."""
        auth_db.close_pool()
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(auth_db.DatabaseNotConfigured):
            auth_db.init_pool()

    def test_get_pool_before_init_raises(self):
        auth_db.close_pool()
        with pytest.raises(auth_db.DatabaseNotConfigured):
            auth_db.get_pool()

    def test_init_is_idempotent(self, pool):
        assert auth_db.init_pool() is auth_db.get_pool()

    def test_init_applies_the_schema(self, pool):
        with auth_db.transaction() as conn:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                ).fetchall()
            }
        assert {"users", "sessions", "email_tokens"} <= tables


class TestTransaction:
    def test_commits_on_success(self, pool):
        with auth_db.transaction() as conn:
            repo.create_user(
                conn, email="kept@example.com", password_hash="h", display_name="Kept"
            )

        with auth_db.transaction() as conn:
            assert repo.get_user_by_email(conn, "kept@example.com") is not None

    def test_rolls_back_on_exception(self, pool):
        """A failure partway through registration must leave no account behind,
        or the address is taken by a user who can never verify it."""
        with pytest.raises(RuntimeError):
            with auth_db.transaction() as conn:
                repo.create_user(
                    conn,
                    email="discarded@example.com",
                    password_hash="h",
                    display_name="Discarded",
                )
                raise RuntimeError("email provider failed")

        with auth_db.transaction() as conn:
            assert repo.get_user_by_email(conn, "discarded@example.com") is None

    def test_rolls_back_on_keyboard_interrupt(self, pool):
        """BaseException, not Exception — a shutdown signal mid-write must not
        commit a partial unit of work."""
        with pytest.raises(KeyboardInterrupt):
            with auth_db.transaction() as conn:
                repo.create_user(
                    conn, email="int@example.com", password_hash="h", display_name="Int"
                )
                raise KeyboardInterrupt

        with auth_db.transaction() as conn:
            assert repo.get_user_by_email(conn, "int@example.com") is None

    def test_connections_are_returned_to_the_pool(self, pool):
        """More sequential transactions than max_size: if connections leaked,
        this would exhaust the pool and block."""
        for _ in range(10):
            with auth_db.transaction() as conn:
                conn.execute("SELECT 1")
        assert auth_db.get_pool().max_size == 3
