"""Share links, over a real Postgres, through the real handlers."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

pytest.importorskip("flask", reason="flask not installed")

from auth import repository as repo  # noqa: E402
from flask import Flask  # noqa: E402

from backend.api import share_routes as routes  # noqa: E402
from backend.auth import ratelimit  # noqa: E402
from backend.userdata import albums  # noqa: E402

pytestmark = pytest.mark.db


@pytest.fixture
def user(conn):
    return repo.create_user(conn, email="share-a@example.com", password_hash="h", display_name="A")


@pytest.fixture
def other(conn):
    return repo.create_user(conn, email="share-b@example.com", password_hash="h", display_name="B")


@pytest.fixture
def app_for(conn, monkeypatch):
    @contextmanager
    def transaction():
        yield conn

    monkeypatch.setattr(routes.db, "transaction", transaction)
    monkeypatch.setattr(ratelimit.db, "transaction", transaction)

    def make(user):
        monkeypatch.setattr(routes, "current_user", lambda: user)
        monkeypatch.setattr(ratelimit, "current_user", lambda: user)
        app = Flask(__name__)
        routes.register_share_routes(app)
        app.config["TESTING"] = True
        return app.test_client()

    return make


def test_a_look_round_trips_and_a_revoked_token_is_a_404(app_for, user):
    c = app_for(user)
    r = c.post(
        "/api/share",
        json={
            "kind": "look",
            "target": {"image_path": "https://img/x.jpg", "look_number": 12, "designer": "Gucci"},
        },
    )
    assert r.status_code == 200
    token = r.get_json()["token"]
    assert len(token) >= 20

    public = c.get(f"/api/s/{token}").get_json()
    assert public["kind"] == "look"
    assert public["look"]["image_path"] == "https://img/x.jpg"
    assert "notes" not in public["look"]

    assert c.delete(f"/api/share/{token}").status_code == 200
    assert c.get(f"/api/s/{token}").status_code == 404
    assert c.get("/api/s/nope").status_code == 404


def test_someone_else_cannot_revoke_my_token(app_for, user, other):
    token = (
        app_for(user)
        .post("/api/share", json={"kind": "look", "target": {"image_path": "p", "look_number": 1}})
        .get_json()["token"]
    )
    assert app_for(other).delete(f"/api/share/{token}").status_code == 404
    assert app_for(user).get(f"/api/s/{token}").status_code == 200


def test_an_album_share_hides_notes_and_ids(app_for, user, conn):
    album = albums.create(conn, user_id=user.id, name="Resort")
    c = app_for(user)
    token = c.post(
        "/api/share", json={"kind": "album", "target": {"album_id": album["id"]}}
    ).get_json()["token"]
    public = c.get(f"/api/s/{token}").get_json()
    assert public["kind"] == "album"
    assert public["album"]["name"] == "Resort"
    assert "id" not in public["album"]


def test_the_public_route_rate_limits(app_for, user, conn):
    c = app_for(None)  # anonymous
    for _ in range(60):
        assert c.get("/api/s/nope").status_code == 404
    r = c.get("/api/s/nope")
    assert r.status_code == 429
    assert r.headers["Retry-After"]
