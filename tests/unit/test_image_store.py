"""Image storage: key naming, URL building, and the R2 upload call.

R2 itself is stubbed. Real credentials are not available here and would mean
these tests wrote objects into a live bucket, so what is verified is everything
under our control: that the right key is built, the right URL comes back, the
correct content type is sent, and a key cannot escape the local store's root.

The one thing this cannot prove is that Cloudflare accepts the call. That is
confirmed at deploy, with a real upload.
"""

from __future__ import annotations

import pytest
from storage.images import (
    LocalImageStore,
    R2ImageStore,
    favicon_key,
    guess_content_type,
    runway_key,
)

pytestmark = pytest.mark.unit


class StubS3:
    """Records calls the way boto3's client would receive them."""

    def __init__(self, existing=()):
        self.puts = []
        self.existing = set(existing)

    def put_object(self, **kwargs):
        self.puts.append(kwargs)
        self.existing.add(kwargs["Key"])

    def head_object(self, **kwargs):
        if kwargs["Key"] not in self.existing:
            raise Exception("NoSuchKey")


@pytest.fixture
def stub():
    return StubS3()


@pytest.fixture
def r2(stub):
    return R2ImageStore(
        account_id="acct",
        access_key_id="k",
        secret_access_key="s",
        bucket="fashion-archive",
        public_base="https://images.premiumpropogandafashion.studio",
        client=stub,
    )


class TestKeys:
    def test_runway_key_groups_by_designer(self):
        assert runway_key("Balenciaga", "look1.jpg") == "runway/Balenciaga/look1.jpg"

    def test_spaces_and_slashes_are_replaced(self):
        """A designer name goes straight into a public URL; a raw slash would
        invent a directory level and a space would need escaping everywhere."""
        assert runway_key("Comme des Garcons", "a b.jpg") == "runway/Comme_des_Garcons/a_b.jpg"
        assert "/" not in runway_key("Maison/Margiela", "x.jpg").split("/")[1]

    def test_empty_designer_does_not_produce_an_empty_segment(self):
        assert runway_key("", "x.jpg") == "runway/unknown/x.jpg"

    def test_favicon_key_normalises_the_extension(self):
        assert favicon_key("acne", ".ico") == "favicons/acne.ico"
        assert favicon_key("acne", "png") == "favicons/acne.png"

    def test_traversal_characters_do_not_survive(self):
        """Filenames come from scraped URLs, so `../` is a real input."""
        assert ".." not in runway_key("d", "../../etc/passwd")


class TestContentType:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("a.jpg", "image/jpeg"),
            ("a.png", "image/png"),
            ("a.webp", "image/webp"),
            ("a.ico", "image/x-icon"),
        ],
    )
    def test_guessed_from_extension(self, name, expected):
        assert guess_content_type(name) == expected

    def test_unknown_extension_falls_back(self):
        assert guess_content_type("a.unknown") == "application/octet-stream"


class TestR2ImageStore:
    def test_save_returns_the_public_cdn_url(self, r2):
        """Not an API URL. Image loads must never touch the app server — that
        is what makes R2's free egress worth having."""
        url = r2.save("runway/Balenciaga/look1.jpg", b"bytes")
        assert url == "https://images.premiumpropogandafashion.studio/runway/Balenciaga/look1.jpg"

    def test_save_uploads_to_the_right_bucket_and_key(self, r2, stub):
        r2.save("runway/D/look1.jpg", b"bytes")
        assert stub.puts[0]["Bucket"] == "fashion-archive"
        assert stub.puts[0]["Key"] == "runway/D/look1.jpg"
        assert stub.puts[0]["Body"] == b"bytes"

    def test_content_type_is_set_from_the_key(self, r2, stub):
        """R2 serves objects with the type they were uploaded with; the wrong
        one makes the browser download the file instead of showing it."""
        r2.save("runway/D/look1.png", b"bytes")
        assert stub.puts[0]["ContentType"] == "image/png"

    def test_explicit_content_type_wins(self, r2, stub):
        r2.save("runway/D/x", b"bytes", content_type="image/avif")
        assert stub.puts[0]["ContentType"] == "image/avif"

    def test_url_encodes_awkward_characters_but_keeps_separators(self, r2):
        url = r2.url_for("runway/Comme des/look 1.jpg")
        assert "%20" in url
        assert url.count("/") == 5  # https:// + host + 3 path segments

    def test_exists_reports_stored_objects(self, r2):
        assert r2.exists("runway/D/x.jpg") is False
        r2.save("runway/D/x.jpg", b"bytes")
        assert r2.exists("runway/D/x.jpg") is True


class TestLocalImageStore:
    @pytest.fixture
    def local(self, tmp_path):
        return LocalImageStore(root=tmp_path, api_base="http://localhost:8081")

    def test_save_writes_the_file(self, local, tmp_path):
        local.save("runway/D/look1.jpg", b"bytes")
        assert (tmp_path / "runway/D/look1.jpg").read_bytes() == b"bytes"

    def test_save_returns_an_api_url(self, local):
        assert local.save("runway/D/look1.jpg", b"x") == (
            "http://localhost:8081/api/images/runway/D/look1.jpg"
        )

    def test_round_trips(self, local):
        local.save("runway/D/look1.jpg", b"bytes")
        assert local.read("runway/D/look1.jpg") == b"bytes"

    def test_missing_file_reads_as_none(self, local):
        assert local.read("runway/D/nope.jpg") is None

    def test_creates_intermediate_directories(self, local):
        local.save("a/b/c/d.jpg", b"x")
        assert local.exists("a/b/c/d.jpg")

    @pytest.mark.parametrize(
        "evil",
        [
            "../escaped.jpg",
            "runway/../../escaped.jpg",
            "../../../../../../etc/passwd",
        ],
    )
    def test_keys_cannot_escape_the_root(self, local, evil):
        """Keys reach this from request paths, so traversal is a real input.
        The old endpoint took an absolute path from the client and read it."""
        with pytest.raises(ValueError):
            local.save(evil, b"x")

    def test_root_is_absolute_regardless_of_cwd(self, tmp_path):
        """The old cache directory was relative to the working directory, so
        starting the server elsewhere wrote images somewhere unexpected."""
        store = LocalImageStore(root=tmp_path / "imgs", api_base="http://x")
        store.save("a.jpg", b"x")
        assert (tmp_path / "imgs" / "a.jpg").is_file()
