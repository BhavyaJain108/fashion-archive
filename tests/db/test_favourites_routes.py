"""The favourites endpoints, over a real Postgres.

These exist because the interesting failures in this layer are not exceptions.
A `DELETE` keyed on three columns where the row is keyed on four succeeds and
reports success, having deleted the wrong row; an `ON CONFLICT` that names a
partial index without its predicate raises on every insert, which no amount of
fake-connection testing notices because the fake never infers an index. So the
handlers run here against the actual database, through the actual SQL.

The unit suite (`tests/unit/test_favourites_queries.py`) pins what the query
strings say. This pins what Postgres does with them.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

pytest.importorskip("flask", reason="flask not installed")

from auth import repository as repo  # noqa: E402
from flask import Flask  # noqa: E402

from backend.api import favorites_routes as routes  # noqa: E402

pytestmark = pytest.mark.db

SEASON = {"name": "Fall 2024", "url": "https://example.com/fall-2024", "link_text": "F24"}
COLLECTION = {"designer": "Balenciaga", "url": "https://example.com/balenciaga-f24"}


@pytest.fixture
def user(conn):
    return repo.create_user(conn, email="one@example.com", password_hash="h", display_name="One")


@pytest.fixture
def client(conn, user, monkeypatch):
    """The real handlers, on the test's own transaction.

    `db.transaction` and `current_user` are the only two things replaced: the
    routing, the request parsing, the normalisation and every query are the
    shipping ones.
    """

    @contextmanager
    def transaction():
        yield conn

    monkeypatch.setattr(routes.db, "transaction", transaction)
    monkeypatch.setattr(routes, "current_user", lambda: user)

    app = Flask(__name__)
    routes.register_favorites_routes(app)
    return app.test_client()


def rows(conn, kind=None):
    where = "" if kind is None else f" WHERE kind = '{kind}'"
    return conn.execute(f"SELECT count(*) FROM favourites{where}").fetchone()[0]


def save_look(client, number=12):
    return client.post(
        "/api/favourites",
        json={
            "season": SEASON,
            "collection": COLLECTION,
            "look": {"number": number, "total": 48},
            "image_path": f"/api/images/balenciaga/f24/look{number}.jpg",
        },
    )


def save_show(client):
    return client.post(
        "/api/favourites",
        json={
            "kind": "show",
            "season": SEASON,
            "collection": COLLECTION,
            "image_path": "/api/images/balenciaga/f24/look1.jpg",
        },
    )


def save_view(client, filters, name=None):
    body = {"kind": "view", "filters": filters}
    if name is not None:
        body["name"] = name
    return client.post("/api/favourites", json=body)


class TestALookIsUnchanged:
    """The frontend sends these requests today. Task 3 is what changes them."""

    def test_the_request_and_the_answer_are_what_they_were(self, client, conn):
        response = save_look(client)
        assert response.status_code == 200
        assert response.get_json() == {"success": True, "message": "Added to favourites"}
        assert rows(conn, "look") == 1

    def test_no_kind_in_the_body_still_means_a_look(self, client, conn):
        save_look(client)
        assert conn.execute("SELECT kind FROM favourites").fetchone()[0] == "look"

    def test_saving_twice_is_reported_not_raised(self, client):
        save_look(client)
        assert save_look(client).get_json() == {
            "success": False,
            "message": "Already in favourites",
        }

    def test_the_delete_body_is_what_it_was(self, client, conn):
        save_look(client)
        response = client.delete(
            "/api/favourites",
            json={
                "season_url": SEASON["url"],
                "collection_url": COLLECTION["url"],
                "look_number": 12,
            },
        )
        assert response.get_json() == {"success": True, "message": "Removed from favourites"}
        assert rows(conn) == 0

    def test_check_answers_the_one_key_it_always_did(self, client):
        save_look(client)
        body = {
            "season_url": SEASON["url"],
            "collection_url": COLLECTION["url"],
            "look_number": 12,
        }
        assert client.post("/api/favourites/check", json=body).get_json() == {
            "is_favourite": True
        }


class TestAShow:
    def test_a_show_is_saved_without_a_number(self, client, conn):
        assert save_show(client).get_json()["success"] is True
        assert conn.execute("SELECT kind, look_number FROM favourites").fetchone() == (
            "show",
            None,
        )

    def test_the_answer_says_which_kind_it_was(self, client):
        assert save_show(client).get_json()["kind"] == "show"

    def test_saving_the_same_show_twice_is_one_row(self, client, conn):
        """ON CONFLICT on a partial index: without the predicate this raises."""
        save_show(client)
        assert save_show(client).get_json()["success"] is False
        assert rows(conn, "show") == 1

    def test_a_show_lists_as_a_show(self, client):
        save_show(client)
        item = client.get("/api/favourites").get_json()["favourites"][0]
        assert item["kind"] == "show"
        assert item["look"] == {"number": None, "total": None}
        assert item["collection"]["designer"] == "Balenciaga"

    def test_check_and_delete_agree_about_a_show(self, client):
        save_show(client)
        body = {
            "kind": "show",
            "season_url": SEASON["url"],
            "collection_url": COLLECTION["url"],
        }
        assert client.post("/api/favourites/check", json=body).get_json()["is_favourite"]
        assert client.delete("/api/favourites", json=body).get_json()["success"] is True
        assert not client.post("/api/favourites/check", json=body).get_json()["is_favourite"]


class TestAShowAndItsLooksAreSeparate:
    """The failure this whole file exists for: a delete that takes the wrong
    row reports success, and nothing notices until the user does."""

    def test_deleting_the_show_leaves_the_look(self, client, conn):
        save_look(client)
        save_show(client)
        client.delete(
            "/api/favourites",
            json={
                "kind": "show",
                "season_url": SEASON["url"],
                "collection_url": COLLECTION["url"],
            },
        )
        assert rows(conn, "show") == 0
        assert rows(conn, "look") == 1

    def test_deleting_the_look_leaves_the_show(self, client, conn):
        save_look(client)
        save_show(client)
        client.delete(
            "/api/favourites",
            json={
                "season_url": SEASON["url"],
                "collection_url": COLLECTION["url"],
                "look_number": 12,
            },
        )
        assert rows(conn, "look") == 0
        assert rows(conn, "show") == 1

    def test_a_look_number_sent_with_a_show_delete_is_ignored(self, client, conn):
        """The page knows which look is open and may send it. A show is not at
        a position, and narrowing by one would delete nothing while saying it
        deleted something."""
        save_show(client)
        response = client.delete(
            "/api/favourites",
            json={
                "kind": "show",
                "season_url": SEASON["url"],
                "collection_url": COLLECTION["url"],
                "look_number": 12,
            },
        )
        assert response.get_json()["success"] is True
        assert rows(conn, "show") == 0

    def test_saving_a_show_does_not_report_the_look_as_a_duplicate(self, client, conn):
        save_look(client)
        assert save_show(client).get_json()["success"] is True
        assert rows(conn) == 2


class TestAView:
    def test_a_view_is_its_filters(self, client, conn):
        save_view(client, {"year": "1997", "city": "Paris"})
        stored = conn.execute("SELECT view_filters FROM favourites").fetchone()[0]
        assert stored == {"year": "1997", "city": "Paris"}

    def test_key_order_does_not_make_a_second_row(self, client, conn):
        """md5(view_filters::text) is the key, and jsonb renders canonically —
        but only if what is stored is the filter object and nothing else."""
        assert save_view(client, {"year": "1997", "city": "Paris"}).get_json()["success"]
        assert save_view(client, {"city": "Paris", "year": "1997"}).get_json()["success"] is False
        assert rows(conn, "view") == 1

    def test_junk_keys_cannot_make_a_second_row(self, client, conn):
        """Normalised server-side against FILTER_KEYS, so a client that sends a
        page number or a token alongside the filters saves the same view."""
        save_view(client, {"year": "1997", "city": "Paris"})
        noisy = {"city": "Paris", "year": "1997", "page": 3, "token": "abc", "season": ""}
        assert save_view(client, noisy).get_json()["success"] is False
        assert rows(conn, "view") == 1

    def test_a_number_and_its_text_are_the_same_view(self, client, conn):
        save_view(client, {"year": "1997"})
        assert save_view(client, {"year": 1997}).get_json()["success"] is False
        assert rows(conn, "view") == 1

    def test_different_filters_are_different_views(self, client, conn):
        save_view(client, {"city": "Paris"})
        save_view(client, {"city": "Milan"})
        assert rows(conn, "view") == 2

    def test_a_view_is_named_from_its_filters_when_unnamed(self, client):
        answer = save_view(client, {"year": "1997", "city": "Paris"}).get_json()
        assert answer["view"]["name"] == "1997 · Paris"

    def test_a_supplied_name_wins(self, client, conn):
        save_view(client, {"city": "Paris"}, name="The good one")
        assert conn.execute("SELECT view_name FROM favourites").fetchone()[0] == "The good one"

    def test_a_blank_name_falls_back_to_the_derived_one(self, client, conn):
        save_view(client, {"city": "Paris"}, name="   ")
        assert conn.execute("SELECT view_name FROM favourites").fetchone()[0] == "Paris"

    def test_a_name_is_not_an_identity(self, client, conn):
        """Two views called the same thing are two views."""
        save_view(client, {"city": "Paris"}, name="Mine")
        save_view(client, {"city": "Milan"}, name="Mine")
        assert rows(conn, "view") == 2

    def test_a_view_with_nothing_filtered_is_still_one_row(self, client, conn):
        assert save_view(client, {}).get_json()["view"]["name"] == "All of the archive"
        assert save_view(client, {"page": 2}).get_json()["success"] is False
        assert rows(conn, "view") == 1

    def test_a_view_lists_with_its_filters_and_name(self, client):
        save_view(client, {"city": "Paris"})
        item = client.get("/api/favourites").get_json()["favourites"][0]
        assert item["kind"] == "view"
        assert item["view"] == {"name": "Paris", "filters": {"city": "Paris"}}

    def test_a_view_is_removed_by_its_filters_in_any_order(self, client, conn):
        save_view(client, {"year": "1997", "city": "Paris"})
        response = client.delete(
            "/api/favourites",
            json={"kind": "view", "filters": {"city": "Paris", "year": "1997"}},
        )
        assert response.get_json()["success"] is True
        assert rows(conn, "view") == 0

    def test_check_finds_a_view_however_the_keys_are_ordered(self, client):
        save_view(client, {"year": "1997", "city": "Paris"})
        response = client.post(
            "/api/favourites/check",
            json={"kind": "view", "filters": {"city": "Paris", "year": "1997"}},
        )
        assert response.get_json() == {"is_favourite": True}

    def test_deleting_one_view_leaves_the_other(self, client, conn):
        save_view(client, {"city": "Paris"})
        save_view(client, {"city": "Milan"})
        client.delete("/api/favourites", json={"kind": "view", "filters": {"city": "Paris"}})
        assert conn.execute("SELECT view_filters FROM favourites").fetchone()[0] == {
            "city": "Milan"
        }

    def test_a_view_delete_does_not_touch_a_look(self, client, conn):
        save_look(client)
        save_view(client, {"city": "Paris"})
        client.delete("/api/favourites", json={"kind": "view", "filters": {"city": "Paris"}})
        assert rows(conn, "look") == 1


class TestAnUnknownKind:
    """No index covers it, so no delete finds it and nothing cleans it up. It
    must be refused at the door rather than stored."""

    @pytest.mark.parametrize("kind", ["folder", "Look", "collection", "looks", "show "])
    def test_saving_one_is_a_400_and_no_row(self, client, conn, kind):
        response = client.post("/api/favourites", json={"kind": kind, "filters": {}})
        assert response.status_code == 400
        assert response.get_json()["success"] is False
        assert rows(conn) == 0

    def test_deleting_one_is_a_400(self, client):
        response = client.delete("/api/favourites", json={"kind": "folder"})
        assert response.status_code == 400

    def test_checking_one_is_a_400(self, client):
        response = client.post("/api/favourites/check", json={"kind": "folder"})
        assert response.status_code == 400

    def test_listing_one_is_a_400(self, client):
        assert client.get("/api/favourites?kind=folder").status_code == 400

    def test_the_error_names_the_kinds_that_do_exist(self, client):
        body = client.post("/api/favourites", json={"kind": "folder"}).get_json()
        assert "look" in body["error"] and "show" in body["error"] and "view" in body["error"]


class TestListing:
    def test_all_three_kinds_come_back_tagged(self, client):
        save_look(client)
        save_show(client)
        save_view(client, {"city": "Paris"})
        kinds = {i["kind"] for i in client.get("/api/favourites").get_json()["favourites"]}
        assert kinds == {"look", "show", "view"}

    def test_every_kind_carries_every_key(self, client):
        save_look(client)
        save_show(client)
        save_view(client, {"city": "Paris"})
        shapes = [set(i) for i in client.get("/api/favourites").get_json()["favourites"]]
        assert shapes[0] == shapes[1] == shapes[2]

    def test_one_kind_can_be_asked_for(self, client):
        save_look(client)
        save_show(client)
        save_view(client, {"city": "Paris"})
        items = client.get("/api/favourites?kind=view").get_json()["favourites"]
        assert [i["kind"] for i in items] == ["view"]

    def test_the_stats_count_each_kind(self, client):
        save_look(client)
        save_show(client)
        save_view(client, {"city": "Paris"})
        stats = client.get("/api/favourites/stats").get_json()["stats"]
        assert (stats["looks"], stats["shows"], stats["views"]) == (1, 1, 1)
        assert stats["total_favourites"] == 3


class TestListingIsBounded:
    """`?limit=` on the listing endpoint.

    The archive page fetches the whole library on every mount. There is no
    default cap — the client keys its stars off these rows, so a row that did
    not arrive is a dark star over something the reader saved — but a caller
    that wants the newest few can say so, and a query string is somebody's
    input.
    """

    def _save(self, client, number):
        return client.post(
            "/api/favourites",
            json={
                "season": SEASON,
                "collection": COLLECTION,
                "look": {"number": number, "total": 48},
                "image_path": f"/api/images/b/{number}.jpg",
            },
        )

    def test_no_limit_returns_everything(self, client):
        for number in range(1, 5):
            self._save(client, number)

        body = client.get("/api/favourites").get_json()

        assert len(body["favourites"]) == 4

    def test_a_limit_returns_that_many(self, client):
        for number in range(1, 5):
            self._save(client, number)

        body = client.get("/api/favourites?limit=2").get_json()

        assert len(body["favourites"]) == 2

    def test_a_limit_that_is_not_a_number_is_no_limit(self, client):
        for number in range(1, 5):
            self._save(client, number)

        body = client.get("/api/favourites?limit=all").get_json()

        assert len(body["favourites"]) == 4
