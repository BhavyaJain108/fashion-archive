"""Favourites and following over HTTP, with real sessions.

The repository tests prove the queries are scoped by user_id. These prove the
routes actually pass the *session's* user id and not something a client can
influence — the difference between isolation in the data layer and isolation as
experienced by two people using the site at once.
"""

from __future__ import annotations

import pytest

from .conftest import sign_in

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


class TestFavouritesOverHttp:
    def test_add_then_list(self, client):
        sign_in(client, "one@example.com")
        assert client.post("/api/favourites", json=FAVOURITE_BODY).get_json()["success"]

        items = client.get("/api/favourites").get_json()["favourites"]
        assert len(items) == 1
        assert items[0]["collection"]["designer"] == "Balenciaga"

    def test_adding_twice_reports_already_present(self, client):
        sign_in(client, "one@example.com")
        client.post("/api/favourites", json=FAVOURITE_BODY)
        body = client.post("/api/favourites", json=FAVOURITE_BODY).get_json()
        assert body["success"] is False
        assert "already" in body["message"].lower()

    def test_check_and_remove(self, client):
        sign_in(client, "one@example.com")
        client.post("/api/favourites", json=FAVOURITE_BODY)
        key = {
            "season_url": SEASON["url"],
            "collection_url": COLLECTION["url"],
            "look_number": 12,
        }

        assert client.post("/api/favourites/check", json=key).get_json()["is_favourite"]
        assert client.delete("/api/favourites", json=key).get_json()["success"]
        assert not client.post("/api/favourites/check", json=key).get_json()["is_favourite"]

    def test_stats(self, client):
        sign_in(client, "one@example.com")
        client.post("/api/favourites", json=FAVOURITE_BODY)
        stats = client.get("/api/favourites/stats").get_json()["stats"]
        assert stats["total_favourites"] == 1

    def test_cleanup_endpoint_is_gone(self, client):
        """Removed with the per-user image copies it used to tidy up."""
        sign_in(client, "one@example.com")
        assert client.post("/api/favourites/cleanup").status_code == 404

    def test_all_favourites_endpoints_need_a_session(self, client):
        assert client.get("/api/favourites").status_code == 401
        assert client.post("/api/favourites", json=FAVOURITE_BODY).status_code == 401
        assert client.get("/api/favourites/stats").status_code == 401


class TestFollowingOverHttp:
    def test_follow_then_list(self, client):
        sign_in(client, "one@example.com")
        client.post("/api/brands/follow", json={"brand_id": "acne", "brand_name": "Acne"})

        body = client.get("/api/brands/following").get_json()
        assert body["count"] == 1
        assert body["brands"][0]["brand_name"] == "Acne"

    def test_unfollow(self, client):
        sign_in(client, "one@example.com")
        client.post("/api/brands/follow", json={"brand_id": "acne", "brand_name": "Acne"})
        assert client.post("/api/brands/unfollow", json={"brand_id": "acne"}).get_json()["success"]
        assert client.get("/api/brands/following").get_json()["count"] == 0

    def test_missing_brand_id_is_a_400_not_a_500(self, client):
        sign_in(client, "one@example.com")
        assert client.post("/api/brands/follow", json={}).status_code == 400

    def test_notes_on_a_brand_not_followed_is_404(self, client):
        sign_in(client, "one@example.com")
        response = client.post("/api/brands/notes", json={"brand_id": "nope", "notes": "x"})
        assert response.status_code == 404


class TestIsolationBetweenRealSessions:
    def test_two_users_do_not_see_each_others_favourites(self, flask_app, client):
        """The test that matters: the route must use the session's user, not
        anything the request body could name."""
        sign_in(client, "one@example.com")
        client.post("/api/favourites", json=FAVOURITE_BODY)
        assert len(client.get("/api/favourites").get_json()["favourites"]) == 1

        with flask_app.test_client() as second:
            sign_in(second, "two@example.com")
            assert second.get("/api/favourites").get_json()["favourites"] == []

    def test_two_users_do_not_see_each_others_follows(self, flask_app, client):
        sign_in(client, "one@example.com")
        client.post("/api/brands/follow", json={"brand_id": "acne", "brand_name": "Acne"})

        with flask_app.test_client() as second:
            sign_in(second, "two@example.com")
            assert second.get("/api/brands/following").get_json()["count"] == 0

    def test_one_user_cannot_delete_anothers_favourite(self, flask_app, client):
        sign_in(client, "one@example.com")
        client.post("/api/favourites", json=FAVOURITE_BODY)

        with flask_app.test_client() as second:
            sign_in(second, "two@example.com")
            second.delete(
                "/api/favourites",
                json={
                    "season_url": SEASON["url"],
                    "collection_url": COLLECTION["url"],
                    "look_number": 12,
                },
            )

        assert len(client.get("/api/favourites").get_json()["favourites"]) == 1


class TestMeOperations:
    """The same rows through the registry's door: /api/me/… and the MCP tools."""

    def test_favourites_through_me(self, client):
        sign_in(client, "one@example.com")
        assert client.post("/api/me/favourites", json=FAVOURITE_BODY).get_json()["success"]
        listed = client.get("/api/me/favourites").get_json()
        assert listed["total"] == 1
        keys = client.get("/api/me/favourites?fields=keys").get_json()["keys"]
        assert len(keys) == 1
        assert (
            client.get("/api/me/favourites?fields=stats").get_json()["stats"]["total_favourites"]
            == 1
        )
        key = {"season_url": SEASON["url"], "collection_url": COLLECTION["url"], "look_number": 12}
        assert client.delete("/api/me/favourites", json=key).get_json()["success"]
        assert client.get("/api/me/favourites").get_json()["total"] == 0

    def test_a_bad_kind_is_a_400_with_a_code(self, client):
        sign_in(client, "one@example.com")
        r = client.get("/api/me/favourites?kind=hat")
        assert r.status_code == 400
        assert r.get_json()["code"] == "BAD_REQUEST"

    def test_following_is_one_put(self, client):
        sign_in(client, "one@example.com")
        first = client.put("/api/me/following/acne", json={"brand_name": "Acne"}).get_json()
        assert first["created"] is True
        again = client.put(
            "/api/me/following/acne", json={"notes": "the denim", "notify_new_products": True}
        ).get_json()
        assert again["created"] is False
        rows = client.get("/api/me/following").get_json()["brands"]
        assert rows[0]["brand_id"] == "acne" and rows[0]["notes"] == "the denim"
        assert rows[0]["notify_new_products"] is True
        assert client.delete("/api/me/following/acne").get_json()["success"]
        assert client.get("/api/me/following").get_json()["count"] == 0

    def test_me_is_per_person(self, client):
        sign_in(client, "one@example.com")
        client.put("/api/me/following/acne", json={})
        sign_in(client, "two@example.com")
        assert client.get("/api/me/following").get_json()["count"] == 0

    def test_mcp_lists_and_calls_the_same_operations(self, client):
        sign_in(client, "one@example.com")
        listed = client.post(
            "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        ).get_json()
        names = {t["name"] for t in listed["result"]["tools"]}
        assert {"me_favourites", "me_follow", "catalogue_products", "dev_brand_action"} <= names
        called = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "me_follow", "arguments": {"brand": "acne"}},
            },
        ).get_json()
        assert called["result"]["structuredContent"]["created"] is True
        # the dev tool is the owner's: a plain session is refused
        refused = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "dev_brand_action",
                    "arguments": {"brand": "acne.com", "action": "run"},
                },
            },
        ).get_json()
        assert refused["error"]["message"].startswith("not an owner")

    def test_mcp_needs_a_session_or_the_token(self, client, monkeypatch):
        assert (
            client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code
            == 401
        )
        monkeypatch.setenv("MCP_TOKEN", "s3cret")
        ok = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Authorization": "Bearer s3cret"},
        )
        assert ok.status_code == 200 and ok.get_json()["result"] == {}
        assert client.get("/api/docs").status_code == 401
