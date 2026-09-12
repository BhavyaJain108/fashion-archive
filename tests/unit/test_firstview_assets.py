"""firstVIEW asset URLs: deriving the full-size image from the thumbnail.

The full-size URL is never fetched from the site — it is derived from the
thumbnail URL that the collection page already gave us. That derivation is
the single point where a whole era of the archive can go missing without
anything failing loudly, which is what these tests exist to stop.

It happened: the legacy branch rebuilt a flat `/files/photo_mid_def_{id}.jpg`
from the image id, throwing away the directory. Collections before about 2019
are served from `/files/0/{year}/{cid}/`, so every look in every older show
404ed while the file sat there under its real path. The only symptom was
per-image warnings in the browser console.

No network here. These are string transforms, and pinning them costs nothing.
"""

from __future__ import annotations

import pytest
from high_fashion.firstview import (
    SCHEME_HASHED,
    SCHEME_LEGACY,
    _full_from_hashed_thumb,
    _full_from_legacy_thumb,
    parse_collection_page,
)

pytestmark = pytest.mark.unit


class TestFullFromLegacyThumb:
    """The legacy scheme, in both the flat and foldered layouts."""

    def test_foldered_keeps_its_directory(self):
        """The regression. 2010-2018 collections live under /files/0/{year}/{cid}/."""
        thumb = "https://www.firstview.com/files/0/2010/24295/photo_thumbnail_3361660.jpg"
        assert _full_from_legacy_thumb(thumb) == (
            "https://www.firstview.com/files/0/2010/24295/photo_mid_def_3361660.jpg"
        )

    def test_flat_layout_still_works(self):
        """Newer legacy collections sit directly in /files/."""
        thumb = "https://www.firstview.com/files/photo_thumbnail_8225562.jpg"
        assert _full_from_legacy_thumb(thumb) == (
            "https://www.firstview.com/files/photo_mid_def_8225562.jpg"
        )

    def test_only_the_filename_is_rewritten(self):
        """A directory that happens to contain the token is left alone."""
        thumb = "https://www.firstview.com/files/photo_thumbnail_9/photo_thumbnail_42.jpg"
        assert _full_from_legacy_thumb(thumb) == (
            "https://www.firstview.com/files/photo_thumbnail_9/photo_mid_def_42.jpg"
        )

    def test_an_id_alone_is_not_enough(self):
        """Why the id-based builder could not have been right.

        Two collections, same filename, different directories: nothing about
        the id says which. The URL has to come off the page.
        """
        a = "https://www.firstview.com/files/0/2013/34998/photo_thumbnail_4965456.jpg"
        b = "https://www.firstview.com/files/photo_thumbnail_4965456.jpg"
        assert _full_from_legacy_thumb(a) != _full_from_legacy_thumb(b)


class TestFullFromHashedThumb:
    def test_drops_the_thumb_prefix(self):
        thumb = "https://www.firstview.com/files/53365/thumb_8562574-69e74bb7a13e4.jpg"
        assert _full_from_hashed_thumb(thumb) == (
            "https://www.firstview.com/files/53365/8562574-69e74bb7a13e4.jpg"
        )

    def test_leaves_the_hash_alone(self):
        """The hash is opaque and identical across both sizes."""
        thumb = "https://www.firstview.com/files/1/thumb_2-abc123def456.jpg"
        assert _full_from_hashed_thumb(thumb).endswith("/2-abc123def456.jpg")


def _page(*thumb_srcs: str) -> str:
    """A collection page carrying one look per thumbnail src."""
    blocks = "".join(
        f'<div class="thumbnailjt">'
        f'<img class="picture" src="{src}">'
        f'<a href="collection_image_closeup.php?of={i}&collection=99&image=1"></a>'
        f"</div>"
        for i, src in enumerate(thumb_srcs)
    )
    return f"<html><body>{blocks}</body></html>"


class TestParseCollectionPage:
    """The parser picks a scheme per look and derives the full URL from it."""

    def test_foldered_legacy_page(self):
        src = "/files/0/2016/43739/photo_thumbnail_6248330.jpg"
        coll = parse_collection_page(
            _page(src), "https://www.firstview.com/collection_images.php?id=43739"
        )
        assert len(coll.looks) == 1
        look = coll.looks[0]
        assert look.scheme == SCHEME_LEGACY
        assert look.image_id == "6248330"
        assert look.full_url == (
            "https://www.firstview.com/files/0/2016/43739/photo_mid_def_6248330.jpg"
        )

    def test_flat_legacy_page(self):
        coll = parse_collection_page(
            _page("/files/photo_thumbnail_8225562.jpg"),
            "https://www.firstview.com/collection_images.php?id=50990",
        )
        assert coll.looks[0].full_url == (
            "https://www.firstview.com/files/photo_mid_def_8225562.jpg"
        )

    def test_hashed_page(self):
        coll = parse_collection_page(
            _page("/files/53365/thumb_8562574-69e74bb7a13e4.jpg"),
            "https://www.firstview.com/collection_images.php?id=53365",
        )
        look = coll.looks[0]
        assert look.scheme == SCHEME_HASHED
        assert look.image_id == "8562574"
        assert look.full_url == ("https://www.firstview.com/files/53365/8562574-69e74bb7a13e4.jpg")

    def test_no_full_url_is_ever_a_flat_guess_from_the_id(self):
        """Every look's full URL sits in the directory its thumbnail came from."""
        srcs = [
            "/files/0/2010/24295/photo_thumbnail_3361660.jpg",
            "/files/0/2013/34998/photo_thumbnail_4965456.jpg",
            "/files/photo_thumbnail_8225562.jpg",
        ]
        coll = parse_collection_page(
            _page(*srcs), "https://www.firstview.com/collection_images.php?id=1"
        )
        for src, look in zip(srcs, coll.looks, strict=True):
            directory = src.rsplit("/", 1)[0]
            assert look.full_url.endswith(".jpg")
            assert directory in look.full_url
