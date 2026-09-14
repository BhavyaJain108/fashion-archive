"""Favourites and brand following in Postgres.

The property these tests exist for is isolation. Under the old design each user
got their own SQLite file, so separation depended on constructing the right
directory name; here it depends on a WHERE clause and a foreign key. The
cross-user tests below are the ones that would have caught a missing
`user_id = %s`.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest
from auth import repository as repo
from high_fashion import firstview as fv
from userdata import favourites, following

pytestmark = pytest.mark.db

SEASON = {"name": "Fall 2024", "url": "https://example.com/fall-2024", "link_text": "F24"}
COLLECTION = {"designer": "Balenciaga", "url": "https://example.com/balenciaga-f24"}
LOOK = {"number": 12, "total": 48}

# The userdata half of the schema, re-read here because the collection_id tests
# below apply it again inside their own transaction to watch it repair rows.
USERDATA_SCHEMA = (
    Path(__file__).resolve().parents[2] / "backend" / "userdata" / "schema.sql"
).read_text()

# One show, in the two spellings phase 3 found in production: the archive list's
# and the recents drawer's. They are still two favourites — the unique indexes
# did not change — but they now agree on which show they are.
SHOW_ID = "12345"
LIST_URL = f"https://www.firstview.com/collection_images.php?id={SHOW_ID}&list=all"
DRAWER_URL = f"https://www.firstview.com/collection_images.php?id={SHOW_ID}"


@pytest.fixture
def user(conn):
    return repo.create_user(conn, email="one@example.com", password_hash="h", display_name="One")


@pytest.fixture
def other_user(conn):
    return repo.create_user(conn, email="two@example.com", password_hash="h", display_name="Two")


def add_look(conn, user, look_number=12):
    return favourites.add(
        conn,
        user_id=user.id,
        season=SEASON,
        collection=COLLECTION,
        look={"number": look_number, "total": 48},
        image_path=f"/api/images/balenciaga/f24/look{look_number}.jpg",
    )


class TestFavourites:
    def test_add_then_list(self, conn, user):
        add_look(conn, user)
        items = favourites.list_all(conn, user_id=user.id)
        assert len(items) == 1
        assert items[0]["collection"]["designer"] == "Balenciaga"
        assert items[0]["look"]["number"] == 12

    def test_shape_matches_what_the_frontend_consumes(self, conn, user):
        """Storage moved; the JSON did not. `kind` and `view` are additions —
        every key the frontend already read is still here and still spelled the
        same."""
        add_look(conn, user)
        item = favourites.list_all(conn, user_id=user.id)[0]
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
        }
        assert set(item["season"]) == {"name", "url", "link_text"}
        assert set(item["collection"]) == {"designer", "url", "id"}
        assert set(item["look"]) == {"number", "total"}
        assert item["kind"] == "look"

    def test_adding_twice_is_reported_not_duplicated(self, conn, user):
        assert add_look(conn, user) is True
        assert add_look(conn, user) is False
        assert len(favourites.list_all(conn, user_id=user.id)) == 1

    def test_exists_reflects_state(self, conn, user):
        args = dict(
            user_id=user.id,
            season_url=SEASON["url"],
            collection_url=COLLECTION["url"],
            look_number=12,
        )
        assert favourites.exists(conn, **args) is False
        add_look(conn, user)
        assert favourites.exists(conn, **args) is True

    def test_remove(self, conn, user):
        add_look(conn, user)
        assert (
            favourites.remove(
                conn,
                user_id=user.id,
                season_url=SEASON["url"],
                collection_url=COLLECTION["url"],
                look_number=12,
            )
            is True
        )
        assert favourites.list_all(conn, user_id=user.id) == []

    def test_removing_something_absent_reports_false(self, conn, user):
        assert (
            favourites.remove(
                conn,
                user_id=user.id,
                season_url=SEASON["url"],
                collection_url=COLLECTION["url"],
                look_number=99,
            )
            is False
        )

    def test_newest_first(self, conn, user):
        for n in (1, 2, 3):
            add_look(conn, user, look_number=n)
        numbers = [f["look"]["number"] for f in favourites.list_all(conn, user_id=user.id)]
        assert numbers == [3, 2, 1]

    def test_stats(self, conn, user):
        add_look(conn, user, look_number=1)
        add_look(conn, user, look_number=2)
        s = favourites.stats(conn, user_id=user.id)
        assert s["total_favourites"] == 2
        assert s["unique_seasons"] == 1
        assert s["unique_designers"] == 1

    def test_stats_on_an_empty_collection(self, conn, user):
        assert favourites.stats(conn, user_id=user.id)["total_favourites"] == 0


class TestSavedShows:
    """A show is a favourite with no look number.

    The old unique constraint could not express one: it covered look_number,
    and null is not equal to null, so every save of the same show would have
    been accepted as a new row."""

    def add_show(self, conn, user):
        return favourites.add(
            conn,
            user_id=user.id,
            kind="show",
            season=SEASON,
            collection=COLLECTION,
            image_path="/api/images/balenciaga/f24/look1.jpg",
        )

    def test_a_show_saves_with_no_look_number(self, conn, user):
        assert self.add_show(conn, user) is True
        item = favourites.list_all(conn, user_id=user.id)[0]
        assert item["kind"] == "show"
        assert item["look"]["number"] is None

    def test_saving_the_same_show_twice_is_reported_not_duplicated(self, conn, user):
        assert self.add_show(conn, user) is True
        assert self.add_show(conn, user) is False
        assert len(favourites.list_all(conn, user_id=user.id)) == 1

    def test_two_users_can_save_the_same_show(self, conn, user, other_user):
        assert self.add_show(conn, user) is True
        assert self.add_show(conn, other_user) is True

    def test_saving_a_show_does_not_save_its_looks(self, conn, user):
        """Starring a whole show must not light up every look in it."""
        self.add_show(conn, user)
        assert (
            favourites.exists(
                conn,
                user_id=user.id,
                season_url=SEASON["url"],
                collection_url=COLLECTION["url"],
                look_number=12,
            )
            is False
        )

    def test_removing_a_look_leaves_the_show_saved(self, conn, user):
        self.add_show(conn, user)
        add_look(conn, user)
        favourites.remove(
            conn,
            user_id=user.id,
            season_url=SEASON["url"],
            collection_url=COLLECTION["url"],
            look_number=12,
        )
        assert (
            favourites.exists(
                conn,
                user_id=user.id,
                kind="show",
                season_url=SEASON["url"],
                collection_url=COLLECTION["url"],
            )
            is True
        )


class TestSavedViews:
    """A view is its filters. Identity is the filters themselves, which is why
    the client's key order must not be able to produce two of the same view."""

    def add_view(self, conn, user, filters, name="Paris 1997"):
        return favourites.add(
            conn, user_id=user.id, kind="view", view_filters=filters, view_name=name
        )

    def test_a_view_saves_with_its_filters_and_name(self, conn, user):
        assert self.add_view(conn, user, {"city": "Paris", "year": 1997}) is True
        item = favourites.list_all(conn, user_id=user.id)[0]
        assert item["kind"] == "view"
        assert item["view"] == {"name": "Paris 1997", "filters": {"city": "Paris", "year": 1997}}

    def test_the_same_filters_in_another_key_order_are_the_same_view(self, conn, user):
        assert self.add_view(conn, user, {"city": "Paris", "year": 1997}) is True
        assert self.add_view(conn, user, {"year": 1997, "city": "Paris"}, name="again") is False
        assert len(favourites.list_all(conn, user_id=user.id)) == 1

    def test_different_filters_are_different_views(self, conn, user):
        assert self.add_view(conn, user, {"city": "Paris"}) is True
        assert self.add_view(conn, user, {"city": "Milan"}, name="Milan") is True

    def test_a_view_is_removable_by_filters_in_either_order(self, conn, user):
        self.add_view(conn, user, {"city": "Paris", "year": 1997})
        assert (
            favourites.remove(
                conn, user_id=user.id, kind="view", view_filters={"year": 1997, "city": "Paris"}
            )
            is True
        )
        assert favourites.list_all(conn, user_id=user.id) == []


class TestAllThreeKinds:
    def test_an_unknown_kind_never_reaches_the_table(self, conn, user):
        with pytest.raises(favourites.UnknownKind):
            favourites.add(conn, user_id=user.id, kind="folder")
        assert conn.execute("SELECT count(*) FROM favourites").fetchone()[0] == 0

    def test_list_all_returns_every_kind_tagged(self, conn, user):
        add_look(conn, user)
        favourites.add(
            conn,
            user_id=user.id,
            kind="show",
            season=SEASON,
            collection=COLLECTION,
            image_path="/api/images/balenciaga/f24/look1.jpg",
        )
        favourites.add(
            conn, user_id=user.id, kind="view", view_filters={"city": "Paris"}, view_name="Paris"
        )
        kinds = {item["kind"] for item in favourites.list_all(conn, user_id=user.id)}
        assert kinds == {"look", "show", "view"}

    def test_list_all_can_be_narrowed_to_one_kind(self, conn, user):
        add_look(conn, user)
        favourites.add(
            conn, user_id=user.id, kind="view", view_filters={"city": "Paris"}, view_name="Paris"
        )
        only = favourites.list_all(conn, user_id=user.id, kind="view")
        assert [item["kind"] for item in only] == ["view"]

    def test_list_all_can_be_asked_for_a_page(self, conn, user):
        """Unbounded by default, bounded on request.

        The whole library is fetched on every archive-page mount, so the
        caller has to be able to ask for less. It is not capped by default:
        the client keys its stars off these rows, and a row that did not
        arrive is a dark star over something the reader saved.
        """
        for number in range(1, 6):
            add_look(conn, user, look_number=number)

        assert len(favourites.list_all(conn, user_id=user.id)) == 5
        assert len(favourites.list_all(conn, user_id=user.id, limit=2)) == 2

    def test_a_page_is_the_newest_rows(self, conn, user):
        """Same order as the unlimited list, which is what makes it a page."""
        for number in range(1, 6):
            add_look(conn, user, look_number=number)

        everything = favourites.list_all(conn, user_id=user.id)
        page = favourites.list_all(conn, user_id=user.id, limit=2)

        assert [item["id"] for item in page] == [item["id"] for item in everything[:2]]

    def test_an_absurd_limit_is_clamped_rather_than_obeyed(self, conn, user):
        """`?limit=` comes off a query string, so it is somebody's input."""
        add_look(conn, user)

        assert len(favourites.list_all(conn, user_id=user.id, limit=10 ** 9)) == 1
        assert favourites.list_all(conn, user_id=user.id, limit=0) == []
        assert favourites.list_all(conn, user_id=user.id, limit=-4) == []

    def test_stats_counts_each_kind_and_ignores_a_views_empty_season(self, conn, user):
        """A view has no season; the empty strings standing in for NOT NULL
        must not be counted as one."""
        add_look(conn, user)
        favourites.add(
            conn, user_id=user.id, kind="view", view_filters={"city": "Paris"}, view_name="Paris"
        )
        s = favourites.stats(conn, user_id=user.id)
        assert s["total_favourites"] == 2
        assert s["looks"] == 1
        assert s["views"] == 1
        assert s["unique_seasons"] == 1


class TestFavouritesIsolation:
    def test_one_user_cannot_see_anothers(self, conn, user, other_user):
        add_look(conn, user)
        assert favourites.list_all(conn, user_id=other_user.id) == []

    def test_two_users_can_favourite_the_same_look(self, conn, user, other_user):
        """The uniqueness constraint is per user, not global."""
        assert add_look(conn, user) is True
        assert add_look(conn, other_user) is True

    def test_one_user_cannot_remove_anothers(self, conn, user, other_user):
        add_look(conn, user)
        removed = favourites.remove(
            conn,
            user_id=other_user.id,
            season_url=SEASON["url"],
            collection_url=COLLECTION["url"],
            look_number=12,
        )
        assert removed is False
        assert len(favourites.list_all(conn, user_id=user.id)) == 1

    def test_exists_is_scoped_to_the_user(self, conn, user, other_user):
        add_look(conn, user)
        assert (
            favourites.exists(
                conn,
                user_id=other_user.id,
                season_url=SEASON["url"],
                collection_url=COLLECTION["url"],
                look_number=12,
            )
            is False
        )

    def test_deleting_a_user_removes_their_favourites(self, conn, user):
        add_look(conn, user)
        repo.delete_user(conn, user.id)
        assert conn.execute("SELECT count(*) FROM favourites").fetchone()[0] == 0


class TestCollectionId:
    """The better identity for a show, available on every favourite.

    Two phase-3 bugs were one show under two URL spellings. The rest of the
    page long ago moved to firstVIEW's integer id; this column puts it on the
    table that still keys on URLs, so the switch has something to switch to.
    Nothing keys on it yet — see TestTheKeyIsUnchanged.
    """

    def look_at(self, conn, user, url, number=12):
        return favourites.add(
            conn,
            user_id=user.id,
            season=SEASON,
            collection={"designer": "Balenciaga", "url": url},
            look={"number": number, "total": 48},
            image_path="/api/images/x.jpg",
        )

    def ids(self, conn, user):
        return {
            (row["collection"]["url"], row["collection"]["id"])
            for row in favourites.list_all(conn, user_id=user.id)
        }

    def test_a_saved_look_carries_the_shows_id(self, conn, user):
        self.look_at(conn, user, LIST_URL)
        assert self.ids(conn, user) == {(LIST_URL, SHOW_ID)}

    def test_a_saved_show_carries_it_too(self, conn, user):
        favourites.add(
            conn,
            user_id=user.id,
            kind="show",
            season=SEASON,
            collection={"designer": "Balenciaga", "url": LIST_URL},
            image_path="/api/images/x.jpg",
        )
        assert self.ids(conn, user) == {(LIST_URL, SHOW_ID)}

    def test_a_saved_view_has_no_show_and_stores_null(self, conn, user):
        """A view is a slice of the archive, not a run. Its collection_url is
        the empty string the NOT NULL column needs, and the empty string names
        no show — so the id is null rather than '' or a stand-in."""
        favourites.add(
            conn, user_id=user.id, kind="view", view_filters={"city": "Paris"},
            view_name="Paris",
        )
        assert self.ids(conn, user) == {("", None)}

    def test_a_url_that_names_no_show_stores_null(self, conn, user):
        """Null is the honest answer. A guess would be worse than nothing, and
        the row is kept exactly as it is either way."""
        add_look(conn, user)
        assert self.ids(conn, user) == {(COLLECTION["url"], None)}

    def test_the_two_spellings_of_one_show_agree_on_which_show(self, conn, user):
        """The whole point. `?id=NNN` and `?id=NNN&list=all` are the two URLs
        that made one show two favourites; they are still two rows, and they
        now say the same thing about which show they are."""
        self.look_at(conn, user, LIST_URL)
        self.look_at(conn, user, DRAWER_URL)
        rows = favourites.list_all(conn, user_id=user.id)
        assert len(rows) == 2
        assert {row["collection"]["id"] for row in rows} == {SHOW_ID}

    # ------------------------------------------------- the pair must agree ---

    def test_the_url_cannot_be_moved_without_the_id(self, conn, user):
        """The consistency check, doing its job. An UPDATE that repoints a
        favourite at another show without moving the id is the beginning of two
        identities for one row, and the database refuses it."""
        self.look_at(conn, user, LIST_URL)
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute(
                    "UPDATE favourites SET collection_url = "
                    "'https://www.firstview.com/collection_images.php?id=999&list=all'"
                )

    def test_the_id_cannot_be_moved_without_the_url(self, conn, user):
        self.look_at(conn, user, LIST_URL)
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute("UPDATE favourites SET collection_id = '999'")

    def test_an_insert_that_writes_its_own_id_is_refused(self, conn, user):
        """Nothing in favourites.py can do this — `add` derives the id inside
        the INSERT — but psql can, and the albums migration will be able to.
        The check is in the database for exactly that reason."""
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute(
                    """
                    INSERT INTO favourites (user_id, kind, season_name, season_url,
                        collection_designer, collection_url, collection_id,
                        look_number, image_path)
                    VALUES (%s, 'look', 'F24', 's', 'B', %s, '999', 12, '/i.jpg')
                    """,
                    (user.id, LIST_URL),
                )

    def test_moving_both_together_is_allowed(self, conn, user):
        """The check forbids disagreement, not change."""
        self.look_at(conn, user, LIST_URL)
        other = "https://www.firstview.com/collection_images.php?id=999&list=all"
        conn.execute(
            "UPDATE favourites SET collection_url = %s, collection_id = '999'", (other,)
        )
        assert self.ids(conn, user) == {(other, "999")}

    # ------------------------------------------ one rule, in two languages ---

    @pytest.mark.parametrize(
        "url,expected",
        [
            (LIST_URL, SHOW_ID),
            (DRAWER_URL, SHOW_ID),
            ("https://www.firstview.com/collection_images.php?list=all&id=7", "7"),
            ("https://www.firstview.com/collection_images.php?id=7#top", "7"),
            ("https://www.firstview.com/collection_images.php?collection=7", "7"),
            # `id` wins when a url somehow carries both, as it does in Python.
            ("https://www.firstview.com/x.php?collection=7&id=9", "9"),
            ("", None),
            ("https://example.com/balenciaga-f24", None),
            ("https://www.firstview.com/collection_images.php?id=", None),
            # Not a firstVIEW id: `xid` is not `id`, and `7a` is not a number.
            ("https://www.firstview.com/collection_images.php?xid=7", None),
            ("https://www.firstview.com/collection_images.php?id=7a", None),
            ("collection_images.php?id=7", "7"),
            ("id=7", None),
        ],
    )
    def test_the_database_rule_is_the_python_rule(self, conn, url, expected):
        """schema.sql derives the id in SQL; firstview.collection_id_from_url
        derives it in Python. Two spellings of one rule is the bug class this
        column exists to end, so the two are held to the same case table —
        including the two places they deliberately part company, where Python
        would return something that is not a firstVIEW id at all.
        """
        got = conn.execute(
            "SELECT favourites_collection_id(%s)", (url,)
        ).fetchone()[0]
        assert got == expected

        python = fv.collection_id_from_url(url)
        if python is not None and python.isdigit():
            assert got == python
        else:
            assert got is None

    # ------------------------------------------------------- the backfill ---

    def legacy_row(self, conn, user, url, number):
        """One favourite as it was stored before this column existed."""
        conn.execute(
            """
            INSERT INTO favourites (user_id, kind, season_name, season_url,
                season_link_text, collection_designer, collection_url,
                look_number, look_total, image_path, notes)
            VALUES (%s, 'look', 'Fall 2024', %s, 'F24', 'Balenciaga', %s,
                    %s, 48, '/api/images/x.jpg', 'kept')
            """,
            (user.id, SEASON["url"], url, number),
        )

    def rows(self, conn):
        return conn.execute(
            "SELECT id, collection_url, collection_id, season_url, look_number, notes "
            "FROM favourites ORDER BY id"
        ).fetchall()

    def test_the_backfill_fills_rows_that_predate_the_column(self, conn, user):
        """A database with favourites in it takes the change: every row keeps
        its identity, the id is right where it is derivable and null where it
        is not, and applying the file again changes nothing.

        The column is dropped first so this is the real path a deployed
        database takes, not a simulation of it. All of it is inside the test's
        transaction, which is rolled back.
        """
        conn.execute("ALTER TABLE favourites DROP COLUMN collection_id")
        self.legacy_row(conn, user, LIST_URL, 12)
        self.legacy_row(conn, user, DRAWER_URL, 12)
        self.legacy_row(conn, user, "https://example.com/not-a-show", 3)
        self.legacy_row(conn, user, "", 4)
        before = conn.execute(
            "SELECT id, collection_url, season_url, look_number, notes "
            "FROM favourites ORDER BY id"
        ).fetchall()

        conn.execute(USERDATA_SCHEMA)
        first = self.rows(conn)

        # Same rows, same ids, nothing but the new column touched.
        assert [(r[0], r[1], r[3], r[4], r[5]) for r in first] == before
        assert [r[2] for r in first] == [SHOW_ID, SHOW_ID, None, None]

        # And again, and again. Nothing moves.
        conn.execute(USERDATA_SCHEMA)
        assert self.rows(conn) == first
        conn.execute(USERDATA_SCHEMA)
        assert self.rows(conn) == first

    def test_the_backfill_repairs_a_row_whose_id_went_stale(self, conn, user):
        """The reason this is a plain column and not GENERATED ALWAYS AS: a
        generated column would never recompute if the rule changed, while this
        statement reapplies it to the whole table on the next boot."""
        conn.execute("ALTER TABLE favourites DROP COLUMN collection_id")
        self.legacy_row(conn, user, LIST_URL, 12)
        conn.execute("ALTER TABLE favourites ADD COLUMN collection_id text")
        conn.execute("UPDATE favourites SET collection_id = 'wrong'")

        conn.execute(USERDATA_SCHEMA)
        assert [r[2] for r in self.rows(conn)] == [SHOW_ID]


class TestTheKeyIsUnchanged:
    """This task made a better identity available. It did not switch to it.

    Re-keying is not reversible and needs a merge strategy for the duplicate
    rows already in production, so the three unique indexes stay exactly as
    they were and these tests say so out loud.
    """

    def test_two_spellings_of_one_show_are_still_two_favourites(self, conn, user):
        """Not a bug being asserted as correct — a scope line. The duplicates
        phase 3 left behind are still duplicates, and merging them is the next
        change, not this one."""
        for url in (LIST_URL, DRAWER_URL):
            favourites.add(
                conn,
                user_id=user.id,
                season=SEASON,
                collection={"designer": "Balenciaga", "url": url},
                look={"number": 12, "total": 48},
                image_path="/api/images/x.jpg",
            )
        assert len(favourites.list_all(conn, user_id=user.id)) == 2

    def test_the_indexes_are_the_url_ones(self, conn, user):
        keyed = dict(
            conn.execute(
                """
                SELECT indexname, indexdef FROM pg_indexes
                WHERE tablename = 'favourites'
                  AND indexname IN ('favourites_look_key', 'favourites_show_key',
                                    'favourites_view_key')
                """
            ).fetchall()
        )
        assert set(keyed) == {
            "favourites_look_key",
            "favourites_show_key",
            "favourites_view_key",
        }
        for name, definition in keyed.items():
            assert "collection_id" not in definition, name
        assert "look_number" in keyed["favourites_look_key"]
        assert "collection_url" in keyed["favourites_show_key"]


class TestFollowing:
    def test_follow_then_list(self, conn, user):
        following.follow(conn, user_id=user.id, brand_id="acne", brand_name="Acne Studios")
        brands = following.list_following(conn, user_id=user.id)
        assert len(brands) == 1
        assert brands[0]["brand_name"] == "Acne Studios"

    def test_following_twice_is_reported_not_duplicated(self, conn, user):
        assert following.follow(conn, user_id=user.id, brand_id="acne", brand_name="A") is True
        assert following.follow(conn, user_id=user.id, brand_id="acne", brand_name="A") is False
        assert following.count(conn, user_id=user.id) == 1

    def test_unfollow(self, conn, user):
        following.follow(conn, user_id=user.id, brand_id="acne", brand_name="A")
        assert following.unfollow(conn, user_id=user.id, brand_id="acne") is True
        assert following.count(conn, user_id=user.id) == 0

    def test_unfollowing_something_not_followed_reports_false(self, conn, user):
        assert following.unfollow(conn, user_id=user.id, brand_id="nope") is False

    def test_default_notification_preferences(self, conn, user):
        following.follow(conn, user_id=user.id, brand_id="acne", brand_name="A")
        brand = following.list_following(conn, user_id=user.id)[0]
        assert brand["notify_new_products"] is True
        assert brand["notify_price_changes"] is False

    def test_updating_one_flag_leaves_the_other_alone(self, conn, user):
        """A client sending only one preference must not silently reset the
        other to its default."""
        following.follow(conn, user_id=user.id, brand_id="acne", brand_name="A")
        following.set_notification_preferences(
            conn, user_id=user.id, brand_id="acne", notify_price_changes=True
        )
        brand = following.list_following(conn, user_id=user.id)[0]
        assert brand["notify_price_changes"] is True
        assert brand["notify_new_products"] is True  # untouched

    def test_updating_a_brand_not_followed_reports_false(self, conn, user):
        assert (
            following.set_notification_preferences(
                conn, user_id=user.id, brand_id="nope", notify_new_products=False
            )
            is False
        )

    def test_notes(self, conn, user):
        following.follow(conn, user_id=user.id, brand_id="acne", brand_name="A")
        following.set_notes(conn, user_id=user.id, brand_id="acne", notes="watch SS25")
        assert following.list_following(conn, user_id=user.id)[0]["notes"] == "watch SS25"


class TestFollowingIsolation:
    def test_one_user_cannot_see_anothers(self, conn, user, other_user):
        following.follow(conn, user_id=user.id, brand_id="acne", brand_name="A")
        assert following.list_following(conn, user_id=other_user.id) == []

    def test_two_users_can_follow_the_same_brand(self, conn, user, other_user):
        assert following.follow(conn, user_id=user.id, brand_id="acne", brand_name="A") is True
        assert (
            following.follow(conn, user_id=other_user.id, brand_id="acne", brand_name="A") is True
        )

    def test_one_user_cannot_unfollow_for_another(self, conn, user, other_user):
        following.follow(conn, user_id=user.id, brand_id="acne", brand_name="A")
        assert following.unfollow(conn, user_id=other_user.id, brand_id="acne") is False
        assert following.count(conn, user_id=user.id) == 1

    def test_deleting_a_user_removes_their_follows(self, conn, user):
        following.follow(conn, user_id=user.id, brand_id="acne", brand_name="A")
        repo.delete_user(conn, user.id)
        assert conn.execute("SELECT count(*) FROM brand_following").fetchone()[0] == 0
