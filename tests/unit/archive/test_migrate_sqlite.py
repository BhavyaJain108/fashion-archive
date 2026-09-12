"""Moving a SQLite catalogue into objects. Built against the old schema on purpose:
the point is that a database written by code that no longer exists still reads."""

import json
import sqlite3

import pytest

from backend.archive.store.catalog import Catalog
from backend.archive.store.migrate_sqlite import _run_key, migrate
from backend.archive.store.objects import DirectoryObjectStore

LEGACY_SCHEMA = """
CREATE TABLE brands (domain TEXT PRIMARY KEY, homepage_url TEXT, display_name TEXT,
                     notes TEXT, state TEXT NOT NULL DEFAULT 'new');
CREATE TABLE scrape_plans (domain TEXT PRIMARY KEY, plan_json TEXT, fingerprinted_at TEXT);
CREATE TABLE runs (id INTEGER PRIMARY KEY AUTOINCREMENT, domain TEXT, mode TEXT,
                   started_at TEXT, finished_at TEXT, exit_status INTEGER, coverage_json TEXT);
CREATE TABLE products (id INTEGER PRIMARY KEY AUTOINCREMENT, domain TEXT, itemurl TEXT,
                       product_code TEXT, change_hint TEXT, first_seen_run INTEGER,
                       last_seen_run INTEGER, current_json TEXT);
CREATE TABLE observations (id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER,
                           run_id INTEGER, price REAL, full_price REAL, in_stock INTEGER,
                           size_availability TEXT);
CREATE TABLE recipe_books (domain TEXT PRIMARY KEY, book_json TEXT, learned_at TEXT);
CREATE TABLE images (id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER, url TEXT,
                     local_path TEXT, content_hash TEXT, stored_url TEXT);
CREATE TABLE field_evidence (domain TEXT, field TEXT, source TEXT, examined INTEGER,
                             found INTEGER, run_id INTEGER, searched_at TEXT);
CREATE TABLE schedule (domain TEXT PRIMARY KEY, enabled INTEGER, cadence_seconds INTEGER,
                       next_due TEXT, claimed_by TEXT, claimed_at TEXT);
CREATE TABLE daemon_control (id INTEGER PRIMARY KEY, stop INTEGER, code_version TEXT);
CREATE TABLE scorecards (run_id INTEGER PRIMARY KEY, domain TEXT, card_json TEXT, scored_at TEXT);
CREATE TABLE requests (id INTEGER PRIMARY KEY AUTOINCREMENT, host TEXT, status INTEGER,
                       latency_ms INTEGER, retry_after INTEGER, at TEXT);
CREATE TABLE extraction_versions (domain TEXT PRIMARY KEY, version TEXT, seen_at TEXT);
"""

COV = json.dumps(
    {
        "extracted": 2,
        "channel_counts": {},
        "coverage_pct": 1.0,
        "field_fill": {},
        "verdict": "ok",
        "reasons": [],
    }
)


def _record(slug, price=100.0):
    return json.dumps(
        {
            "itemurl": f"https://k.com/p/{slug}",
            "product_title": slug.title(),
            "price": price,
            "in_stock": True,
            "all_images": json.dumps([f"https://cdn/{slug}.jpg"]),
        }
    )


@pytest.fixture()
def legacy(tmp_path):
    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.executescript(LEGACY_SCHEMA)
    db.execute("INSERT INTO brands VALUES ('k.com','https://k.com','K',NULL,'active')")
    db.execute("INSERT INTO brands VALUES ('z.com','https://z.com',NULL,NULL,'gated')")
    db.execute(
        "INSERT INTO runs (id,domain,mode,started_at,finished_at,exit_status,coverage_json) "
        "VALUES (1,'k.com','full','2026-09-08T17:44:32+00:00','2026-09-08T17:50:00+00:00',0,?)",
        (COV,),
    )
    for pid, slug in ((1, "tee"), (2, "cap")):
        db.execute(
            "INSERT INTO products (id,domain,itemurl,product_code,change_hint,"
            "first_seen_run,last_seen_run,current_json) VALUES (?,?,?,?,?,1,1,?)",
            (pid, "k.com", f"https://k.com/p/{slug}", f"SKU{pid}", "h", _record(slug)),
        )
        db.execute(
            "INSERT INTO observations (product_id,run_id,price,full_price,in_stock,"
            "size_availability) VALUES (?,1,100.0,NULL,1,NULL)",
            (pid,),
        )
    db.execute(
        "INSERT INTO images (product_id,url,local_path,content_hash,stored_url) "
        "VALUES (1,'https://cdn/tee.jpg','','aa','https://r2/tee.jpg')"
    )
    db.execute("INSERT INTO field_evidence VALUES ('k.com','color_info','channel',10,4,1,'t1')")
    db.execute("INSERT INTO schedule VALUES ('k.com',1,3600,'t2',NULL,NULL)")
    db.execute("INSERT INTO extraction_versions VALUES ('k.com','abc','2026-09-08T17:50:00+00:00')")
    db.commit()
    db.close()
    return path


@pytest.mark.unit
def test_migration_counts_what_it_moved(legacy, tmp_path):
    counts = migrate(legacy, DirectoryObjectStore(tmp_path / "objects"))
    assert counts["brands"] == 2
    assert counts["products"] == 2
    assert counts["observations"] == 2
    assert counts["images"] == 1
    assert counts["evidence"] == 1
    assert counts["schedule"] == 1


@pytest.mark.unit
def test_the_migrated_archive_reads_back_through_the_new_store(legacy, tmp_path):
    store = DirectoryObjectStore(tmp_path / "objects")
    migrate(legacy, store)
    cat = Catalog(store)

    assert cat.get_brand("k.com").display_name == "K"
    assert cat.get_brand_state("z.com") == "gated"
    assert {p["product_title"] for p in cat.current_products("k.com")} == {"Tee", "Cap"}
    assert cat.observation_count("k.com") == 2
    assert cat.load_evidence("k.com") == {("color_info", "channel"): (10, 4)}
    assert cat.extraction_version_for("k.com") == "abc"
    assert cat.archived_images("k.com") == {"https://k.com/p/tee": ["https://r2/tee.jpg"]}
    assert cat.live_product_counts() == {"k.com": 2}


@pytest.mark.unit
def test_a_migrated_run_sorts_before_a_later_one(legacy, tmp_path):
    """The store orders runs lexically, so a migrated id must begin with a timestamp.

    `legacy-00000042` did not: 'l' sorts after '2', so every migrated run outranked
    every new one. The first uncapped re-scrape of staud.clothing found 1,530 products
    and the page showed zero, because the latest covered run was still a migrated one.
    """
    from backend.archive.store.catalog import new_run_id

    assert _run_key(1, "2026-09-08T17:44:32+00:00") < new_run_id()
    assert _run_key(2, "2026-09-01T00:00:00+00:00") < _run_key(1, "2026-09-08T00:00:00+00:00")


@pytest.mark.unit
def test_the_latest_migrated_run_is_the_one_that_started_last(legacy, tmp_path):
    store = DirectoryObjectStore(tmp_path / "objects")
    migrate(legacy, store)
    assert Catalog(store).latest_run("k.com")["id"] == _run_key(1, "2026-09-08T17:44:32+00:00")


@pytest.mark.unit
def test_a_run_after_a_migration_is_the_one_the_live_view_uses(legacy, tmp_path):
    """The whole point: scrape a migrated brand and its new products must be visible."""
    from backend.archive.domain.product import ProductRecord
    from backend.archive.domain.run import Coverage

    store = DirectoryObjectStore(tmp_path / "objects")
    migrate(legacy, store)
    cat = Catalog(store)
    assert len(cat.current_products("k.com")) == 2

    run = cat.open_run("k.com", "full")
    for slug in ("tee", "cap", "hat"):
        cat.record_product(
            "k.com",
            run,
            ProductRecord(itemurl=f"https://k.com/p/{slug}", product_title=slug, price=1.0),
            None,
        )
    cat.finalize_run(
        run,
        0,
        Coverage(extracted=3, channel_counts={}, coverage_pct=1.0, field_fill={}, verdict="ok"),
    )
    cat.close()
    assert len(Catalog(store).current_products("k.com")) == 3


@pytest.mark.unit
def test_migrating_twice_leaves_the_same_archive(legacy, tmp_path):
    store = DirectoryObjectStore(tmp_path / "objects")
    migrate(legacy, store)
    first = {k: store.get(k)[0] for k in store.list("")}
    migrate(legacy, store)
    second = {k: store.get(k)[0] for k in store.list("")}
    assert first.keys() == second.keys()
    assert first == second


@pytest.mark.unit
def test_the_source_database_is_not_touched(legacy, tmp_path):
    before = legacy.read_bytes()
    migrate(legacy, DirectoryObjectStore(tmp_path / "objects"))
    assert legacy.read_bytes() == before, "a migration that eats its source leaves nothing to check"
