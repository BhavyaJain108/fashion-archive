"""Photographs and products are flushed on separate counters and never at once."""

import threading

import pytest

from backend.archive.store.catalog import FLUSH_EVERY, Catalog
from backend.archive.store.objects import DirectoryObjectStore


@pytest.mark.unit
def test_photographs_never_flush_the_product_buffers(tmp_path):
    """record_image shared _since_flush with record_product, so a photograph could
    flush — and clear — buffers that nothing locks. Safe only because the image pass
    happened to hold its own Catalog, which is an accident, not a design."""
    cat = Catalog(DirectoryObjectStore(tmp_path))
    cat._open["k.com"] = {"products": {"u": {"record": {}}}}
    cat._dirty.add("k.com")

    for i in range(FLUSH_EVERY + 10):
        cat.record_image("k.com", f"https://k.com/p/{i}", f"https://cdn/{i}.jpg", "h")

    assert "k.com" in cat._dirty, "a photograph flushed the product buffer"
    assert cat._open["k.com"]["products"], "a photograph cleared the product buffer"


@pytest.mark.unit
def test_many_threads_flushing_at_once_do_not_trip_over_each_other(tmp_path):
    cat = Catalog(DirectoryObjectStore(tmp_path))
    errors: list[Exception] = []

    def work(n):
        try:
            for i in range(60):
                cat.record_image("k.com", f"https://k.com/p/{n}", f"https://cdn/{n}-{i}.jpg", "h")
        except Exception as e:  # noqa: BLE001 — the point of the test
            errors.append(e)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    cat.close()

    assert not errors, errors
    fresh = Catalog(DirectoryObjectStore(tmp_path))
    assert fresh.stored_image_count("k.com") == 0  # none had a stored_url
    assert sum(len(v) for v in fresh._images("k.com").values()) == 8 * 60
