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


class TestTheShowsId:
    """`collection.id` on the way out, and nothing on the way in.

    A client that could send an id could send one its url disagrees with, and
    two identities for one show is the bug the column was added to end. So the
    server derives it and the API only reports it.
    """

    SHOW = {
        "designer": "Balenciaga",
        "url": "https://www.firstview.com/collection_images.php?id=12345&list=all",
    }

    def save(self, client, collection, number=12):
        return client.post(
            "/api/favourites",
            json={
                "season": SEASON,
                "collection": collection,
                "look": {"number": number, "total": 48},
                "image_path": "/api/images/x.jpg",
            },
        )

    def listed(self, client):
        return client.get("/api/favourites").get_json()["favourites"]

    def test_a_listed_favourite_carries_it(self, client):
        self.save(client, self.SHOW)
        assert self.listed(client)[0]["collection"]["id"] == "12345"

    def test_a_url_that_names_no_show_lists_a_null_id(self, client):
        save_look(client)
        assert self.listed(client)[0]["collection"]["id"] is None

    def test_a_view_lists_a_null_id(self, client):
        save_view(client, {"city": "Paris"})
        assert self.listed(client)[0]["collection"]["id"] is None

    def test_an_id_in_the_body_is_ignored_not_stored(self, client, conn):
        """The one that matters: a client insisting on a different show does
        not get one. The url is the only thing consulted."""
        self.save(client, {**self.SHOW, "id": "999999"})
        assert conn.execute("SELECT collection_id FROM favourites").fetchone()[0] == "12345"

    def test_an_id_in_the_body_cannot_make_a_second_row(self, client, conn):
        """It is not part of the key, so it cannot be part of a duplicate."""
        self.save(client, self.SHOW)
        self.save(client, {**self.SHOW, "id": "999999"})
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


class TestPagingTheList:
    """`?limit=` and `?cursor=`, against the real ordering.

    The interesting failures here are all about the boundary between two pages,
    and none of them raise. A cursor applied in a different order than the one
    it was minted in returns plausible rows in the wrong place. A `hasMore`
    inferred from `len(rows) == limit` is wrong exactly when the list divides
    evenly. And an OFFSET — which is what this deliberately is not — returns a
    page that has quietly skipped a row, which is a favourite the reader never
    sees again. So these run against Postgres, through the handler, and check
    the rows themselves rather than the counts.
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

    def _numbers(self, body):
        return [row["look"]["number"] for row in body["favourites"]]

    def _save_many(self, client, count):
        for number in range(1, count + 1):
            self._save(client, number)
        # Newest first, so the last one saved is the first one listed.
        return list(range(count, 0, -1))

    def test_the_unpaged_answer_still_has_the_key_it_always_had(self, client):
        self._save_many(client, 3)

        body = client.get("/api/favourites").get_json()

        # Backward compatibility, literally: a caller that sends no paging
        # parameters reads `favourites` and gets everything, as before.
        assert self._numbers(body) == [3, 2, 1]
        assert body["total"] == 3
        assert body["hasMore"] is False
        assert body["nextCursor"] is None

    def test_a_page_reports_the_whole_total_not_the_page(self, client):
        self._save_many(client, 5)

        body = client.get("/api/favourites?limit=2").get_json()

        assert self._numbers(body) == [5, 4]
        # Five, not two. The sidebar counts with this, and a count of the page
        # would have the library claim the reader has as many saves as are
        # currently drawn.
        assert body["total"] == 5
        assert body["hasMore"] is True
        assert body["nextCursor"]

    def test_the_cursor_walks_the_whole_list_exactly_once(self, client):
        expected = self._save_many(client, 7)

        seen = []
        cursor = None
        for _ in range(10):                      # a bound, so a bug cannot hang
            url = "/api/favourites?limit=3"
            if cursor:
                url += f"&cursor={cursor}"
            body = client.get(url).get_json()
            seen.extend(self._numbers(body))
            cursor = body["nextCursor"]
            if not body["hasMore"]:
                break

        # Every row, in order, with nothing repeated at a boundary and nothing
        # dropped over one.
        assert seen == expected
        assert len(seen) == len(set(seen))

    def test_has_more_is_false_on_a_list_that_divides_evenly(self, client):
        self._save_many(client, 4)

        first = client.get("/api/favourites?limit=2").get_json()
        second = client.get(
            f"/api/favourites?limit=2&cursor={first['nextCursor']}"
        ).get_json()

        assert self._numbers(second) == [2, 1]
        # Four rows, two pages of two. `len(rows) == limit` would claim a third
        # page here and the reader would meet an empty "load more".
        assert second["hasMore"] is False
        assert second["nextCursor"] is None

    def test_unsaving_above_the_cursor_does_not_skip_a_row(self, client, conn):
        """The whole reason this is a cursor and not an offset.

        Page one, then unsave two things that were ON page one, then page two.
        With OFFSET the second request would start two rows late and two
        favourites would fall through the gap unseen.
        """
        self._save_many(client, 6)

        first = client.get("/api/favourites?limit=3").get_json()
        assert self._numbers(first) == [6, 5, 4]

        for number in (6, 5):
            client.delete(
                "/api/favourites",
                json={
                    "season_url": SEASON["url"],
                    "collection_url": COLLECTION["url"],
                    "look_number": number,
                },
            )
        assert rows(conn) == 4

        second = client.get(
            f"/api/favourites?limit=3&cursor={first['nextCursor']}"
        ).get_json()

        # The rest of the list, all of it. Not [2, 1] with 3 skipped.
        assert self._numbers(second) == [3, 2, 1]
        assert second["total"] == 4

    def test_a_kind_narrows_the_page_and_the_total(self, client):
        self._save_many(client, 3)
        save_show(client)
        save_view(client, {"year": "2024"})

        body = client.get("/api/favourites?kind=look&limit=2").get_json()

        assert self._numbers(body) == [3, 2]
        assert {row["kind"] for row in body["favourites"]} == {"look"}
        # Three looks, not five favourites: the count is under the same filter
        # as the page, which is what each of the library's panes counts with.
        assert body["total"] == 3
        assert body["hasMore"] is True

    def test_a_cursor_from_one_kind_is_not_read_against_another(self, client):
        """A cursor names a place, not a row of a particular kind."""
        self._save_many(client, 3)
        save_show(client)

        looks = client.get("/api/favourites?kind=look&limit=1").get_json()
        rest = client.get(
            f"/api/favourites?kind=look&limit=5&cursor={looks['nextCursor']}"
        ).get_json()

        assert self._numbers(rest) == [2, 1]
        assert all(row["kind"] == "look" for row in rest["favourites"])

    def test_a_cursor_we_did_not_mint_is_refused(self, client):
        self._save_many(client, 3)

        response = client.get("/api/favourites?limit=2&cursor=not-a-cursor")

        # 400, not a silent first page: a load-more control handed the page it
        # already has would loop, and look like a list with no end.
        assert response.status_code == 400
        assert "cursor" in response.get_json()["error"]

    @pytest.mark.parametrize(
        "payload",
        [
            b"yesterday|12",              # the timestamp is not one
            b"2026-09-14T00:00:00+00:00|twelve",   # the id is not one
            b"2026-09-14T00:00:00+00:00",          # no pair at all
        ],
    )
    def test_a_cursor_whose_halves_are_junk_is_refused(self, client, payload):
        """Refused as a 400, not raised as a database error.

        Both halves are checked before they reach a cast: a cast that refuses
        raises mid-transaction, which is a 500 over somebody's query string.
        """
        import base64

        forged = base64.urlsafe_b64encode(payload).decode().rstrip("=")

        response = client.get(f"/api/favourites?limit=2&cursor={forged}")

        assert response.status_code == 400

    def test_a_cursor_alone_means_the_default_page_size(self, client):
        self._save_many(client, 3)

        first = client.get("/api/favourites?limit=1").get_json()
        rest = client.get(f"/api/favourites?cursor={first['nextCursor']}").get_json()

        assert self._numbers(rest) == [2, 1]


class TestTheKeys:
    """GET /api/favourites/keys — complete, cheap, and shaped like a row.

    This endpoint is what makes paging the rows safe, so what is pinned here is
    that it is not itself paged and that what it returns is enough to key on and
    no more.
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

    def test_every_save_is_there_however_many_there_are(self, client):
        for number in range(1, 13):
            self._save(client, number)
        save_show(client)
        save_view(client, {"year": "2024"})

        keys = client.get("/api/favourites/keys").get_json()["keys"]

        # Fourteen, with no limit accepted and none applied. A page of these
        # would be a dark star over something the reader saved.
        assert len(keys) == 14
        assert {k["kind"] for k in keys} == {"look", "show", "view"}

    def test_a_key_carries_the_identity_and_not_the_display(self, client):
        self._save(client, 7)

        key = client.get("/api/favourites/keys").get_json()["keys"][0]

        assert key == {
            "kind": "look",
            "season": {"url": SEASON["url"]},
            "collection": {"url": COLLECTION["url"]},
            "look": {"number": 7},
            "view": {"filters": None},
        }
        # The heavy half is absent, which is the point: this is the half the
        # star reads and the star never draws a designer or an image.
        assert "image_path" not in key
        assert "designer" not in key["collection"]

    def test_a_view_key_carries_its_filters_because_that_is_its_identity(self, client):
        save_view(client, {"year": "2024", "city": "Paris"})

        key = client.get("/api/favourites/keys").get_json()["keys"][0]

        assert key["kind"] == "view"
        assert key["view"]["filters"] == {"year": "2024", "city": "Paris"}

    def test_another_users_saves_are_not_in_it(self, client, conn, monkeypatch):
        self._save(client, 7)
        stranger = repo.create_user(
            conn, email="two@example.com", password_hash="h", display_name="Two"
        )
        monkeypatch.setattr(routes, "current_user", lambda: stranger)

        assert client.get("/api/favourites/keys").get_json()["keys"] == []
