"""Favourites and brand following in Postgres.

The property these tests exist for is isolation. Under the old design each user
got their own SQLite file, so separation depended on constructing the right
directory name; here it depends on a WHERE clause and a foreign key. The
cross-user tests below are the ones that would have caught a missing
`user_id = %s`.
"""

from __future__ import annotations

import pytest
from auth import repository as repo
from userdata import favourites, following

pytestmark = pytest.mark.db

SEASON = {"name": "Fall 2024", "url": "https://example.com/fall-2024", "link_text": "F24"}
COLLECTION = {"designer": "Balenciaga", "url": "https://example.com/balenciaga-f24"}
LOOK = {"number": 12, "total": 48}


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
        assert set(item["collection"]) == {"designer", "url"}
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
