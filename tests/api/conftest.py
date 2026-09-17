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
# No provider credentials: tests install a stub provider where they need one.
for _k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "APPLE_CLIENT_ID"):
    os.environ.pop(_k, None)


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
def client(flask_app):
    """A test client against an empty database."""
    from backend.auth import db as auth_db

    with auth_db.transaction() as conn:
        conn.execute("TRUNCATE users CASCADE")

    with flask_app.test_client() as test_client:
        yield test_client


def sign_in(client, email="user@example.test", *, display_name=None):
    """Put a real session cookie on the client.

    Sign-in goes through Google or Apple now, so a test cannot walk the flow
    without a provider. It creates the account and session directly instead —
    the same rows a callback would have written.
    """
    from backend.auth import db as auth_db
    from backend.auth import repository as repo
    from backend.auth.middleware import SESSION_COOKIE_NAME, SESSION_TTL
    from backend.auth.tokens import new_token

    with auth_db.transaction() as conn:
        user = repo.get_user_by_email(conn, email)
        if user is None:
            user = repo.create_user(
                conn, email=email, display_name=display_name or email.split("@")[0]
            )
            repo.mark_email_verified(conn, user.id)
        token = new_token()
        repo.create_session(conn, user_id=user.id, token=token, ttl=SESSION_TTL)

    client.set_cookie(SESSION_COOKIE_NAME, token, domain="localhost")
    return user
