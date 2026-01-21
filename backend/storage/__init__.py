"""
Storage Package
===============

Provides unified storage interface for brand and product data.
Uses extractions/{domain}/ folder structure.
"""

from .extraction_manager import ExtractionManager
from .storage_layer import Storage, get_storage

__all__ = ['ExtractionManager', 'Storage', 'get_storage']
