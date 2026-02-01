"""
Unified Storage Layer
====================

Provides single interface for all storage operations.
Uses extractions/{domain}/ folder structure.
"""

from typing import Dict, List, Optional, Tuple, Any
from .extraction_manager import ExtractionManager


class Storage:
    """Unified storage interface for brand/product data"""

    def __init__(self):
        """Initialize storage with ExtractionManager."""
        self.extraction_manager = ExtractionManager()

    # =========================================================================
    # BRAND OPERATIONS
    # =========================================================================

    def get_brand(self, brand_id: str) -> Optional[Dict]:
        """Get brand by ID from extractions."""
        return self.extraction_manager.read_brand(brand_id)

    def create_brand(self, brand_id: str, brand_data: Dict) -> bool:
        """Create brand by saving brand.json to the extraction directory."""
        try:
            domain = brand_data.get("domain", "")
            domain_folder = domain.replace('.', '_') if domain else f"{brand_id}_com"
            domain_path = self.extraction_manager.base_path / domain_folder
            domain_path.mkdir(parents=True, exist_ok=True)

            brand_json_path = domain_path / "brand.json"
            import json
            with open(brand_json_path, 'w') as f:
                json.dump(brand_data, f, indent=2)
            return True
        except Exception as e:
            print(f"Error creating brand {brand_id}: {e}")
            return False

    def update_brand(self, brand_id: str, brand_data: Dict):
        """Update brand.json."""
        self.create_brand(brand_id, brand_data)

    def delete_brand(self, brand_id: str) -> bool:
        """Stub - would need to delete extraction folder."""
        return False

    def list_brands(self, limit: int = 50, offset: int = 0,
                   sort_by: str = "name", order: str = "asc") -> Tuple[List[Dict], int]:
        """
        List brands with pagination.

        Returns:
            (brands_list, total_count)
        """
        index = self.extraction_manager.get_brand_index()
        brands = index.get("brands", [])

        # Simple sorting
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

    # =========================================================================
    # PRODUCT OPERATIONS
    # =========================================================================

    def get_product(self, product_url: str) -> Optional[Dict]:
        """Get single product by URL."""
        return self.extraction_manager.get_product(product_url)

    def query_products(self, filters: Dict, limit: int = 50, offset: int = 0) -> Tuple[List[Dict], int]:
        """
        Query products with flexible filters.

        Args:
            filters: Dict with filter criteria
            limit: Results per page
            offset: Pagination offset

        Returns:
            (products_list, total_count)
        """
        brand_id = filters.get("brand_id")

        if not brand_id:
            return [], 0

        products_data = self.extraction_manager.read_products(brand_id)
        if not products_data:
            return [], 0

        products = products_data.get("products", [])

        # Apply filters
        filtered = products

        # Classification name filter
        if filters.get("classification_name"):
            name = filters["classification_name"]
            filtered = [
                p for p in filtered
                if any(c.get("name") == name for c in p.get("classifications", []))
            ]

        # Classification URL filter - use urls.json to find products in category
        if filters.get("classification_url"):
            category_url = filters["classification_url"]
            # Get product URLs for this category from urls.json
            urls_data = self.extraction_manager.read_urls(brand_id)
            product_urls_in_category = set()

            if urls_data:
                def find_products_for_url(nodes, target_url):
                    """Recursively find products for a category URL."""
                    for node in nodes:
                        if node.get("url") == target_url:
                            return set(node.get("products", []))
                        children = node.get("children", [])
                        if children:
                            result = find_products_for_url(children, target_url)
                            if result:
                                return result
                    return set()

                product_urls_in_category = find_products_for_url(
                    urls_data.get("category_tree", []),
                    category_url
                )

            def get_product_slug(url):
                """Extract product slug from URL, stripping variant suffix."""
                # e.g., /products/the-snap-black -> the-snap
                if '/products/' in url:
                    slug = url.split('/products/')[-1].split('?')[0]
                    # Strip common color/variant suffixes
                    parts = slug.rsplit('-', 1)
                    if len(parts) == 2 and len(parts[1]) <= 12:
                        # Likely a variant suffix, return base
                        return parts[0]
                    return slug
                return url

            # Build set of base slugs from category products
            category_slugs = {get_product_slug(url) for url in product_urls_in_category}

            filtered = [
                p for p in filtered
                if p.get("url") in product_urls_in_category
                or p.get("source_url") in product_urls_in_category
                or get_product_slug(p.get("url", "")) in category_slugs
            ]

        # Search filter - search in name and description
        if filters.get("search"):
            search = filters["search"].lower()
            filtered = [
                p for p in filtered
                if search in p.get("name", "").lower()
                or search in p.get("description", "").lower()
            ]

        total = len(filtered)
        paginated = filtered[offset:offset + limit]

        return paginated, total

    def get_product_counts_by_url(self, brand_id: str) -> Dict[str, int]:
        """
        Get product counts grouped by category URL.

        Args:
            brand_id: Brand to get counts for

        Returns:
            Dict mapping category URL to product count
        """
        return self.extraction_manager.get_product_counts_by_url(brand_id)

    def aggregate_products(self, brand_id: str, group_by: str) -> List[Dict]:
        """Aggregate products by classification or attribute."""
        # Could implement if needed
        return []

    # =========================================================================
    # NAVIGATION OPERATIONS
    # =========================================================================

    def get_navigation(self, brand_id: str) -> Optional[Dict]:
        """Get navigation tree."""
        return self.extraction_manager.read_navigation(brand_id)

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def get_all_classifications(self, brand_id: str) -> Dict:
        """
        Get all unique classifications for a brand.

        Returns:
            Dict of {type: [classification_objects]}
        """
        return self.extraction_manager.get_all_classifications(brand_id)

    def get_all_attributes(self, brand_id: str) -> Dict:
        """
        Get all unique attributes for a brand.

        Returns:
            Dict of {attribute_key: {type, unique_values, products_with_attribute}}
        """
        return self.extraction_manager.get_all_attributes(brand_id)

    def get_metrics(self, brand_id: str) -> Optional[Dict]:
        """Get metrics data for a brand."""
        return self.extraction_manager.read_metrics(brand_id)

    def get_urls(self, brand_id: str) -> Optional[Dict]:
        """Get URLs tree for a brand."""
        return self.extraction_manager.read_urls(brand_id)

    def get_scrape_runs(self, brand_id: str, limit: int = 10, offset: int = 0) -> Tuple[List[Dict], int]:
        """Get scrape run history - returns metrics as single run."""
        metrics = self.extraction_manager.read_metrics(brand_id)
        if metrics:
            # Convert metrics to a single "run" entry
            run = {
                "run_id": "pipeline_run",
                "status": "completed",
                "stages": metrics
            }
            return [run], 1
        return [], 0

    def get_scraping_intel(self, brand_id: str) -> Optional[Dict]:
        """Get scraping intelligence - returns config as intel."""
        return self.extraction_manager.read_config(brand_id)

    def close(self):
        """Close connections (no-op for file-based storage)."""
        pass


# Global storage instance (singleton pattern)
_storage = None


def get_storage(mode: str = None) -> Storage:
    """Get or create global storage instance."""
    global _storage
    if _storage is None:
        _storage = Storage()
    return _storage
