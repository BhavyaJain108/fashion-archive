"""
Database Manager
================

Handles database operations for brand/product data.
Supports both PostgreSQL and SQLite with same interface.
"""

import sqlite3
import json
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from pathlib import Path


class DatabaseManager:
    """Manages database operations for brand scraping data"""

    def __init__(self, db_path: str = "data/brands.db", db_type: str = "sqlite"):
        """
        Initialize DatabaseManager

        Args:
            db_path: Path to SQLite database file (if using SQLite)
            db_type: 'sqlite' or 'postgres'
        """
        self.db_type = db_type
        self.db_path = db_path

        if db_type == "sqlite":
            self.conn = sqlite3.connect(db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row  # Return rows as dicts
            self._create_tables()
        else:
            # TODO: PostgreSQL support
            raise NotImplementedError("PostgreSQL support coming soon")

    def _create_tables(self):
        """Create tables if they don't exist"""
        schema_path = Path(__file__).parent / "schema.sql"

        with open(schema_path, 'r') as f:
            schema_sql = f.read()

        # Execute schema (SQLite supports IF NOT EXISTS)
        self.conn.executescript(schema_sql)
        self.conn.commit()

    def _dict_from_row(self, row: sqlite3.Row) -> Dict:
        """Convert sqlite3.Row to dict"""
        return dict(row) if row else None

    # =========================================================================
    # BRAND OPERATIONS
    # =========================================================================

    def insert_brand(self, brand_data: Dict) -> bool:
        """
        Insert new brand

        Args:
            brand_data: Dict with brand fields

        Returns:
            True if inserted, False if already exists
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO brands (
                    brand_id, name, homepage_url, domain,
                    last_scrape_run_id, last_scrape_at, last_scrape_status,
                    total_products, total_categories,
                    added_at, total_scrape_runs, scraper_version, data_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                brand_data.get("brand_id"),
                brand_data.get("name"),
                brand_data.get("homepage_url"),
                brand_data.get("domain"),
                brand_data.get("status", {}).get("last_scrape_run_id"),
                brand_data.get("status", {}).get("last_scrape_at"),
                brand_data.get("status", {}).get("last_scrape_status"),
                brand_data.get("status", {}).get("total_products", 0),
                brand_data.get("status", {}).get("total_categories", 0),
                brand_data.get("metadata", {}).get("added_at"),
                brand_data.get("metadata", {}).get("total_scrape_runs", 0),
                brand_data.get("metadata", {}).get("scraper_version"),
                brand_data.get("data_path")
            ))
            self.conn.commit()
            return True

        except sqlite3.IntegrityError:
            return False  # Already exists

    def get_brand(self, brand_id: str) -> Optional[Dict]:
        """Get brand by ID"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM brands WHERE brand_id = ?", (brand_id,))
        row = cursor.fetchone()

        if not row:
            return None

        # Convert to dict and restructure to match file format
        brand = self._dict_from_row(row)

        return {
            "brand_id": brand["brand_id"],
            "name": brand["name"],
            "homepage_url": brand["homepage_url"],
            "domain": brand["domain"],
            "status": {
                "last_scrape_run_id": brand["last_scrape_run_id"],
                "last_scrape_at": brand["last_scrape_at"],
                "last_scrape_status": brand["last_scrape_status"],
                "total_products": brand["total_products"],
                "total_categories": brand["total_categories"]
            },
            "metadata": {
                "added_at": brand["added_at"],
                "total_scrape_runs": brand["total_scrape_runs"],
                "scraper_version": brand["scraper_version"]
            },
            "data_path": brand["data_path"]
        }

    def update_brand(self, brand_id: str, brand_data: Dict):
        """Update brand"""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE brands SET
                name = ?,
                homepage_url = ?,
                domain = ?,
                last_scrape_run_id = ?,
                last_scrape_at = ?,
                last_scrape_status = ?,
                total_products = ?,
                total_categories = ?,
                total_scrape_runs = ?,
                scraper_version = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE brand_id = ?
        """, (
            brand_data.get("name"),
            brand_data.get("homepage_url"),
            brand_data.get("domain"),
            brand_data.get("status", {}).get("last_scrape_run_id"),
            brand_data.get("status", {}).get("last_scrape_at"),
            brand_data.get("status", {}).get("last_scrape_status"),
            brand_data.get("status", {}).get("total_products", 0),
            brand_data.get("status", {}).get("total_categories", 0),
            brand_data.get("metadata", {}).get("total_scrape_runs", 0),
            brand_data.get("metadata", {}).get("scraper_version"),
            brand_id
        ))
        self.conn.commit()

    def delete_brand(self, brand_id: str) -> bool:
        """Delete brand (CASCADE deletes products and runs)"""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM brands WHERE brand_id = ?", (brand_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def list_brands(self, limit: int = 50, offset: int = 0,
                   sort_by: str = "name", order: str = "asc") -> Tuple[List[Dict], int]:
        """
        List brands with pagination

        Args:
            limit: Results per page
            offset: Pagination offset
            sort_by: Sort field
            order: 'asc' or 'desc'

        Returns:
            (brands_list, total_count)
        """
        # Validate sort field
        valid_sorts = {"name", "last_scrape_at", "total_products", "added_at"}
        if sort_by not in valid_sorts:
            sort_by = "name"

        order = "DESC" if order.lower() == "desc" else "ASC"

        # Get total count
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM brands")
        total = cursor.fetchone()["count"]

        # Get paginated results
        cursor.execute(f"""
            SELECT * FROM brands
            ORDER BY {sort_by} {order}
            LIMIT ? OFFSET ?
        """, (limit, offset))

        rows = cursor.fetchall()
        brands = [self._dict_from_row(row) for row in rows]

        return brands, total

    # =========================================================================
    # PRODUCT OPERATIONS
    # =========================================================================

    def insert_product(self, product_data: Dict) -> bool:
        """Insert new product"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO products (
                    product_url, product_id, product_name, brand_id,
                    attributes, classifications, images,
                    discovered_at, extraction_source, dom_lineage, run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                product_data.get("product_url"),
                product_data.get("product_id"),
                product_data.get("product_name"),
                product_data.get("brand_id"),
                json.dumps(product_data.get("attributes", {})),
                json.dumps(product_data.get("classifications", [])),
                json.dumps(product_data.get("images", [])),
                product_data.get("metadata", {}).get("discovered_at"),
                product_data.get("metadata", {}).get("extraction_source"),
                product_data.get("metadata", {}).get("dom_lineage"),
                product_data.get("metadata", {}).get("run_id")
            ))
            self.conn.commit()
            return True

        except sqlite3.IntegrityError:
            return False  # Duplicate product_url

    def get_product(self, product_url: str) -> Optional[Dict]:
        """Get product by URL"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM products WHERE product_url = ?", (product_url,))
        row = cursor.fetchone()

        if not row:
            return None

        return self._product_from_row(row)

    def _product_from_row(self, row: sqlite3.Row) -> Dict:
        """Convert product row to dict"""
        product = self._dict_from_row(row)

        return {
            "product_url": product["product_url"],
            "product_id": product["product_id"],
            "product_name": product["product_name"],
            "brand_id": product["brand_id"],
            "attributes": json.loads(product["attributes"]) if product["attributes"] else {},
            "classifications": json.loads(product["classifications"]) if product["classifications"] else [],
            "images": json.loads(product["images"]) if product["images"] else [],
            "metadata": {
                "discovered_at": product["discovered_at"],
                "last_updated": product["last_updated"],
                "extraction_source": product["extraction_source"],
                "dom_lineage": product["dom_lineage"],
                "run_id": product["run_id"]
            }
        }

    def query_products(self, filters: Dict, limit: int = 50, offset: int = 0) -> Tuple[List[Dict], int]:
        """
        Query products with flexible filters

        Args:
            filters: Dict with filter criteria:
                - brand_id: Filter by brand
                - classification_type: Filter by classification type
                - classification_name: Filter by classification name
                - classification_url: Filter by classification URL
                - attribute_{key}: Filter by attribute value
                - search: Full-text search in product name
            limit: Results per page
            offset: Pagination offset

        Returns:
            (products_list, total_count)
        """
        where_clauses = []
        params = []

        # Brand filter
        if filters.get("brand_id"):
            where_clauses.append("brand_id = ?")
            params.append(filters["brand_id"])

        # Search filter
        if filters.get("search"):
            where_clauses.append("product_name LIKE ?")
            params.append(f"%{filters['search']}%")

        # Classification filters (requires JSON functions)
        if filters.get("classification_url"):
            where_clauses.append("""
                EXISTS (
                    SELECT 1 FROM json_each(classifications)
                    WHERE json_extract(value, '$.url') = ?
                )
            """)
            params.append(filters["classification_url"])

        if filters.get("classification_type"):
            where_clauses.append("""
                EXISTS (
                    SELECT 1 FROM json_each(classifications)
                    WHERE json_extract(value, '$.type') = ?
                )
            """)
            params.append(filters["classification_type"])

        if filters.get("classification_name"):
            where_clauses.append("""
                EXISTS (
                    SELECT 1 FROM json_each(classifications)
                    WHERE json_extract(value, '$.name') = ?
                )
            """)
            params.append(filters["classification_name"])

        # Attribute filters
        for key, value in filters.items():
            if key.startswith("attribute_"):
                attr_key = key.replace("attribute_", "")
                where_clauses.append(f"json_extract(attributes, '$.{attr_key}') = ?")
                params.append(value)

        # Build WHERE clause
        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

        # Get total count
        cursor = self.conn.cursor()
        count_sql = f"SELECT COUNT(*) as count FROM products WHERE {where_sql}"
        cursor.execute(count_sql, params)
        total = cursor.fetchone()["count"]

        # Get paginated results
        query_sql = f"""
            SELECT * FROM products
            WHERE {where_sql}
            ORDER BY discovered_at DESC
            LIMIT ? OFFSET ?
        """
        cursor.execute(query_sql, params + [limit, offset])

        rows = cursor.fetchall()
        products = [self._product_from_row(row) for row in rows]

        return products, total

    # =========================================================================
    # SCRAPE RUN OPERATIONS
    # =========================================================================

    def insert_scrape_run(self, run_data: Dict) -> bool:
        """Insert scrape run"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO scrape_runs (
                    run_id, brand_id, start_time, end_time, duration_seconds, status,
                    summary, categories_processed, errors, scraper_config, file_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run_data.get("run_id"),
                run_data.get("brand_id"),
                run_data.get("start_time"),
                run_data.get("end_time"),
                run_data.get("duration_seconds"),
                run_data.get("status"),
                json.dumps(run_data.get("summary", {})),
                json.dumps(run_data.get("categories_processed", [])),
                json.dumps(run_data.get("errors", [])),
                json.dumps(run_data.get("scraper_config", {})),
                run_data.get("file_path")
            ))
            self.conn.commit()
            return True

        except sqlite3.IntegrityError:
            return False

    def get_scrape_runs(self, brand_id: str, limit: int = 10, offset: int = 0) -> Tuple[List[Dict], int]:
        """Get scrape run history for a brand"""
        cursor = self.conn.cursor()

        # Get total count
        cursor.execute("SELECT COUNT(*) as count FROM scrape_runs WHERE brand_id = ?", (brand_id,))
        total = cursor.fetchone()["count"]

        # Get paginated results
        cursor.execute("""
            SELECT * FROM scrape_runs
            WHERE brand_id = ?
            ORDER BY start_time DESC
            LIMIT ? OFFSET ?
        """, (brand_id, limit, offset))

        rows = cursor.fetchall()
        runs = []

        for row in rows:
            run = self._dict_from_row(row)
            run["summary"] = json.loads(run["summary"]) if run["summary"] else {}
            run["categories_processed"] = json.loads(run["categories_processed"]) if run["categories_processed"] else []
            run["errors"] = json.loads(run["errors"]) if run["errors"] else []
            run["scraper_config"] = json.loads(run["scraper_config"]) if run["scraper_config"] else {}
            runs.append(run)

        return runs, total

    # =========================================================================
    # AGGREGATION QUERIES
    # =========================================================================

    def aggregate_products_by_classification(self, brand_id: str, classification_type: str = "category") -> List[Dict]:
        """
        Aggregate products by classification

        Args:
            brand_id: Brand to aggregate
            classification_type: Type of classification to group by

        Returns:
            List of {name, count, sample_products}
        """
        cursor = self.conn.cursor()

        # This is a complex query in SQLite - we'll fetch all products and aggregate in Python
        cursor.execute("""
            SELECT * FROM products WHERE brand_id = ?
        """, (brand_id,))

        rows = cursor.fetchall()
        products = [self._product_from_row(row) for row in rows]

        # Group by classification name
        groups = {}
        for product in products:
            for classification in product.get("classifications", []):
                if classification.get("type") == classification_type:
                    name = classification.get("name", "Unknown")

                    if name not in groups:
                        groups[name] = {
                            "key": name,
                            "count": 0,
                            "sample_products": []
                        }

                    groups[name]["count"] += 1
                    if len(groups[name]["sample_products"]) < 3:
                        groups[name]["sample_products"].append(product)

        return list(groups.values())

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
