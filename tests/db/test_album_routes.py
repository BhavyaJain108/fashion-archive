"""The album endpoints, over a real Postgres.

Two properties are what this file exists for, and neither is visible in a
handler read on its own.

**404, not 403, for somebody else's album.** An album id is a small integer a
stranger can type. Answering 403 would be the honest description of what
happened and the wrong thing to say: it confirms the row exists, which is a
fact about another person's library. So every endpoint that takes an album id
is asked for one belonging to a second real user here — not one id, every
endpoint — and has to answer the same 404 it answers for an id nobody owns.
`album_items` has no `user_id` column of its own; isolation is a JOIN through
`albums` and `favourites` on every query, and a JOIN is exactly the thing that
can be right in seven queries and missing from the eighth.

**Save-then-add is one transaction.** An album holds favourites, so adding
something unsaved saves it first — two writes that must both land or neither.
The fake `db.transaction` below therefore uses a real savepoint rather than
just yielding the connection, so a handler that raises rolls back here the way
it would in production. The tests that force the second half to fail assert
that no favourite was left behind, which is the half that would otherwise be
invisible: a stray membership row renders a broken tile, a stray favourite is
silently in the user's library forever.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

pytest.importorskip("flask", reason="flask not installed")

from auth import repository as repo  # noqa: E402
from flask import Flask  # noqa: E402
from userdata import favourites as fav  # noqa: E402

from backend.api import album_routes as routes  # noqa: E402

pytestmark = pytest.mark.db

SEASON = {"name": "Fall 2024", "url": "https://example.com/fall-2024", "link_text": "F24"}
COLLECTION = {"designer": "Balenciaga", "url": "https://example.com/balenciaga-f24"}


# Emails nothing else in the suite uses. `tests/api/conftest.py` truncates
# `users` on setup and leaves its last signed-up user committed; it is
# `tests/db/test_db.py` that happens to clear it, and this module sorts ahead of
# that one. Rather than depend on that ordering it just does not collide with
# anybody — the same workaround `tests/db/test_albums.py` took.
@pytest.fixture
def user(conn):
    return repo.create_user(
        conn, email="album-routes-one@example.com", password_hash="h", display_name="One"
    )


@pytest.fixture
def other_user(conn):
    return repo.create_user(
        conn, email="album-routes-two@example.com", password_hash="h", display_name="Two"
    )


@pytest.fixture
def acting(user):
    """Who the handlers think is logged in. Mutable, so one test can be two
    people without building two apps."""
    return {"user": user}


@pytest.fixture
def client(conn, acting, monkeypatch):
    """The real handlers, on the test's own transaction.

    `db.transaction` and `current_user` are the only two things replaced. The
    routing, the body parsing, the ownership checks and every query are the
    shipping ones.

    The fake transaction opens a savepoint rather than handing the connection
    over bare: `backend.auth.db.transaction` commits on the way out and rolls
    back on any exception, and the save-then-add rule is a claim about exactly
    that. A fake that only yielded would report a rollback that never happened.
    """

    @contextmanager
    def transaction():
        with conn.transaction():
            yield conn

    monkeypatch.setattr(routes.db, "transaction", transaction)
    monkeypatch.setattr(routes, "current_user", lambda: acting["user"])

    app = Flask(__name__)
    routes.register_album_routes(app)
    return app.test_client()


def as_user(acting, who):
    """Switch which user the next request is made by."""
    acting["user"] = who


# ---------------------------------------------------------------- helpers ---


def look_body(number=12, designer="Balenciaga"):
    return {
        "season": SEASON,
        "collection": {"designer": designer, "url": f"https://example.com/{designer.lower()}-f24"},
        "look": {"number": number, "total": 48},
        "image_path": f"/api/images/{designer}/{number}.jpg",
    }


def save_for(conn, who, number=1, designer="Balenciaga"):
    """Save a look for a user straight through the data layer, and return its
    id — setup, not the thing under test."""
    body = look_body(number, designer)
    favourite_id, _ = fav.add_returning_id(
        conn,
        user_id=who.id,
        season=body["season"],
        collection=body["collection"],
        look=body["look"],
        image_path=body["image_path"],
    )
    return favourite_id


def make_album(conn, who, name):
    return conn.execute(
        "INSERT INTO albums (user_id, name) VALUES (%s, %s) RETURNING id", (who.id, name)
    ).fetchone()[0]


def put_in(conn, album_id, favourite_id, sort_index=1024):
    conn.execute(
        "INSERT INTO album_items (album_id, favourite_id, sort_index) VALUES (%s, %s, %s)",
        (album_id, favourite_id, sort_index),
    )


def member_ids(conn, album_id):
    return [
        row[0]
        for row in conn.execute(
            """
            SELECT favourite_id FROM album_items
             WHERE album_id = %s ORDER BY sort_index, favourite_id
            """,
            (album_id,),
        ).fetchall()
    ]


# Counts are scoped to one user, never to the whole table. Other modules in the
# suite commit rows that outlive them — `tests/api/conftest.py` leaves its last
# signed-up user behind, and what that user saved comes with it — so a bare
# `count(*)` here passes alone and fails in a full run. Per-user is also the
# question these tests are actually asking.
def favourite_count(conn, who):
    return conn.execute("SELECT count(*) FROM favourites WHERE user_id = %s", (who.id,)).fetchone()[
        0
    ]


def album_count(conn, who):
    return conn.execute("SELECT count(*) FROM albums WHERE user_id = %s", (who.id,)).fetchone()[0]


# ------------------------------------------------------------- the basics ---


class TestCreatingAnAlbum:
    def test_a_new_album_comes_back_with_its_id(self, client, conn, user):
        response = client.post("/api/albums", json={"name": "Resort"})
        assert response.status_code == 201
        album = response.get_json()["album"]
        assert album["name"] == "Resort"
        assert album["layout_mode"] == "grid"
        assert album["sort_by"] == "added"
        assert isinstance(album["id"], int)
        assert album_count(conn, user) == 1

    def test_the_name_is_trimmed_not_rejected(self, client, conn, user):
        client.post("/api/albums", json={"name": "  Resort  "})
        assert (
            conn.execute("SELECT name FROM albums WHERE user_id = %s", (user.id,)).fetchone()[0]
            == "Resort"
        )

    def test_a_blank_name_is_a_400_and_no_row(self, client, conn, user):
        response = client.post("/api/albums", json={"name": "   "})
        assert response.status_code == 400
        assert album_count(conn, user) == 0

    def test_a_missing_name_is_a_400(self, client):
        assert client.post("/api/albums", json={}).status_code == 400

    def test_the_same_name_twice_is_a_409(self, client, conn, user):
        client.post("/api/albums", json={"name": "Resort"})
        response = client.post("/api/albums", json={"name": "resort"})
        assert response.status_code == 409
        assert response.get_json()["success"] is False
        assert album_count(conn, user) == 1

    def test_a_409_leaves_the_connection_usable(self, client):
        """`create` inserts ON CONFLICT DO NOTHING so a duplicate does not abort
        the transaction on its way to being a 409. If it did, the next request
        on this connection would fail rather than answer."""
        client.post("/api/albums", json={"name": "Resort"})
        client.post("/api/albums", json={"name": "Resort"})
        assert client.post("/api/albums", json={"name": "Other"}).status_code == 201

    def test_an_option_the_table_forbids_is_a_400(self, client, conn, user):
        response = client.post("/api/albums", json={"name": "X", "layout_mode": "freeform"})
        assert response.status_code == 400
        assert album_count(conn, user) == 0

    def test_an_unknown_sort_is_a_400(self, client):
        assert client.post("/api/albums", json={"name": "X", "sort_by": "price"}).status_code == 400

    def test_options_are_stored_when_they_are_allowed(self, client):
        album = client.post(
            "/api/albums", json={"name": "X", "layout_mode": "canvas", "sort_by": "designer"}
        ).get_json()["album"]
        assert (album["layout_mode"], album["sort_by"]) == ("canvas", "designer")


class TestListingAlbums:
    def test_an_empty_shelf(self, client):
        assert client.get("/api/albums").get_json() == {"albums": [], "count": 0}

    def test_each_album_carries_a_count_and_a_cover(self, client, conn, user):
        album_id = client.post("/api/albums", json={"name": "Resort"}).get_json()["album"]["id"]
        first = save_for(conn, user, number=1)
        second = save_for(conn, user, number=2)
        put_in(conn, album_id, first, 1024)
        put_in(conn, album_id, second, 2048)

        listed = client.get("/api/albums").get_json()["albums"]

        assert listed[0]["item_count"] == 2
        assert listed[0]["cover_image_path"] == "/api/images/Balenciaga/1.jpg"

    def test_an_album_of_views_has_no_cover_rather_than_a_broken_one(self, client, conn, user):
        album_id = client.post("/api/albums", json={"name": "Filters"}).get_json()["album"]["id"]
        view_id, _ = fav.add_returning_id(
            conn, user_id=user.id, kind="view", view_filters={"city": "Paris"}, view_name="Paris"
        )
        put_in(conn, album_id, view_id)

        listed = client.get("/api/albums").get_json()["albums"]

        assert listed[0]["item_count"] == 1
        assert listed[0]["cover_image_path"] is None

    def test_newest_first(self, client):
        client.post("/api/albums", json={"name": "One"})
        client.post("/api/albums", json={"name": "Two"})
        names = [a["name"] for a in client.get("/api/albums").get_json()["albums"]]
        assert names == ["Two", "One"]


class TestOneAlbum:
    def test_it_comes_back_with_its_items(self, client, conn, user):
        album_id = client.post("/api/albums", json={"name": "Resort"}).get_json()["album"]["id"]
        favourite_id = save_for(conn, user, number=4)
        put_in(conn, album_id, favourite_id)

        body = client.get(f"/api/albums/{album_id}").get_json()

        assert body["album"]["name"] == "Resort"
        assert [i["id"] for i in body["items"]] == [favourite_id]
        assert body["items"][0]["look"]["number"] == 4
        assert body["items"][0]["sort_index"] == 1024

    def test_an_item_is_a_favourite_plus_its_place(self, client, conn, user):
        album_id = make_album(conn, user, "Resort")
        put_in(conn, album_id, save_for(conn, user))
        item = client.get(f"/api/albums/{album_id}").get_json()["items"][0]
        assert item["collection"]["designer"] == "Balenciaga"
        assert item["placement"] == {"x": None, "y": None, "w": None, "z": None}

    def test_an_album_id_that_does_not_exist_is_a_404(self, client):
        assert client.get("/api/albums/999999").status_code == 404

    def test_a_sort_the_column_forbids_is_a_400(self, client, conn, user):
        album_id = make_album(conn, user, "Resort")
        assert client.get(f"/api/albums/{album_id}?sort_by=price").status_code == 400

    def test_a_sort_can_be_asked_for_without_storing_it(self, client, conn, user):
        album_id = make_album(conn, user, "Resort")
        put_in(conn, album_id, save_for(conn, user, 1, "Balenciaga"), 1024)
        put_in(conn, album_id, save_for(conn, user, 1, "Alaia"), 2048)

        by_designer = client.get(f"/api/albums/{album_id}?sort_by=designer").get_json()

        assert [i["collection"]["designer"] for i in by_designer["items"]] == [
            "Alaia",
            "Balenciaga",
        ]
        assert by_designer["album"]["sort_by"] == "added"


class TestRenamingAndOptions:
    def test_a_rename_sticks(self, client, conn, user):
        album_id = client.post("/api/albums", json={"name": "Resort"}).get_json()["album"]["id"]
        response = client.patch(f"/api/albums/{album_id}", json={"name": "Resort 2025"})
        assert response.get_json()["album"]["name"] == "Resort 2025"
        assert (
            conn.execute("SELECT name FROM albums WHERE user_id = %s", (user.id,)).fetchone()[0]
            == "Resort 2025"
        )

    def test_renaming_onto_another_album_is_a_409(self, client, conn):
        client.post("/api/albums", json={"name": "Resort"})
        second = client.post("/api/albums", json={"name": "Pre-Fall"}).get_json()["album"]["id"]
        response = client.patch(f"/api/albums/{second}", json={"name": "resort"})
        assert response.status_code == 409
        assert (
            conn.execute("SELECT name FROM albums WHERE id = %s", (second,)).fetchone()[0]
            == "Pre-Fall"
        )

    def test_a_blank_rename_is_a_400(self, client, conn, user):
        album_id = client.post("/api/albums", json={"name": "Resort"}).get_json()["album"]["id"]
        assert client.patch(f"/api/albums/{album_id}", json={"name": " "}).status_code == 400
        assert (
            conn.execute("SELECT name FROM albums WHERE user_id = %s", (user.id,)).fetchone()[0]
            == "Resort"
        )

    def test_one_option_does_not_reset_the_other(self, client, conn):
        album_id = client.post(
            "/api/albums", json={"name": "Resort", "layout_mode": "canvas"}
        ).get_json()["album"]["id"]

        body = client.patch(f"/api/albums/{album_id}", json={"sort_by": "season"}).get_json()

        assert body["album"]["layout_mode"] == "canvas"
        assert body["album"]["sort_by"] == "season"

    def test_a_forbidden_option_is_a_400_and_changes_nothing(self, client, conn, user):
        album_id = client.post("/api/albums", json={"name": "Resort"}).get_json()["album"]["id"]
        assert client.patch(f"/api/albums/{album_id}", json={"sort_by": "price"}).status_code == 400
        assert (
            conn.execute("SELECT sort_by FROM albums WHERE user_id = %s", (user.id,)).fetchone()[0]
            == "added"
        )

    def test_an_unknown_album_is_a_404(self, client):
        assert client.patch("/api/albums/999999", json={"name": "X"}).status_code == 404


class TestDeletingAnAlbum:
    def test_the_album_goes(self, client, conn, user):
        album_id = client.post("/api/albums", json={"name": "Resort"}).get_json()["album"]["id"]
        assert client.delete(f"/api/albums/{album_id}").get_json()["success"] is True
        assert album_count(conn, user) == 0

    def test_the_favourites_in_it_stay_saved(self, client, conn, user):
        """The opposite mistake loses saved work with no way back."""
        album_id = make_album(conn, user, "Resort")
        put_in(conn, album_id, save_for(conn, user))

        client.delete(f"/api/albums/{album_id}")

        assert favourite_count(conn, user) == 1
        assert member_ids(conn, album_id) == []

    def test_an_unknown_album_is_a_404(self, client):
        assert client.delete("/api/albums/999999").status_code == 404


# ----------------------------------------------------- adding and removing ---


class TestAddingSomethingAlreadySaved:
    def test_a_favourite_id_goes_in(self, client, conn, user):
        album_id = make_album(conn, user, "Resort")
        favourite_id = save_for(conn, user)

        body = client.post(
            f"/api/albums/{album_id}/items", json={"favourite_id": favourite_id}
        ).get_json()

        assert body == {
            "success": True,
            "favourite_id": favourite_id,
            "saved": False,
            "added": True,
            "message": "Added to album",
        }
        assert member_ids(conn, album_id) == [favourite_id]

    def test_adding_it_twice_is_reported_not_an_error(self, client, conn, user):
        album_id = make_album(conn, user, "Resort")
        favourite_id = save_for(conn, user)
        client.post(f"/api/albums/{album_id}/items", json={"favourite_id": favourite_id})

        body = client.post(
            f"/api/albums/{album_id}/items", json={"favourite_id": favourite_id}
        ).get_json()

        assert (body["success"], body["added"]) == (True, False)
        assert member_ids(conn, album_id) == [favourite_id]

    def test_a_favourite_id_that_does_not_exist_is_a_404(self, client, conn, user):
        album_id = make_album(conn, user, "Resort")
        assert (
            client.post(f"/api/albums/{album_id}/items", json={"favourite_id": 999999}).status_code
            == 404
        )

    def test_a_favourite_id_that_is_not_a_number_is_a_400(self, client, conn, user):
        album_id = make_album(conn, user, "Resort")
        response = client.post(f"/api/albums/{album_id}/items", json={"favourite_id": "12"})
        assert response.status_code == 400


class TestAddingSomethingNotYetSaved:
    """The spec's rule: an album holds favourites, so it is saved first."""

    def test_a_look_is_saved_and_added_in_one_request(self, client, conn, user):
        album_id = make_album(conn, user, "Resort")

        body = client.post(f"/api/albums/{album_id}/items", json=look_body(12)).get_json()

        assert body["success"] is True
        assert body["saved"] is True
        assert body["added"] is True
        assert favourite_count(conn, user) == 1
        assert member_ids(conn, album_id) == [body["favourite_id"]]

    def test_something_already_saved_is_not_saved_twice(self, client, conn, user):
        album_id = make_album(conn, user, "Resort")
        favourite_id = save_for(conn, user, number=12)

        body = client.post(f"/api/albums/{album_id}/items", json=look_body(12)).get_json()

        assert body["saved"] is False
        assert body["favourite_id"] == favourite_id
        assert favourite_count(conn, user) == 1

    def test_the_row_it_makes_is_the_row_a_plain_save_would_have_made(self, client, conn, user):
        """Both endpoints read the body through `favourite_target`. If they did
        not, starring the look afterwards would write a second copy."""
        album_id = make_album(conn, user, "Resort")
        client.post(f"/api/albums/{album_id}/items", json=look_body(12))

        assert fav.exists(
            conn,
            user_id=user.id,
            season_url=SEASON["url"],
            collection_url=COLLECTION["url"],
            look_number=12,
        )

    def test_a_show_can_be_saved_into_an_album(self, client, conn, user):
        album_id = make_album(conn, user, "Resort")
        body = client.post(
            f"/api/albums/{album_id}/items",
            json={"kind": "show", "season": SEASON, "collection": COLLECTION},
        ).get_json()
        assert body["saved"] is True
        assert (
            conn.execute("SELECT kind FROM favourites WHERE user_id = %s", (user.id,)).fetchone()[0]
            == "show"
        )

    def test_a_view_can_be_saved_into_an_album(self, client, conn, user):
        album_id = make_album(conn, user, "Resort")
        body = client.post(
            f"/api/albums/{album_id}/items",
            json={"kind": "view", "filters": {"city": "Paris", "year": "1997"}},
        ).get_json()
        assert body["saved"] is True
        stored = conn.execute(
            "SELECT view_filters, view_name FROM favourites WHERE user_id = %s", (user.id,)
        ).fetchone()
        assert stored == ({"city": "Paris", "year": "1997"}, "1997 · Paris")

    def test_a_kind_no_index_covers_is_a_400_and_no_rows(self, client, conn, user):
        album_id = make_album(conn, user, "Resort")
        response = client.post(f"/api/albums/{album_id}/items", json={"kind": "folder"})
        assert response.status_code == 400
        assert favourite_count(conn, user) == 0
        assert member_ids(conn, album_id) == []

    def test_appending_puts_the_new_one_last(self, client, conn, user):
        album_id = make_album(conn, user, "Resort")
        first = client.post(f"/api/albums/{album_id}/items", json=look_body(1)).get_json()
        second = client.post(f"/api/albums/{album_id}/items", json=look_body(2)).get_json()
        assert member_ids(conn, album_id) == [first["favourite_id"], second["favourite_id"]]


class TestSaveThenAddIsOneTransaction:
    """Force each half to fail and check nothing of the other half survives.

    The fake `db.transaction` in this module opens a savepoint, so these assert
    the real rollback rather than a fake one.
    """

    def test_a_failed_membership_insert_leaves_no_favourite(self, client, conn, user, monkeypatch):
        album_id = make_album(conn, user, "Resort")

        def boom(*args, **kwargs):
            raise RuntimeError("membership insert failed")

        monkeypatch.setattr(routes.albums, "add_item", boom)

        response = client.post(f"/api/albums/{album_id}/items", json=look_body(12))

        assert response.status_code == 500
        assert favourite_count(conn, user) == 0
        assert member_ids(conn, album_id) == []

    def test_a_save_that_cannot_be_found_again_leaves_no_favourite(
        self, client, conn, user, monkeypatch
    ):
        """The one branch the handler cannot answer: the insert landed and the
        lookup disagreed about the key. It raises rather than returning a 400,
        because a 400 would commit the favourite nobody asked for."""
        album_id = make_album(conn, user, "Resort")
        monkeypatch.setattr(routes.favourites, "find_id", lambda *a, **k: None)

        response = client.post(f"/api/albums/{album_id}/items", json=look_body(12))

        assert response.status_code == 500
        assert favourite_count(conn, user) == 0
        assert member_ids(conn, album_id) == []

    def test_a_failed_save_leaves_no_membership_row(self, client, conn, user, monkeypatch):
        album_id = make_album(conn, user, "Resort")

        def boom(*args, **kwargs):
            raise RuntimeError("save failed")

        monkeypatch.setattr(routes.favourites, "add_returning_id", boom)

        response = client.post(f"/api/albums/{album_id}/items", json=look_body(12))

        assert response.status_code == 500
        assert favourite_count(conn, user) == 0
        assert member_ids(conn, album_id) == []

    def test_a_404_album_is_answered_before_anything_is_saved(self, client, conn, user):
        """The ownership check comes first, so a 404 cannot be preceded by a
        save the user never asked for."""
        assert client.post("/api/albums/999999/items", json=look_body(12)).status_code == 404
        assert favourite_count(conn, user) == 0


class TestRemovingFromAnAlbum:
    def test_it_comes_out_of_the_album(self, client, conn, user):
        album_id = make_album(conn, user, "Resort")
        favourite_id = save_for(conn, user)
        put_in(conn, album_id, favourite_id)

        body = client.delete(f"/api/albums/{album_id}/items/{favourite_id}").get_json()

        assert body["success"] is True
        assert member_ids(conn, album_id) == []

    def test_it_stays_saved(self, client, conn, user):
        album_id = make_album(conn, user, "Resort")
        favourite_id = save_for(conn, user)
        put_in(conn, album_id, favourite_id)

        client.delete(f"/api/albums/{album_id}/items/{favourite_id}")

        assert favourite_count(conn, user) == 1

    def test_removing_something_that_is_not_in_it_is_reported(self, client, conn, user):
        album_id = make_album(conn, user, "Resort")
        favourite_id = save_for(conn, user)
        body = client.delete(f"/api/albums/{album_id}/items/{favourite_id}").get_json()
        assert body["success"] is False

    def test_an_unknown_album_is_a_404(self, client, conn, user):
        favourite_id = save_for(conn, user)
        assert client.delete(f"/api/albums/999999/items/{favourite_id}").status_code == 404

    def test_removing_from_one_album_leaves_the_other(self, client, conn, user):
        keep = make_album(conn, user, "Keep")
        drop = make_album(conn, user, "Drop")
        favourite_id = save_for(conn, user)
        put_in(conn, keep, favourite_id)
        put_in(conn, drop, favourite_id)

        client.delete(f"/api/albums/{drop}/items/{favourite_id}")

        assert member_ids(conn, keep) == [favourite_id]


# ------------------------------------------------------------- reordering ---


class TestReordering:
    def one_album_of_three(self, conn, user):
        album_id = make_album(conn, user, "Resort")
        ids = [save_for(conn, user, number=n) for n in (1, 2, 3)]
        for position, favourite_id in enumerate(ids, start=1):
            put_in(conn, album_id, favourite_id, 1024 * position)
        return album_id, ids

    def test_a_whole_order_is_one_request(self, client, conn, user):
        album_id, ids = self.one_album_of_three(conn, user)
        wanted = [ids[2], ids[0], ids[1]]

        body = client.put(
            f"/api/albums/{album_id}/order", json={"favourite_ids": wanted}
        ).get_json()

        assert body == {"success": True, "reordered": 3}
        assert member_ids(conn, album_id) == wanted

    def test_the_new_order_is_what_the_album_lists(self, client, conn, user):
        album_id, ids = self.one_album_of_three(conn, user)
        wanted = [ids[1], ids[2], ids[0]]

        client.put(f"/api/albums/{album_id}/order", json={"favourite_ids": wanted})

        listed = client.get(f"/api/albums/{album_id}").get_json()["items"]
        assert [i["id"] for i in listed] == wanted

    def test_ids_that_are_not_in_the_album_move_nothing(self, client, conn, user):
        album_id, ids = self.one_album_of_three(conn, user)
        body = client.put(
            f"/api/albums/{album_id}/order", json={"favourite_ids": [999999, ids[0]]}
        ).get_json()
        assert body["reordered"] == 1

    def test_a_body_without_a_list_is_a_400(self, client, conn, user):
        album_id, _ = self.one_album_of_three(conn, user)
        assert client.put(f"/api/albums/{album_id}/order", json={}).status_code == 400

    def test_a_list_of_something_else_is_a_400(self, client, conn, user):
        album_id, ids = self.one_album_of_three(conn, user)
        response = client.put(
            f"/api/albums/{album_id}/order", json={"favourite_ids": [str(ids[0])]}
        )
        assert response.status_code == 400
        assert member_ids(conn, album_id) == ids

    def test_an_unknown_album_is_a_404(self, client):
        assert client.put("/api/albums/999999/order", json={"favourite_ids": []}).status_code == 404


# --------------------------------------------------------------- isolation ---


class TestSomebodyElsesAlbumIsA404:
    """Every endpoint that takes an album id, against a second real user.

    `album_items` has no `user_id`; isolation is a predicate on each query, so
    one endpoint getting it wrong is not caught by another getting it right.
    404 rather than 403 throughout: a 403 confirms the row is there, which is
    a fact about somebody else's library.
    """

    @pytest.fixture
    def theirs(self, conn, other_user):
        """An album belonging to the other user, with one favourite in it."""
        album_id = make_album(conn, other_user, "Theirs")
        favourite_id = save_for(conn, other_user, number=7)
        put_in(conn, album_id, favourite_id)
        return album_id, favourite_id

    def test_reading_it(self, client, theirs):
        album_id, _ = theirs
        response = client.get(f"/api/albums/{album_id}")
        assert response.status_code == 404
        assert "Theirs" not in response.get_data(as_text=True)

    def test_renaming_it(self, client, conn, theirs):
        album_id, _ = theirs
        assert client.patch(f"/api/albums/{album_id}", json={"name": "Mine"}).status_code == 404
        assert (
            conn.execute("SELECT name FROM albums WHERE id = %s", (album_id,)).fetchone()[0]
            == "Theirs"
        )

    def test_deleting_it(self, client, conn, theirs):
        album_id, _ = theirs
        assert client.delete(f"/api/albums/{album_id}").status_code == 404
        assert (
            conn.execute("SELECT count(*) FROM albums WHERE id = %s", (album_id,)).fetchone()[0]
            == 1
        )

    def test_adding_a_saved_favourite_to_it(self, client, conn, theirs, user):
        album_id, _ = theirs
        mine = save_for(conn, user, number=3)
        response = client.post(f"/api/albums/{album_id}/items", json={"favourite_id": mine})
        assert response.status_code == 404
        assert mine not in member_ids(conn, album_id)

    def test_saving_something_into_it(self, client, conn, theirs, user):
        """The 404 must come before the save, or a stranger's request leaves a
        favourite behind in their own library."""
        album_id, _ = theirs
        before = favourite_count(conn, user)
        assert client.post(f"/api/albums/{album_id}/items", json=look_body(12)).status_code == 404
        assert favourite_count(conn, user) == before
        assert len(member_ids(conn, album_id)) == 1

    def test_removing_something_from_it(self, client, conn, theirs):
        album_id, favourite_id = theirs
        response = client.delete(f"/api/albums/{album_id}/items/{favourite_id}")
        assert response.status_code == 404
        assert member_ids(conn, album_id) == [favourite_id]

    def test_reordering_it(self, client, conn, theirs, other_user):
        album_id, first = theirs
        second = save_for(conn, other_user, number=8)
        put_in(conn, album_id, second, 2048)

        response = client.put(
            f"/api/albums/{album_id}/order", json={"favourite_ids": [second, first]}
        )

        assert response.status_code == 404
        assert member_ids(conn, album_id) == [first, second]

    def test_it_is_not_in_my_listing(self, client, theirs):
        assert client.get("/api/albums").get_json() == {"albums": [], "count": 0}


class TestSomebodyElsesFavouriteIsA404:
    def test_it_cannot_be_added_to_my_album(self, client, conn, user, other_user):
        album_id = make_album(conn, user, "Mine")
        theirs = save_for(conn, other_user, number=7)

        response = client.post(f"/api/albums/{album_id}/items", json={"favourite_id": theirs})

        assert response.status_code == 404
        assert member_ids(conn, album_id) == []

    def test_it_cannot_be_reordered_into_my_album(self, client, conn, user, other_user):
        album_id = make_album(conn, user, "Mine")
        mine = save_for(conn, user, number=1)
        put_in(conn, album_id, mine)
        theirs = save_for(conn, other_user, number=7)

        client.put(f"/api/albums/{album_id}/order", json={"favourite_ids": [theirs, mine]})

        assert member_ids(conn, album_id) == [mine]


class TestTwoUsersSideBySide:
    def test_both_can_have_an_album_of_the_same_name(self, client, acting, user, other_user):
        assert client.post("/api/albums", json={"name": "Resort"}).status_code == 201
        as_user(acting, other_user)
        assert client.post("/api/albums", json={"name": "Resort"}).status_code == 201

    def test_each_sees_only_their_own(self, client, acting, user, other_user):
        client.post("/api/albums", json={"name": "Mine"})
        as_user(acting, other_user)
        client.post("/api/albums", json={"name": "Theirs"})

        assert [a["name"] for a in client.get("/api/albums").get_json()["albums"]] == ["Theirs"]
        as_user(acting, user)
        assert [a["name"] for a in client.get("/api/albums").get_json()["albums"]] == ["Mine"]

    def test_the_same_look_saved_by_both_is_two_rows_in_two_albums(
        self, client, acting, conn, user, other_user
    ):
        """Nothing is shared between them, including the favourite itself."""
        mine = client.post("/api/albums", json={"name": "A"}).get_json()["album"]["id"]
        client.post(f"/api/albums/{mine}/items", json=look_body(12))

        as_user(acting, other_user)
        theirs = client.post("/api/albums", json={"name": "A"}).get_json()["album"]["id"]
        answer = client.post(f"/api/albums/{theirs}/items", json=look_body(12)).get_json()

        assert answer["saved"] is True
        assert favourite_count(conn, user) == 1
        assert favourite_count(conn, other_user) == 1
        assert member_ids(conn, mine) != member_ids(conn, theirs)
