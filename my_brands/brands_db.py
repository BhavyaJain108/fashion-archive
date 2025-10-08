#!/usr/bin/env python3
"""
Brands Database Manager
======================

Manages storage and retrieval of fashion brands, products, and user favorites.
"""

import sqlite3
import os
import json
from datetime import datetime
from typing import List, Dict, Optional, Any
from pathlib import Path

class BrandsDatabase:
    def __init__(self, db_path: str = "my_brands/brands.db"):
        """Initialize brands database"""
        self.db_path = db_path
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        self._init_database()
    
    def _init_database(self):
        """Initialize database with required tables"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS brands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL UNIQUE,
                    description TEXT,
                    validation_status TEXT DEFAULT 'pending',
                    validation_reason TEXT,
                    scraping_strategy TEXT,
                    scraping_config TEXT, -- JSON
                    date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_scraped TIMESTAMP,
                    is_active BOOLEAN DEFAULT 1
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    brand_id INTEGER,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL,
                    price TEXT,
                    currency TEXT,
                    category TEXT,
                    description TEXT,
                    images TEXT, -- JSON array of image URLs
                    metadata TEXT, -- JSON for additional data
                    date_scraped TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_available BOOLEAN DEFAULT 1,
                    FOREIGN KEY (brand_id) REFERENCES brands (id)
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS brand_favorites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER,
                    notes TEXT,
                    date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (product_id) REFERENCES products (id)
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scraping_strategies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT,
                    strategy_type TEXT, -- 'homepage', 'category', 'product', 'pagination'
                    config TEXT, -- JSON configuration
                    success_rate REAL DEFAULT 0.0,
                    date_created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.commit()
    
    def add_brand(self, name: str, url: str, description: str = "") -> int:
        """Add a new brand to the database"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                INSERT INTO brands (name, url, description)
                VALUES (?, ?, ?)
            """, (name, url, description))
            return cursor.lastrowid
    
    def update_brand_validation(self, brand_id: int, status: str, reason: str = ""):
        """Update brand validation status"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE brands 
                SET validation_status = ?, validation_reason = ?
                WHERE id = ?
            """, (status, reason, brand_id))
    
    def update_brand_scraping_config(self, brand_id: int, strategy: str, config: Dict[str, Any]):
        """Update brand scraping strategy and configuration"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE brands 
                SET scraping_strategy = ?, scraping_config = ?
                WHERE id = ?
            """, (strategy, json.dumps(config), brand_id))
    
    def get_all_brands(self) -> List[Dict[str, Any]]:
        """Get all active brands"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM brands 
                WHERE is_active = 1 
                ORDER BY date_added DESC
            """)
            return [dict(row) for row in cursor.fetchall()]
    
    def get_brand_by_id(self, brand_id: int) -> Optional[Dict[str, Any]]:
        """Get brand by ID"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM brands WHERE id = ?", (brand_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def add_product(self, brand_id: int, name: str, url: str, price: str = "", 
                   currency: str = "", category: str = "", description: str = "",
                   images: List[str] = None, metadata: Dict[str, Any] = None) -> int:
        """Add a product to the database"""
        images = images or []
        metadata = metadata or {}
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                INSERT INTO products 
                (brand_id, name, url, price, currency, category, description, images, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (brand_id, name, url, price, currency, category, description,
                  json.dumps(images), json.dumps(metadata)))
            return cursor.lastrowid
    
    def get_brand_products(self, brand_id: int) -> List[Dict[str, Any]]:
        """Get all products for a brand"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM products 
                WHERE brand_id = ? AND is_available = 1
                ORDER BY 
                    CAST(JSON_EXTRACT(metadata, '$.extraction_order') AS INTEGER) ASC,
                    id ASC
            """, (brand_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    def add_scraping_strategy(self, name: str, description: str, strategy_type: str, 
                            config: Dict[str, Any]) -> int:
        """Add a new scraping strategy"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                INSERT INTO scraping_strategies (name, description, strategy_type, config)
                VALUES (?, ?, ?, ?)
            """, (name, description, strategy_type, json.dumps(config)))
            return cursor.lastrowid
    
    def get_scraping_strategies(self, strategy_type: str = None) -> List[Dict[str, Any]]:
        """Get scraping strategies by type"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if strategy_type:
                cursor = conn.execute("""
                    SELECT * FROM scraping_strategies 
                    WHERE strategy_type = ?
                    ORDER BY success_rate DESC
                """, (strategy_type,))
            else:
                cursor = conn.execute("""
                    SELECT * FROM scraping_strategies 
                    ORDER BY strategy_type, success_rate DESC
                """)
            return [dict(row) for row in cursor.fetchall()]
    
    def add_favorite_product(self, product_id: int, notes: str = "") -> int:
        """Add product to favorites"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                INSERT INTO brand_favorites (product_id, notes)
                VALUES (?, ?)
            """, (product_id, notes))
            return cursor.lastrowid
    
    def get_favorite_products(self) -> List[Dict[str, Any]]:
        """Get all favorite products with brand and product details"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT 
                    bf.*,
                    p.name as product_name,
                    p.url as product_url,
                    p.price,
                    p.currency,
                    p.category,
                    p.images,
                    b.name as brand_name,
                    b.url as brand_url
                FROM brand_favorites bf
                JOIN products p ON bf.product_id = p.id
                JOIN brands b ON p.brand_id = b.id
                WHERE p.is_available = 1
                ORDER BY bf.date_added DESC
            """)
            return [dict(row) for row in cursor.fetchall()]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics"""
        with sqlite3.connect(self.db_path) as conn:
            stats = {}
            
            # Total brands
            cursor = conn.execute("SELECT COUNT(*) FROM brands WHERE is_active = 1")
            stats['total_brands'] = cursor.fetchone()[0]
            
            # Validated brands
            cursor = conn.execute("SELECT COUNT(*) FROM brands WHERE validation_status = 'approved'")
            stats['validated_brands'] = cursor.fetchone()[0]
            
            # Total products
            cursor = conn.execute("SELECT COUNT(*) FROM products WHERE is_available = 1")
            stats['total_products'] = cursor.fetchone()[0]
            
            # Favorite products
            cursor = conn.execute("SELECT COUNT(*) FROM brand_favorites")
            stats['favorite_products'] = cursor.fetchone()[0]
            
            return stats
    
    def _update_last_scraped(self, brand_id: int):
        """Update last scraped timestamp for a brand"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE brands 
                SET last_scraped = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (brand_id,))
    
    def _clear_brand_products(self, brand_id: int):
        """Clear all products for a specific brand to avoid accumulation during re-scraping"""
        with sqlite3.connect(self.db_path) as conn:
            # First remove from favorites if any
            conn.execute("""
                DELETE FROM brand_favorites 
                WHERE product_id IN (
                    SELECT id FROM products WHERE brand_id = ?
                )
            """, (brand_id,))
            
            # Then remove products
            cursor = conn.execute("DELETE FROM products WHERE brand_id = ?", (brand_id,))
            deleted_count = cursor.rowcount
            conn.commit()
            return deleted_count
    
    def clear_all_data(self):
        """Clear all data from the brands database"""
        with sqlite3.connect(self.db_path) as conn:
            # Clear in order to respect foreign key constraints
            conn.execute("DELETE FROM brand_favorites")
            conn.execute("DELETE FROM products") 
            conn.execute("DELETE FROM brands")
            conn.execute("DELETE FROM scraping_strategies")
            conn.commit()
            print("🧹 Cleared all data from brands database")

# Global instance
brands_db = BrandsDatabase()