"""The My Brands endpoints, over a catalogue built in the test."""

import json

import pytest
from flask import Flask

from backend.api import archive_routes
from backend.archive.domain.brand import Brand
from backend.archive.domain.product import ProductRecord
from backend.archive.domain.run import Coverage
from backend.archive.store.catalog import Catalog

COV = Coverage(extracted=3, channel_counts={}, coverage_pct=1.0, field_fill={}, verdict="ok")

YML = """
brands:
  - {domain: shown.com, homepage_url: "https://shown.com", display_name: "Shown", size: small}
  - {domain: outlet.com, homepage_url: "https://outlet.com", display_name: "Outlet", size: multi_brand}
"""


def product(slug, title, category1=None, category2=None, price=100.0):
    return ProductRecord(
        itemurl=f"https://shown.com/products/{slug}",
        product_title=title,
        price=price,
        in_stock=True,
        main_image_url=f"https://cdn.shown.com/{slug}.jpg",
        all_images=json.dumps([f"https://cdn.shown.com/{slug}.jpg"]),
        category1=category1,
        category2=category2,
    )


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db = tmp_path / "catalog.db"
    catalog = Catalog(db)
    for domain in ("shown.com", "outlet.com"):
        catalog.upsert_brand(Brand(domain=domain, homepage_url=f"https://{domain}"))
    run = catalog.open_run("shown.com", "full")
    catalog.record_product("shown.com", run, product("tee", "Cotton Tee", "TOPS", "TEES"), None)
    catalog.record_product("shown.com", run, product("cap", "Wool Cap", "ACCESSORIES"), None)
    catalog.record_product("shown.com", run, product("odd", "Unfiled Thing"), None)
    catalog.finalize_run(run, 0, COV)
    catalog.close()

    roster = tmp_path / "brands.yml"
    roster.write_text(YML)
    monkeypatch.setattr(archive_routes, "db_path", lambda: db)
    monkeypatch.setattr(archive_routes, "app_roster", lambda: _roster(roster))

    app = Flask(__name__)
    archive_routes.register_archive_routes(app)
    return app.test_client()


def _roster(path):
    from backend.archive.roster import app_roster

    return app_roster(path)


def get(client, url):
    response = client.get(url)
    return response.status_code, response.get_json()


@pytest.mark.unit
def test_roster_carries_what_the_archive_holds(client):
    status, body = get(client, "/api/archive/brands")
    assert status == 200
    assert [b["brand_id"] for b in body["brands"]] == ["shown.com"]
    assert body["brands"][0]["products"] == 3
    assert body["brands"][0]["verdict"] == "ok"


@pytest.mark.unit
def test_the_count_beside_a_brand_is_what_you_can_browse(tmp_path, client):
    # The archive keeps a product the shop has taken down, but the tree is built from
    # the live view. Counting all rows here and live rows there reads as a bug.
    catalog = Catalog(tmp_path / "catalog.db")
    run = catalog.open_run("shown.com", "full")
    catalog.record_product("shown.com", run, product("tee", "Cotton Tee", "TOPS", "TEES"), None)
    catalog.finalize_run(run, 0, COV)
    catalog.close()

    _, body = get(client, "/api/archive/brands")
    assert body["brands"][0]["products"] == 1
    assert get(client, "/api/archive/products/counts?brand_id=shown.com")[1]["counts"]["*"] == 1
    assert get(client, "/api/archive/health")[1]["products"] == 1


@pytest.mark.unit
def test_a_withheld_brand_is_not_reachable_by_guessing_its_id(client):
    # The roster is the boundary, so it has to hold on the product routes too and not
    # only on the list the sidebar draws.
    assert get(client, "/api/archive/brands/outlet.com")[0] == 404
    assert get(client, "/api/archive/products?brand_id=outlet.com")[0] == 404
    assert get(client, "/api/archive/products/counts?brand_id=outlet.com")[0] == 404


@pytest.mark.unit
def test_hierarchy_is_built_from_the_categories_products_carry(client):
    status, body = get(client, "/api/archive/brands/shown.com/categories/hierarchy")
    assert status == 200
    names = {node["url"]: node for node in body["hierarchy"]}
    assert "*" in names, "every brand needs a leaf, including one with no taxonomy"
    assert names["TOPS"]["children"][0]["url"] == "TOPS/TEES"
    assert "(uncategorised)" in names, "a product with no category is still in the archive"


@pytest.mark.unit
def test_counts_include_every_ancestor(client):
    _, body = get(client, "/api/archive/products/counts?brand_id=shown.com")
    counts = body["counts"]
    assert counts["*"] == 3
    assert counts["TOPS"] == 1 and counts["TOPS/TEES"] == 1
    assert counts["(uncategorised)"] == 1


@pytest.mark.unit
def test_a_parent_category_returns_its_childrens_products(client):
    _, body = get(client, "/api/archive/products?brand_id=shown.com&category=TOPS")
    assert [p["product_title"] for p in body["products"]] == ["Cotton Tee"]


@pytest.mark.unit
def test_products_drop_the_connector_payload(client):
    _, body = get(client, "/api/archive/products?brand_id=shown.com")
    assert body["total"] == 3
    assert all("raw" not in p for p in body["products"])
    assert all(p["brand_id"] == "shown.com" for p in body["products"])


@pytest.mark.unit
def test_search_spans_the_roster_and_nothing_else(client):
    _, body = get(client, "/api/archive/products/search?q=wool")
    assert [p["product_title"] for p in body["products"]] == ["Wool Cap"]
    assert get(client, "/api/archive/products/search?q=")[1]["products"] == []


@pytest.mark.unit
def test_wildcards_typed_into_the_search_box_are_letters(client):
    # "%" matching everything would make a stray keystroke look like a working search.
    assert get(client, "/api/archive/products/search?q=%25")[1]["products"] == []


@pytest.mark.unit
def test_archived_copies_travel_as_urls(tmp_path, client):
    # The copy we kept is offered beside the shop's own URL, so a tile whose CDN link has
    # died falls back to our bytes before it falls back to a placeholder.
    catalog = Catalog(tmp_path / "catalog.db")
    pid = catalog.product_id_for("shown.com", "https://shown.com/products/tee")
    catalog.record_image(
        pid,
        "https://cdn.shown.com/tee.jpg",
        "",
        "aa",
        stored_url="https://images.example.com/archive/shown.com/aa/aa.jpg",
    )
    catalog.close()

    _, body = get(client, "/api/archive/products?brand_id=shown.com&category=TOPS")
    assert body["products"][0]["archived_images"] == [
        "https://images.example.com/archive/shown.com/aa/aa.jpg"
    ]


@pytest.mark.unit
def test_health_reports_the_catalogue_it_actually_read(client):
    status, body = get(client, "/api/archive/health")
    assert status == 200
    assert body["ok"] is True
    assert body["brands_shown"] == 1
    assert body["products"] == 3


@pytest.mark.unit
def test_a_missing_catalogue_says_so_instead_of_inventing_an_empty_one(tmp_path, monkeypatch):
    """On a host with no disk there is no catalogue. Catalog() would create one, and
    every endpoint would then succeed with every brand at zero products — an archive
    that looks like it scraped nothing rather than one that is not there."""
    roster = tmp_path / "brands.yml"
    roster.write_text(YML)
    gone = tmp_path / "nowhere" / "catalog.db"
    monkeypatch.setattr(archive_routes, "db_path", lambda: gone)
    monkeypatch.setattr(archive_routes, "app_roster", lambda: _roster(roster))

    app = Flask(__name__)
    archive_routes.register_archive_routes(app)
    client = app.test_client()

    for url in (
        "/api/archive/health",
        "/api/archive/brands",
        "/api/archive/products?brand_id=shown.com",
        "/api/archive/products/search?q=wool",
    ):
        status, body = get(client, url)
        assert status == 503, url
        assert body["code"] == "NO_CATALOGUE"
    assert not gone.exists(), "asking for the archive must not create one"
