"""Serving images over HTTP.

Replaces `/api/image?path=<absolute path>`, which took a filesystem path from
the client and read whatever it pointed at. The endpoint now names a key inside
the store, and the store refuses keys that escape its root.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.db

from .conftest import token_from  # noqa: E402


def sign_up(client, sender, email="img@example.com"):
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "a-good-password", "display_name": "Img"},
    )
    client.get(f"/api/auth/verify?token={token_from(sender)}")
    client.post("/api/auth/login", json={"email": email, "password": "a-good-password"})


@pytest.fixture
def stored(tmp_path):
    """Point the app at a temporary local store holding one image."""
    from backend.storage import images

    previous = images.get_store()
    store = images.LocalImageStore(root=tmp_path, api_base="http://localhost:8081")
    store.save("runway/Balenciaga/look1.png", b"\x89PNG\r\n\x1a\n-fake")
    images.set_store(store)
    yield store
    images.set_store(previous)


class TestServeStoredImage:
    def test_requires_a_session(self, client, sender, stored):
        assert client.get("/api/images/runway/Balenciaga/look1.png").status_code == 401

    def test_serves_the_bytes(self, client, sender, stored):
        sign_up(client, sender)
        response = client.get("/api/images/runway/Balenciaga/look1.png")
        assert response.status_code == 200
        assert response.data.startswith(b"\x89PNG")

    def test_sets_the_content_type(self, client, sender, stored):
        """Wrong type makes the browser download the file instead of showing it."""
        sign_up(client, sender)
        response = client.get("/api/images/runway/Balenciaga/look1.png")
        assert response.mimetype == "image/png"

    def test_missing_image_is_404(self, client, sender, stored):
        sign_up(client, sender)
        assert client.get("/api/images/runway/Nope/none.png").status_code == 404

    def test_traversal_is_refused(self, client, sender, stored, tmp_path):
        """The predecessor would have read and returned this file."""
        secret = tmp_path.parent / "secret.txt"
        secret.write_text("do not serve me")
        sign_up(client, sender)
        response = client.get("/api/images/../secret.txt")
        assert response.status_code in (400, 404)
        assert b"do not serve me" not in response.data
