#!/usr/bin/env python3
"""
Favourites Database Manager
Handles storage and retrieval of favourite fashion looks with complete metadata
"""

import sqlite3
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

class FavouritesDB:
    """
    Database manager for favourite fashion looks
    
    Stores complete metadata for each favourite look:
    - Season information (name, url)
    - Collection information (designer, url)
    - Look details (number, image path)
    - User metadata (date added, notes)
    """
    
    def __init__(self, favourites_base_dir="data/favourites"):
        """Initialize database connection and create tables if needed"""
        self.favourites_base_dir = Path(favourites_base_dir)
        self.favourites_base_dir.mkdir(exist_ok=True)  # Create base favourites directory
        
        # Database goes inside the favourites directory
        self.db_path = self.favourites_base_dir / "favourites.db"
        
        # Images go in images subfolder for better organization
        self.favourites_dir = self.favourites_base_dir / "images"
        self.favourites_dir.mkdir(exist_ok=True)  # Create images directory
        
        self.init_database()
    
    def init_database(self):
        """Create favourites table if it doesn't exist"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS favourites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    
                    -- Season metadata
                    season_name TEXT NOT NULL,
                    season_url TEXT NOT NULL,
                    season_link_text TEXT,
                    
                    -- Collection metadata  
                    collection_designer TEXT NOT NULL,
                    collection_url TEXT NOT NULL,
                    
                    -- Look metadata
                    look_number INTEGER NOT NULL,
                    look_total INTEGER NOT NULL,
                    image_path TEXT NOT NULL,
                    
                    -- User metadata
                    date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    notes TEXT,
                    
                    -- Unique constraint to prevent duplicates
                    UNIQUE(season_url, collection_url, look_number)
                )
            """)
            
            # Create index for faster lookups
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_favourites_lookup 
                ON favourites(season_url, collection_url, look_number)
            """)
    
    def _generate_favourite_filename(self, season_data, collection_data, look_data, original_path):
        """Generate a unique filename for the favourites directory"""
        original_file = Path(original_path)
        extension = original_file.suffix
        
        # Create a safe filename from metadata
        season_name = season_data.get('name', 'Unknown-Season').replace('/', '-').replace(' ', '-')
        designer = collection_data.get('designer', 'Unknown-Designer').replace('/', '-').replace(' ', '-')
        look_num = str(look_data.get('lookNumber', 0)).zfill(3)
        
        # Format: Season-Designer-Look001.jpg
        safe_filename = f"{season_name}-{designer}-Look{look_num}{extension}"
        
        # Remove any remaining problematic characters
        safe_filename = "".join(c for c in safe_filename if c.isalnum() or c in '-._')
        
        return self.favourites_dir / safe_filename
    
    def _copy_image_to_favourites(self, original_path, season_data, collection_data, look_data):
        """
        Copy image from cache to permanent favourites storage.
        This ensures favourites persist even when cache is cleared.
        """
        # Generate permanent filename
        favourite_path = self._generate_favourite_filename(season_data, collection_data, look_data, original_path)

        # Copy the image if it doesn't already exist
        if not favourite_path.exists():
            try:
                # Ensure parent directory exists
                favourite_path.parent.mkdir(parents=True, exist_ok=True)

                # Copy the file from cache to favourites
                shutil.copy2(original_path, favourite_path)
                print(f"✅ Copied image to favourites: {favourite_path}")
            except Exception as e:
                print(f"❌ Error copying image to favourites: {e}")
                # Fall back to original path if copy fails
                return str(original_path)

        return str(favourite_path)
    
    def _remove_image_from_favourites(self, favourite_path):
        """
        Delete the copied image from favourites storage.
        """
        try:
            if favourite_path and Path(favourite_path).exists():
                Path(favourite_path).unlink()
                print(f"✅ Deleted favourite image: {favourite_path}")
            return True
        except Exception as e:
            print(f"❌ Error deleting favourite image: {e}")
            return False
    
    def add_favourite(self, season_data, collection_data, look_data, image_path, notes=""):
        """
        Add a look to favourites
        
        Args:
            season_data: Dict with 'name', 'url', 'link_text'
            collection_data: Dict with 'designer', 'url'
            look_data: Dict with 'lookNumber', 'total'
            image_path: String path to the image file
            notes: Optional user notes
            
        Returns:
            bool: True if added successfully, False if already exists
        """
        try:
            # Copy image to favourites directory first
            favourite_image_path = self._copy_image_to_favourites(image_path, season_data, collection_data, look_data)
            
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO favourites (
                        season_name, season_url, season_link_text,
                        collection_designer, collection_url,
                        look_number, look_total, image_path, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    season_data.get('name', ''),
                    season_data.get('url', ''),
                    season_data.get('link_text', ''),
                    collection_data.get('designer', ''),
                    collection_data.get('url', ''),
                    look_data.get('lookNumber', 0),
                    look_data.get('total', 0),
                    favourite_image_path,  # Use the copied image path
                    notes
                ))
                return True
        except sqlite3.IntegrityError:
            # Already exists - don't copy image again
            return False
    
    def remove_favourite(self, season_url, collection_url, look_number):
        """
        Remove a look from favourites
        
        Args:
            season_url: Season URL identifier
            collection_url: Collection URL identifier
            look_number: Look number within the collection
            
        Returns:
            bool: True if removed, False if not found
        """
        with sqlite3.connect(self.db_path) as conn:
            # First, get the image path before deleting
            cursor = conn.execute("""
                SELECT image_path FROM favourites 
                WHERE season_url = ? AND collection_url = ? AND look_number = ?
            """, (season_url, collection_url, look_number))
            
            result = cursor.fetchone()
            if result:
                image_path = result[0]
                
                # Delete from database
                cursor = conn.execute("""
                    DELETE FROM favourites 
                    WHERE season_url = ? AND collection_url = ? AND look_number = ?
                """, (season_url, collection_url, look_number))
                
                if cursor.rowcount > 0:
                    # Remove image from favourites directory
                    self._remove_image_from_favourites(image_path)
                    return True
            
            return False
    
    def is_favourite(self, season_url, collection_url, look_number):
        """
        Check if a look is already favourited
        
        Returns:
            bool: True if the look is in favourites
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT 1 FROM favourites 
                WHERE season_url = ? AND collection_url = ? AND look_number = ?
            """, (season_url, collection_url, look_number))
            return cursor.fetchone() is not None
    
    def get_all_favourites(self):
        """
        Get all favourite looks with complete metadata
        
        Returns:
            List of dicts with all favourite look data
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row  # Enable column access by name
            cursor = conn.execute("""
                SELECT * FROM favourites 
                ORDER BY date_added DESC
            """)
            
            favourites = []
            for row in cursor.fetchall():
                favourites.append({
                    'id': row['id'],
                    'season': {
                        'name': row['season_name'],
                        'url': row['season_url'],
                        'link_text': row['season_link_text']
                    },
                    'collection': {
                        'designer': row['collection_designer'],
                        'url': row['collection_url']
                    },
                    'look': {
                        'number': row['look_number'],
                        'total': row['look_total']
                    },
                    'image_path': row['image_path'],
                    'date_added': row['date_added'],
                    'notes': row['notes']
                })
            
            return favourites
    
    def get_favourites_by_season(self, season_url):
        """Get all favourites from a specific season"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM favourites 
                WHERE season_url = ?
                ORDER BY collection_designer, look_number
            """, (season_url,))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_favourites_by_collection(self, collection_url):
        """Get all favourites from a specific collection"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM favourites 
                WHERE collection_url = ?
                ORDER BY look_number
            """, (collection_url,))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_stats(self):
        """Get favourites statistics"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row  # Enable column access by name
            cursor = conn.execute("""
                SELECT 
                    COUNT(*) as total_favourites,
                    COUNT(DISTINCT season_url) as unique_seasons,
                    COUNT(DISTINCT collection_url) as unique_collections,
                    COUNT(DISTINCT collection_designer) as unique_designers
                FROM favourites
            """)
            
            row = cursor.fetchone()
            return dict(row) if row else {
                'total_favourites': 0,
                'unique_seasons': 0, 
                'unique_collections': 0,
                'unique_designers': 0
            }
    
    def cleanup_orphaned_images(self):
        """Remove images from favourites directory that are no longer in the database"""
        try:
            # Get all image paths from database
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("SELECT image_path FROM favourites")
                db_image_paths = {row[0] for row in cursor.fetchall()}
            
            # Get all files in favourites directory
            if self.favourites_dir.exists():
                removed_count = 0
                for image_file in self.favourites_dir.iterdir():
                    if image_file.is_file():
                        image_path = str(image_file)
                        if image_path not in db_image_paths:
                            # This image is not in the database, remove it
                            image_file.unlink()
                            removed_count += 1
                            print(f"Removed orphaned image: {image_path}")
                
                print(f"Cleanup complete: {removed_count} orphaned images removed")
                return removed_count
            
            return 0
        except Exception as e:
            print(f"Error during cleanup: {e}")
            return 0

# Global database instance - will create data/favourites/favourites.db and data/favourites/images/
favourites_db = FavouritesDB()