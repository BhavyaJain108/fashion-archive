#!/usr/bin/env python3
"""
Brand Data Models
================

Standardized data structures for brand information.
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class Brand:
    """Brand data model"""
    id: int
    slug: str
    name: str
    url: str
    validation_status: str = 'approved'
    scraping_strategy: str = 'premium_scraper'
    date_added: str = ''
    last_scraped: Optional[str] = None
    product_count: int = 0
    collections_count: int = 0
    status: str = 'active'
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses"""
        return {
            'id': self.id,
            'slug': self.slug,
            'name': self.name,
            'url': self.url,
            'validation_status': self.validation_status,
            'scraping_strategy': self.scraping_strategy,
            'date_added': self.date_added,
            'product_count': self.product_count,
            'collections_count': self.collections_count,
            'last_scraped': self.last_scraped,
            'status': self.status
        }
    
    @classmethod
    def from_collection_data(cls, brand_data: Dict[str, Any], brand_id: int) -> 'Brand':
        """Create Brand instance from collection manager data"""
        date_added = brand_data.get('last_scraped') or '2025-01-01T00:00:00Z'
        last_scraped = brand_data.get('last_scraped') or '2025-01-01T00:00:00Z'
        
        return cls(
            id=brand_id,
            slug=brand_data['slug'],
            name=brand_data['name'],
            url=brand_data['url'],
            date_added=date_added,
            last_scraped=last_scraped,
            product_count=brand_data.get('products_count', 0),
            collections_count=brand_data.get('collections_count', 0),
            status=brand_data.get('status', 'active')
        )