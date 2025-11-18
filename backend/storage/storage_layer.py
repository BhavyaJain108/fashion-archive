"""
Unified Storage Layer
====================

Provides single interface for all storage operations.
Supports files, database, or both with seamless switching.
"""

from typing import Dict, List, Optional, Tuple, Any
from .file_manager import DataManager
from .database import DatabaseManager


class Storage:
    """Unified storage interface for brand/product data"""

    def __init__(self, mode: str = "files", db_path: str = "data/brands.db"):
        """
        Initialize storage

        Args:
            mode: Storage mode - 'files', 'database', or 'both'
            db_path: Path to database file (if using database)
        """
        self.mode = mode

        # Initialize storage backends
        if mode in ["files", "both"]:
            self.data_manager = DataManager()
        else:
            self.data_manager = None

        if mode in ["database", "both"]:
            self.db_manager = DatabaseManager(db_path=db_path)
        else:
            self.db_manager = None

    # =========================================================================
    # BRAND OPERATIONS
    # =========================================================================

    def create_brand(self, brand_id: str, brand_data: Dict) -> bool:
        """Create new brand"""
        success = True

        if self.data_manager:
            success = self.data_manager.create_brand(brand_id, brand_data) and success

        if self.db_manager:
            success = self.db_manager.insert_brand(brand_data) and success

        return success

    def get_brand(self, brand_id: str) -> Optional[Dict]:
        """Get brand by ID - prefer database, fallback to files"""
        if self.db_manager:
            return self.db_manager.get_brand(brand_id)
        elif self.data_manager:
            return self.data_manager.read_brand(brand_id)
        return None

    def update_brand(self, brand_id: str, brand_data: Dict):
        """Update brand"""
        if self.data_manager:
            self.data_manager.write_brand(brand_id, brand_data)

        if self.db_manager:
            self.db_manager.update_brand(brand_id, brand_data)

    def delete_brand(self, brand_id: str) -> bool:
        """Delete brand and all associated data"""
        success = True

        if self.data_manager:
            success = self.data_manager.delete_brand(brand_id) and success

        if self.db_manager:
            success = self.db_manager.delete_brand(brand_id) and success

        return success

    def list_brands(self, limit: int = 50, offset: int = 0,
                   sort_by: str = "name", order: str = "asc") -> Tuple[List[Dict], int]:
        """
        List brands with pagination

        Returns:
            (brands_list, total_count)
        """
        if self.db_manager:
            return self.db_manager.list_brands(limit, offset, sort_by, order)

        elif self.data_manager:
            # File-based listing
            index = self.data_manager.read_brand_index()
            brands = index.get("brands", [])

            # Simple sorting (not as sophisticated as DB)
            reverse = (order.lower() == "desc")
            if sort_by == "name":
                brands.sort(key=lambda x: x.get("name", "").lower(), reverse=reverse)
            elif sort_by == "total_products":
                brands.sort(key=lambda x: x.get("total_products", 0), reverse=reverse)
            elif sort_by == "last_scrape_at":
                brands.sort(key=lambda x: x.get("last_scrape_at") or "", reverse=reverse)

            total = len(brands)
            paginated = brands[offset:offset + limit]

            return paginated, total

        return [], 0

    # =========================================================================
    # PRODUCT OPERATIONS
    # =========================================================================

    def save_products(self, brand_id: str, products_data: Dict):
        """Save products for a brand"""
        if self.data_manager:
            self.data_manager.write_products(brand_id, products_data)

        if self.db_manager:
            # Insert each product
            for product in products_data.get("products", []):
                product["brand_id"] = brand_id
                self.db_manager.insert_product(product)

    def get_product(self, product_url: str) -> Optional[Dict]:
        """Get single product by URL"""
        if self.db_manager:
            return self.db_manager.get_product(product_url)

        elif self.data_manager:
            # Need to search through all brand products (slower)
            # For now, return None - this is why database is better for product queries
            return None

        return None

    def query_products(self, filters: Dict, limit: int = 50, offset: int = 0) -> Tuple[List[Dict], int]:
        """
        Query products with flexible filters

        Args:
            filters: Dict with filter criteria (see db_manager.query_products)
            limit: Results per page
            offset: Pagination offset

        Returns:
            (products_list, total_count)
        """
        if self.db_manager:
            return self.db_manager.query_products(filters, limit, offset)

        elif self.data_manager:
            # File-based querying (basic implementation)
            brand_id = filters.get("brand_id")
            if not brand_id:
                return [], 0

            products_data = self.data_manager.read_products(brand_id)
            if not products_data:
                return [], 0

            products = products_data.get("products", [])

            # Apply simple filters
            filtered = products

            # Classification URL filter
            if filters.get("classification_url"):
                url = filters["classification_url"]
                filtered = [
                    p for p in filtered
                    if any(c.get("url") == url for c in p.get("classifications", []))
                ]

            # Search filter
            if filters.get("search"):
                search = filters["search"].lower()
                filtered = [
                    p for p in filtered
                    if search in p.get("product_name", "").lower()
                ]

            total = len(filtered)
            paginated = filtered[offset:offset + limit]

            return paginated, total

        return [], 0

    def aggregate_products(self, brand_id: str, group_by: str) -> List[Dict]:
        """
        Aggregate products by classification or attribute

        Args:
            brand_id: Brand to aggregate
            group_by: Field to group by (e.g., 'classification.category.name', 'attribute.color')

        Returns:
            List of {key, count, sample_products}
        """
        if self.db_manager:
            # Parse group_by
            if group_by.startswith("classification."):
                parts = group_by.split(".")
                if len(parts) >= 2:
                    classification_type = parts[1]  # 'category', 'collection', etc.
                    return self.db_manager.aggregate_products_by_classification(brand_id, classification_type)

        elif self.data_manager:
            # File-based aggregation
            products_data = self.data_manager.read_products(brand_id)
            if not products_data:
                return []

            products = products_data.get("products", [])
            groups = {}

            if group_by.startswith("classification."):
                parts = group_by.split(".")
                if len(parts) >= 3:
                    classification_type = parts[1]
                    field = parts[2]  # 'name'

                    for product in products:
                        for classification in product.get("classifications", []):
                            if classification.get("type") == classification_type:
                                key = classification.get(field, "Unknown")

                                if key not in groups:
                                    groups[key] = {
                                        "key": key,
                                        "count": 0,
                                        "sample_products": []
                                    }

                                groups[key]["count"] += 1
                                if len(groups[key]["sample_products"]) < 3:
                                    groups[key]["sample_products"].append(product)

            elif group_by.startswith("attribute."):
                attr_key = group_by.replace("attribute.", "")

                for product in products:
                    value = product.get("attributes", {}).get(attr_key)
                    if value:
                        key = str(value)

                        if key not in groups:
                            groups[key] = {
                                "key": key,
                                "count": 0,
                                "sample_products": []
                            }

                        groups[key]["count"] += 1
                        if len(groups[key]["sample_products"]) < 3:
                            groups[key]["sample_products"].append(product)

            return list(groups.values())

        return []

    def get_product_counts_by_url(self, brand_id: str) -> Dict[str, int]:
        """
        Get product counts grouped by classification URL

        Args:
            brand_id: Brand to get counts for

        Returns:
            Dict mapping classification URL to product count
        """
        if self.db_manager:
            return self.db_manager.get_product_counts_by_url(brand_id)

        elif self.data_manager:
            # File-based count aggregation
            products_data = self.data_manager.read_products(brand_id)
            if not products_data:
                return {}

            products = products_data.get("products", [])
            url_counts = {}

            for product in products:
                for classification in product.get("classifications", []):
                    url = classification.get("url")
                    if url:
                        url_counts[url] = url_counts.get(url, 0) + 1

            return url_counts

        return {}

    # =========================================================================
    # NAVIGATION OPERATIONS
    # =========================================================================

    def save_navigation(self, brand_id: str, navigation_data: Dict):
        """Save navigation tree"""
        if self.data_manager:
            self.data_manager.write_navigation(brand_id, navigation_data)

    def get_navigation(self, brand_id: str) -> Optional[Dict]:
        """Get navigation tree"""
        if self.data_manager:
            return self.data_manager.read_navigation(brand_id)
        return None

    # =========================================================================
    # SCRAPING INTELLIGENCE OPERATIONS
    # =========================================================================

    def save_scraping_intel(self, brand_id: str, intel_data: Dict):
        """Save scraping intelligence"""
        if self.data_manager:
            self.data_manager.write_scraping_intel(brand_id, intel_data)

    def get_scraping_intel(self, brand_id: str) -> Optional[Dict]:
        """Get scraping intelligence"""
        if self.data_manager:
            return self.data_manager.read_scraping_intel(brand_id)
        return None

    # =========================================================================
    # SCRAPE RUN OPERATIONS
    # =========================================================================

    def save_scrape_run(self, brand_id: str, run_data: Dict) -> str:
        """Save scrape run history"""
        run_id = run_data.get("run_id")

        if self.data_manager:
            run_id = self.data_manager.save_scrape_run(brand_id, run_data)

        if self.db_manager:
            self.db_manager.insert_scrape_run(run_data)

        return run_id

    def get_scrape_runs(self, brand_id: str, limit: int = 10, offset: int = 0) -> Tuple[List[Dict], int]:
        """Get scrape run history"""
        if self.db_manager:
            return self.db_manager.get_scrape_runs(brand_id, limit, offset)

        elif self.data_manager:
            run_ids = self.data_manager.list_scrape_runs(brand_id)
            total = len(run_ids)

            # Sort by run_id (which includes timestamp) desc
            run_ids.sort(reverse=True)

            # Paginate
            paginated_ids = run_ids[offset:offset + limit]

            runs = []
            for run_id in paginated_ids:
                run = self.data_manager.read_scrape_run(brand_id, run_id)
                if run:
                    runs.append(run)

            return runs, total

        return [], 0

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def get_all_classifications(self, brand_id: str) -> Dict:
        """
        Get all unique classifications for a brand

        Returns:
            Dict of {type: [classification_objects]}
        """
        products_data = None

        if self.data_manager:
            products_data = self.data_manager.read_products(brand_id)

        if not products_data:
            return {}

        classifications_by_type = {}

        for product in products_data.get("products", []):
            for classification in product.get("classifications", []):
                classification_type = classification.get("type", "unknown")

                if classification_type not in classifications_by_type:
                    classifications_by_type[classification_type] = []

                # Check if already exists (by URL)
                exists = any(
                    c.get("url") == classification.get("url")
                    for c in classifications_by_type[classification_type]
                )

                if not exists:
                    classifications_by_type[classification_type].append({
                        "name": classification.get("name"),
                        "url": classification.get("url"),
                        "hierarchy": classification.get("hierarchy", [])
                    })

        # Count products for each classification
        for classification_type, classifications in classifications_by_type.items():
            for classification in classifications:
                classification["product_count"] = sum(
                    1 for product in products_data.get("products", [])
                    if any(
                        c.get("url") == classification["url"]
                        for c in product.get("classifications", [])
                    )
                )

        return classifications_by_type

    def get_all_attributes(self, brand_id: str) -> Dict:
        """
        Get all unique attributes for a brand

        Returns:
            Dict of {attribute_key: {type, unique_values, products_with_attribute}}
        """
        products_data = None

        if self.data_manager:
            products_data = self.data_manager.read_products(brand_id)

        if not products_data:
            return {}

        attributes_map = {}

        for product in products_data.get("products", []):
            for attr_key, attr_value in product.get("attributes", {}).items():
                if attr_key not in attributes_map:
                    attributes_map[attr_key] = {
                        "type": type(attr_value).__name__,
                        "unique_values": set(),
                        "products_with_attribute": 0
                    }

                # Add value to set
                if isinstance(attr_value, list):
                    for v in attr_value:
                        attributes_map[attr_key]["unique_values"].add(str(v))
                else:
                    attributes_map[attr_key]["unique_values"].add(str(attr_value))

                attributes_map[attr_key]["products_with_attribute"] += 1

        # Convert sets to lists
        for attr_key in attributes_map:
            attributes_map[attr_key]["unique_values"] = sorted(list(attributes_map[attr_key]["unique_values"]))
            attributes_map[attr_key]["unique_values_count"] = len(attributes_map[attr_key]["unique_values"])

        return attributes_map

    def close(self):
        """Close all connections"""
        if self.db_manager:
            self.db_manager.close()


# Global storage instance (singleton pattern)
_storage = None


def get_storage(mode: str = "files") -> Storage:
    """Get or create global storage instance"""
    global _storage
    if _storage is None:
        _storage = Storage(mode=mode)
    return _storage
