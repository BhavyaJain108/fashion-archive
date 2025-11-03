#!/usr/bin/env python3
"""
Brand Collection Manager
=======================

Manages organized storage of brand collections with pattern intelligence.
Replaces scattered test files with professional brand collection system.
"""

import os
import json
import shutil
from datetime import datetime
from typing import Dict, List, Any, Optional
from pathlib import Path
import re
import time
from urllib.parse import urlparse


class BrandCollectionManager:
    """
    Manages organized brand collection storage with pattern intelligence.
    """
    
    def __init__(self, base_storage_dir: str = "brand_collections"):
        """
        Initialize the brand collection manager.
        
        Args:
            base_storage_dir: Root directory for brand collections
        """
        self.base_dir = Path(base_storage_dir)
        self.base_dir.mkdir(exist_ok=True)
        self.index_file = self.base_dir / "index.json"
        
        # Initialize index if it doesn't exist
        if not self.index_file.exists():
            self._create_index()
    
    def _create_index(self):
        """Create master index file"""
        index_data = {
            "version": "1.0",
            "created": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
            "total_brands": 0,
            "total_products": 0,
            "brands": []
        }
        self._save_json(self.index_file, index_data)
    
    def _load_json(self, file_path: Path) -> Dict:
        """Load JSON file safely"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
    
    def _save_json(self, file_path: Path, data: Dict):
        """Save JSON file safely"""
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def _generate_brand_slug(self, brand_name: str, brand_url: str) -> str:
        """Generate a filesystem-safe slug for brand"""
        if brand_name and brand_name != "Unknown":
            slug = re.sub(r'[^a-zA-Z0-9\-_]', '-', brand_name.lower())
        else:
            domain = urlparse(brand_url).netloc
            slug = re.sub(r'[^a-zA-Z0-9\-_]', '-', domain.replace('www.', ''))
        
        # Clean up multiple dashes
        slug = re.sub(r'-+', '-', slug).strip('-')
        return slug
    
    def _generate_collection_slug(self, collection_name: str, collection_url: str) -> str:
        """Generate a filesystem-safe slug for collection"""
        if collection_name and collection_name != "Unknown":
            slug = re.sub(r'[^a-zA-Z0-9\-_]', '-', collection_name.lower())
        else:
            # Extract from URL path
            path = urlparse(collection_url).path.strip('/')
            slug = path.split('/')[-1] if '/' in path else path
            slug = re.sub(r'[^a-zA-Z0-9\-_]', '-', slug)
        
        # Clean up multiple dashes
        slug = re.sub(r'-+', '-', slug).strip('-')
        return slug
    
    def create_brand_fresh(self, brand_name: str, brand_url: str, **metadata) -> str:
        """
        Create a fresh brand directory, deleting any existing data.
        
        Args:
            brand_name: Name of the brand
            brand_url: URL of the brand website
            **metadata: Additional brand metadata
            
        Returns:
            Brand slug (directory name)
        """
        brand_slug = self._generate_brand_slug(brand_name, brand_url)
        brand_dir = self.base_dir / brand_slug
        
        # Delete existing brand directory for fresh start
        if brand_dir.exists():
            import shutil
            shutil.rmtree(brand_dir, ignore_errors=True)
        
        # Create fresh brand structure
        brand_dir.mkdir(exist_ok=True)
        (brand_dir / "collections").mkdir(exist_ok=True)
        (brand_dir / "images").mkdir(exist_ok=True)
        (brand_dir / "exports").mkdir(exist_ok=True)
        
        # Create brand info file
        brand_info = {
            "brand": {
                "slug": brand_slug,
                "name": brand_name,
                "url": brand_url,
                "created_date": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat(),
                **metadata
            },
            "collections": [],
            "stats": {
                "total_collections": 0,
                "total_products": 0,
                "last_scraped": None
            }
        }
        
        self._save_json(brand_dir / "brand_info.json", brand_info)
        
        # Update master index
        self._update_brand_in_index(brand_slug, brand_name, brand_url)
        
        return brand_slug
    
    def create_collection_directory(self, brand_slug: str, collection_name: str, collection_url: str) -> str:
        """
        Create directory structure for a collection.
        
        Args:
            brand_slug: Brand identifier
            collection_name: Name of the collection
            collection_url: URL of the collection
            
        Returns:
            Path to the collection's images directory
        """
        collection_slug = self._generate_collection_slug(collection_name, collection_url)
        brand_dir = self.base_dir / brand_slug
        collection_dir = brand_dir / "collections" / collection_slug
        images_dir = collection_dir / "images"
        
        # Create directory structure
        collection_dir.mkdir(parents=True, exist_ok=True)
        images_dir.mkdir(exist_ok=True)
        
        return str(images_dir)
    
    def create_brand(self, brand_name: str, brand_url: str, **metadata) -> str:
        """
        Create a new brand in the collection system.
        
        Args:
            brand_name: Name of the brand
            brand_url: URL of the brand website
            **metadata: Additional brand metadata
            
        Returns:
            Brand slug (directory name)
        """
        brand_slug = self._generate_brand_slug(brand_name, brand_url)
        brand_dir = self.base_dir / brand_slug
        brand_dir.mkdir(exist_ok=True)
        
        # Create brand structure
        (brand_dir / "collections").mkdir(exist_ok=True)
        (brand_dir / "images").mkdir(exist_ok=True)
        (brand_dir / "exports").mkdir(exist_ok=True)
        
        # Create brand info file
        brand_info = {
            "brand": {
                "slug": brand_slug,
                "name": brand_name,
                "url": brand_url,
                "created_date": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat(),
                **metadata
            },
            "collections": [],
            "stats": {
                "total_collections": 0,
                "total_products": 0,
                "last_scraped": None
            }
        }
        
        self._save_json(brand_dir / "brand_info.json", brand_info)
        
        # Update master index
        self._update_brand_in_index(brand_slug, brand_name, brand_url)
        
        return brand_slug
    
    def save_collection_scrape(self, brand_slug: str, collection_name: str, 
                              collection_url: str, products: List[Dict],
                              extraction_pattern: Dict, scrape_stats: Dict) -> str:
        """
        Save a complete collection scrape with products and pattern data.
        Images are assumed to be already in the correct location.
        
        Args:
            brand_slug: Brand identifier
            collection_name: Name of the collection
            collection_url: URL of the collection
            products: List of product dictionaries
            extraction_pattern: The CSS pattern that worked for this collection
            scrape_stats: Performance stats from scraping
            
        Returns:
            Collection slug (directory name)
        """
        collection_slug = self._generate_collection_slug(collection_name, collection_url)
        brand_dir = self.base_dir / brand_slug
        collection_dir = brand_dir / "collections" / collection_slug
        collection_dir.mkdir(parents=True, exist_ok=True)
        
        # Create collection images directory
        images_dir_path = collection_dir / "images"
        images_dir_path.mkdir(exist_ok=True)
        
        # Images are already in correct location, no copying needed
        local_products = products.copy()
        
        # Save collection info
        collection_info = {
            "collection": {
                "slug": collection_slug,
                "name": collection_name,
                "url": collection_url,
                "brand": brand_slug,
                "last_scraped": datetime.now().isoformat(),
                "products_count": len(products)
            },
            "extraction_pattern": extraction_pattern,
            "scrape_result": {
                "extraction_time": scrape_stats.get("extraction_time", 0),
                "products_found": len(products),
                "success": scrape_stats.get("success", True),
                **scrape_stats
            }
        }
        
        self._save_json(collection_dir / "collection_info.json", collection_info)
        
        # Save products data
        products_data = {
            "collection": {
                "slug": collection_slug,
                "name": collection_name,
                "brand": brand_slug,
                "url": collection_url,
                "last_scraped": datetime.now().isoformat()
            },
            "products": local_products
        }
        
        self._save_json(collection_dir / "products.json", products_data)
        
        # Update brand info
        self._update_brand_collections(brand_slug, collection_slug, collection_name, 
                                      collection_url, len(products))
        
        return collection_slug
    
    def _update_brand_collections(self, brand_slug: str, collection_slug: str, 
                                 collection_name: str, collection_url: str, products_count: int):
        """Update brand info with new collection"""
        brand_dir = self.base_dir / brand_slug
        brand_info_file = brand_dir / "brand_info.json"
        
        brand_info = self._load_json(brand_info_file)
        if not brand_info:
            return
        
        # Update or add collection
        collections = brand_info.get("collections", [])
        existing_collection = None
        for i, coll in enumerate(collections):
            if coll.get("slug") == collection_slug:
                existing_collection = i
                break
        
        collection_data = {
            "slug": collection_slug,
            "name": collection_name,
            "url": collection_url,
            "products_count": products_count,
            "last_updated": datetime.now().isoformat()
        }
        
        if existing_collection is not None:
            collections[existing_collection] = collection_data
        else:
            collections.append(collection_data)
        
        brand_info["collections"] = collections
        
        # Update stats
        brand_info["stats"] = {
            "total_collections": len(collections),
            "total_products": sum(c.get("products_count", 0) for c in collections),
            "last_scraped": datetime.now().isoformat()
        }
        
        brand_info["brand"]["last_updated"] = datetime.now().isoformat()
        
        self._save_json(brand_info_file, brand_info)
    
    def _update_brand_in_index(self, brand_slug: str, brand_name: str, brand_url: str):
        """Update master index with brand info"""
        index_data = self._load_json(self.index_file)
        if not index_data:
            self._create_index()
            index_data = self._load_json(self.index_file)
        
        # Update or add brand in index
        brands = index_data.get("brands", [])
        existing_brand = None
        for i, brand in enumerate(brands):
            if brand.get("slug") == brand_slug:
                existing_brand = i
                break
        
        # Get brand stats
        brand_dir = self.base_dir / brand_slug
        brand_info_file = brand_dir / "brand_info.json"
        brand_info = self._load_json(brand_info_file)
        stats = brand_info.get("stats", {})
        
        brand_data = {
            "slug": brand_slug,
            "name": brand_name,
            "url": brand_url,
            "collections_count": stats.get("total_collections", 0),
            "products_count": stats.get("total_products", 0),
            "last_scraped": stats.get("last_scraped"),
            "status": "active"
        }
        
        if existing_brand is not None:
            brands[existing_brand] = brand_data
        else:
            brands.append(brand_data)
        
        # Update index stats
        index_data["brands"] = brands
        index_data["total_brands"] = len(brands)
        index_data["total_products"] = sum(b.get("products_count", 0) for b in brands)
        index_data["last_updated"] = datetime.now().isoformat()
        
        self._save_json(self.index_file, index_data)
    
    def get_brand_info(self, brand_slug: str) -> Optional[Dict]:
        """Get complete brand information"""
        brand_dir = self.base_dir / brand_slug
        brand_info_file = brand_dir / "brand_info.json"
        return self._load_json(brand_info_file) if brand_info_file.exists() else None
    
    def get_collection_products(self, brand_slug: str, collection_slug: str) -> Optional[Dict]:
        """Get all products from a specific collection"""
        collection_dir = self.base_dir / brand_slug / "collections" / collection_slug
        products_file = collection_dir / "products.json"
        return self._load_json(products_file) if products_file.exists() else None
    
    def get_collection_pattern(self, brand_slug: str, collection_slug: str) -> Optional[Dict]:
        """Get extraction pattern for a specific collection"""
        collection_dir = self.base_dir / brand_slug / "collections" / collection_slug
        info_file = collection_dir / "collection_info.json"
        collection_info = self._load_json(info_file)
        return collection_info.get("extraction_pattern") if collection_info else None
    
    def list_brands(self) -> List[Dict]:
        """Get list of all brands"""
        index_data = self._load_json(self.index_file)
        return index_data.get("brands", [])
    
    def get_image_path(self, brand_slug: str, collection_slug: str, image_filename: str) -> Optional[Path]:
        """Get full path to collection image"""
        image_path = self.base_dir / brand_slug / "collections" / collection_slug / "images" / image_filename
        return image_path if image_path.exists() else None
    
    def export_brand(self, brand_slug: str, format: str = "json") -> Optional[Path]:
        """Export complete brand data for backup/sharing"""
        brand_dir = self.base_dir / brand_slug
        if not brand_dir.exists():
            return None
        
        export_dir = brand_dir / "exports"
        export_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        if format == "json":
            # Create comprehensive JSON export
            brand_info = self.get_brand_info(brand_slug)
            if not brand_info:
                return None
            
            export_data = {
                "export_info": {
                    "brand_slug": brand_slug,
                    "export_date": datetime.now().isoformat(),
                    "format": "json"
                },
                "brand": brand_info["brand"],
                "collections": []
            }
            
            # Add all collections
            for collection in brand_info.get("collections", []):
                collection_data = self.get_collection_products(brand_slug, collection["slug"])
                collection_info_file = brand_dir / "collections" / collection["slug"] / "collection_info.json"
                collection_info = self._load_json(collection_info_file)
                
                if collection_data and collection_info:
                    export_data["collections"].append({
                        "info": collection_info,
                        "products": collection_data["products"]
                    })
            
            export_file = export_dir / f"{brand_slug}_export_{timestamp}.json"
            self._save_json(export_file, export_data)
            return export_file
        
        return None
    
    def get_brand_products(self, brand_slug: str) -> Dict[str, List[Dict]]:
        """Get all products for a brand organized by collection"""
        brand_dir = self.base_dir / brand_slug
        if not brand_dir.exists():
            return {}
        
        collections_dir = brand_dir / "collections"
        if not collections_dir.exists():
            return {}
        
        brand_products = {}
        
        # Iterate through all collections for this brand
        for collection_dir in collections_dir.iterdir():
            if collection_dir.is_dir():
                products_file = collection_dir / "products.json"
                if products_file.exists():
                    products_data = self._load_json(products_file)
                    if products_data and "products" in products_data:
                        collection_name = products_data.get("collection", {}).get("name", collection_dir.name)
                        brand_products[collection_name] = products_data["products"]
        
        return brand_products
    
    def cleanup_old_exports(self, brand_slug: str, keep_count: int = 5):
        """Remove old export files, keeping only the most recent ones"""
        export_dir = self.base_dir / brand_slug / "exports"
        if not export_dir.exists():
            return
        
        # Get all export files sorted by modification time (newest first)
        export_files = sorted(export_dir.glob(f"{brand_slug}_export_*.json"), 
                             key=lambda x: x.stat().st_mtime, reverse=True)
        
        # Remove old exports beyond keep_count
        for old_export in export_files[keep_count:]:
            old_export.unlink()
    
    def save_navigation_tree(self, brand_slug: str, navigation_tree: List[Dict]) -> bool:
        """
        Save navigation tree structure to brand_info.json.
        
        Args:
            brand_slug: Brand slug identifier
            navigation_tree: Navigation tree structure from LLM analysis
            
        Returns:
            True if successful, False otherwise
        """
        try:
            brand_dir = self.base_dir / brand_slug
            if not brand_dir.exists():
                return False
            
            brand_info_file = brand_dir / "brand_info.json"
            brand_info = self._load_json(brand_info_file)
            
            if not brand_info:
                return False
            
            # Add navigation tree to brand info
            brand_info['navigation'] = navigation_tree
            brand_info['navigation_updated'] = datetime.now().isoformat()
            
            # Save updated brand info
            self._save_json(brand_info_file, brand_info)
            
            print(f"✅ Saved navigation tree for {brand_slug}")
            return True
            
        except Exception as e:
            print(f"❌ Error saving navigation tree for {brand_slug}: {e}")
            return False
    
    def create_hierarchical_collections(self, brand_slug: str, navigation_tree: List[Dict]) -> Dict[str, str]:
        """
        Create hierarchical folder structure matching navigation tree.
        
        Args:
            brand_slug: Brand slug identifier
            navigation_tree: Navigation tree structure
            
        Returns:
            Dictionary mapping URLs to collection folder paths
        """
        import sys
        import os
        # Add scraper_premium to path
        scraper_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scraper_premium')
        if scraper_path not in sys.path:
            sys.path.append(scraper_path)
        from page_extractor import extract_collection_hierarchy
        
        url_to_path = {}
        
        try:
            # Get hierarchical structure info
            collections_info = extract_collection_hierarchy(navigation_tree)
            
            brand_dir = self.base_dir / brand_slug / "collections"
            brand_dir.mkdir(parents=True, exist_ok=True)
            
            for collection_info in collections_info:
                name = collection_info['name']
                url = collection_info['url']
                path = collection_info['path']
                has_url = collection_info['has_url']
                
                # Convert path to filesystem-safe folder structure
                folder_path = self._create_safe_folder_path(brand_dir, path)
                folder_path.mkdir(parents=True, exist_ok=True)
                
                # If this collection has a URL, it needs products/images folders
                if has_url and url:
                    # Create products.json and images folder
                    products_file = folder_path / "products.json"
                    images_dir = folder_path / "images"
                    collection_info_file = folder_path / "collection_info.json"
                    
                    images_dir.mkdir(exist_ok=True)
                    
                    # Initialize empty products file if it doesn't exist
                    if not products_file.exists():
                        initial_products = {
                            "collection": {
                                "name": name,
                                "url": url,
                                "slug": self._generate_collection_slug(name, url),
                                "created": datetime.now().isoformat()
                            },
                            "products": []
                        }
                        self._save_json(products_file, initial_products)
                    
                    # Initialize collection info file
                    if not collection_info_file.exists():
                        collection_info_data = {
                            "name": name,
                            "url": url,
                            "path": path,
                            "created": datetime.now().isoformat(),
                            "pattern_used": None,
                            "last_scraped": None,
                            "products_count": 0
                        }
                        self._save_json(collection_info_file, collection_info_data)
                    
                    # Map URL to folder path for later use
                    url_to_path[url] = str(folder_path)
            
            print(f"✅ Created hierarchical collections for {brand_slug}")
            return url_to_path
            
        except Exception as e:
            print(f"❌ Error creating hierarchical collections for {brand_slug}: {e}")
            return {}
    
    def _create_safe_folder_path(self, base_dir: Path, hierarchical_path: str) -> Path:
        """
        Convert hierarchical path to safe filesystem path.
        
        Args:
            base_dir: Base collections directory
            hierarchical_path: Path like "Parent/Child/Grandchild"
            
        Returns:
            Safe filesystem path
        """
        # Split path and slugify each component
        path_components = hierarchical_path.split('/')
        safe_components = []
        
        for component in path_components:
            safe_component = self._generate_collection_slug(component, "")
            safe_components.append(safe_component)
        
        return base_dir / Path(*safe_components)
    
    def store_collection_results(self, brand_slug: str, collection_url: str, collection_name: str, 
                                 products: List[Dict], extraction_pattern: Dict, 
                                 url_to_path_mapping: Dict[str, str]) -> bool:
        """
        Store scraping results for a specific collection.
        
        Args:
            brand_slug: Brand slug identifier
            collection_url: URL of the scraped collection
            collection_name: Name of the collection
            products: List of extracted products
            extraction_pattern: Pattern used for extraction
            url_to_path_mapping: Mapping from URLs to folder paths
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if collection_url not in url_to_path_mapping:
                print(f"⚠️ No folder mapping found for {collection_url}")
                return False
            
            collection_path = Path(url_to_path_mapping[collection_url])
            
            # Update products.json
            products_file = collection_path / "products.json"
            products_data = self._load_json(products_file)
            
            if products_data:
                products_data["products"] = products
                products_data["collection"]["last_updated"] = datetime.now().isoformat()
                products_data["collection"]["products_count"] = len(products)
                self._save_json(products_file, products_data)
            
            # Update collection_info.json with pattern and stats
            collection_info_file = collection_path / "collection_info.json"
            collection_info = self._load_json(collection_info_file)
            
            if collection_info:
                collection_info["pattern_used"] = extraction_pattern
                collection_info["last_scraped"] = datetime.now().isoformat()
                collection_info["products_count"] = len(products)
                collection_info["scrape_success"] = True
                self._save_json(collection_info_file, collection_info)
            
            print(f"✅ Stored {len(products)} products for {collection_name}")
            return True
            
        except Exception as e:
            print(f"❌ Error storing collection results for {collection_name}: {e}")
            return False