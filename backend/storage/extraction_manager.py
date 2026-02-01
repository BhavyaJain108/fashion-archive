"""
Extraction Manager
==================

Reads data from the new pipeline output at extractions/{domain}/.
Replaces the old data/brands/{brand_id}/ structure.
"""

import json
import fcntl
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
from datetime import datetime


class ExtractionManager:
    """Reads extraction data from extractions/{domain}/ folders"""

    def __init__(self, base_path: str = None):
        """
        Initialize ExtractionManager

        Args:
            base_path: Base directory for extractions (default: backend/extractions)
        """
        if base_path:
            self.base_path = Path(base_path)
        else:
            # Default to extractions/ directory relative to backend
            self.base_path = Path(__file__).parent.parent / "extractions"

        # Ensure directory exists
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _read_json(self, file_path: Path) -> Optional[Dict]:
        """Read JSON file with file locking"""
        if not file_path.exists():
            return None

        with open(file_path, 'r') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                data = json.load(f)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        return data

    def _get_domain_path(self, domain: str) -> Path:
        """Get path to domain directory (with underscores)"""
        clean_domain = domain.replace('.', '_')
        return self.base_path / clean_domain

    def _domain_to_brand_id(self, domain: str) -> str:
        """Convert domain folder name to brand_id.

        The brand_id IS the folder name (e.g. devi-clothing_com).
        This avoids lossy conversions that strip hyphens or TLDs.
        """
        return domain

    def _brand_id_to_domain(self, brand_id: str) -> str:
        """Convert brand_id to domain folder name.

        First checks for an exact match, then does a fuzzy search
        to stay compatible with old brand_ids that stripped the TLD.
        """
        if not self.base_path.exists():
            return brand_id

        # Exact match (brand_id IS the folder name in the new scheme)
        if (self.base_path / brand_id).is_dir():
            return brand_id

        # Fuzzy fallback: support old-style brand_ids that dropped TLD/hyphens
        normalized = brand_id.replace('-', '').replace('_', '').lower()

        for d in self.base_path.iterdir():
            if not d.is_dir():
                continue
            folder_normalized = d.name.replace('-', '').replace('_', '').lower()
            if folder_normalized == normalized:
                return d.name
            # Also try stripping TLD from folder for matching
            parts = d.name.rsplit('_', 1)
            if len(parts) == 2:
                base_normalized = parts[0].replace('-', '').replace('_', '').lower()
                if base_normalized == normalized:
                    return d.name

        return brand_id  # fallback: return as-is

    # =========================================================================
    # BRAND OPERATIONS
    # =========================================================================

    def list_brands(self) -> List[str]:
        """Get list of all brand IDs (extracted domains)"""
        if not self.base_path.exists():
            return []

        domains = []
        for d in self.base_path.iterdir():
            if d.is_dir() and ((d / "nav.json").exists() or (d / "brand.json").exists()):
                domains.append(d.name)

        return domains

    def read_brand(self, brand_id: str) -> Optional[Dict]:
        """
        Read brand info aggregated from extraction files.

        Builds brand data from:
        - nav.json (navigation, category count)
        - urls.json (product counts)
        - metrics.json (timing, costs)
        - config.json (extraction config)
        """
        domain_folder = self._brand_id_to_domain(brand_id)
        domain_path = self._get_domain_path(domain_folder)

        if not domain_path.exists():
            # Try with the brand_id directly as folder name
            domain_path = self.base_path / brand_id
            if not domain_path.exists():
                return None

        # Load available data
        nav_data = self._read_json(domain_path / "nav.json")
        urls_data = self._read_json(domain_path / "urls.json")
        metrics_data = self._read_json(domain_path / "metrics.json")
        config_data = self._read_json(domain_path / "config.json")

        # If no extraction data yet, check for brand.json (newly created brand)
        if not nav_data and not urls_data:
            brand_json = self._read_json(domain_path / "brand.json")
            if brand_json:
                return brand_json
            return None

        # Build brand object
        domain = domain_path.name.replace('_', '.')
        # Derive display name: strip TLD, replace separators with spaces
        name_base = domain_path.name.rsplit('_', 1)[0]  # e.g. "devi-clothing"
        brand_name = name_base.replace('-', ' ').replace('_', ' ').title()

        # Get stats
        category_count = nav_data.get("category_count", 0) if nav_data else 0
        unique_products = urls_data.get("unique_products", 0) if urls_data else 0

        # Get last run time from metrics
        last_scrape_at = None
        if metrics_data:
            # Get most recent stage run time
            for stage_key in ["stage_3", "stage_2", "stage_1"]:
                if stage_key in metrics_data:
                    last_scrape_at = metrics_data[stage_key].get("run_time")
                    if last_scrape_at:
                        break

        brand_data = {
            "brand_id": brand_id,
            "name": brand_name,
            "domain": domain,
            "homepage_url": f"https://{domain}",
            "data_path": str(domain_path),
            "status": {
                "total_products": unique_products,
                "total_categories": category_count,
                "last_scrape_at": last_scrape_at,
                "last_scrape_status": "completed" if unique_products > 0 else "pending"
            },
            "metadata": {
                "extraction_method": nav_data.get("method", "unknown") if nav_data else "unknown",
                "total_scrape_runs": 1 if metrics_data else 0
            }
        }

        # Add metrics summary if available
        if metrics_data:
            total_cost = 0
            total_duration = 0
            for stage_data in metrics_data.values():
                if isinstance(stage_data, dict):
                    total_duration += stage_data.get("duration", 0)
                    summary = stage_data.get("summary", {})
                    total_cost += summary.get("cost", 0)

            brand_data["metrics"] = {
                "total_duration": total_duration,
                "total_cost": total_cost
            }

        return brand_data

    def get_brand_index(self) -> Dict:
        """Get summary of all brands for listing"""
        brands = []

        for domain_folder in self.list_brands():
            brand_id = self._domain_to_brand_id(domain_folder)
            brand_data = self.read_brand(brand_id)

            if brand_data:
                brands.append({
                    "brand_id": brand_id,
                    "name": brand_data.get("name", brand_id),
                    "domain": brand_data.get("domain", ""),
                    "total_products": brand_data.get("status", {}).get("total_products", 0),
                    "total_categories": brand_data.get("status", {}).get("total_categories", 0),
                    "last_scrape_at": brand_data.get("status", {}).get("last_scrape_at")
                })

        # Sort by name
        brands.sort(key=lambda x: x["name"].lower())

        return {
            "brands": brands,
            "total_brands": len(brands),
            "last_updated": datetime.utcnow().isoformat() + "Z"
        }

    # =========================================================================
    # NAVIGATION OPERATIONS
    # =========================================================================

    def read_navigation(self, brand_id: str) -> Optional[Dict]:
        """Read navigation tree from nav.json"""
        domain_folder = self._brand_id_to_domain(brand_id)
        domain_path = self._get_domain_path(domain_folder)

        if not domain_path.exists():
            domain_path = self.base_path / brand_id
            if not domain_path.exists():
                return None

        return self._read_json(domain_path / "nav.json")

    # =========================================================================
    # PRODUCTS OPERATIONS
    # =========================================================================

    def read_products(self, brand_id: str) -> Optional[Dict]:
        """
        Read all products from products/{category}/*.json files.

        Returns dict with:
        - products: list of product dicts
        - total_products: count
        """
        domain_folder = self._brand_id_to_domain(brand_id)
        domain_path = self._get_domain_path(domain_folder)

        if not domain_path.exists():
            domain_path = self.base_path / brand_id
            if not domain_path.exists():
                return None

        products_dir = domain_path / "products"
        if not products_dir.exists():
            # Maybe products aren't extracted yet, return empty
            return {"products": [], "total_products": 0}

        # Deduplicate by product URL, keeping the most recently modified file
        seen = {}  # product_url -> (mtime, product_data)

        # Walk through category folders
        for category_path in products_dir.rglob("*.json"):
            product_data = self._read_json(category_path)
            if product_data:
                # Add category from path
                rel_path = category_path.relative_to(products_dir)
                category_parts = list(rel_path.parent.parts)

                # Build classification from path
                product_data["brand_id"] = brand_id
                product_data["classifications"] = [{
                    "type": "category",
                    "name": " > ".join(p.replace('-', ' ').title() for p in category_parts) if category_parts else "Uncategorized",
                    "url": product_data.get("url", ""),
                    "hierarchy": category_parts
                }]

                product_url = product_data.get("url") or product_data.get("source_url") or ""
                mtime = category_path.stat().st_mtime if category_path.exists() else 0

                if product_url and product_url in seen:
                    # Keep the newer file
                    if mtime > seen[product_url][0]:
                        seen[product_url] = (mtime, product_data)
                else:
                    seen[product_url or str(category_path)] = (mtime, product_data)

        products = [entry[1] for entry in seen.values()]

        return {
            "products": products,
            "total_products": len(products)
        }

    def get_product(self, product_url: str, brand_id: str = None) -> Optional[Dict]:
        """
        Find a product by URL.

        If brand_id is not provided, searches all brands.
        """
        brands_to_search = [brand_id] if brand_id else self.list_brands()

        for bid in brands_to_search:
            if not brand_id:
                bid = self._domain_to_brand_id(bid)

            products_data = self.read_products(bid)
            if products_data:
                for product in products_data.get("products", []):
                    if product.get("url") == product_url:
                        return product

        return None

    # =========================================================================
    # URLS TREE OPERATIONS
    # =========================================================================

    def read_urls(self, brand_id: str) -> Optional[Dict]:
        """Read URLs tree from urls.json"""
        domain_folder = self._brand_id_to_domain(brand_id)
        domain_path = self._get_domain_path(domain_folder)

        if not domain_path.exists():
            domain_path = self.base_path / brand_id
            if not domain_path.exists():
                return None

        return self._read_json(domain_path / "urls.json")

    # =========================================================================
    # METRICS OPERATIONS
    # =========================================================================

    def read_metrics(self, brand_id: str) -> Optional[Dict]:
        """Read metrics from metrics.json"""
        domain_folder = self._brand_id_to_domain(brand_id)
        domain_path = self._get_domain_path(domain_folder)

        if not domain_path.exists():
            domain_path = self.base_path / brand_id
            if not domain_path.exists():
                return None

        return self._read_json(domain_path / "metrics.json")

    # =========================================================================
    # CONFIG OPERATIONS
    # =========================================================================

    def read_config(self, brand_id: str) -> Optional[Dict]:
        """Read extraction config from config.json"""
        domain_folder = self._brand_id_to_domain(brand_id)
        domain_path = self._get_domain_path(domain_folder)

        if not domain_path.exists():
            domain_path = self.base_path / brand_id
            if not domain_path.exists():
                return None

        return self._read_json(domain_path / "config.json")

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def get_all_classifications(self, brand_id: str) -> Dict:
        """Get all unique classifications for a brand"""
        products_data = self.read_products(brand_id)

        if not products_data:
            return {}

        classifications_by_type = {}

        for product in products_data.get("products", []):
            for classification in product.get("classifications", []):
                classification_type = classification.get("type", "unknown")

                if classification_type not in classifications_by_type:
                    classifications_by_type[classification_type] = []

                # Check if already exists (by name)
                exists = any(
                    c.get("name") == classification.get("name")
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
                        c.get("name") == classification["name"]
                        for c in product.get("classifications", [])
                    )
                )

        return classifications_by_type

    def get_all_attributes(self, brand_id: str) -> Dict:
        """Get all unique attributes for a brand"""
        products_data = self.read_products(brand_id)

        if not products_data:
            return {}

        attributes_map = {}

        for product in products_data.get("products", []):
            # Extract standard fields as attributes
            for key in ["brand", "category", "sku"]:
                value = product.get(key)
                if value:
                    if key not in attributes_map:
                        attributes_map[key] = {
                            "type": "string",
                            "unique_values": set(),
                            "products_with_attribute": 0
                        }
                    attributes_map[key]["unique_values"].add(str(value))
                    attributes_map[key]["products_with_attribute"] += 1

            # Extract from variants if present
            variants = product.get("variants", [])
            if variants:
                for variant in variants:
                    for key in ["size", "color"]:
                        value = variant.get(key)
                        if value:
                            if key not in attributes_map:
                                attributes_map[key] = {
                                    "type": "string",
                                    "unique_values": set(),
                                    "products_with_attribute": 0
                                }
                            attributes_map[key]["unique_values"].add(str(value))

                # Count product once even if multiple variants
                if "size" in attributes_map:
                    attributes_map["size"]["products_with_attribute"] += 1
                if "color" in attributes_map:
                    attributes_map["color"]["products_with_attribute"] += 1

        # Convert sets to sorted lists
        for attr_key in attributes_map:
            attributes_map[attr_key]["unique_values"] = sorted(list(attributes_map[attr_key]["unique_values"]))
            attributes_map[attr_key]["unique_values_count"] = len(attributes_map[attr_key]["unique_values"])

        return attributes_map

    def get_product_counts_by_url(self, brand_id: str) -> Dict[str, int]:
        """
        Get product counts grouped by category URL from urls.json tree.

        Returns:
            Dict mapping category URL to product count
        """
        urls_data = self.read_urls(brand_id)

        if not urls_data:
            return {}

        url_counts = {}

        def count_from_tree(nodes):
            for node in nodes:
                url = node.get("url")
                products = node.get("products", [])
                if url and products:
                    url_counts[url] = len(products)

                # Recurse into children
                children = node.get("children", [])
                if children:
                    count_from_tree(children)

        tree = urls_data.get("category_tree", [])
        count_from_tree(tree)

        return url_counts
