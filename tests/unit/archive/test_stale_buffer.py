import pytest

from backend.archive.domain.brand import Brand
from backend.archive.domain.product import ProductRecord
from backend.archive.store.catalog import Catalog
from backend.archive.store.objects import DirectoryObjectStore


def rec(url="https://k.com/p/a"):
    return ProductRecord(
        itemurl=url,
        product_title="Tee",
        price=40.0,
        in_stock=True,
        main_image_url="https://cdn.x/a.jpg",
        all_images='["https://cdn.x/a.jpg"]',
    )


@pytest.mark.unit
def test_a_long_lived_catalog_does_not_clobber_another_instances_write(tmp_path):
    store = DirectoryObjectStore(tmp_path)
    worker = Catalog(store)  # the daemon's long-lived handle
    worker.upsert_brand(Brand(domain="k.com", homepage_url="https://k.com"))

    r1 = worker.open_run("k.com", "full")
    worker.record_product("k.com", r1, rec(), None)
    worker.finalize_run(r1, 0, None)
    worker.flush()

    # a second instance — the image pass — writes to the same brand
    other = Catalog(DirectoryObjectStore(tmp_path))
    other._catalogue("k.com")["products"]["https://k.com/p/a"]["stamp_from_other"] = True
    other._dirty.add("k.com")
    other.close()

    # the worker comes back to the same brand on its next turn
    r2 = worker.open_run("k.com", "full")
    worker.record_product("k.com", r2, rec(), None)
    worker.finalize_run(r2, 0, None)
    worker.close()

    fresh = Catalog(DirectoryObjectStore(tmp_path))
    row = fresh._catalogue("k.com")["products"]["https://k.com/p/a"]
    assert row.get("stamp_from_other") is True, "the other instance's write was lost"
