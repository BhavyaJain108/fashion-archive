"""
Data Manager
============

Handles all file-based storage operations for brand data.
Provides thread-safe file I/O with atomic writes.
"""

import os
import json
import fcntl
import tempfile
from typing import Dict, List, Optional, Any
from pathlib import Path
from datetime import datetime
import shutil


class DataManager:
    """Manages file-based storage for brand scraping data"""

    def __init__(self, base_path: str = "data"):
        """
        Initialize DataManager

        Args:
            base_path: Base directory for all data storage
        """
        self.base_path = Path(base_path)
        self.brands_path = self.base_path / "brands"
        self.indexes_path = self.base_path / "indexes"

        # Ensure directories exist
        self.brands_path.mkdir(parents=True, exist_ok=True)
        self.indexes_path.mkdir(parents=True, exist_ok=True)

    def _slugify(self, text: str) -> str:
        """Convert text to URL-safe slug"""
        import re
        text = text.lower().strip()
        text = re.sub(r'[^\w\s-]', '', text)
        text = re.sub(r'[-\s]+', '_', text)
        return text

    def _atomic_write(self, file_path: Path, data: Any):
        """
        Write JSON data atomically using temp file + rename

        Args:
            file_path: Target file path
            data: Data to write (will be JSON serialized)
        """
        # Create temp file in same directory
        temp_fd, temp_path = tempfile.mkstemp(
            dir=file_path.parent,
            prefix='.tmp_',
            suffix='.json'
        )

        try:
            # Write to temp file
            with os.fdopen(temp_fd, 'w') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            # Atomic rename
            os.replace(temp_path, file_path)

        except Exception as e:
            # Clean up temp file on error
            try:
                os.unlink(temp_path)
            except:
                pass
            raise e

    def _read_json(self, file_path: Path) -> Optional[Dict]:
        """
        Read JSON file with file locking

        Args:
            file_path: Path to JSON file

        Returns:
            Parsed JSON data or None if file doesn't exist
        """
        if not file_path.exists():
            return None

        with open(file_path, 'r') as f:
            # Acquire shared lock for reading
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                data = json.load(f)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        return data

    def _get_brand_path(self, brand_id: str) -> Path:
        """Get path to brand directory"""
        return self.brands_path / brand_id

    # =========================================================================
    # BRAND OPERATIONS
    # =========================================================================

    def create_brand(self, brand_id: str, brand_data: Dict) -> bool:
        """
        Create new brand with directory structure

        Args:
            brand_id: Unique brand identifier (slug)
            brand_data: Brand metadata (name, homepage_url, domain, etc.)

        Returns:
            True if created, False if already exists
        """
        brand_path = self._get_brand_path(brand_id)

        if brand_path.exists():
            return False

        # Create directory structure
        brand_path.mkdir(parents=True, exist_ok=True)
        (brand_path / "images").mkdir(exist_ok=True)
        (brand_path / "scrape_runs").mkdir(exist_ok=True)

        # Write brand.json
        brand_file = brand_path / "brand.json"
        self._atomic_write(brand_file, brand_data)

        # Update brand index
        self._update_brand_index()

        return True

    def read_brand(self, brand_id: str) -> Optional[Dict]:
        """Read brand.json"""
        brand_path = self._get_brand_path(brand_id)
        brand_file = brand_path / "brand.json"
        return self._read_json(brand_file)

    def write_brand(self, brand_id: str, brand_data: Dict):
        """Write brand.json"""
        brand_path = self._get_brand_path(brand_id)
        brand_file = brand_path / "brand.json"
        self._atomic_write(brand_file, brand_data)

        # Update index
        self._update_brand_index()

    def update_brand_status(self, brand_id: str, status_update: Dict):
        """
        Update brand status fields

        Args:
            brand_id: Brand identifier
            status_update: Dict with status fields to update
        """
        brand_data = self.read_brand(brand_id)
        if not brand_data:
            raise ValueError(f"Brand {brand_id} not found")

        if "status" not in brand_data:
            brand_data["status"] = {}

        brand_data["status"].update(status_update)
        self.write_brand(brand_id, brand_data)

    def delete_brand(self, brand_id: str) -> bool:
        """
        Delete brand and all associated data

        Args:
            brand_id: Brand identifier

        Returns:
            True if deleted, False if not found
        """
        brand_path = self._get_brand_path(brand_id)

        if not brand_path.exists():
            return False

        # Delete entire directory
        shutil.rmtree(brand_path)

        # Update index
        self._update_brand_index()

        return True

    def list_brands(self) -> List[str]:
        """Get list of all brand IDs"""
        if not self.brands_path.exists():
            return []

        return [d.name for d in self.brands_path.iterdir() if d.is_dir()]

    # =========================================================================
    # PRODUCTS OPERATIONS
    # =========================================================================

    def read_products(self, brand_id: str) -> Optional[Dict]:
        """Read products.json"""
        brand_path = self._get_brand_path(brand_id)
        products_file = brand_path / "products.json"
        return self._read_json(products_file)

    def write_products(self, brand_id: str, products_data: Dict):
        """Write products.json"""
        brand_path = self._get_brand_path(brand_id)
        products_file = brand_path / "products.json"
        self._atomic_write(products_file, products_data)

        # Update brand status
        total_products = len(products_data.get("products", []))
        self.update_brand_status(brand_id, {
            "total_products": total_products
        })

    # =========================================================================
    # NAVIGATION OPERATIONS
    # =========================================================================

    def read_navigation(self, brand_id: str) -> Optional[Dict]:
        """Read navigation.json"""
        brand_path = self._get_brand_path(brand_id)
        nav_file = brand_path / "navigation.json"
        return self._read_json(nav_file)

    def write_navigation(self, brand_id: str, navigation_data: Dict):
        """Write navigation.json"""
        brand_path = self._get_brand_path(brand_id)
        nav_file = brand_path / "navigation.json"
        self._atomic_write(nav_file, navigation_data)

        # Update brand status with category count
        if "all_category_urls" in navigation_data:
            self.update_brand_status(brand_id, {
                "total_categories": len(navigation_data["all_category_urls"])
            })

    # =========================================================================
    # SCRAPING INTELLIGENCE OPERATIONS
    # =========================================================================

    def read_scraping_intel(self, brand_id: str) -> Optional[Dict]:
        """Read scraping_intel.json"""
        brand_path = self._get_brand_path(brand_id)
        intel_file = brand_path / "scraping_intel.json"
        return self._read_json(intel_file)

    def write_scraping_intel(self, brand_id: str, intel_data: Dict):
        """Write scraping_intel.json"""
        brand_path = self._get_brand_path(brand_id)
        intel_file = brand_path / "scraping_intel.json"
        self._atomic_write(intel_file, intel_data)

    # =========================================================================
    # SCRAPE RUN HISTORY
    # =========================================================================

    def save_scrape_run(self, brand_id: str, run_data: Dict) -> str:
        """
        Save scrape run to history

        Args:
            brand_id: Brand identifier
            run_data: Scrape run data

        Returns:
            run_id that was saved
        """
        brand_path = self._get_brand_path(brand_id)
        runs_dir = brand_path / "scrape_runs"
        runs_dir.mkdir(exist_ok=True)

        run_id = run_data.get("run_id")
        if not run_id:
            raise ValueError("run_data must contain 'run_id'")

        run_file = runs_dir / f"{run_id}.json"
        self._atomic_write(run_file, run_data)

        # Update brand status
        self.update_brand_status(brand_id, {
            "last_scrape_run_id": run_id,
            "last_scrape_at": run_data.get("start_time"),
            "last_scrape_status": run_data.get("status")
        })

        # Update total_scrape_runs count
        brand_data = self.read_brand(brand_id)
        if brand_data:
            if "metadata" not in brand_data:
                brand_data["metadata"] = {}

            current_runs = brand_data["metadata"].get("total_scrape_runs", 0)
            brand_data["metadata"]["total_scrape_runs"] = current_runs + 1
            self.write_brand(brand_id, brand_data)

        return run_id

    def read_scrape_run(self, brand_id: str, run_id: str) -> Optional[Dict]:
        """Read specific scrape run"""
        brand_path = self._get_brand_path(brand_id)
        run_file = brand_path / "scrape_runs" / f"{run_id}.json"
        return self._read_json(run_file)

    def list_scrape_runs(self, brand_id: str) -> List[str]:
        """Get list of all scrape run IDs for a brand"""
        brand_path = self._get_brand_path(brand_id)
        runs_dir = brand_path / "scrape_runs"

        if not runs_dir.exists():
            return []

        return [f.stem for f in runs_dir.glob("*.json")]

    # =========================================================================
    # IMAGE OPERATIONS
    # =========================================================================

    def get_image_path(self, brand_id: str, category_slug: str, filename: str) -> Path:
        """Get path to image file"""
        brand_path = self._get_brand_path(brand_id)
        return brand_path / "images" / category_slug / filename

    def ensure_image_dir(self, brand_id: str, category_slug: str):
        """Ensure image directory exists for category"""
        brand_path = self._get_brand_path(brand_id)
        image_dir = brand_path / "images" / category_slug
        image_dir.mkdir(parents=True, exist_ok=True)
        return image_dir

    # =========================================================================
    # BRAND INDEX
    # =========================================================================

    def _update_brand_index(self):
        """Update global brand index file"""
        index_file = self.indexes_path / "brands.json"

        brands = []
        for brand_id in self.list_brands():
            brand_data = self.read_brand(brand_id)
            if brand_data:
                brands.append({
                    "brand_id": brand_id,
                    "name": brand_data.get("name", brand_id),
                    "domain": brand_data.get("domain", ""),
                    "total_products": brand_data.get("status", {}).get("total_products", 0),
                    "last_scrape_at": brand_data.get("status", {}).get("last_scrape_at")
                })

        # Sort by name
        brands.sort(key=lambda x: x["name"].lower())

        index_data = {
            "brands": brands,
            "total_brands": len(brands),
            "last_updated": datetime.utcnow().isoformat() + "Z"
        }

        self._atomic_write(index_file, index_data)

    def read_brand_index(self) -> Dict:
        """Read global brand index"""
        index_file = self.indexes_path / "brands.json"
        data = self._read_json(index_file)

        if data is None:
            # Return empty index
            return {
                "brands": [],
                "total_brands": 0,
                "last_updated": datetime.utcnow().isoformat() + "Z"
            }

        return data
