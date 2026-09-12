"""The image pass: what it fetches, what it refuses to fetch twice, and where it stops."""

import hashlib
import json
import pathlib

import httpx
import pytest

from backend.archive.budget import HostBudget
from backend.archive.domain.brand import Brand
from backend.archive.domain.product import ProductRecord
from backend.archive.domain.run import Coverage
from backend.archive.runner.archive_images import (
    _resolve,
    archive_all,
    archive_brand,
    outstanding,
)
from backend.archive.store.catalog import Catalog
from backend.storage.images import LocalImageStore

COV = Coverage(extracted=2, channel_counts={}, coverage_pct=1.0, field_fill={}, verdict="ok")
JPEG = b"\xff\xd8\xff\xe0FAKEJPEG"


def product(slug, images):
    return ProductRecord(
        itemurl=f"https://kuurth.com/products/{slug}",
        product_title=slug,
        main_image_url=images[0],
        all_images=json.dumps(images),
    )


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "catalog.db"
    catalog = Catalog(path)
    catalog.upsert_brand(Brand(domain="kuurth.com", homepage_url="https://kuurth.com"))
    run = catalog.open_run("kuurth.com", "full")
    catalog.record_product(
        "kuurth.com", run, product("nemo", ["https://cdn.x/a.jpg", "https://cdn.x/b.jpg"]), None
    )
    catalog.record_product("kuurth.com", run, product("dory", ["https://cdn.x/c.jpg"]), None)
    catalog.finalize_run(run, 0, COV)
    catalog.close()
    return path


@pytest.fixture()
def sink(tmp_path):
    return LocalImageStore(root=tmp_path / "images", api_base="http://api.test")


def serving(counter, body=JPEG, status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        counter.append(str(request.url))
        return httpx.Response(
            status, content=body, headers={"content-type": "image/jpeg"} if status == 200 else {}
        )

    return handler


@pytest.fixture(autouse=True)
def no_network(monkeypatch, request):
    """Every fetch in this module goes through a mock; a real one would be a bug."""
    counter: list[str] = []
    import backend.archive.transport as transport_module

    original = transport_module.httpx.Client

    def client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(serving(counter))
        return original(*args, **kwargs)

    monkeypatch.setattr(transport_module.httpx, "Client", client)
    request.node.fetched = counter
    return counter


@pytest.mark.unit
def test_the_pass_stores_every_image_the_products_name(db, sink, no_network):
    out = archive_brand("kuurth.com", db, sink, HostBudget(gap=0))
    assert out.fetched == 3
    assert out.outstanding == 0
    assert len(no_network) == 3

    catalog = Catalog(db)
    assert catalog.stored_image_count("kuurth.com") == 3
    assert sorted(catalog.archived_images("kuurth.com")) == [
        "https://kuurth.com/products/dory",
        "https://kuurth.com/products/nemo",
    ]


@pytest.mark.unit
def test_a_second_pass_asks_for_nothing(db, sink, no_network):
    archive_brand("kuurth.com", db, sink, HostBudget(gap=0))
    before = len(no_network)
    again = archive_brand("kuurth.com", db, sink, HostBudget(gap=0))
    assert again.fetched == 0
    assert len(no_network) == before


@pytest.mark.unit
def test_a_killed_pass_resumes_from_what_is_missing(db, sink, no_network):
    # No resume file and nothing to reconcile: the work is recomputed from the catalogue
    # every time, so an interrupted pass loses only the request in flight.
    first = archive_brand("kuurth.com", db, sink, HostBudget(gap=0), limit=1)
    assert first.fetched == 1
    assert first.outstanding == 2

    rest = archive_brand("kuurth.com", db, sink, HostBudget(gap=0))
    assert rest.fetched == 2
    assert rest.outstanding == 0


@pytest.mark.unit
def test_outstanding_counts_what_is_left_without_fetching(db, sink, no_network):
    catalog = Catalog(db)
    assert outstanding(catalog, "kuurth.com") == 3
    assert no_network == []


@pytest.mark.unit
def test_bytes_already_on_disk_are_adopted_rather_than_refetched(db, sink, tmp_path, no_network):
    """An earlier run left 1,585 photographs in a directory. Asking the shops for them
    again to move them into the bucket would be a request none of them owes us."""
    on_disk = tmp_path / "old.jpg"
    on_disk.write_bytes(JPEG)
    catalog = Catalog(db)
    pid = catalog.product_id_for("kuurth.com", "https://kuurth.com/products/nemo")
    catalog.record_image(pid, "https://cdn.x/a.jpg", str(on_disk), "whatever")
    catalog.close()

    out = archive_brand("kuurth.com", db, sink, HostBudget(gap=0))
    assert out.adopted == 1
    assert out.fetched == 2
    assert "https://cdn.x/a.jpg" not in no_network
    key = f"archive/kuurth.com/{hashlib.sha256(JPEG).hexdigest()[:2]}/"
    assert sink.exists(f"{key}{hashlib.sha256(JPEG).hexdigest()}.jpg")


@pytest.mark.unit
def test_one_brand_failing_does_not_end_the_pass(db, sink, monkeypatch):
    import backend.archive.runner.archive_images as module

    def explode(domain, *a, **kw):
        if domain == "broken.com":
            raise RuntimeError("its CDN is on fire")
        return module.Outcome(domain, fetched=1)

    monkeypatch.setattr(module, "archive_brand", explode)
    results = archive_all(["broken.com", "fine.com"], db, sink, workers=2)
    assert {r.domain for r in results} == {"broken.com", "fine.com"}
    assert sum(r.fetched for r in results) == 1


@pytest.mark.unit
def test_old_image_paths_resolve_beside_the_catalogue_not_the_cwd():
    """The photographs sit beside the database that indexes them. Resolving against the
    working directory instead made adoption fail silently from any other directory, and
    the pass quietly re-downloaded what it already had."""
    db = pathlib.Path("/srv/archive/backend/archive/data/catalog.db")
    assert _resolve("backend/archive/data/images/x/aa/b.jpg", db) == pathlib.Path(
        "/srv/archive/backend/archive/data/images/x/aa/b.jpg"
    )
    assert _resolve("/already/absolute.jpg", db) == pathlib.Path("/already/absolute.jpg")
