"""The recents endpoint, over a real Postgres.

`recent_collections` does not store season_url. It stores gender, year and
season, and season_url is a pure function of those three — so the endpoint has
to derive it.

That matters because a favourite's identity is
(user_id, season_url, collection_url, look_number). A look kept from the
recents drawer and the same look kept from the show list must produce the same
key. Without the derivation the drawer sends '' and the list sends a URL, the
two land as separate rows, and removing one leaves the other behind — silently,
with both paths reporting success.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

pytest.importorskip("flask", reason="flask not installed")

from auth import repository as repo  # noqa: E402
from flask import Flask  # noqa: E402

from backend.api import high_fashion_routes as routes  # noqa: E402
from backend.userdata import recents  # noqa: E402

pytestmark = pytest.mark.db


@pytest.fixture
def user(conn):
    return repo.create_user(conn, email="rec@example.com", password_hash="h", display_name="Rec")


@pytest.fixture
def client(conn, user, monkeypatch):
    """The real handler on the test's own transaction."""

    @contextmanager
    def transaction():
        yield conn

    monkeypatch.setattr(routes.db, "transaction", transaction)
    monkeypatch.setattr(routes, "current_user", lambda: user)

    app = Flask(__name__)
    routes.register_high_fashion_routes(app)
    app.config["TESTING"] = True
    return app.test_client()


def _record(conn, user, **kw):
    recents.record(
        conn,
        user_id=user.id,
        collection_id=kw.get("collection_id", "1234"),
        designer=kw.get("designer", "Gucci"),
        season=kw.get("season", "Fall / Winter"),
        year=kw.get("year", 2024),
        gender=kw.get("gender", "Women"),
        collection_url=kw.get("collection_url", "https://example.com/gucci-fw24"),
    )


def test_a_recent_carries_a_season_url(client, conn, user):
    _record(conn, user)

    body = client.get("/api/recents").get_json()
    row = body["recents"][0]

    assert row["season_url"], "a recent with gender, year and season must carry a season_url"


def test_the_drawer_and_the_list_key_a_look_identically(client, conn, user):
    """The invariant the derivation exists for."""
    _record(conn, user)

    from_drawer = client.get("/api/recents").get_json()["recents"][0]

    # What the show list sends for the same show.
    from_list = routes._index_row_to_dict(
        {
            "collection_id": "1234",
            "designer": "Gucci",
            "gender": "Women",
            "year": 2024,
            "season": "Fall / Winter",
        }
    )

    assert from_drawer["season_url"] == from_list["season_url"]


def test_a_sparse_recent_does_not_crash_the_endpoint(client, conn, user):
    """A show recorded before its metadata arrived has nulls in all three."""
    _record(conn, user, gender=None, year=None, season=None)

    response = client.get("/api/recents")

    assert response.status_code == 200
    assert "season_url" in response.get_json()["recents"][0]
