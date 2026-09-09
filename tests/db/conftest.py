"""Fixtures for tests that need a real Postgres.

We test against real Postgres rather than a mock or SQLite because the things
most likely to break are Postgres-specific: `citext` case-insensitive email
uniqueness, `timestamptz` comparison semantics, and `on delete cascade`. A mock
would pass while production failed.

Point `TEST_DATABASE_URL` at any scratch database. Tests skip (not fail) when
none is reachable, so the unit suite still runs on a machine without Postgres.
"""

from __future__ import annotations

import os

import pytest

psycopg = pytest.importorskip("psycopg", reason="psycopg not installed")

from auth.migrate import apply_schema  # noqa: E402

DEFAULT_URL = "postgresql://postgres@127.0.0.1:55432/fashion_archive_test"
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", DEFAULT_URL)


@pytest.fixture(scope="session")
def schema_applied():
    """Create the schema once for the whole session."""
    try:
        with psycopg.connect(TEST_DATABASE_URL, connect_timeout=5) as conn:
            apply_schema(conn)
            conn.commit()
    except psycopg.OperationalError as exc:
        pytest.skip(f"no Postgres at {TEST_DATABASE_URL}: {exc}")
    return TEST_DATABASE_URL


@pytest.fixture
def conn(schema_applied):
    """A connection wrapped in a transaction that is always rolled back.

    Each test therefore starts from the same empty tables and cannot leak rows
    into its neighbours, without paying to recreate the schema per test.
    """
    connection = psycopg.connect(schema_applied)
    connection.autocommit = False
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()
