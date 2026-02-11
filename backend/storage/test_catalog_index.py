#!/usr/bin/env python3
"""
Catalog Index Tests
===================

Tests for the SQLite product catalog index with FTS5.
Covers: unit tests, integration tests, performance benchmarks, and verification.

Run:
    python tests/test_catalog_index.py
    python tests/test_catalog_index.py TestUnit
    python tests/test_catalog_index.py TestUnit.test_fts_basic_search
"""

import json
import os
import glob
import sys
import time
import tempfile
import unittest
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

EXTRACTIONS_PATH = project_root / "backend" / "extractions"


def get_catalog(db_path=None):
    """Create a CatalogIndex pointing at the real extractions data."""
    from backend.storage.catalog_index import CatalogIndex
    if db_path is None:
        db_path = str(project_root / "data" / "catalog_test.db")
    return CatalogIndex(db_path=db_path, extractions_path=str(EXTRACTIONS_PATH))


def count_json_files(brand_id):
    """Count product JSON files on disk for a brand."""
    products_dir = EXTRACTIONS_PATH / brand_id / "products"
    if not products_dir.exists():
        return 0
    return len(list(products_dir.rglob("*.json")))


# =============================================================================
# UNIT TESTS
# =============================================================================

class TestUnit(unittest.TestCase):
    """Unit tests for CatalogIndex directly."""

    @classmethod
    def setUpClass(cls):
        """Build test catalog once for all unit tests."""
        cls.db_path = str(project_root / "data" / "catalog_test.db")
        # Remove stale test db
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)
        cls.catalog = get_catalog(cls.db_path)
        cls.catalog.rebuild_full()

    @classmethod
    def tearDownClass(cls):
        """Clean up test database."""
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)

    def test_schema_creation(self):
        """Verify all tables, FTS, triggers, and indexes exist."""
        conn = self.catalog._get_connection()
        try:
            rows = conn.execute(
                "SELECT name, type FROM sqlite_master WHERE type IN ('table', 'trigger', 'index')"
            ).fetchall()
            names = {r["name"] for r in rows}

            # Tables
            self.assertIn("products", names)
            self.assertIn("product_variants", names)
            self.assertIn("product_categories", names)
            self.assertIn("index_metadata", names)
            self.assertIn("products_fts", names)

            # Triggers
            self.assertIn("products_fts_ai", names)
            self.assertIn("products_fts_ad", names)
            self.assertIn("products_fts_au", names)

            # Key indexes
            self.assertIn("idx_products_brand", names)
            self.assertIn("idx_products_price", names)
            self.assertIn("idx_variants_color", names)
            self.assertIn("idx_variants_size", names)
        finally:
            conn.close()

    def test_index_single_brand(self):
        """Index count for balenciaga_com should be reasonable vs file count."""
        conn = self.catalog._get_connection()
        try:
            row = conn.execute(
                "SELECT product_count FROM index_metadata WHERE brand_id = 'balenciaga_com'"
            ).fetchone()
            self.assertIsNotNone(row, "balenciaga_com should be in index_metadata")
            indexed = row["product_count"]

            # Should have products (accounting for dedup, indexed <= file count)
            file_count = count_json_files("balenciaga_com")
            self.assertGreater(indexed, 0, "Should have indexed products")
            self.assertLessEqual(indexed, file_count,
                                 "Indexed count should be <= file count (dedup)")
        finally:
            conn.close()

    def test_index_full_rebuild(self):
        """Total indexed products should be roughly ~4000+."""
        conn = self.catalog._get_connection()
        try:
            row = conn.execute("SELECT COUNT(*) as cnt FROM products").fetchone()
            total = row["cnt"]
            self.assertGreater(total, 3000,
                               f"Expected 3000+ products, got {total}")
        finally:
            conn.close()

    def test_deduplication(self):
        """Same product URL should only appear once."""
        conn = self.catalog._get_connection()
        try:
            # Check for duplicate URLs
            rows = conn.execute("""
                SELECT url, COUNT(*) as cnt FROM products
                GROUP BY url HAVING cnt > 1
                LIMIT 5
            """).fetchall()
            if rows:
                dupes = [(r["url"], r["cnt"]) for r in rows]
                self.fail(f"Found duplicate product URLs: {dupes[:3]}")
        finally:
            conn.close()

    def test_fts_basic_search(self):
        """Search for 'sunglasses' should return results."""
        products, total = self.catalog.search(query="sunglasses", limit=20)
        self.assertGreater(total, 0, "Should find products matching 'sunglasses'")
        # At least one should be from Balenciaga (they have many sunglasses)
        brands = {p.get("brand_id") for p in products}
        self.assertIn("balenciaga_com", brands,
                       "Balenciaga should appear in sunglasses results")

    def test_fts_multi_word(self):
        """Search for 'silver sunglasses' should return results."""
        products, total = self.catalog.search(query="silver sunglasses", limit=20)
        self.assertGreater(total, 0, "Should find 'silver sunglasses'")

    def test_cross_brand_search(self):
        """Search with no brand_id should return results from multiple brands."""
        products, total = self.catalog.search(query="bag", limit=100)
        self.assertGreater(total, 0, "Should find products matching 'bag'")
        brands = {p.get("brand_id") for p in products}
        self.assertGreaterEqual(len(brands), 2,
                                 f"Expected results from 2+ brands, got {brands}")

    def test_filter_by_price_range(self):
        """Price filter should only return products in range."""
        products, total = self.catalog.search(
            price_min=100.0, price_max=200.0, limit=50
        )
        self.assertGreater(total, 0, "Should find products in $100-$200 range")
        for p in products:
            if p.get("price") is not None:
                self.assertGreaterEqual(p["price"], 100.0,
                                        f"Price {p['price']} below min")
                self.assertLessEqual(p["price"], 200.0,
                                     f"Price {p['price']} above max")

    def test_filter_by_color(self):
        """Color filter should return products with matching variant."""
        products, total = self.catalog.search(color="Silver", limit=20)
        if total == 0:
            self.skipTest("No products with Silver color variant")
        # Verify at least the first result has a Silver variant
        first = products[0]
        variants = first.get("variants", [])
        colors = [v.get("color") for v in variants if v.get("color")]
        self.assertIn("Silver", colors,
                       f"Expected Silver variant, got colors: {colors}")

    def test_filter_by_size(self):
        """Size filter should return products with matching variant."""
        # Find a common size first
        options = self.catalog.get_filter_options()
        sizes = options.get("sizes", [])
        if not sizes:
            self.skipTest("No size data in catalog")
        test_size = sizes[0]
        products, total = self.catalog.search(size=test_size, limit=20)
        self.assertGreater(total, 0, f"Should find products with size '{test_size}'")

    def test_filter_combined(self):
        """Combined filters should AND together."""
        # Search for products from balenciaga with price > 100
        products, total = self.catalog.search(
            brand_id="balenciaga_com",
            price_min=100.0,
            limit=50
        )
        for p in products:
            self.assertEqual(p["brand_id"], "balenciaga_com")
            if p.get("price") is not None:
                self.assertGreaterEqual(p["price"], 100.0)

    def test_sort_price_ascending(self):
        """Sort by price_asc should return ascending prices."""
        products, _ = self.catalog.search(
            brand_id="balenciaga_com", sort_by="price_asc", limit=20
        )
        prices = [p["price"] for p in products if p.get("price") is not None]
        self.assertEqual(prices, sorted(prices),
                         "Prices should be in ascending order")

    def test_sort_price_descending(self):
        """Sort by price_desc should return descending prices."""
        products, _ = self.catalog.search(
            brand_id="balenciaga_com", sort_by="price_desc", limit=20
        )
        prices = [p["price"] for p in products if p.get("price") is not None]
        self.assertEqual(prices, sorted(prices, reverse=True),
                         "Prices should be in descending order")

    def test_sort_name(self):
        """Sort by name should return alphabetical order."""
        products, _ = self.catalog.search(
            brand_id="balenciaga_com", sort_by="name", limit=20
        )
        names = [p["name"].lower() for p in products]
        self.assertEqual(names, sorted(names),
                         "Names should be in alphabetical order")

    def test_pagination(self):
        """Paginated queries should not overlap and total should be consistent."""
        _, total1 = self.catalog.search(brand_id="balenciaga_com", limit=10, offset=0)
        page1, _ = self.catalog.search(brand_id="balenciaga_com", limit=10, offset=0)
        page2, total2 = self.catalog.search(brand_id="balenciaga_com", limit=10, offset=10)

        self.assertEqual(total1, total2, "Total should be consistent across pages")

        urls1 = {p["url"] for p in page1}
        urls2 = {p["url"] for p in page2}
        self.assertEqual(len(urls1 & urls2), 0, "Pages should not overlap")

    def test_category_url_counts(self):
        """Category URL counts should be positive for brands with products."""
        counts = self.catalog.get_product_counts_by_category_url("balenciaga_com")
        self.assertGreater(len(counts), 0,
                           "Should have category URL counts for balenciaga_com")
        for url, count in counts.items():
            self.assertGreater(count, 0, f"Count for {url} should be positive")

    def test_get_filter_options(self):
        """Filter options should return brands, colors, sizes, price_range."""
        options = self.catalog.get_filter_options()
        self.assertIn("brands", options)
        self.assertIn("colors", options)
        self.assertIn("sizes", options)
        self.assertIn("price_range", options)
        self.assertIn("categories", options)

        self.assertGreater(len(options["brands"]), 0, "Should have brands")
        self.assertIsNotNone(options["price_range"]["min"], "Should have min price")
        self.assertIsNotNone(options["price_range"]["max"], "Should have max price")

    def test_get_product_by_url(self):
        """Should find a product by URL."""
        # Get a known URL from the index
        conn = self.catalog._get_connection()
        try:
            row = conn.execute("SELECT url FROM products LIMIT 1").fetchone()
        finally:
            conn.close()

        if not row:
            self.skipTest("No products in index")

        product = self.catalog.get_product_by_url(row["url"])
        self.assertIsNotNone(product, f"Should find product for URL: {row['url']}")
        self.assertEqual(product["url"], row["url"])

    def test_stale_detection(self):
        """After rebuild, brand should not be stale."""
        self.assertFalse(
            self.catalog.is_brand_stale("balenciaga_com"),
            "Brand should not be stale right after rebuild"
        )

    def test_rebuild_idempotent(self):
        """Double rebuild should produce same count."""
        conn = self.catalog._get_connection()
        try:
            before = conn.execute(
                "SELECT product_count FROM index_metadata WHERE brand_id = 'balenciaga_com'"
            ).fetchone()["product_count"]
        finally:
            conn.close()

        self.catalog.rebuild_brand("balenciaga_com")

        conn = self.catalog._get_connection()
        try:
            after = conn.execute(
                "SELECT product_count FROM index_metadata WHERE brand_id = 'balenciaga_com'"
            ).fetchone()["product_count"]
        finally:
            conn.close()

        self.assertEqual(before, after,
                         "Rebuild should be idempotent (no duplicate rows)")

    def test_product_dict_format(self):
        """Returned product dict should have the expected keys."""
        products, _ = self.catalog.search(brand_id="balenciaga_com", limit=1)
        self.assertGreater(len(products), 0)
        p = products[0]

        expected_keys = {
            "name", "price", "currency", "images", "description",
            "url", "source_url", "brand", "brand_id", "sku",
            "category", "variants", "classifications"
        }
        self.assertTrue(
            expected_keys.issubset(set(p.keys())),
            f"Missing keys: {expected_keys - set(p.keys())}"
        )
        self.assertIsInstance(p["images"], list)
        self.assertIsInstance(p["variants"], list)
        self.assertIsInstance(p["classifications"], list)


# =============================================================================
# VERIFICATION / REGRESSION TESTS
# =============================================================================

class TestVerification(unittest.TestCase):
    """Verification tests proving the original problems are fixed."""

    @classmethod
    def setUpClass(cls):
        cls.db_path = str(project_root / "data" / "catalog_test.db")
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)
        cls.catalog = get_catalog(cls.db_path)
        cls.catalog.rebuild_full()

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)

    def test_verify_cross_brand_search_works(self):
        """REGRESSION: search with no brand_id now returns results."""
        products, total = self.catalog.search(query="jacket", limit=50)
        self.assertGreater(total, 0,
                           "Cross-brand search for 'jacket' should return results")
        brands = {p["brand_id"] for p in products}
        self.assertGreaterEqual(len(brands), 1,
                                 "Should have results from at least 1 brand")

    def test_verify_no_rglob_on_query(self):
        """REGRESSION: queries should be fast (<50ms), not doing file scans."""
        # Warm up
        self.catalog.search(query="test", limit=1)

        start = time.time()
        for _ in range(10):
            self.catalog.search(query="jacket", limit=50)
        elapsed = (time.time() - start) / 10

        self.assertLess(elapsed, 0.05,
                         f"Query took {elapsed*1000:.1f}ms, expected <50ms")

    def test_verify_all_brands_indexed(self):
        """All brand directories with products should be indexed."""
        on_disk = set()
        for d in EXTRACTIONS_PATH.iterdir():
            if d.is_dir() and (d / "products").exists():
                # Check if it actually has JSON files
                if list((d / "products").rglob("*.json")):
                    on_disk.add(d.name)

        conn = self.catalog._get_connection()
        try:
            rows = conn.execute("SELECT brand_id FROM index_metadata").fetchall()
            indexed = {r["brand_id"] for r in rows}
        finally:
            conn.close()

        missing = on_disk - indexed
        self.assertEqual(len(missing), 0,
                         f"Brands not indexed: {missing}")

    def test_verify_product_data_fidelity(self):
        """Catalog data should match the source JSON files."""
        conn = self.catalog._get_connection()
        try:
            rows = conn.execute(
                "SELECT file_path, url, name, price FROM products ORDER BY RANDOM() LIMIT 10"
            ).fetchall()
        finally:
            conn.close()

        for row in rows:
            file_path = row["file_path"]
            if not os.path.exists(file_path):
                continue

            with open(file_path, 'r') as f:
                original = json.load(f)

            self.assertEqual(row["name"], original.get("name"),
                             f"Name mismatch for {file_path}")
            if original.get("price") is not None:
                self.assertAlmostEqual(
                    row["price"], original["price"], places=2,
                    msg=f"Price mismatch for {file_path}"
                )


# =============================================================================
# PERFORMANCE BENCHMARKS
# =============================================================================

class TestBenchmarks(unittest.TestCase):
    """Performance benchmarks."""

    @classmethod
    def setUpClass(cls):
        cls.db_path = str(project_root / "data" / "catalog_test.db")
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)
        cls.catalog = get_catalog(cls.db_path)
        cls.catalog.rebuild_full()

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)

    def test_benchmark_full_rebuild(self):
        """Full rebuild should complete in < 5 seconds."""
        start = time.time()
        self.catalog.rebuild_full()
        elapsed = time.time() - start

        print(f"\n  Full rebuild: {elapsed:.2f}s")
        self.assertLess(elapsed, 5.0,
                         f"Full rebuild took {elapsed:.2f}s, target < 5s")

    def test_benchmark_single_brand_rebuild(self):
        """Single brand rebuild should complete in < 1 second."""
        start = time.time()
        self.catalog.rebuild_brand("balenciaga_com")
        elapsed = time.time() - start

        print(f"\n  Single brand rebuild (balenciaga_com): {elapsed:.2f}s")
        self.assertLess(elapsed, 1.0,
                         f"Brand rebuild took {elapsed:.2f}s, target < 1s")

    def test_benchmark_fts_search(self):
        """FTS search should be < 5ms average."""
        # Warm up
        self.catalog.search(query="test", limit=1)

        queries = ["jacket", "sunglasses", "bag", "dress", "silver", "leather",
                    "cotton", "wool", "silk", "velvet"]
        iterations = 100

        start = time.time()
        for _ in range(iterations):
            for q in queries:
                self.catalog.search(query=q, limit=50)
        elapsed = time.time() - start
        avg_ms = (elapsed / (iterations * len(queries))) * 1000

        print(f"\n  FTS search avg: {avg_ms:.2f}ms ({iterations * len(queries)} queries)")
        self.assertLess(avg_ms, 5.0,
                         f"FTS search took {avg_ms:.2f}ms avg, target < 5ms")

    def test_benchmark_cross_brand_search(self):
        """Cross-brand search should be < 10ms."""
        # Warm up
        self.catalog.search(query="test", limit=1)

        start = time.time()
        for _ in range(50):
            self.catalog.search(query="jacket", limit=50)
        elapsed = (time.time() - start) / 50 * 1000

        print(f"\n  Cross-brand search avg: {elapsed:.2f}ms")
        self.assertLess(elapsed, 10.0,
                         f"Cross-brand search took {elapsed:.2f}ms, target < 10ms")

    def test_benchmark_filtered_query(self):
        """Filtered query should be < 10ms."""
        # Warm up
        self.catalog.search(query="test", limit=1)

        start = time.time()
        for _ in range(50):
            self.catalog.search(
                brand_id="balenciaga_com",
                price_min=100.0,
                price_max=500.0,
                limit=50
            )
        elapsed = (time.time() - start) / 50 * 1000

        print(f"\n  Filtered query avg: {elapsed:.2f}ms")
        self.assertLess(elapsed, 10.0,
                         f"Filtered query took {elapsed:.2f}ms, target < 10ms")


# =============================================================================
# INTEGRATION TESTS (Storage Layer + API)
# =============================================================================

class TestStorageIntegration(unittest.TestCase):
    """Test that Storage layer correctly delegates to catalog."""

    @classmethod
    def setUpClass(cls):
        # Build catalog using the real data path
        from backend.storage.catalog_index import CatalogIndex
        cls.db_path = str(project_root / "data" / "catalog_test.db")
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)

        # Reset singleton for test
        import backend.storage.catalog_index as ci
        ci._catalog = None
        cls.catalog = ci.CatalogIndex(
            db_path=cls.db_path,
            extractions_path=str(EXTRACTIONS_PATH)
        )
        ci._catalog = cls.catalog
        cls.catalog.rebuild_full()

        from backend.storage.storage_layer import Storage
        cls.storage = Storage()
        # Point storage's catalog to our test instance
        cls.storage._catalog = cls.catalog

    @classmethod
    def tearDownClass(cls):
        import backend.storage.catalog_index as ci
        ci._catalog = None
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)

    def test_query_products_cross_brand(self):
        """Storage.query_products with search, no brand_id, returns results."""
        products, total = self.storage.query_products(
            {"search": "jacket"}, limit=50
        )
        self.assertGreater(total, 0,
                           "Cross-brand search should return results via Storage")

    def test_query_products_with_brand(self):
        """Storage.query_products with brand_id filter."""
        products, total = self.storage.query_products(
            {"brand_id": "balenciaga_com", "search": "bag"}, limit=50
        )
        for p in products:
            self.assertEqual(p["brand_id"], "balenciaga_com")

    def test_query_products_price_filter(self):
        """Storage.query_products with price range."""
        products, total = self.storage.query_products(
            {"brand_id": "balenciaga_com", "price_min": 100, "price_max": 300},
            limit=50
        )
        for p in products:
            if p.get("price") is not None:
                self.assertGreaterEqual(p["price"], 100)
                self.assertLessEqual(p["price"], 300)

    def test_get_product_counts(self):
        """Storage.get_product_counts_by_url returns counts."""
        counts = self.storage.get_product_counts_by_url("balenciaga_com")
        self.assertIsInstance(counts, dict)
        # Should have some categories
        self.assertGreater(len(counts), 0)

    def test_get_product(self):
        """Storage.get_product by URL."""
        # Get a known product URL
        products, _ = self.storage.query_products(
            {"brand_id": "balenciaga_com"}, limit=1
        )
        if not products:
            self.skipTest("No products found")

        url = products[0]["url"]
        product = self.storage.get_product(url)
        self.assertIsNotNone(product)
        self.assertEqual(product["url"], url)


if __name__ == '__main__':
    # Support running specific test class: python test_catalog_index.py TestUnit
    unittest.main(verbosity=2)
