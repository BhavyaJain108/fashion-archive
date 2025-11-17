"""
Scrape Results Writer
====================

Transforms raw scraper output into normalized storage format.
Handles deduplication, pattern extraction, and storage.
"""

import os
import shutil
import re
from typing import Dict, List, Optional
from datetime import datetime
from urllib.parse import urlparse
from backend.storage import Storage


class ScrapeResultsWriter:
    """Writes scraper results to normalized storage"""

    def __init__(self, storage: Storage):
        """
        Initialize results writer

        Args:
            storage: Storage instance to use
        """
        self.storage = storage

    def _slugify(self, text: str) -> str:
        """Convert text to URL-safe slug"""
        text = text.lower().strip()
        text = re.sub(r'[^\w\s-]', '', text)
        text = re.sub(r'[-\s]+', '_', text)
        return text

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL"""
        parsed = urlparse(url)
        domain = parsed.netloc
        # Remove www. prefix
        if domain.startswith('www.'):
            domain = domain[4:]
        return domain

    def write_scrape_results(self, brand_url: str, scrape_output: Dict, brand_name: Optional[str] = None, brand_id: Optional[str] = None) -> Dict:
        """
        Write scrape results to storage

        Args:
            brand_url: Brand homepage URL
            scrape_output: Raw output from Brand.run_full_extraction_pipeline()
            brand_name: Optional brand name (will extract from URL if not provided)
            brand_id: Optional brand ID (will generate from URL if not provided)

        Returns:
            Dict with status and metadata
        """
        # Extract metadata
        domain = self._extract_domain(brand_url)

        # Use provided brand_id or generate one
        if not brand_id:
            brand_id = self._slugify(domain)

        if not brand_name:
            brand_name = domain.split('.')[0].title()

        run_id = f"run_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        current_time = datetime.utcnow().isoformat() + "Z"

        # 1. UPDATE BRAND (brand should already exist from API)
        existing_brand = self.storage.get_brand(brand_id)

        if existing_brand:
            # Update existing brand status
            self.storage.update_brand(brand_id, {
                **existing_brand,
                "status": {
                    **existing_brand.get("status", {}),
                    "last_scrape_run_id": run_id,
                    "last_scrape_at": current_time,
                    "last_scrape_status": "running"
                }
            })
        else:
            # Fallback: Create new brand if it doesn't exist (for legacy use cases)
            brand_data = {
                "brand_id": brand_id,
                "name": brand_name,
                "homepage_url": brand_url,
                "domain": domain,
                "status": {
                    "last_scrape_run_id": run_id,
                    "last_scrape_at": current_time,
                    "last_scrape_status": "running",
                    "total_products": 0,
                    "total_categories": 0
                },
                "metadata": {
                    "added_at": current_time,
                    "total_scrape_runs": 0,
                    "scraper_version": "1.0"
                },
                "data_path": f"data/brands/{brand_id}"
            }
            self.storage.create_brand(brand_id, brand_data)

        # 2. SAVE NAVIGATION TREE
        navigation_tree = scrape_output.get("navigation_tree", {})
        if navigation_tree:
            navigation_data = {
                "brand_id": brand_id,
                "captured_at": current_time,
                "run_id": run_id,
                **navigation_tree
            }
            self.storage.save_navigation(brand_id, navigation_data)

        # 3. NORMALIZE AND SAVE PRODUCTS
        normalized_products = self._normalize_products(brand_id, scrape_output)

        products_data = {
            "brand_id": brand_id,
            "total_products": len(normalized_products),
            "last_updated": current_time,
            "run_id": run_id,
            "products": normalized_products
        }
        self.storage.save_products(brand_id, products_data)

        # 4. EXTRACT AND SAVE SCRAPING INTELLIGENCE
        scraping_intel = self._extract_scraping_intelligence(brand_id, scrape_output, current_time)
        self.storage.save_scraping_intel(brand_id, scraping_intel)

        # 5. SAVE SCRAPE RUN HISTORY
        summary = scrape_output.get("summary", {})
        run_data = {
            "run_id": run_id,
            "brand_id": brand_id,
            "start_time": current_time,  # Approximation - could pass actual start time
            "end_time": current_time,
            "duration_seconds": summary.get("extraction_time", 0),
            "status": "completed" if scrape_output.get("success") else "failed",
            "summary": summary,
            "categories_processed": self._extract_categories_summary(scrape_output),
            "errors": [],
            "scraper_config": {
                "version": "1.0",
                "test_mode": False
            },
            "file_path": None
        }
        self.storage.save_scrape_run(brand_id, run_data)

        # 6. UPDATE BRAND FINAL STATUS
        brand = self.storage.get_brand(brand_id)
        if brand:
            brand["status"]["last_scrape_status"] = "completed"
            brand["status"]["total_products"] = len(normalized_products)
            brand["status"]["total_categories"] = len(scrape_output.get("categories", {}))
            self.storage.update_brand(brand_id, brand)

        return {
            "success": True,
            "brand_id": brand_id,
            "run_id": run_id,
            "total_products": len(normalized_products),
            "total_categories": len(scrape_output.get("categories", {}))
        }

    def _normalize_products(self, brand_id: str, scrape_output: Dict) -> List[Dict]:
        """
        Normalize products from scraper output

        Args:
            brand_id: Brand identifier
            scrape_output: Raw scraper output

        Returns:
            List of normalized product dicts (deduplicated)
        """
        products_by_url = {}  # Deduplicate by product_url

        categories = scrape_output.get("categories", {})

        for category_url, category_data in categories.items():
            category_name = category_data.get("name", "Unknown")

            for product in category_data.get("products", []):
                product_url = product.get("product_url")

                if not product_url:
                    continue

                # Check if product already exists
                if product_url in products_by_url:
                    # Add this classification to existing product
                    existing_product = products_by_url[product_url]

                    # Add classification if not already present
                    new_classification = {
                        "type": "category",
                        "url": category_url,
                        "name": category_name,
                        "hierarchy": []  # TODO: Extract from navigation tree
                    }

                    # Check if classification already exists
                    classification_exists = any(
                        c.get("url") == category_url
                        for c in existing_product["classifications"]
                    )

                    if not classification_exists:
                        existing_product["classifications"].append(new_classification)

                else:
                    # Create new normalized product
                    normalized_product = {
                        "product_url": product_url,
                        "product_id": product.get("product_id", ""),
                        "product_name": product.get("product_name", ""),
                        "brand_id": brand_id,

                        "images": product.get("images", []),

                        "attributes": {
                            "price": product.get("price", ""),
                            "availability": product.get("availability", "Unknown")
                        },

                        "classifications": [
                            {
                                "type": "category",
                                "url": category_url,
                                "name": category_name,
                                "hierarchy": []  # TODO: Extract from navigation tree
                            }
                        ],

                        "metadata": {
                            "discovered_at": product.get("discovered_at"),
                            "last_updated": datetime.utcnow().isoformat() + "Z",
                            "extraction_source": category_url,
                            "dom_lineage": product.get("full_lineage", ""),
                            "run_id": None  # Will be set when saved
                        }
                    }

                    products_by_url[product_url] = normalized_product

        return list(products_by_url.values())

    def _extract_scraping_intelligence(self, brand_id: str, scrape_output: Dict, timestamp: str) -> Dict:
        """
        Extract scraping intelligence (patterns, lineages, etc.)

        Args:
            brand_id: Brand identifier
            scrape_output: Raw scraper output
            timestamp: Current timestamp

        Returns:
            Scraping intelligence dict
        """
        categories = scrape_output.get("categories", {})

        # Collect unique patterns
        patterns_by_type = {}
        all_lineages = set()

        for category_url, category_data in categories.items():
            pattern_used = category_data.get("pattern_used", {})

            if pattern_used:
                # Extract container selector as pattern identifier
                container_selector = pattern_used.get("container_selector", "")

                if container_selector:
                    if "product_listing" not in patterns_by_type:
                        patterns_by_type["product_listing"] = {
                            "primary": None,
                            "alternatives": []
                        }

                    # Build pattern object
                    pattern = {
                        "container_selector": container_selector,
                        "name_selector": pattern_used.get("name_selector", ""),
                        "link_selector": pattern_used.get("link_selector", ""),
                        "image_selector": "img",  # Default

                        "success_metrics": {
                            "total_uses": 1,
                            "successful_extractions": 1,
                            "success_rate": 1.0,
                            "total_products_found": len(category_data.get("products", []))
                        },

                        "worked_on_categories": [
                            {
                                "category_url": category_url,
                                "category_name": category_data.get("name", "Unknown"),
                                "products_found": len(category_data.get("products", [])),
                                "run_id": None  # Will be set when saved
                            }
                        ],

                        "alternative_selectors": pattern_used.get("alternative_selectors", []),
                        "llm_analysis": pattern_used.get("analysis", "")
                    }

                    # Set as primary if not set
                    if not patterns_by_type["product_listing"]["primary"]:
                        patterns_by_type["product_listing"]["primary"] = pattern
                    else:
                        # Check if this is the same pattern
                        primary = patterns_by_type["product_listing"]["primary"]
                        if primary["container_selector"] == container_selector:
                            # Update metrics
                            primary["success_metrics"]["total_uses"] += 1
                            primary["success_metrics"]["successful_extractions"] += 1
                            primary["success_metrics"]["total_products_found"] += len(category_data.get("products", []))
                            primary["worked_on_categories"].extend(pattern["worked_on_categories"])
                        else:
                            # Different pattern - add as alternative
                            patterns_by_type["product_listing"]["alternatives"].append(pattern)

            # Collect lineages
            for product in category_data.get("products", []):
                lineage = product.get("full_lineage")
                if lineage:
                    all_lineages.add(lineage)

        # Build intelligence object
        intel = {
            "brand_id": brand_id,
            "last_updated": timestamp,

            "patterns": patterns_by_type,

            "navigation": {
                "menu_expansion_required": False,  # TODO: Extract from scraper
                "menu_selectors": []
            },

            "load_more": {
                "has_load_more": False,  # TODO: Extract from scraper
                "button_selector": None,
                "pagination_type": "none"
            },

            "modals": {
                "bypassed": [],
                "strategies": {}
            },

            "lineages": {
                "common_lineages": sorted(list(all_lineages)),
                "unique_lineages_count": len(all_lineages)
            }
        }

        return intel

    def _extract_categories_summary(self, scrape_output: Dict) -> List[Dict]:
        """Extract category processing summary from scrape output"""
        categories = scrape_output.get("categories", {})
        summary = []

        for category_url, category_data in categories.items():
            stats = category_data.get("extraction_stats", {})

            summary.append({
                "url": category_url,
                "name": category_data.get("name", "Unknown"),
                "products_found": len(category_data.get("products", [])),
                "images_queued": stats.get("images_queued", 0),
                "pages_processed": stats.get("pages_processed", 1),
                "extraction_time": stats.get("extraction_time", 0),
                "pattern_used": "product_listing.primary"
            })

        return summary
