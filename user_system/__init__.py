"""
User System Module for Fashion Archive
====================================

Simple user authentication and data isolation system.
Each user gets their own isolated data directories and database files.
"""

from .models import User, UserSession
from .auth import UserAuth
from .manager import UserManager
from .middleware import require_auth, get_current_user

__all__ = [
    'User',
    'UserSession', 
    'UserAuth',
    'UserManager',
    'require_auth',
    'get_current_user'
]