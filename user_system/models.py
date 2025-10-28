#!/usr/bin/env python3
"""
User System Data Models
======================

Simple data models for user authentication and profile management.
"""

import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass
import hashlib
import secrets

@dataclass
class User:
    """User profile data model"""
    id: Optional[int] = None
    username: str = ""
    password_hash: str = ""
    display_name: str = ""
    created_at: Optional[datetime] = None
    last_login: Optional[datetime] = None
    is_active: bool = True
    user_folder: str = ""  # e.g., "user_001"
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'User':
        """Create User from dictionary"""
        return cls(
            id=data.get('id'),
            username=data.get('username', ''),
            password_hash=data.get('password_hash', ''),
            display_name=data.get('display_name', ''),
            created_at=datetime.fromisoformat(data['created_at']) if data.get('created_at') else None,
            last_login=datetime.fromisoformat(data['last_login']) if data.get('last_login') else None,
            is_active=data.get('is_active', True),
            user_folder=data.get('user_folder', '')
        )
    
    def to_dict(self) -> Dict:
        """Convert User to dictionary"""
        return {
            'id': self.id,
            'username': self.username,
            'password_hash': self.password_hash,
            'display_name': self.display_name,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None,
            'is_active': self.is_active,
            'user_folder': self.user_folder
        }
    
    def get_data_path(self, subfolder: str = "") -> str:
        """Get user's data directory path"""
        base_path = f"user_data/{self.user_folder}"
        return f"{base_path}/{subfolder}" if subfolder else base_path
    
    def get_favourites_db_path(self) -> str:
        """Get user's favourites database path"""
        return f"{self.get_data_path()}/favourites.db"
    
    def get_favourites_dir_path(self) -> str:
        """Get user's favourites images directory"""
        return f"{self.get_data_path()}/favourites"

@dataclass 
class UserSession:
    """User session data model"""
    token: str = ""
    user_id: int = 0
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    last_used: Optional[datetime] = None
    
    @classmethod
    def create_new(cls, user_id: int, expires_in_days: int = 7) -> 'UserSession':
        """Create a new session token"""
        now = datetime.now()
        return cls(
            token=secrets.token_urlsafe(32),
            user_id=user_id,
            created_at=now,
            expires_at=now + timedelta(days=expires_in_days),
            last_used=now
        )
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'UserSession':
        """Create UserSession from dictionary"""
        return cls(
            token=data.get('token', ''),
            user_id=data.get('user_id', 0),
            created_at=datetime.fromisoformat(data['created_at']) if data.get('created_at') else None,
            expires_at=datetime.fromisoformat(data['expires_at']) if data.get('expires_at') else None,
            last_used=datetime.fromisoformat(data['last_used']) if data.get('last_used') else None
        )
    
    def to_dict(self) -> Dict:
        """Convert UserSession to dictionary"""
        return {
            'token': self.token,
            'user_id': self.user_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'last_used': self.last_used.isoformat() if self.last_used else None
        }
    
    def is_expired(self) -> bool:
        """Check if session has expired"""
        return self.expires_at and datetime.now() > self.expires_at
    
    def update_last_used(self):
        """Update last used timestamp"""
        self.last_used = datetime.now()

class UserDatabase:
    """Database manager for user accounts and sessions"""
    
    def __init__(self, db_path: str = "user_data/users.db"):
        self.db_path = db_path
        # Ensure user_data directory exists
        Path(db_path).parent.mkdir(exist_ok=True)
        self.init_database()
    
    def init_database(self):
        """Initialize user database tables"""
        with sqlite3.connect(self.db_path) as conn:
            # Users table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE,
                    user_folder TEXT UNIQUE NOT NULL
                )
            """)
            
            # Sessions table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_sessions (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP NOT NULL,
                    last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            """)
            
            # Indexes for better performance
            conn.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON user_sessions(user_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires ON user_sessions(expires_at)")
    
    def create_user(self, username: str, password: str, display_name: str = None) -> User:
        """Create a new user account"""
        if not display_name:
            display_name = username
        
        # Hash password
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        
        # Generate unique user folder
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Find next available user folder number
            cursor.execute("SELECT MAX(CAST(SUBSTR(user_folder, 6) AS INTEGER)) FROM users WHERE user_folder LIKE 'user_%'")
            result = cursor.fetchone()
            next_num = (result[0] or 0) + 1
            user_folder = f"user_{next_num:03d}"
            
            # Insert user
            cursor.execute("""
                INSERT INTO users (username, password_hash, display_name, user_folder)
                VALUES (?, ?, ?, ?)
            """, (username, password_hash, display_name, user_folder))
            
            user_id = cursor.lastrowid
            
            # Create user data directories
            user_path = Path(f"user_data/{user_folder}")
            user_path.mkdir(parents=True, exist_ok=True)
            (user_path / "favourites").mkdir(exist_ok=True)
            (user_path / "brand_collections").mkdir(exist_ok=True)
            (user_path / "downloads").mkdir(exist_ok=True)
            
            return User(
                id=user_id,
                username=username,
                password_hash=password_hash,
                display_name=display_name,
                created_at=datetime.now(),
                is_active=True,
                user_folder=user_folder
            )
    
    def get_user_by_username(self, username: str) -> Optional[User]:
        """Get user by username"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE username = ? AND is_active = TRUE", (username,))
            row = cursor.fetchone()
            return User.from_dict(dict(row)) if row else None
    
    def get_user_by_id(self, user_id: int) -> Optional[User]:
        """Get user by ID"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE id = ? AND is_active = TRUE", (user_id,))
            row = cursor.fetchone()
            return User.from_dict(dict(row)) if row else None
    
    def verify_password(self, username: str, password: str) -> bool:
        """Verify user password"""
        user = self.get_user_by_username(username)
        if not user:
            return False
        
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        return password_hash == user.password_hash
    
    def update_last_login(self, user_id: int):
        """Update user's last login timestamp"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?",
                (user_id,)
            )
    
    def create_session(self, user_id: int) -> UserSession:
        """Create a new user session"""
        session = UserSession.create_new(user_id)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO user_sessions (token, user_id, expires_at)
                VALUES (?, ?, ?)
            """, (session.token, session.user_id, session.expires_at))
        
        return session
    
    def get_session(self, token: str) -> Optional[UserSession]:
        """Get session by token"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_sessions WHERE token = ?", (token,))
            row = cursor.fetchone()
            return UserSession.from_dict(dict(row)) if row else None
    
    def update_session_last_used(self, token: str):
        """Update session last used timestamp"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE user_sessions SET last_used = CURRENT_TIMESTAMP WHERE token = ?",
                (token,)
            )
    
    def delete_session(self, token: str):
        """Delete a session (logout)"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM user_sessions WHERE token = ?", (token,))
    
    def cleanup_expired_sessions(self):
        """Remove expired sessions"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM user_sessions WHERE expires_at < CURRENT_TIMESTAMP")