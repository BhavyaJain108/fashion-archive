import hashlib

import httpx
import pytest

from backend.archive.domain.brand import Brand
from backend.archive.domain.product import ProductRecord
from backend.archive.images import ImageStore
from backend.archive.store.catalog import Catalog
from backend.archive.transport import HttpxTransport
from backend.storage.images import LocalImageStore

JPEG_BYTES = b"\xff\xd8\xff\xe0FAKEJPEG"
SHA = hashlib.sha256(JPEG_BYTES).hexdigest()


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
    sink = LocalImageStore(root=tmp_path / "images", api_base="http://api.test")
    return cat, pid, ImageStore(sink), sink, tmp_path


@pytest.mark.unit
def test_archive_stores_content_addressed_bytes_and_records_the_url(env):
    cat, pid, store, sink, _ = env
    counter: dict = {}
    saved = store.archive(
        make_transport(counter), cat, pid, "kuurth.com", ["https://cdn.shopify.com/nemo-1.jpg"]
    )
    assert saved == 1
    key = f"archive/kuurth.com/{SHA[:2]}/{SHA}.jpg"
    assert sink.read(key) == JPEG_BYTES
    # The URL is what travels. A path under one laptop's home directory was never
    # something another machine could use.
    assert cat.archived_images("kuurth.com") == {
        "https://kuurth.com/products/nemo": [f"http://api.test/api/images/{key}"]
    }


@pytest.mark.unit
def test_known_urls_are_never_redownloaded(env):
    """Delta economics: an unchanged image costs zero requests on re-runs."""
    cat, pid, store, _, _ = env
    counter: dict = {}
    t = make_transport(counter)
    store.archive(t, cat, pid, "kuurth.com", ["https://cdn.shopify.com/nemo-1.jpg"])
    saved = store.archive(t, cat, pid, "kuurth.com", ["https://cdn.shopify.com/nemo-1.jpg"])
    assert saved == 0
    assert counter["https://cdn.shopify.com/nemo-1.jpg"] == 1


@pytest.mark.unit
def test_width_param_appended_for_shopify_cdn(env):
    """Storage policy: fetch resized renditions from Shopify's CDN, not 3000px originals."""
    cat, pid, _, sink, _ = env
    store = ImageStore(sink, width=1200)
    counter: dict = {}
    store.archive(
        make_transport(counter), cat, pid, "kuurth.com", ["https://cdn.shopify.com/nemo-1.jpg?v=3"]
    )
    assert "https://cdn.shopify.com/nemo-1.jpg?v=3&width=1200" in counter
    # DB records the ORIGINAL url so dedupe/backfill stay stable
    assert cat.known_image_urls(pid) == {"https://cdn.shopify.com/nemo-1.jpg?v=3"}


@pytest.mark.unit
def test_non_shopify_urls_are_fetched_unmodified(env):
    cat, pid, _, sink, _ = env
    store = ImageStore(sink, width=1200)
    counter: dict = {}
    store.archive(
        make_transport(counter), cat, pid, "kuurth.com", ["https://img.example.com/a.jpg"]
    )
    assert "https://img.example.com/a.jpg" in counter


@pytest.mark.unit
def test_bad_response_is_skipped_not_fatal(env):
    cat, pid, store, _, _ = env
    t = HttpxTransport(
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    )
    assert store.archive(t, cat, pid, "kuurth.com", ["https://cdn.shopify.com/gone.jpg"]) == 0


@pytest.mark.unit
def test_identical_bytes_are_uploaded_once(env):
    """Two products photographed against the same background share renditions; the key is
    the hash, so the second one costs a HEAD and no upload."""
    cat, pid, store, sink, _ = env
    uploads = []
    original = sink.save

    def counting_save(key, data, **kw):
        uploads.append(key)
        return original(key, data, **kw)

    sink.save = counting_save
    counter: dict = {}
    t = make_transport(counter)
    store.archive(t, cat, pid, "kuurth.com", ["https://cdn.shopify.com/nemo-1.jpg"])
    store.archive(t, cat, pid, "kuurth.com", ["https://cdn.shopify.com/nemo-2.jpg"])
    assert len(uploads) == 1


@pytest.mark.unit
def test_adopt_moves_a_file_an_earlier_run_left_on_disk(env, tmp_path):
    """1,585 photographs were already fetched once. Asking 30 shops for them again to
    move them into the bucket would be a request none of them owes us."""
    cat, pid, store, sink, _ = env
    old = tmp_path / "old" / "nemo.jpg"
    old.parent.mkdir()
    old.write_bytes(JPEG_BYTES)

    assert store.adopt(cat, pid, "kuurth.com", "https://cdn.shopify.com/nemo-1.jpg", old) is True
    key = f"archive/kuurth.com/{SHA[:2]}/{SHA}.jpg"
    assert sink.read(key) == JPEG_BYTES
    assert cat.stored_image_urls(pid) == {"https://cdn.shopify.com/nemo-1.jpg"}


@pytest.mark.unit
def test_adopt_reports_a_file_that_is_gone_rather_than_raising(env, tmp_path):
    cat, pid, store, _, _ = env
    missing = tmp_path / "not-here.jpg"
    assert store.adopt(cat, pid, "kuurth.com", "https://cdn.shopify.com/x.jpg", missing) is False
