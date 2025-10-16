#!/usr/bin/env python3
"""
ID Generation Utilities
=======================

Provides consistent ID generation for brands and products.
"""

import hashlib


def generate_brand_id(slug: str) -> int:
    """Generate consistent brand ID from slug using stable hash"""
    return int(hashlib.md5(slug.encode()).hexdigest()[:8], 16) % 10000


def generate_product_id(product_url: str, product_name: str) -> int:
    """Generate consistent product ID from URL and name"""
    combined = f"{product_url}{product_name}"
    return int(hashlib.md5(combined.encode()).hexdigest()[:8], 16) % 10000