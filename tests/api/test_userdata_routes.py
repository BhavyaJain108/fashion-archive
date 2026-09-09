"""Favourites and following over HTTP, with real sessions.

The repository tests prove the queries are scoped by user_id. These prove the
routes actually pass the *session's* user id and not something a client can
influence — the difference between isolation in the data layer and isolation as
experienced by two people using the site at once.
"""

from __future__ import annotations

import pytest

from .conftest import token_from

pytestmark = pytest.mark.db

SEASON = {"name": "Fall 2024", "url": "https://example.com/f24", "link_text": "F24"}
COLLECTION = {"designer": "Balenciaga", "url": "https://example.com/balenciaga-f24"}
LOOK = {"number": 12, "total": 48}

FAVOURITE_BODY = {
    "season": SEASON,
    "collection": COLLECTION,
    "look": LOOK,
    "image_path": "/api/images/balenciaga/f24/look12.jpg",
    "notes": "",
}


def sign_up(client, sender, email):
    """Register, verify and log in — leaving the client holding a session."""
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "a-good-password", "display_name": email},
    )
    client.get(f"/api/auth/verify?token={token_from(sender)}")
    client.post("/api/auth/login", json={"email": email, "password": "a-good-password"})


class TestFavouritesOverHttp:
    def test_add_then_list(self, client, sender):
        sign_up(client, sender, "one@example.com")
        assert client.post("/api/favourites", json=FAVOURITE_BODY).get_json()["success"]

        items = client.get("/api/favourites").get_json()["favourites"]
        assert len(items) == 1
        assert items[0]["collection"]["designer"] == "Balenciaga"

    def test_adding_twice_reports_already_present(self, client, sender):
        sign_up(client, sender, "one@example.com")
        client.post("/api/favourites", json=FAVOURITE_BODY)
        body = client.post("/api/favourites", json=FAVOURITE_BODY).get_json()
        assert body["success"] is False
        assert "already" in body["message"].lower()

    def test_check_and_remove(self, client, sender):
        sign_up(client, sender, "one@example.com")
        client.post("/api/favourites", json=FAVOURITE_BODY)
        key = {
            "season_url": SEASON["url"],
            "collection_url": COLLECTION["url"],
            "look_number": 12,
        }

        assert client.post("/api/favourites/check", json=key).get_json()["is_favourite"]
        assert client.delete("/api/favourites", json=key).get_json()["success"]
        assert not client.post("/api/favourites/check", json=key).get_json()["is_favourite"]

    def test_stats(self, client, sender):
        sign_up(client, sender, "one@example.com")
        client.post("/api/favourites", json=FAVOURITE_BODY)
        stats = client.get("/api/favourites/stats").get_json()["stats"]
        assert stats["total_favourites"] == 1

    def test_cleanup_endpoint_is_gone(self, client, sender):
        """Removed with the per-user image copies it used to tidy up."""
        sign_up(client, sender, "one@example.com")
        assert client.post("/api/favourites/cleanup").status_code == 404

    def test_all_favourites_endpoints_need_a_session(self, client, sender):
        assert client.get("/api/favourites").status_code == 401
        assert client.post("/api/favourites", json=FAVOURITE_BODY).status_code == 401
        assert client.get("/api/favourites/stats").status_code == 401


class TestFollowingOverHttp:
    def test_follow_then_list(self, client, sender):
        sign_up(client, sender, "one@example.com")
        client.post("/api/brands/follow", json={"brand_id": "acne", "brand_name": "Acne"})

        body = client.get("/api/brands/following").get_json()
        assert body["count"] == 1
        assert body["brands"][0]["brand_name"] == "Acne"

    def test_unfollow(self, client, sender):
        sign_up(client, sender, "one@example.com")
        client.post("/api/brands/follow", json={"brand_id": "acne", "brand_name": "Acne"})
        assert client.post("/api/brands/unfollow", json={"brand_id": "acne"}).get_json()["success"]
        assert client.get("/api/brands/following").get_json()["count"] == 0

    def test_missing_brand_id_is_a_400_not_a_500(self, client, sender):
        sign_up(client, sender, "one@example.com")
        assert client.post("/api/brands/follow", json={}).status_code == 400

    def test_notes_on_a_brand_not_followed_is_404(self, client, sender):
        sign_up(client, sender, "one@example.com")
        response = client.post("/api/brands/notes", json={"brand_id": "nope", "notes": "x"})
        assert response.status_code == 404


class TestIsolationBetweenRealSessions:
    def test_two_users_do_not_see_each_others_favourites(self, flask_app, client, sender):
        """The test that matters: the route must use the session's user, not
        anything the request body could name."""
        sign_up(client, sender, "one@example.com")
        client.post("/api/favourites", json=FAVOURITE_BODY)
        assert len(client.get("/api/favourites").get_json()["favourites"]) == 1

        with flask_app.test_client() as second:
            sign_up(second, sender, "two@example.com")
            assert second.get("/api/favourites").get_json()["favourites"] == []

    def test_two_users_do_not_see_each_others_follows(self, flask_app, client, sender):
        sign_up(client, sender, "one@example.com")
        client.post("/api/brands/follow", json={"brand_id": "acne", "brand_name": "Acne"})

        with flask_app.test_client() as second:
            sign_up(second, sender, "two@example.com")
            assert second.get("/api/brands/following").get_json()["count"] == 0

    def test_one_user_cannot_delete_anothers_favourite(self, flask_app, client, sender):
        sign_up(client, sender, "one@example.com")
        client.post("/api/favourites", json=FAVOURITE_BODY)

        with flask_app.test_client() as second:
            sign_up(second, sender, "two@example.com")
            second.delete(
                "/api/favourites",
                json={
                    "season_url": SEASON["url"],
                    "collection_url": COLLECTION["url"],
                    "look_number": 12,
                },
            )

        assert len(client.get("/api/favourites").get_json()["favourites"]) == 1
