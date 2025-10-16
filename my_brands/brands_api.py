#!/usr/bin/env python3
"""
My Brands API - Modular Version
===============================

Streamlined API using modular services architecture.
Maintains backward compatibility while providing clean separation of concerns.
"""

# Import the modular components
from .api.routes import register_brands_endpoints
from .services.brand_service import BrandService
from .services.product_service import ProductService
from .services.scraping_service import ScrapingService

# For backward compatibility, import key components from original
from flask import request, jsonify, Response
import json
import time
from typing import Dict, Any


class BrandsAPI:
    """
    Main API class - now delegates to modular services
    """
    
    def __init__(self):
        """Initialize with modular services"""
        self.brand_service = BrandService()
        self.product_service = ProductService()
        self.scraping_service = ScrapingService()
        
        # Keep reference to collection manager for direct access if needed
        self.collection_manager = self.brand_service.collection_manager
    
    # Original method signatures maintained for backward compatibility
    def add_brand(self) -> Dict[str, Any]:
        """POST /api/brands - Add a new brand"""
        try:
            data = request.get_json()
            url = data.get('url', '').strip()
            brand_name = data.get('name', '').strip()
            
            if not url:
                return jsonify({'error': 'URL is required'}), 400
            
            # If we have a brand name, use it; otherwise extract from URL
            if not brand_name:
                from urllib.parse import urlparse
                parsed = urlparse(url)
                brand_name = parsed.netloc.replace('www.', '').replace('.com', '').title()
            
            # Use modular service
            brand = self.brand_service.create_brand(brand_name, url)
            
            return jsonify({
                'success': True,
                'brand': brand.to_dict(),
                'message': f'Brand {brand.name} added successfully'
            })
            
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    def get_brands(self) -> Dict[str, Any]:
        """GET /api/brands - Get all brands"""
        try:
            brands = self.brand_service.get_all_brands()
            brands_dict = [brand.to_dict() for brand in brands]
            return jsonify({'brands': brands_dict})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    def get_brand_details(self, brand_id: int) -> Dict[str, Any]:
        """GET /api/brands/{id} - Get brand details"""
        try:
            brand = self.brand_service.get_brand_by_id(brand_id)
            if not brand:
                return jsonify({'error': 'Brand not found'}), 404
            
            all_products, collections_data = self.product_service.get_brand_products(brand)
            
            return jsonify({
                'brand': brand.to_dict(),
                'products': [product.to_dict() for product in all_products],
                'scraping_config': {},
                'product_count': len(all_products)
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    def discover_brand_collections(self, brand_id: int) -> Dict[str, Any]:
        """POST /api/brands/{id}/discover - Discover collections"""
        try:
            result = self.brand_service.discover_brand_collections(brand_id)
            return jsonify(result)
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    def get_brand_products(self, brand_id: int) -> Dict[str, Any]:
        """GET /api/brands/{id}/products - Get all products for a brand"""
        try:
            brand = self.brand_service.get_brand_by_id(brand_id)
            if not brand:
                return jsonify({'error': 'Brand not found'}), 404
            
            all_products, collections_data = self.product_service.get_brand_products(brand)
            
            products_dict = [product.to_dict() for product in all_products]
            collections_dict = {name: collection.to_dict() for name, collection in collections_data.items()}
            
            return jsonify({
                'brand': brand.to_dict(),
                'products': products_dict,  # All products for backward compatibility
                'collections': collections_dict,  # Grouped by collection for new UI
                'count': len(products_dict)
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    def scrape_brand_products(self, brand_id: int) -> Dict[str, Any]:
        """POST /api/brands/{id}/scrape - Scrape products"""
        try:
            data = request.get_json() or {}
            collection_url = data.get('collection_url')
            
            if collection_url:
                collection_name = data.get('collection_name', 'Unknown Collection')
                result = self.scraping_service.scrape_single_collection(brand_id, collection_url, collection_name)
                return jsonify(result)
            else:
                return jsonify({
                    'success': False,
                    'message': 'Use scrape-stream endpoint for full brand scraping'
                })
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    def scrape_brand_products_stream(self, brand_id: int) -> Response:
        """POST /api/brands/{id}/scrape-stream - Stream scraping progress"""
        try:
            def generate():
                for data in self.scraping_service.scrape_brand_products_stream(brand_id):
                    yield data
            
            return Response(generate(), content_type='text/plain')
        except Exception as e:
            def error_response():
                yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"
            
            return Response(error_response(), content_type='text/plain')
    
    def add_product_favorite(self, product_id: int) -> Dict[str, Any]:
        """POST /api/products/{id}/favorite - Add favorite"""
        try:
            data = request.get_json()
            notes = data.get('notes', '')
            result = self.product_service.add_product_favorite(product_id, notes)
            return jsonify(result)
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    def get_brand_favorites(self) -> Dict[str, Any]:
        """GET /api/brand-favorites - Get favorites"""
        try:
            favorites = self.product_service.get_brand_favorites()
            return jsonify({'favorites': favorites})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    def get_brand_stats(self) -> Dict[str, Any]:
        """GET /api/brands/stats - Get statistics"""
        try:
            stats = self.brand_service.get_brand_stats()
            return jsonify({'stats': stats})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    def analyze_brand_url(self) -> Dict[str, Any]:
        """POST /api/brands/analyze - Analyze URL"""
        try:
            data = request.get_json()
            url = data.get('url', '').strip()
            
            if not url:
                return jsonify({'error': 'URL is required'}), 400
            
            return jsonify({
                'success': True,
                'url': url,
                'message': 'URL analysis not yet implemented'
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    def resolve_brand_name(self) -> Dict[str, Any]:
        """POST /api/brands/resolve-name - Resolve brand name"""
        try:
            data = request.get_json()
            brand_name = data.get('brand_name', '').strip()
            
            if not brand_name:
                return jsonify({'error': 'Brand name is required'}), 400
            
            result = self.brand_service.resolve_brand_name(brand_name)
            return jsonify(result)
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    # Legacy method signatures for compatibility
    _generate_brand_id = lambda self, slug: self.brand_service.collection_manager._generate_brand_id(slug) if hasattr(self.brand_service.collection_manager, '_generate_brand_id') else hash(slug) % 10000


def register_brands_endpoints(app, brands_api=None):
    """
    Register My Brands endpoints with existing Flask app
    
    This function maintains the exact same signature as the original
    but now uses the modular architecture under the hood.
    """
    if brands_api is None:
        brands_api = BrandsAPI()
    
    # Use the modular registration but maintain backward compatibility
    from .api.routes import register_brands_endpoints as modular_register
    return modular_register(app, brands_api)


# For backward compatibility
__all__ = ['BrandsAPI', 'register_brands_endpoints']