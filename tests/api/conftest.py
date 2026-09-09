"""Fixtures for HTTP-level tests against the real Flask app.

These import `backend.app` itself rather than building a stripped-down test app.
That is the point: the thing worth testing is whether *this* application, with
every route it actually registers, refuses unauthenticated requests. A purpose
built test app would only prove that the hook works in isolation.

Environment must be set before the import, because `backend/app.py` wires
everything at module scope.
"""

from __future__ import annotations

import os

import pytest

psycopg = pytest.importorskip("psycopg", reason="psycopg not installed")

DEFAULT_URL = "postgresql://postgres@127.0.0.1:55432/fashion_archive_test"
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", DEFAULT_URL)

os.environ.setdefault("DATABASE_URL", TEST_DATABASE_URL)
os.environ.setdefault("APP_BASE_URL", "http://localhost:3000")
os.environ.setdefault("API_BASE_URL", "http://localhost:8081")
os.environ.pop("RESEND_API_KEY", None)  # never send real mail from a test


@pytest.fixture(scope="session")
def flask_app():
    try:
        with psycopg.connect(TEST_DATABASE_URL, connect_timeout=5) as probe:
            probe.execute("SELECT 1")
    except psycopg.OperationalError as exc:
        pytest.skip(f"no Postgres at {TEST_DATABASE_URL}: {exc}")

    from backend.app import app

    app.config.update(TESTING=True)
    return app


@pytest.fixture
def sender(flask_app):
    """Swap in a recording sender and hand it to the test."""
    from backend.auth.email import RecordingSender
    from backend.auth.service import AuthService

    recorder = RecordingSender()
    flask_app.extensions["auth_service"] = AuthService(
        sender=recorder,
        api_base_url="http://localhost:8081",
        app_base_url="http://localhost:3000",
    )
    return recorder


@pytest.fixture
def client(flask_app, sender):
    """A test client against an empty database."""
    from backend.auth import db as auth_db

    with auth_db.transaction() as conn:
        conn.execute("TRUNCATE users CASCADE")

    with flask_app.test_client() as test_client:
        yield test_client


def token_from(sender):
    """Extract a token the way a user would — out of the emailed link."""
    return sender.last.message.text.split("token=")[1].split()[0].strip()
