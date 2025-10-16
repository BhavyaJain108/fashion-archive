#!/usr/bin/env python3
"""
Brand Service
=============

Business logic for brand management operations.
"""

import json
import time
from typing import Dict, Any, List, Optional, Generator
from ..models.brand import Brand
from ..models.product import Product, Collection
from ..utils.id_generator import generate_brand_id, generate_product_id
from ..brand_collection_manager import BrandCollectionManager
# Conditional imports for optional dependencies
try:
    from ..llm_client import create_my_brands_llm
except ImportError:
    create_my_brands_llm = lambda: None

try:
    from ..brand_url_resolver import BrandURLResolver
except ImportError:
    BrandURLResolver = None


class BrandService:
    """Service class for brand operations"""
    
    def __init__(self):
        self.collection_manager = BrandCollectionManager()
        self.llm_client = create_my_brands_llm()
        self.url_resolver = BrandURLResolver()
    
    def get_all_brands(self) -> List[Brand]:
        """Get all brands from the collection manager"""
        brands_data = self.collection_manager.list_brands()
        brands = []
        
        for brand_data in brands_data:
            brand_id = generate_brand_id(brand_data['slug'])
            brand = Brand.from_collection_data(brand_data, brand_id)
            brands.append(brand)
        
        return brands
    
    def get_brand_by_id(self, brand_id: int) -> Optional[Brand]:
        """Get a specific brand by ID"""
        brands_data = self.collection_manager.list_brands()
        
        for brand_data in brands_data:
            if generate_brand_id(brand_data['slug']) == brand_id:
                return Brand.from_collection_data(brand_data, brand_id)
        
        return None
    
    def create_brand(self, brand_name: str, url: str) -> Brand:
        """Create a new brand"""
        # Create brand in collection manager
        brand_slug = self.collection_manager.create_brand(brand_name, url)
        brand_id = generate_brand_id(brand_slug)
        
        # Return brand object
        return Brand(
            id=brand_id,
            slug=brand_slug,
            name=brand_name,
            url=url,
            date_added=time.strftime('%Y-%m-%dT%H:%M:%SZ'),
            validation_status='approved'
        )
    
    def resolve_brand_name(self, brand_name: str) -> Dict[str, Any]:
        """Resolve brand name to URL using the resolver"""
        return self.url_resolver.resolve_brand_name(brand_name)
    
    def validate_brand(self, brand_name: str, url: str) -> Dict[str, Any]:
        """Validate brand using LLM client"""
        # This would integrate with existing validation logic
        # For now, return a simple success response
        return {
            'success': True,
            'brand': {
                'name': brand_name,
                'url': url,
                'validation_status': 'approved'
            }
        }
    
    def get_brand_stats(self) -> Dict[str, Any]:
        """Get statistics about all brands"""
        brands_data = self.collection_manager.list_brands()
        
        total_brands = len(brands_data)
        total_products = sum(brand.get('products_count', 0) for brand in brands_data)
        total_collections = sum(brand.get('collections_count', 0) for brand in brands_data)
        
        # Get status breakdown
        active_brands = len([b for b in brands_data if b.get('status', 'active') == 'active'])
        
        # Get last updated date safely
        last_scraped_dates = [b.get('last_scraped') for b in brands_data if b.get('last_scraped')]
        last_updated = max(last_scraped_dates) if last_scraped_dates else '2025-01-01T00:00:00Z'
        
        return {
            'total_brands': total_brands,
            'active_brands': active_brands,
            'total_products': total_products,
            'total_collections': total_collections,
            'last_updated': last_updated
        }
    
    def discover_brand_collections(self, brand_id: int) -> Dict[str, Any]:
        """Discover collections for a brand without scraping products"""
        brand = self.get_brand_by_id(brand_id)
        if not brand:
            return {'error': 'Brand not found'}
        
        # Get existing collections from collection manager
        brand_products = self.collection_manager.get_brand_products(brand.slug)
        collections = []
        
        for collection_name in brand_products.keys():
            collections.append({
                'name': collection_name,
                'url': '',  # URL not stored in new system
                'type': 'collection'
            })
        
        if collections:
            return {
                'success': True,
                'type': 'collections',
                'collections': collections,
                'message': f'Found {len(collections)} collections'
            }
        else:
            return {
                'success': True,
                'type': 'products',
                'product_count': 0,
                'message': 'No collections found - use scrape to discover products'
            }