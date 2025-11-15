"""
Storage Package
===============

Provides unified storage interface for brand and product data.
"""

from .file_manager import DataManager
from .database import DatabaseManager
from .storage_layer import Storage, get_storage

__all__ = ['DataManager', 'DatabaseManager', 'Storage', 'get_storage']
