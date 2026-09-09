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
    return repo.create_user(
        conn, email="one@example.com", password_hash="h", display_name="One"
    )


@pytest.fixture
def other_user(conn):
    return repo.create_user(
        conn, email="two@example.com", password_hash="h", display_name="Two"
    )


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
        """Storage moved; the JSON did not. This is what makes that true."""
        add_look(conn, user)
        item = favourites.list_all(conn, user_id=user.id)[0]
        assert set(item) == {
            "id", "season", "collection", "look", "image_path", "date_added", "notes"
        }
        assert set(item["season"]) == {"name", "url", "link_text"}
        assert set(item["collection"]) == {"designer", "url"}
        assert set(item["look"]) == {"number", "total"}

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
        assert favourites.remove(
            conn, user_id=user.id, season_url=SEASON["url"],
            collection_url=COLLECTION["url"], look_number=12
        ) is True
        assert favourites.list_all(conn, user_id=user.id) == []

    def test_removing_something_absent_reports_false(self, conn, user):
        assert favourites.remove(
            conn, user_id=user.id, season_url=SEASON["url"],
            collection_url=COLLECTION["url"], look_number=99
        ) is False

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
            conn, user_id=other_user.id, season_url=SEASON["url"],
            collection_url=COLLECTION["url"], look_number=12
        )
        assert removed is False
        assert len(favourites.list_all(conn, user_id=user.id)) == 1

    def test_exists_is_scoped_to_the_user(self, conn, user, other_user):
        add_look(conn, user)
        assert favourites.exists(
            conn, user_id=other_user.id, season_url=SEASON["url"],
            collection_url=COLLECTION["url"], look_number=12
        ) is False

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
        assert following.set_notification_preferences(
            conn, user_id=user.id, brand_id="nope", notify_new_products=False
        ) is False

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
        assert following.follow(conn, user_id=other_user.id, brand_id="acne", brand_name="A") is True

    def test_one_user_cannot_unfollow_for_another(self, conn, user, other_user):
        following.follow(conn, user_id=user.id, brand_id="acne", brand_name="A")
        assert following.unfollow(conn, user_id=other_user.id, brand_id="acne") is False
        assert following.count(conn, user_id=user.id) == 1

    def test_deleting_a_user_removes_their_follows(self, conn, user):
        following.follow(conn, user_id=user.id, brand_id="acne", brand_name="A")
        repo.delete_user(conn, user.id)
        assert conn.execute("SELECT count(*) FROM brand_following").fetchone()[0] == 0
