#!/usr/bin/env python3
"""
User Management System
=====================

High-level user management operations.
"""

from typing import List, Optional, Dict, Tuple
from pathlib import Path
import shutil
import sqlite3
from .models import User, UserDatabase

class UserManager:
    """High-level user management operations"""
    
    def __init__(self):
        self.db = UserDatabase()
    
    def list_all_users(self) -> List[User]:
        """Get list of all users"""
        with self.db.conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users ORDER BY created_at DESC")
            rows = cursor.fetchall()
            return [User.from_dict(dict(row)) for row in rows]
    
    def get_user_stats(self, user: User) -> Dict:
        """Get user statistics and storage usage"""
        stats = {
            'username': user.username,
            'display_name': user.display_name,
            'created_at': user.created_at,
            'last_login': user.last_login,
            'user_folder': user.user_folder,
            'storage_mb': 0,
            'total_favorites': 0,
            'total_brands': 0,
            'total_downloads': 0
        }
        
        user_path = Path(user.get_data_path())
        if user_path.exists():
            # Calculate storage usage
            total_size = sum(
                f.stat().st_size for f in user_path.rglob('*') if f.is_file()
            )
            stats['storage_mb'] = round(total_size / (1024 * 1024), 2)
            
            # Count favorites
            favourites_db = Path(user.get_favourites_db_path())
            if favourites_db.exists():
                import sqlite3
                try:
                    with sqlite3.connect(str(favourites_db)) as conn:
                        cursor = conn.cursor()
                        cursor.execute("SELECT COUNT(*) FROM favourites")
                        stats['total_favorites'] = cursor.fetchone()[0]
                except:
                    pass
            
            # Count brand collections
            brand_collections_path = Path(user.get_data_path("brand_collections"))
            if brand_collections_path.exists():
                stats['total_brands'] = len([
                    d for d in brand_collections_path.iterdir() 
                    if d.is_dir() and d.name != '__pycache__'
                ])
            
            # Count downloads
            downloads_path = Path(user.get_data_path("downloads"))
            if downloads_path.exists():
                stats['total_downloads'] = len([
                    f for f in downloads_path.iterdir() 
                    if f.is_file()
                ])
        
        return stats
    
    def delete_user(self, username: str, delete_data: bool = True) -> Tuple[bool, str]:
        """
        Delete user account and optionally their data
        
        Returns:
            (success, message)
        """
        user = self.db.get_user_by_username(username)
        if not user:
            return False, f"User '{username}' not found"
        
        try:
            # Delete user data if requested
            if delete_data:
                user_path = Path(user.get_data_path())
                if user_path.exists():
                    shutil.rmtree(user_path)
            
            # Delete user sessions
            with sqlite3.connect(self.db.db_path) as conn:
                conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (user.id,))
                conn.execute("DELETE FROM users WHERE id = ?", (user.id,))
            
            return True, f"User '{username}' deleted successfully"
        
        except Exception as e:
            return False, f"Failed to delete user: {str(e)}"
    
    def deactivate_user(self, username: str) -> Tuple[bool, str]:
        """Deactivate user (soft delete)"""
        user = self.db.get_user_by_username(username)
        if not user:
            return False, f"User '{username}' not found"
        
        try:
            with sqlite3.connect(self.db.db_path) as conn:
                conn.execute("UPDATE users SET is_active = FALSE WHERE id = ?", (user.id,))
                conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (user.id,))
            
            return True, f"User '{username}' deactivated"
        
        except Exception as e:
            return False, f"Failed to deactivate user: {str(e)}"
    
    def export_user_data(self, username: str) -> Tuple[bool, Optional[str], str]:
        """
        Export all user data as ZIP file
        
        Returns:
            (success, zip_path, message)
        """
        user = self.db.get_user_by_username(username)
        if not user:
            return False, None, f"User '{username}' not found"
        
        try:
            import zipfile
            from datetime import datetime
            
            user_path = Path(user.get_data_path())
            if not user_path.exists():
                return False, None, "No user data found"
            
            # Create export ZIP
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            zip_filename = f"{username}_export_{timestamp}.zip"
            zip_path = Path("exports") / zip_filename
            zip_path.parent.mkdir(exist_ok=True)
            
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for file_path in user_path.rglob('*'):
                    if file_path.is_file():
                        arcname = file_path.relative_to(user_path)
                        zipf.write(file_path, arcname)
            
            return True, str(zip_path), f"User data exported to {zip_filename}"
        
        except Exception as e:
            return False, None, f"Failed to export user data: {str(e)}"
    
    def create_admin_user_from_existing_data(self) -> Tuple[bool, str]:
        """
        Migrate existing data to admin user
        This is for your transition to multi-user system
        """
        try:
            # Check if admin already exists
            admin = self.db.get_user_by_username("admin")
            if admin:
                return False, "Admin user already exists"
            
            # Create admin user
            admin = self.db.create_user("admin", "admin123", "Administrator")
            
            # Move existing data to admin folder
            admin_path = Path(admin.get_data_path())
            
            # Move existing favourites
            if Path("favourites.db").exists():
                shutil.move("favourites.db", admin.get_favourites_db_path())
            
            if Path("favourites").exists():
                if Path(admin.get_favourites_dir_path()).exists():
                    shutil.rmtree(admin.get_favourites_dir_path())
                shutil.move("favourites", admin.get_favourites_dir_path())
            
            # Move existing brand collections
            if Path("brand_collections").exists():
                admin_brands_path = Path(admin.get_data_path("brand_collections"))
                if admin_brands_path.exists():
                    shutil.rmtree(admin_brands_path)
                shutil.move("brand_collections", admin_brands_path)
            
            # Move existing downloads
            if Path("downloads").exists():
                admin_downloads_path = Path(admin.get_data_path("downloads"))
                if admin_downloads_path.exists():
                    shutil.rmtree(admin_downloads_path)
                shutil.move("downloads", admin_downloads_path)
            
            return True, "Admin user created and existing data migrated"
        
        except Exception as e:
            return False, f"Failed to create admin user: {str(e)}"