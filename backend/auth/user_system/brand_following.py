#!/usr/bin/env python3
"""
User Brand Following System
============================

Manages which brands a user is following.
Brands are stored centrally in data/brands/, but each user has their own list.
"""

import sqlite3
import json
from pathlib import Path
from typing import List, Dict, Optional, Tuple


class BrandFollowing:
    """
    Manages brand following for a specific user

    - Central brand data in data/brands/
    - User-specific following list in data/user_data/{user_folder}/brand_collections/following.db
    """

    def __init__(self, user_folder: str):
        """Initialize brand following manager for a user"""
        self.user_folder = user_folder
        self.user_data_path = Path(f"data/user_data/{user_folder}")
        self.brand_collections_path = self.user_data_path / "brand_collections"

        # Ensure directory exists
        self.brand_collections_path.mkdir(parents=True, exist_ok=True)

        # Database for tracking followed brands
        self.db_path = self.brand_collections_path / "following.db"

        self.init_database()

    def init_database(self):
        """Create following table if it doesn't exist"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS following (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    brand_id TEXT NOT NULL UNIQUE,
                    brand_name TEXT NOT NULL,
                    date_followed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    notes TEXT,

                    -- Notification preferences
                    notify_new_products BOOLEAN DEFAULT 1,
                    notify_price_changes BOOLEAN DEFAULT 0
                )
            """)

            # Create index for faster lookups
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_brand_id
                ON following(brand_id)
            """)

    def follow_brand(self, brand_id: str, brand_name: str, notes: str = "") -> Tuple[bool, str]:
        """
        Follow a brand

        Args:
            brand_id: Unique brand identifier
            brand_name: Display name of the brand
            notes: Optional user notes

        Returns:
            (success, message) tuple
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO following (brand_id, brand_name, notes)
                    VALUES (?, ?, ?)
                """, (brand_id, brand_name, notes))
                return True, f"Now following {brand_name}"
        except sqlite3.IntegrityError:
            return False, f"Already following {brand_name}"

    def unfollow_brand(self, brand_id: str) -> Tuple[bool, str]:
        """
        Unfollow a brand

        Returns:
            (success, message) tuple
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                DELETE FROM following WHERE brand_id = ?
            """, (brand_id,))

            if cursor.rowcount > 0:
                return True, "Unfollowed successfully"
            else:
                return False, "Brand not found in following list"

    def is_following(self, brand_id: str) -> bool:
        """Check if user is following a brand"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT 1 FROM following WHERE brand_id = ?
            """, (brand_id,))
            return cursor.fetchone() is not None

    def get_following_brands(self) -> List[Dict]:
        """Get all brands the user is following"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM following
                ORDER BY date_followed DESC
            """)

            return [dict(row) for row in cursor.fetchall()]

    def get_following_count(self) -> int:
        """Get count of followed brands"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM following")
            return cursor.fetchone()[0]

    def update_notification_preferences(
        self,
        brand_id: str,
        notify_new_products: bool = None,
        notify_price_changes: bool = None
    ) -> Tuple[bool, str]:
        """
        Update notification preferences for a brand

        Returns:
            (success, message) tuple
        """
        updates = []
        params = []

        if notify_new_products is not None:
            updates.append("notify_new_products = ?")
            params.append(notify_new_products)

        if notify_price_changes is not None:
            updates.append("notify_price_changes = ?")
            params.append(notify_price_changes)

        if not updates:
            return False, "No preferences specified"

        params.append(brand_id)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(f"""
                UPDATE following
                SET {', '.join(updates)}
                WHERE brand_id = ?
            """, params)

            if cursor.rowcount > 0:
                return True, "Preferences updated"
            else:
                return False, "Brand not found in following list"

    def add_notes(self, brand_id: str, notes: str) -> Tuple[bool, str]:
        """
        Add or update notes for a followed brand

        Returns:
            (success, message) tuple
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                UPDATE following SET notes = ? WHERE brand_id = ?
            """, (notes, brand_id))

            if cursor.rowcount > 0:
                return True, "Notes updated"
            else:
                return False, "Brand not found in following list"
