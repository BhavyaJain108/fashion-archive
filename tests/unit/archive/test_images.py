import hashlib

import httpx
import pytest

from backend.archive.domain.brand import Brand
from backend.archive.domain.product import ProductRecord
from backend.archive.images import ImageStore
from backend.archive.store.catalog import Catalog
from backend.archive.transport import HttpxTransport

JPEG_BYTES = b"\xff\xd8\xff\xe0FAKEJPEG"


def make_transport(counter: dict) -> HttpxTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        counter[str(request.url)] = counter.get(str(request.url), 0) + 1
        return httpx.Response(200, content=JPEG_BYTES, headers={"content-type": "image/jpeg"})

    return HttpxTransport(client=httpx.Client(transport=httpx.MockTransport(handler)))


@pytest.fixture()
def env(tmp_path):
    cat = Catalog(tmp_path / "catalog.db")
    cat.upsert_brand(Brand(domain="kuurth.com", homepage_url="https://kuurth.com"))
    run = cat.open_run("kuurth.com", "full")
    cat.record_product(
        "kuurth.com",
        run,
        ProductRecord(
            itemurl="https://kuurth.com/products/nemo",
            product_title="Nemo",
            all_images='["https://cdn.shopify.com/nemo-1.jpg"]',
        ),
        None,
    )
    pid = cat.product_id_for("kuurth.com", "https://kuurth.com/products/nemo")
    return cat, pid, ImageStore(tmp_path / "images"), tmp_path


@pytest.mark.unit
def test_archive_downloads_content_addressed_file(env):
    cat, pid, store, tmp = env
    counter: dict = {}
    saved = store.archive(
        make_transport(counter), cat, pid, "kuurth.com", ["https://cdn.shopify.com/nemo-1.jpg"]
    )
    assert saved == 1
    sha = hashlib.sha256(JPEG_BYTES).hexdigest()
    expected = tmp / "images" / "kuurth.com" / sha[:2] / f"{sha}.jpg"
    assert expected.read_bytes() == JPEG_BYTES
    assert cat.image_count("kuurth.com") == 1


@pytest.mark.unit
def test_known_urls_are_never_redownloaded(env):
    """Delta economics: an unchanged image costs zero requests on re-runs."""
    cat, pid, store, _ = env
    counter: dict = {}
    t = make_transport(counter)
    store.archive(t, cat, pid, "kuurth.com", ["https://cdn.shopify.com/nemo-1.jpg"])
    saved = store.archive(t, cat, pid, "kuurth.com", ["https://cdn.shopify.com/nemo-1.jpg"])
    assert saved == 0
    assert counter["https://cdn.shopify.com/nemo-1.jpg"] == 1


@pytest.mark.unit
def test_width_param_appended_for_shopify_cdn(env):
    """Storage policy: fetch resized renditions from Shopify's CDN, not 3000px originals."""
    cat, pid, store, tmp = env
    store = ImageStore(tmp / "images", width=1200)
    counter: dict = {}
    store.archive(
        make_transport(counter), cat, pid, "kuurth.com", ["https://cdn.shopify.com/nemo-1.jpg?v=3"]
    )
    assert "https://cdn.shopify.com/nemo-1.jpg?v=3&width=1200" in counter
    # DB records the ORIGINAL url so dedupe/backfill stay stable
    assert cat.known_image_urls(pid) == {"https://cdn.shopify.com/nemo-1.jpg?v=3"}


@pytest.mark.unit
def test_non_shopify_urls_are_fetched_unmodified(env):
    cat, pid, store, tmp = env
    store = ImageStore(tmp / "images", width=1200)
    counter: dict = {}
    store.archive(
        make_transport(counter), cat, pid, "kuurth.com", ["https://img.example.com/a.jpg"]
    )
    assert "https://img.example.com/a.jpg" in counter


@pytest.mark.unit
def test_bad_response_is_skipped_not_fatal(env):
    cat, pid, store, _ = env
    t = HttpxTransport(
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    )
    assert store.archive(t, cat, pid, "kuurth.com", ["https://cdn.shopify.com/gone.jpg"]) == 0
