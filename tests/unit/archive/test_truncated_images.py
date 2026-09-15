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


@pytest.mark.unit
def test_a_truncated_query_is_retried_without_it(tmp_path):
    """psylos1's URLs carry ?x-oss-process=... cut off mid-value; the server rejects
    it, and the same path without the query serves the photograph at full size."""
    import httpx

    from backend.archive.images import ImageStore
    from backend.archive.store.catalog import Catalog
    from backend.archive.store.objects import DirectoryObjectStore
    from backend.archive.transport import HttpxTransport
    from backend.storage.images import LocalImageStore

    seen = []

    def handler(request):
        seen.append(str(request.url))
        if request.url.query:
            return httpx.Response(
                400, content=b"<Error/>", headers={"content-type": "application/xml"}
            )
        return httpx.Response(200, content=b"\xff\xd8\xff", headers={"content-type": "image/jpeg"})

    cat = Catalog(DirectoryObjectStore(tmp_path / "o"))
    images = ImageStore(LocalImageStore(root=tmp_path / "i", api_base="http://x"))
    transport = HttpxTransport(client=httpx.Client(transport=httpx.MockTransport(handler)))
    url = "https://esa.psylos1.com/a/b.jpg?x-oss-process=image%2Fresize%2Cq"

    assert images.archive_one(transport, cat, "https://k.com/p/a", "k.com", url) is True
    assert len(seen) == 2  # tried as given, then bare
    assert cat.archived_images("k.com")["https://k.com/p/a"]


@pytest.mark.unit
def test_a_photograph_that_keeps_failing_leaves_the_queue(tmp_path):
    from backend.archive.domain.product import ProductRecord
    from backend.archive.domain.run import Coverage
    from backend.archive.store.catalog import Catalog
    from backend.archive.store.objects import DirectoryObjectStore

    cat = Catalog(DirectoryObjectStore(tmp_path))
    run = cat.open_run("k.com", "full")
    cat.record_product(
        "k.com",
        run,
        ProductRecord(
            itemurl="https://k.com/p/a",
            product_title="T",
            all_images='["https://cdn.shopify.com/gone.jpg"]',
        ),
        None,
    )
    cat.finalize_run(run, 0, Coverage(extracted=1, coverage_pct=1.0, verdict="ok"))
    assert cat.images_awaiting_archive("k.com")
    for _ in range(3):
        cat.record_image_miss("k.com", "https://k.com/p/a", "https://cdn.shopify.com/gone.jpg")
    assert cat.images_awaiting_archive("k.com") == []
