"""A gallery read from a page can be cut off mid-URL; those entries are not work."""

import json

import pytest

from backend.archive.domain.product import usable_image_url
from backend.archive.runner.run import _coerce


@pytest.mark.unit
@pytest.mark.parametrize(
    "url,ok",
    [
        ("https://cdn.shopify.com/s/files/1/0608/a.jpg?v=1", True),
        ("https://esa.psylos1.com/common/2026/09/04/3b8ff7.jpg?x-oss-process=x", True),
        ("https://cdn.shopify.com", False),  # the host alone: the front of a URL
        ("https://esa.psylos1.com/common/2026/0", False),  # cut mid-path
        ("https://cdn.shopif", False),
        ("", False),
    ],
)
def test_only_whole_image_urls_count(url, ok):
    assert usable_image_url(url) is ok


@pytest.mark.unit
def test_a_truncated_tail_is_dropped_from_a_learned_gallery():
    """psylos1's theme caps the attribute at ~2048 chars, so the last URL arrives
    half-written — and because the list was *longer*, it replaced the clean one."""
    value = (
        "https://cdn.shopify.com/s/files/1/a.jpg, "
        "https://cdn.shopify.com/s/files/1/b.jpg, "
        "https://cdn.shopify.com/s/fil"
    )
    assert json.loads(_coerce("all_images", value)) == [
        "https://cdn.shopify.com/s/files/1/a.jpg",
        "https://cdn.shopify.com/s/files/1/b.jpg",
    ]


@pytest.mark.unit
def test_the_images_command_can_finish(tmp_path, capsys):
    """`summarise` was imported only in the scrape branch, which made it a local name
    for the whole function — so `images` did all its work and then raised."""
    import backend.archive.runner.cli as cli

    brands = tmp_path / "brands.yml"
    brands.write_text('brands:\n  - {domain: k.com, homepage_url: "https://k.com"}\n')
    code = cli.main(
        [
            "images",
            "k.com",
            "--objects",
            str(tmp_path / "o"),
            "--brands",
            str(brands),
            "--images-dir",
            str(tmp_path / "i"),
        ]
    )
    assert code == 0
    assert "still outstanding" in capsys.readouterr().out
