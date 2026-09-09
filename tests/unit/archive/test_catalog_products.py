import pytest

from backend.archive.domain.brand import Brand
from backend.archive.domain.product import ProductRecord
from backend.archive.domain.run import Coverage
from backend.archive.store.catalog import Catalog

COV = Coverage(extracted=1, channel_counts={}, coverage_pct=1.0, field_fill={}, verdict="ok")


def rec(price=126.0, in_stock=True) -> ProductRecord:
    return ProductRecord(
        itemurl="https://kuurth.com/products/nemo",
        product_title="Nemo",
        price=price,
        in_stock=in_stock,
    )


@pytest.fixture()
def cat(tmp_path):
    c = Catalog(tmp_path / "catalog.db")
    c.upsert_brand(Brand(domain="kuurth.com", homepage_url="https://kuurth.com"))
    return c


@pytest.mark.unit
def test_first_sight_always_appends_observation(cat):
    run = cat.open_run("kuurth.com", "full")
    assert cat.record_product("kuurth.com", run, rec(), "hint-1") is True
    assert cat.observation_count("kuurth.com") == 1


@pytest.mark.unit
def test_unchanged_product_appends_nothing(cat):
    r1 = cat.open_run("kuurth.com", "full")
    cat.record_product("kuurth.com", r1, rec(), "hint-1")
    cat.finalize_run(r1, 0, COV)
    r2 = cat.open_run("kuurth.com", "delta")
    assert cat.record_product("kuurth.com", r2, rec(), "hint-1") is False
    assert cat.observation_count("kuurth.com") == 1  # history stores change, not repetition


@pytest.mark.unit
def test_price_change_appends_observation_and_updates_hint(cat):
    r1 = cat.open_run("kuurth.com", "full")
    cat.record_product("kuurth.com", r1, rec(price=180.0), "hint-1")
    r2 = cat.open_run("kuurth.com", "delta")
    assert cat.record_product("kuurth.com", r2, rec(price=126.0), "hint-2") is True
    assert cat.observation_count("kuurth.com") == 2
    assert cat.get_change_hints("kuurth.com") == {"https://kuurth.com/products/nemo": "hint-2"}


@pytest.mark.unit
def test_delisted_product_leaves_current_view_but_stays_stored(cat):
    r1 = cat.open_run("kuurth.com", "full")
    cat.record_product("kuurth.com", r1, rec(), None)
    cat.finalize_run(r1, 0, COV)
    r2 = cat.open_run("kuurth.com", "full")  # product NOT seen this run
    cat.finalize_run(r2, 0, COV)
    assert cat.current_products("kuurth.com", live_only=True) == []
    assert len(cat.current_products("kuurth.com", live_only=False)) == 1  # the archive keeps it


@pytest.mark.unit
def test_mark_seen_advances_last_seen_without_observation(cat):
    r1 = cat.open_run("kuurth.com", "full")
    cat.record_product("kuurth.com", r1, rec(), "h1")
    cat.finalize_run(r1, 0, COV)
    r2 = cat.open_run("kuurth.com", "delta")
    cat.mark_seen("kuurth.com", r2, ["https://kuurth.com/products/nemo"])
    cat.finalize_run(r2, 0, COV)
    assert len(cat.current_products("kuurth.com", live_only=True)) == 1
    assert cat.observation_count("kuurth.com") == 1


@pytest.mark.unit
def test_a_run_that_stored_nothing_does_not_hide_the_catalogue(tmp_path):
    """A rate-limited run exits 1 having stored nothing. Treating it as the reference
    made a brand's whole catalogue disappear from view."""
    from backend.archive.domain.brand import Brand
    from backend.archive.domain.product import ProductRecord
    from backend.archive.store.catalog import Catalog

    cat = Catalog(tmp_path / "c.db")
    cat.upsert_brand(Brand(domain="kuurth.com", homepage_url="https://kuurth.com"))
    good = cat.open_run("kuurth.com", "full")
    cat.record_product(
        "kuurth.com",
        good,
        ProductRecord(itemurl="https://kuurth.com/products/a", product_title="Tee"),
        "h1",
    )
    cat.finalize_run(good, 0, COV)  # a real run always measures its coverage
    assert len(cat.current_products("kuurth.com")) == 1

    # 429 before a single product was fetched: the run never measured any coverage
    busy = cat.open_run("kuurth.com", "full")
    cat.finalize_run(busy, 1, None)
    assert len(cat.current_products("kuurth.com")) == 1  # the catalogue is still there
