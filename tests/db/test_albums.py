"""Albums, against a real Postgres.

The property this file exists for is the cascade. An album row names a
favourite by id, so the whole design rests on `ON DELETE CASCADE` pointing the
way we think it does: un-saving something must remove it from every album, and
deleting an album must not touch a single favourite. Those two are opposite
mistakes and the second one loses a user's saved work permanently, so both are
asserted here against the database rather than read off the DDL — a foreign key
action is exactly the thing that is easy to get backwards and impossible to
notice until it matters.

The rest is isolation, which the favourites tests already care about for the
same reason: separation is a WHERE clause and a JOIN, and a missing one hands
somebody another person's collection.
"""

from __future__ import annotations

import psycopg
import pytest
from auth import repository as repo
from userdata import albums, favourites

pytestmark = pytest.mark.db

SEASON = {"name": "Fall 2024", "url": "https://example.com/fall-2024", "link_text": "F24"}
COLLECTION = {"designer": "Balenciaga", "url": "https://example.com/balenciaga-f24"}


# Emails nothing else in the suite uses. `tests/api/conftest.py` leaves its last
# signed-up user committed, and it is `tests/db/test_db.py` — whose fixture
# truncates — that happens to clear it before the other db modules run. This
# module sorts ahead of that one, so it does not get to assume an empty users
# table; it just does not collide with anybody.
@pytest.fixture
def user(conn):
    return repo.create_user(
        conn, email="albums-one@example.com", password_hash="h", display_name="One"
    )


@pytest.fixture
def other_user(conn):
    return repo.create_user(
        conn, email="albums-two@example.com", password_hash="h", display_name="Two"
    )


def save_look(conn, user, number=1, designer="Balenciaga", season="Fall 2024"):
    """Save a look and return its favourite id."""
    favourites.add(
        conn,
        user_id=user.id,
        season={"name": season, "url": f"https://example.com/{season}", "link_text": "x"},
        collection={"designer": designer, "url": f"https://example.com/{designer}-{season}"},
        look={"number": number, "total": 48},
        image_path=f"/api/images/{designer}/{number}.jpg",
    )
    return conn.execute(
        """
        SELECT id FROM favourites
         WHERE user_id = %s AND collection_designer = %s AND season_name = %s
           AND look_number = %s
        """,
        (user.id, designer, season, number),
    ).fetchone()[0]


def save_view(conn, user, filters):
    favourites.add(conn, user_id=user.id, kind="view", view_filters=filters, view_name="A view")
    return conn.execute(
        "SELECT id FROM favourites WHERE user_id = %s AND kind = 'view'", (user.id,)
    ).fetchone()[0]


def indices(conn, album_id):
    return dict(
        conn.execute(
            "SELECT favourite_id, sort_index FROM album_items WHERE album_id = %s", (album_id,)
        ).fetchall()
    )


def ids_in_order(items):
    return [item["id"] for item in items]


class TestCreating:
    def test_create_returns_the_album(self, conn, user):
        album = albums.create(conn, user_id=user.id, name="Resort")
        assert album["name"] == "Resort"
        assert album["layout_mode"] == "grid"
        assert album["sort_by"] == "added"
        assert isinstance(album["id"], int)

    def test_the_name_is_trimmed(self, conn, user):
        assert albums.create(conn, user_id=user.id, name="  Resort  ")["name"] == "Resort"

    def test_a_blank_name_is_refused(self, conn, user):
        with pytest.raises(albums.BlankName):
            albums.create(conn, user_id=user.id, name="")

    def test_a_whitespace_name_is_refused(self, conn, user):
        with pytest.raises(albums.BlankName):
            albums.create(conn, user_id=user.id, name="   ")

    def test_two_albums_of_the_same_name_are_refused(self, conn, user):
        albums.create(conn, user_id=user.id, name="Resort")
        with pytest.raises(albums.DuplicateName):
            albums.create(conn, user_id=user.id, name="Resort")

    def test_the_name_clash_is_case_insensitive(self, conn, user):
        albums.create(conn, user_id=user.id, name="Resort")
        with pytest.raises(albums.DuplicateName):
            albums.create(conn, user_id=user.id, name="resort")

    def test_trailing_space_does_not_buy_a_second_album(self, conn, user):
        albums.create(conn, user_id=user.id, name="Resort")
        with pytest.raises(albums.DuplicateName):
            albums.create(conn, user_id=user.id, name="Resort ")

    def test_a_refused_name_leaves_the_transaction_usable(self, conn, user):
        """The reason `create` uses ON CONFLICT DO NOTHING rather than letting
        the unique index raise. This layer never commits, so a constraint
        violation would abort the caller's whole request on the way to becoming
        a 409 — and the next statement would fail with something unrelated."""
        albums.create(conn, user_id=user.id, name="Resort")
        with pytest.raises(albums.DuplicateName):
            albums.create(conn, user_id=user.id, name="Resort")
        assert albums.create(conn, user_id=user.id, name="Tailoring")["name"] == "Tailoring"

    def test_two_users_can_both_have_a_resort(self, conn, user, other_user):
        assert (
            albums.create(conn, user_id=user.id, name="Resort")["id"]
            != albums.create(conn, user_id=other_user.id, name="Resort")["id"]
        )

    def test_an_unknown_layout_mode_is_refused(self, conn, user):
        with pytest.raises(albums.UnknownOption):
            albums.create(conn, user_id=user.id, name="Resort", layout_mode="freeform")

    def test_an_unknown_sort_is_refused(self, conn, user):
        with pytest.raises(albums.UnknownOption):
            albums.create(conn, user_id=user.id, name="Resort", sort_by="colour")

    def test_the_database_refuses_them_too(self, conn, user):
        """Not only the Python check: a writer that is not this module — psql,
        a later service — must not be able to store a mode nothing renders."""
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO albums (user_id, name, layout_mode) VALUES (%s, 'X', 'freeform')",
                (user.id,),
            )


class TestListing:
    def test_newest_first(self, conn, user):
        for name in ("One", "Two", "Three"):
            albums.create(conn, user_id=user.id, name=name)
        assert [a["name"] for a in albums.list_albums(conn, user_id=user.id)] == [
            "Three",
            "Two",
            "One",
        ]

    def test_item_count(self, conn, user):
        album = albums.create(conn, user_id=user.id, name="Resort")
        for number in (1, 2, 3):
            albums.add_item(
                conn,
                user_id=user.id,
                album_id=album["id"],
                favourite_id=save_look(conn, user, number),
            )
        assert albums.list_albums(conn, user_id=user.id)[0]["item_count"] == 3

    def test_an_empty_album_has_no_cover(self, conn, user):
        albums.create(conn, user_id=user.id, name="Resort")
        listed = albums.list_albums(conn, user_id=user.id)[0]
        assert listed["item_count"] == 0
        assert listed["cover_image_path"] is None

    def test_the_cover_is_the_first_item(self, conn, user):
        album = albums.create(conn, user_id=user.id, name="Resort")
        first = save_look(conn, user, 1)
        second = save_look(conn, user, 2)
        albums.add_item(conn, user_id=user.id, album_id=album["id"], favourite_id=first)
        albums.add_item(conn, user_id=user.id, album_id=album["id"], favourite_id=second)
        assert albums.list_albums(conn, user_id=user.id)[0]["cover_image_path"] == (
            "/api/images/Balenciaga/1.jpg"
        )

    def test_the_cover_skips_a_saved_view(self, conn, user):
        """A view is a set of filters and has no image at all. An album whose
        first item is one gets the next item's picture, not a broken tile."""
        album = albums.create(conn, user_id=user.id, name="Resort")
        albums.add_item(
            conn,
            user_id=user.id,
            album_id=album["id"],
            favourite_id=save_view(conn, user, {"year": "1997"}),
        )
        albums.add_item(
            conn, user_id=user.id, album_id=album["id"], favourite_id=save_look(conn, user, 1)
        )
        assert albums.list_albums(conn, user_id=user.id)[0]["cover_image_path"] == (
            "/api/images/Balenciaga/1.jpg"
        )

    def test_one_user_cannot_see_anothers_albums(self, conn, user, other_user):
        albums.create(conn, user_id=user.id, name="Resort")
        assert albums.list_albums(conn, user_id=other_user.id) == []


class TestGetRenameDelete:
    def test_get(self, conn, user):
        album = albums.create(conn, user_id=user.id, name="Resort")
        assert albums.get(conn, user_id=user.id, album_id=album["id"])["name"] == "Resort"

    def test_another_users_album_is_not_found_rather_than_forbidden(self, conn, user, other_user):
        album = albums.create(conn, user_id=user.id, name="Resort")
        assert albums.get(conn, user_id=other_user.id, album_id=album["id"]) is None

    def test_get_an_album_that_does_not_exist(self, conn, user):
        assert albums.get(conn, user_id=user.id, album_id=99999) is None

    def test_rename(self, conn, user):
        album = albums.create(conn, user_id=user.id, name="Resort")
        assert albums.rename(conn, user_id=user.id, album_id=album["id"], name="Cruise") is True
        assert albums.get(conn, user_id=user.id, album_id=album["id"])["name"] == "Cruise"

    def test_renaming_to_its_own_name_in_another_case_is_allowed(self, conn, user):
        album = albums.create(conn, user_id=user.id, name="resort")
        assert albums.rename(conn, user_id=user.id, album_id=album["id"], name="Resort") is True
        assert albums.get(conn, user_id=user.id, album_id=album["id"])["name"] == "Resort"

    def test_renaming_onto_another_album_is_refused(self, conn, user):
        albums.create(conn, user_id=user.id, name="Resort")
        other = albums.create(conn, user_id=user.id, name="Tailoring")
        with pytest.raises(albums.DuplicateName):
            albums.rename(conn, user_id=user.id, album_id=other["id"], name="resort")
        assert albums.get(conn, user_id=user.id, album_id=other["id"])["name"] == "Tailoring"

    def test_a_refused_rename_leaves_the_transaction_usable(self, conn, user):
        albums.create(conn, user_id=user.id, name="Resort")
        other = albums.create(conn, user_id=user.id, name="Tailoring")
        with pytest.raises(albums.DuplicateName):
            albums.rename(conn, user_id=user.id, album_id=other["id"], name="Resort")
        assert albums.rename(conn, user_id=user.id, album_id=other["id"], name="Suits") is True

    def test_one_user_cannot_rename_anothers_album(self, conn, user, other_user):
        album = albums.create(conn, user_id=user.id, name="Resort")
        assert albums.rename(conn, user_id=other_user.id, album_id=album["id"], name="X") is False
        assert albums.get(conn, user_id=user.id, album_id=album["id"])["name"] == "Resort"

    def test_delete(self, conn, user):
        album = albums.create(conn, user_id=user.id, name="Resort")
        assert albums.delete(conn, user_id=user.id, album_id=album["id"]) is True
        assert albums.delete(conn, user_id=user.id, album_id=album["id"]) is False

    def test_one_user_cannot_delete_anothers_album(self, conn, user, other_user):
        album = albums.create(conn, user_id=user.id, name="Resort")
        assert albums.delete(conn, user_id=other_user.id, album_id=album["id"]) is False
        assert albums.get(conn, user_id=user.id, album_id=album["id"]) is not None

    def test_setting_one_option_leaves_the_other_alone(self, conn, user):
        album = albums.create(conn, user_id=user.id, name="Resort")
        albums.set_options(conn, user_id=user.id, album_id=album["id"], sort_by="designer")
        stored = albums.get(conn, user_id=user.id, album_id=album["id"])
        assert stored["sort_by"] == "designer"
        assert stored["layout_mode"] == "grid"

    def test_setting_the_layout_mode(self, conn, user):
        album = albums.create(conn, user_id=user.id, name="Resort")
        albums.set_options(conn, user_id=user.id, album_id=album["id"], layout_mode="canvas")
        assert albums.get(conn, user_id=user.id, album_id=album["id"])["layout_mode"] == "canvas"

    def test_setting_options_on_an_album_that_is_not_yours(self, conn, user, other_user):
        album = albums.create(conn, user_id=user.id, name="Resort")
        assert (
            albums.set_options(
                conn, user_id=other_user.id, album_id=album["id"], sort_by="designer"
            )
            is False
        )


class TestMembership:
    def test_add_then_list(self, conn, user):
        album = albums.create(conn, user_id=user.id, name="Resort")
        favourite = save_look(conn, user, 1)
        assert (
            albums.add_item(conn, user_id=user.id, album_id=album["id"], favourite_id=favourite)
            is True
        )
        items = albums.list_items(conn, user_id=user.id, album_id=album["id"])
        assert ids_in_order(items) == [favourite]

    def test_an_album_holds_a_favourite_once(self, conn, user):
        album = albums.create(conn, user_id=user.id, name="Resort")
        favourite = save_look(conn, user, 1)
        assert (
            albums.add_item(conn, user_id=user.id, album_id=album["id"], favourite_id=favourite)
            is True
        )
        assert (
            albums.add_item(conn, user_id=user.id, album_id=album["id"], favourite_id=favourite)
            is False
        )
        assert len(albums.list_items(conn, user_id=user.id, album_id=album["id"])) == 1

    def test_a_favourite_can_be_in_many_albums(self, conn, user):
        first = albums.create(conn, user_id=user.id, name="Resort")
        second = albums.create(conn, user_id=user.id, name="Tailoring")
        favourite = save_look(conn, user, 1)
        for album in (first, second):
            assert (
                albums.add_item(conn, user_id=user.id, album_id=album["id"], favourite_id=favourite)
                is True
            )
        assert ids_in_order(albums.list_items(conn, user_id=user.id, album_id=first["id"])) == [
            favourite
        ]
        assert ids_in_order(albums.list_items(conn, user_id=user.id, album_id=second["id"])) == [
            favourite
        ]

    def test_an_item_is_the_favourite_plus_where_it_sits(self, conn, user):
        album = albums.create(conn, user_id=user.id, name="Resort")
        favourite = save_look(conn, user, 1)
        albums.add_item(conn, user_id=user.id, album_id=album["id"], favourite_id=favourite)
        item = albums.list_items(conn, user_id=user.id, album_id=album["id"])[0]
        assert set(item) == {
            "id",
            "kind",
            "season",
            "collection",
            "look",
            "view",
            "image_path",
            "date_added",
            "notes",
            "sort_index",
            "placement",
        }
        assert item["look"]["number"] == 1

    def test_the_canvas_placement_is_null_until_phase_six(self, conn, user):
        album = albums.create(conn, user_id=user.id, name="Resort")
        albums.add_item(
            conn, user_id=user.id, album_id=album["id"], favourite_id=save_look(conn, user, 1)
        )
        item = albums.list_items(conn, user_id=user.id, album_id=album["id"])[0]
        assert item["placement"] == {"x": None, "y": None, "w": None, "z": None}

    def test_remove(self, conn, user):
        album = albums.create(conn, user_id=user.id, name="Resort")
        favourite = save_look(conn, user, 1)
        albums.add_item(conn, user_id=user.id, album_id=album["id"], favourite_id=favourite)
        assert (
            albums.remove_item(conn, user_id=user.id, album_id=album["id"], favourite_id=favourite)
            is True
        )
        assert albums.list_items(conn, user_id=user.id, album_id=album["id"]) == []

    def test_removing_something_not_in_the_album(self, conn, user):
        album = albums.create(conn, user_id=user.id, name="Resort")
        favourite = save_look(conn, user, 1)
        assert (
            albums.remove_item(conn, user_id=user.id, album_id=album["id"], favourite_id=favourite)
            is False
        )

    def test_removing_from_an_album_does_not_unsave(self, conn, user):
        """The two destructive acts the UI has to keep apart. This is the one
        that is not supposed to lose anything."""
        album = albums.create(conn, user_id=user.id, name="Resort")
        favourite = save_look(conn, user, 1)
        albums.add_item(conn, user_id=user.id, album_id=album["id"], favourite_id=favourite)
        albums.remove_item(conn, user_id=user.id, album_id=album["id"], favourite_id=favourite)
        assert len(favourites.list_all(conn, user_id=user.id)) == 1


class TestMembershipIsolation:
    def test_a_favourite_cannot_be_added_to_someone_elses_album(self, conn, user, other_user):
        album = albums.create(conn, user_id=user.id, name="Resort")
        favourite = save_look(conn, other_user, 1)
        assert (
            albums.add_item(
                conn, user_id=other_user.id, album_id=album["id"], favourite_id=favourite
            )
            is False
        )
        assert albums.list_items(conn, user_id=user.id, album_id=album["id"]) == []

    def test_someone_elses_favourite_cannot_be_added_to_your_album(self, conn, user, other_user):
        """The hole this closes: album_items carries no user_id, so without the
        join on ownership an id guessed out of another person's collection
        would put their picture in your album."""
        album = albums.create(conn, user_id=user.id, name="Resort")
        theirs = save_look(conn, other_user, 1)
        assert (
            albums.add_item(conn, user_id=user.id, album_id=album["id"], favourite_id=theirs)
            is False
        )
        assert albums.list_items(conn, user_id=user.id, album_id=album["id"]) == []

    def test_one_user_cannot_remove_from_anothers_album(self, conn, user, other_user):
        album = albums.create(conn, user_id=user.id, name="Resort")
        favourite = save_look(conn, user, 1)
        albums.add_item(conn, user_id=user.id, album_id=album["id"], favourite_id=favourite)
        assert (
            albums.remove_item(
                conn, user_id=other_user.id, album_id=album["id"], favourite_id=favourite
            )
            is False
        )
        assert len(albums.list_items(conn, user_id=user.id, album_id=album["id"])) == 1

    def test_one_user_cannot_read_anothers_album(self, conn, user, other_user):
        album = albums.create(conn, user_id=user.id, name="Resort")
        albums.add_item(
            conn, user_id=user.id, album_id=album["id"], favourite_id=save_look(conn, user, 1)
        )
        assert albums.list_items(conn, user_id=other_user.id, album_id=album["id"]) == []


class TestTheCascades:
    """The point of the design, asserted against the database.

    A foreign key action is easy to write backwards and impossible to notice
    until a user loses something, so both directions are here: one table
    cascades, the other must not."""

    def test_unsaving_drops_the_look_out_of_every_album(self, conn, user):
        first = albums.create(conn, user_id=user.id, name="Resort")
        second = albums.create(conn, user_id=user.id, name="Tailoring")
        favourite = save_look(conn, user, 1)
        keeper = save_look(conn, user, 2)
        for album in (first, second):
            albums.add_item(conn, user_id=user.id, album_id=album["id"], favourite_id=favourite)
            albums.add_item(conn, user_id=user.id, album_id=album["id"], favourite_id=keeper)

        assert (
            favourites.remove(
                conn,
                user_id=user.id,
                season_url="https://example.com/Fall 2024",
                collection_url="https://example.com/Balenciaga-Fall 2024",
                look_number=1,
            )
            is True
        )

        for album in (first, second):
            assert ids_in_order(albums.list_items(conn, user_id=user.id, album_id=album["id"])) == [
                keeper
            ]

    def test_unsaving_does_not_delete_the_albums(self, conn, user):
        album = albums.create(conn, user_id=user.id, name="Resort")
        favourite = save_look(conn, user, 1)
        albums.add_item(conn, user_id=user.id, album_id=album["id"], favourite_id=favourite)
        conn.execute("DELETE FROM favourites WHERE id = %s", (favourite,))
        assert albums.get(conn, user_id=user.id, album_id=album["id"]) is not None
        assert albums.list_albums(conn, user_id=user.id)[0]["item_count"] == 0

    def test_deleting_an_album_leaves_its_favourites_saved(self, conn, user):
        """The opposite mistake, and the unrecoverable one. An album is an
        arrangement of things the user kept, not the keeping of them."""
        album = albums.create(conn, user_id=user.id, name="Resort")
        for number in (1, 2, 3):
            albums.add_item(
                conn,
                user_id=user.id,
                album_id=album["id"],
                favourite_id=save_look(conn, user, number),
            )
        albums.delete(conn, user_id=user.id, album_id=album["id"])
        assert len(favourites.list_all(conn, user_id=user.id)) == 3

    def test_deleting_an_album_leaves_its_items_in_other_albums(self, conn, user):
        first = albums.create(conn, user_id=user.id, name="Resort")
        second = albums.create(conn, user_id=user.id, name="Tailoring")
        favourite = save_look(conn, user, 1)
        albums.add_item(conn, user_id=user.id, album_id=first["id"], favourite_id=favourite)
        albums.add_item(conn, user_id=user.id, album_id=second["id"], favourite_id=favourite)
        albums.delete(conn, user_id=user.id, album_id=first["id"])
        assert ids_in_order(albums.list_items(conn, user_id=user.id, album_id=second["id"])) == [
            favourite
        ]

    def test_deleting_an_album_drops_only_its_own_membership_rows(self, conn, user):
        album = albums.create(conn, user_id=user.id, name="Resort")
        favourite = save_look(conn, user, 1)
        albums.add_item(conn, user_id=user.id, album_id=album["id"], favourite_id=favourite)
        albums.delete(conn, user_id=user.id, album_id=album["id"])
        assert (
            conn.execute(
                "SELECT count(*) FROM album_items WHERE album_id = %s", (album["id"],)
            ).fetchone()[0]
            == 0
        )

    def test_deleting_a_user_takes_albums_and_memberships_with_it(self, conn, user):
        album = albums.create(conn, user_id=user.id, name="Resort")
        favourite = save_look(conn, user, 1)
        albums.add_item(conn, user_id=user.id, album_id=album["id"], favourite_id=favourite)

        repo.delete_user(conn, user.id)

        # Counted by id rather than by table, because this module does not get
        # a clean users table (see the fixtures above) and another user's rows
        # are none of this test's business.
        assert (
            conn.execute("SELECT count(*) FROM albums WHERE id = %s", (album["id"],)).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM album_items WHERE album_id = %s", (album["id"],)
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute("SELECT count(*) FROM favourites WHERE id = %s", (favourite,)).fetchone()[
                0
            ]
            == 0
        )

    def test_a_membership_row_cannot_name_a_favourite_that_is_not_there(self, conn, user):
        """The other half of the same guarantee: the cascade keeps stale rows
        from surviving a delete, and the foreign key keeps them from being
        written in the first place."""
        album = albums.create(conn, user_id=user.id, name="Resort")
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            conn.execute(
                "INSERT INTO album_items (album_id, favourite_id) VALUES (%s, 999999)",
                (album["id"],),
            )


class TestOrdering:
    """`sort_index` is sparse so that a drag is one write.

    These tests are about that cost, not just the resulting order: phase 6
    drags these tiles, and an implementation that renumbers the album on every
    drag would pass an order assertion while doing N writes a frame."""

    @pytest.fixture
    def album_of_three(self, conn, user):
        album = albums.create(conn, user_id=user.id, name="Resort")
        ids = []
        for number in (1, 2, 3):
            favourite = save_look(conn, user, number)
            albums.add_item(conn, user_id=user.id, album_id=album["id"], favourite_id=favourite)
            ids.append(favourite)
        return album, ids

    def test_items_are_appended_a_gap_apart(self, conn, album_of_three):
        album, ids = album_of_three
        assert [indices(conn, album["id"])[i] for i in ids] == [
            albums.SORT_GAP,
            albums.SORT_GAP * 2,
            albums.SORT_GAP * 3,
        ]

    def test_added_order_is_the_order_they_went_in(self, conn, user, album_of_three):
        album, ids = album_of_three
        assert ids_in_order(albums.list_items(conn, user_id=user.id, album_id=album["id"])) == ids

    def test_move_to_the_front(self, conn, user, album_of_three):
        album, ids = album_of_three
        assert albums.move(conn, user_id=user.id, album_id=album["id"], favourite_id=ids[2]) is True
        assert ids_in_order(albums.list_items(conn, user_id=user.id, album_id=album["id"])) == [
            ids[2],
            ids[0],
            ids[1],
        ]

    def test_move_after_an_item(self, conn, user, album_of_three):
        album, ids = album_of_three
        assert (
            albums.move(
                conn, user_id=user.id, album_id=album["id"], favourite_id=ids[0], after=ids[1]
            )
            is True
        )
        assert ids_in_order(albums.list_items(conn, user_id=user.id, album_id=album["id"])) == [
            ids[1],
            ids[0],
            ids[2],
        ]

    def test_move_to_the_end(self, conn, user, album_of_three):
        album, ids = album_of_three
        albums.move(conn, user_id=user.id, album_id=album["id"], favourite_id=ids[0], after=ids[2])
        assert ids_in_order(albums.list_items(conn, user_id=user.id, album_id=album["id"])) == [
            ids[1],
            ids[2],
            ids[0],
        ]

    def test_a_drag_writes_one_row(self, conn, user, album_of_three):
        """The whole reason the indices are sparse. Reordering N items is one
        UPDATE of one row, not N."""
        album, ids = album_of_three
        before = indices(conn, album["id"])
        albums.move(conn, user_id=user.id, album_id=album["id"], favourite_id=ids[0], after=ids[1])
        after = indices(conn, album["id"])
        moved = [key for key in before if before[key] != after[key]]
        assert moved == [ids[0]]

    def test_moving_an_item_to_where_it_already_is(self, conn, user, album_of_three):
        album, ids = album_of_three
        assert (
            albums.move(
                conn, user_id=user.id, album_id=album["id"], favourite_id=ids[1], after=ids[1]
            )
            is True
        )
        assert ids_in_order(albums.list_items(conn, user_id=user.id, album_id=album["id"])) == ids

    def test_a_closed_gap_respaces_the_album_rather_than_failing(self, conn, user, album_of_three):
        """There is no integer between 5 and 6. The move still has to land
        between them, so the album is renumbered first and then the same single
        write happens."""
        album, ids = album_of_three
        for favourite, index in zip(ids, (5, 6, 99), strict=True):
            conn.execute(
                "UPDATE album_items SET sort_index = %s WHERE album_id = %s AND favourite_id = %s",
                (index, album["id"], favourite),
            )
        assert (
            albums.move(
                conn, user_id=user.id, album_id=album["id"], favourite_id=ids[2], after=ids[0]
            )
            is True
        )
        order = ids_in_order(albums.list_items(conn, user_id=user.id, album_id=album["id"]))
        assert order == [ids[0], ids[2], ids[1]]
        spaced = indices(conn, album["id"])
        assert len(set(spaced.values())) == 3

    def test_dragging_into_the_same_slot_over_and_over_keeps_working(
        self, conn, user, album_of_three
    ):
        """Twenty drops into one gap. 1024 halves away in about ten, so this
        crosses the renumber at least once and has to come out the same."""
        album, ids = album_of_three
        for _ in range(20):
            assert (
                albums.move(
                    conn, user_id=user.id, album_id=album["id"], favourite_id=ids[2], after=ids[0]
                )
                is True
            )
            assert ids_in_order(albums.list_items(conn, user_id=user.id, album_id=album["id"])) == [
                ids[0],
                ids[2],
                ids[1],
            ]
        assert len(set(indices(conn, album["id"]).values())) == 3

    def test_repeated_moves_to_the_front_do_not_run_off_the_bottom(
        self, conn, user, album_of_three
    ):
        album, ids = album_of_three
        conn.execute(
            "UPDATE album_items SET sort_index = %s WHERE album_id = %s AND favourite_id = %s",
            (albums.SORT_FLOOR, album["id"], ids[0]),
        )
        assert albums.move(conn, user_id=user.id, album_id=album["id"], favourite_id=ids[1]) is True
        assert (
            ids_in_order(albums.list_items(conn, user_id=user.id, album_id=album["id"]))[0]
            == ids[1]
        )

    def test_moving_something_that_is_not_in_the_album(self, conn, user, album_of_three):
        album, _ = album_of_three
        loose = save_look(conn, user, 9)
        assert albums.move(conn, user_id=user.id, album_id=album["id"], favourite_id=loose) is False

    def test_moving_after_something_that_is_not_in_the_album(self, conn, user, album_of_three):
        album, ids = album_of_three
        loose = save_look(conn, user, 9)
        assert (
            albums.move(
                conn, user_id=user.id, album_id=album["id"], favourite_id=ids[0], after=loose
            )
            is False
        )

    def test_one_user_cannot_reorder_anothers_album(self, conn, user, other_user, album_of_three):
        album, ids = album_of_three
        assert (
            albums.move(conn, user_id=other_user.id, album_id=album["id"], favourite_id=ids[0])
            is False
        )
        assert ids_in_order(albums.list_items(conn, user_id=user.id, album_id=album["id"])) == ids

    def test_set_order_writes_a_whole_arrangement(self, conn, user, album_of_three):
        album, ids = album_of_three
        wanted = [ids[2], ids[0], ids[1]]
        assert (
            albums.set_order(conn, user_id=user.id, album_id=album["id"], favourite_ids=wanted) == 3
        )
        assert (
            ids_in_order(albums.list_items(conn, user_id=user.id, album_id=album["id"])) == wanted
        )

    def test_set_order_leaves_the_album_respaced(self, conn, user, album_of_three):
        """A full rewrite is also the moment to put the gaps back, so the drag
        after it is a midpoint again rather than a second rewrite."""
        album, ids = album_of_three
        albums.set_order(
            conn, user_id=user.id, album_id=album["id"], favourite_ids=[ids[2], ids[0], ids[1]]
        )
        assert sorted(indices(conn, album["id"]).values()) == [
            albums.SORT_GAP,
            albums.SORT_GAP * 2,
            albums.SORT_GAP * 3,
        ]

    def test_one_user_cannot_set_the_order_of_anothers_album(
        self, conn, user, other_user, album_of_three
    ):
        album, ids = album_of_three
        assert (
            albums.set_order(
                conn, user_id=other_user.id, album_id=album["id"], favourite_ids=list(reversed(ids))
            )
            == 0
        )
        assert ids_in_order(albums.list_items(conn, user_id=user.id, album_id=album["id"])) == ids

    def test_renumber_keeps_the_order_and_respaces_it(self, conn, user, album_of_three):
        album, ids = album_of_three
        for favourite, index in zip(ids, (5, 6, 7), strict=True):
            conn.execute(
                "UPDATE album_items SET sort_index = %s WHERE album_id = %s AND favourite_id = %s",
                (index, album["id"], favourite),
            )
        assert albums.renumber(conn, album_id=album["id"]) == 3
        assert [indices(conn, album["id"])[i] for i in ids] == [
            albums.SORT_GAP,
            albums.SORT_GAP * 2,
            albums.SORT_GAP * 3,
        ]


class TestSorting:
    @pytest.fixture
    def mixed_album(self, conn, user):
        album = albums.create(conn, user_id=user.id, name="Resort")
        ids = {}
        for designer, season, number in (
            ("Margiela", "Spring 2001", 1),
            ("Balenciaga", "Fall 2024", 2),
            ("Comme", "Autumn 1998", 3),
        ):
            favourite = save_look(conn, user, number, designer=designer, season=season)
            albums.add_item(conn, user_id=user.id, album_id=album["id"], favourite_id=favourite)
            ids[designer] = favourite
        return album, ids

    def test_the_album_is_read_in_its_stored_order(self, conn, user, mixed_album):
        album, ids = mixed_album
        albums.set_options(conn, user_id=user.id, album_id=album["id"], sort_by="designer")
        assert ids_in_order(albums.list_items(conn, user_id=user.id, album_id=album["id"])) == [
            ids["Balenciaga"],
            ids["Comme"],
            ids["Margiela"],
        ]

    def test_a_caller_can_override_the_stored_sort(self, conn, user, mixed_album):
        album, ids = mixed_album
        assert ids_in_order(
            albums.list_items(conn, user_id=user.id, album_id=album["id"], sort_by="added")
        ) == [ids["Margiela"], ids["Balenciaga"], ids["Comme"]]

    def test_by_season(self, conn, user, mixed_album):
        album, ids = mixed_album
        assert ids_in_order(
            albums.list_items(conn, user_id=user.id, album_id=album["id"], sort_by="season")
        ) == [ids["Comme"], ids["Balenciaga"], ids["Margiela"]]

    def test_an_unknown_sort_is_refused_rather_than_interpolated(self, conn, user, mixed_album):
        """`sort_by` becomes an ORDER BY. It is looked up in a dict of known
        orders and never taken from a caller's string."""
        album, _ = mixed_album
        with pytest.raises(albums.UnknownOption):
            albums.list_items(
                conn, user_id=user.id, album_id=album["id"], sort_by="id; DROP TABLE albums"
            )

    def test_listing_an_album_that_does_not_exist(self, conn, user):
        assert albums.list_items(conn, user_id=user.id, album_id=99999) == []
