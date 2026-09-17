"""How many times a run uploads its large objects.

Render bills bandwidth, and each of these writes is the whole object. Re-uploading
the image index once per photograph cost 312 GB before anyone noticed, so the count
is tested directly rather than inferred from behaviour.
"""

import pytest

from backend.archive.domain.product import ProductRecord
from backend.archive.domain.run import Coverage
from backend.archive.store.catalog import Catalog
from backend.archive.store.objects import DirectoryObjectStore


class CountingStore(DirectoryObjectStore):
    def __init__(self, root):
        super().__init__(root)
        self.puts: list[str] = []

    def put(self, key, body, *, if_match=None, if_none_match=False):
        self.puts.append(key)
        return super().put(key, body, if_match=if_match, if_none_match=if_none_match)


OK = Coverage(extracted=1, coverage_pct=1.0, verdict="ok")


@pytest.mark.unit
def test_a_run_uploads_its_catalogue_exactly_once(tmp_path):
    store = CountingStore(tmp_path)
    cat = Catalog(store)
    run = cat.open_run("k.com", "full")
    for i in range(950):  # enough to have flushed four times under the old rule
        cat.record_product(
            "k.com", run, ProductRecord(itemurl=f"https://k.com/p/{i}", product_title="T"), None
        )
    cat.finalize_run(run, 0, OK)

    assert store.puts.count("catalogue/k.com.json") == 1
    assert store.puts.count("search/k.com.json") == 1
    # and what was uploaded once is the stamped, visible version
    assert len(Catalog(DirectoryObjectStore(tmp_path)).current_products("k.com")) == 950


@pytest.mark.unit
def test_the_image_index_is_not_uploaded_per_photograph(tmp_path):
    store = CountingStore(tmp_path)
    cat = Catalog(store)
    for i in range(5000):
        cat.record_image("k.com", f"https://k.com/p/{i % 50}", f"https://cdn/{i}.jpg", "h", "u")
    cat.close()
    assert store.puts.count("images/k.com.json") <= 3  # 2 at 2000 and 4000, 1 on close
    rows = Catalog(DirectoryObjectStore(tmp_path))._read("images/k.com.json")
    assert sum(len(v) for v in rows.values()) == 5000
