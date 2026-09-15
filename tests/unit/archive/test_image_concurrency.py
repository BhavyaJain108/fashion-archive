"""Several fetchers, one handle: every photograph must still be recorded."""

import json

import httpx
import pytest

from backend.archive.budget import HostBudget
from backend.archive.domain.brand import Brand
from backend.archive.domain.product import ProductRecord
from backend.archive.domain.run import Coverage
from backend.archive.runner.archive_images import archive_brand
from backend.archive.store.catalog import Catalog
from backend.archive.store.objects import DirectoryObjectStore
from backend.storage.images import LocalImageStore

PIXEL = b"\xff\xd8\xff\xdb" + b"0" * 64


@pytest.mark.unit
def test_every_photograph_is_recorded_when_fetched_in_parallel(tmp_path, monkeypatch):
    store = DirectoryObjectStore(tmp_path / "objects")
    cat = Catalog(store)
    cat.upsert_brand(Brand(domain="k.com", homepage_url="https://k.com"))
    run = cat.open_run("k.com", "full")
    urls = [f"https://cdn.shopify.com/{i}.jpg" for i in range(120)]
    cat.record_product(
        "k.com",
        run,
        ProductRecord(
            itemurl="https://k.com/p/a",
            product_title="Tee",
            all_images=json.dumps(urls),
        ),
        None,
    )
    cat.finalize_run(run, 0, Coverage(extracted=1, coverage_pct=1.0, verdict="ok"))
    cat.flush()

    def handler(request):
        return httpx.Response(200, content=PIXEL, headers={"content-type": "image/jpeg"})

    import backend.archive.runner.archive_images as mod
    from backend.archive.transport import HttpxTransport

    monkeypatch.setattr(
        mod,
        "HttpxTransport",
        lambda **kw: HttpxTransport(
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            **{k: v for k, v in kw.items() if k != "client"},
        ),
    )

    out = archive_brand(
        "k.com",
        store,
        LocalImageStore(root=tmp_path / "img", api_base="http://x"),
        HostBudget(gap=0.0, sleep=lambda s: None),
        workers=16,
    )
    assert out.fetched == 120 and out.failed == 0
    assert Catalog(DirectoryObjectStore(tmp_path / "objects")).stored_image_count("k.com") == 120
