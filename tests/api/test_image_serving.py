"""Serving images over HTTP.

Replaces `/api/image?path=<absolute path>`, which took a filesystem path from
the client and read whatever it pointed at. The endpoint now names a key inside
the store, and the store refuses keys that escape its root.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.db

from .conftest import sign_in  # noqa: E402


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
    def test_is_public(self, client, stored):
        """Deliberately open: a shared page shows its pictures to someone with
        no account. Keys are opaque, the handler is read-only and rate-limited."""
        assert client.get("/api/images/runway/Balenciaga/look1.png").status_code == 200

    def test_serves_the_bytes(self, client, stored):
        sign_in(client, "img@example.test")
        response = client.get("/api/images/runway/Balenciaga/look1.png")
        assert response.status_code == 200
        assert response.data.startswith(b"\x89PNG")

    def test_sets_the_content_type(self, client, stored):
        """Wrong type makes the browser download the file instead of showing it."""
        sign_in(client, "img@example.test")
        response = client.get("/api/images/runway/Balenciaga/look1.png")
        assert response.mimetype == "image/png"

    def test_missing_image_is_404(self, client, stored):
        sign_in(client, "img@example.test")
        assert client.get("/api/images/runway/Nope/none.png").status_code == 404

    def test_traversal_is_refused(self, client, stored, tmp_path):
        """The predecessor would have read and returned this file."""
        secret = tmp_path.parent / "secret.txt"
        secret.write_text("do not serve me")
        sign_in(client, "img@example.test")
        response = client.get("/api/images/../secret.txt")
        assert response.status_code in (400, 404)
        assert b"do not serve me" not in response.data
