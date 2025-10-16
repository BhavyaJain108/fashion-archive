#!/usr/bin/env python3
"""
API Request Handlers
===================

HTTP request/response handling for My Brands API.
Separates HTTP concerns from business logic.
"""

from typing import Dict, Any

# Import Flask components conditionally
try:
    from flask import request, jsonify, Response
except ImportError:
    # Flask not available, create dummy functions for testing
    request = None
    jsonify = lambda x: x
    Response = lambda x, **kwargs: x

from ..services.brand_service import BrandService
from ..services.product_service import ProductService
from ..services.scraping_service import ScrapingService
from ..brand_url_resolver import BrandURLResolver


class BrandHandlers:
    """HTTP handlers for brand-related endpoints"""
    
    def __init__(self):
        self.brand_service = BrandService()
        self.url_resolver = BrandURLResolver()
    
    def add_brand(self) -> Dict[str, Any]:
        """
        POST /api/brands
        Add a new brand to the collection
        """
        try:
            data = request.get_json()
            url = data.get('url', '').strip()
            brand_name = data.get('name', '').strip()
            
            if not url:
                return jsonify({'error': 'URL is required'}), 400
            
            # If we have a brand name, use it; otherwise extract from URL
            if not brand_name:
                # Extract brand name from URL or use domain
                from urllib.parse import urlparse
                parsed = urlparse(url)
                brand_name = parsed.netloc.replace('www.', '').replace('.com', '').title()
            
            # Create brand using service
            brand = self.brand_service.create_brand(brand_name, url)
            
            return jsonify({
                'success': True,
                'brand': brand.to_dict(),
                'message': f'Brand {brand.name} added successfully'
            })
            
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    def get_brands(self) -> Dict[str, Any]:
        """
        GET /api/brands
        Get all brands in the collection
        """
        try:
            brands = self.brand_service.get_all_brands()
            brands_dict = [brand.to_dict() for brand in brands]
            return jsonify({'brands': brands_dict})
            
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    def get_brand_details(self, brand_id: int) -> Dict[str, Any]:
        """
        GET /api/brands/{id}
        Get detailed information about a specific brand
        """
        try:
            brand = self.brand_service.get_brand_by_id(brand_id)
            if not brand:
                return jsonify({'error': 'Brand not found'}), 404
            
            # Get products using product service
            product_service = ProductService()
            all_products, collections_data = product_service.get_brand_products(brand)
            
            return jsonify({
                'brand': brand.to_dict(),
                'products': [product.to_dict() for product in all_products],
                'scraping_config': {},  # No longer used
                'product_count': len(all_products)
            })
            
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    def discover_brand_collections(self, brand_id: int) -> Dict[str, Any]:
        """
        POST /api/brands/{id}/discover
        Discover collections for a brand without scraping products
        """
        try:
            result = self.brand_service.discover_brand_collections(brand_id)
            return jsonify(result)
            
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    def get_brand_stats(self) -> Dict[str, Any]:
        """
        GET /api/brands/stats
        Get statistics about brands collection
        """
        try:
            stats = self.brand_service.get_brand_stats()
            return jsonify({'stats': stats})
            
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    def analyze_brand_url(self) -> Dict[str, Any]:
        """
        POST /api/brands/analyze
        Analyze a brand URL without adding it (for preview)
        """
        try:
            data = request.get_json()
            url = data.get('url', '').strip()
            
            if not url:
                return jsonify({'error': 'URL is required'}), 400
            
            # This would contain analysis logic
            return jsonify({
                'success': True,
                'url': url,
                'message': 'URL analysis not yet implemented'
            })
            
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    def resolve_brand_name(self) -> Dict[str, Any]:
        """
        POST /api/brands/resolve-name
        Resolve brand name to URL
        """
        try:
            data = request.get_json()
            brand_name = data.get('brand_name', '').strip()
            
            if not brand_name:
                return jsonify({'error': 'Brand name is required'}), 400
            
            result = self.url_resolver.resolve_brand_name(brand_name)
            return jsonify(result)
            
        except Exception as e:
            return jsonify({'error': str(e)}), 500


class ProductHandlers:
    """HTTP handlers for product-related endpoints"""
    
    def __init__(self):
        self.brand_service = BrandService()
        self.product_service = ProductService()
    
    def get_brand_products(self, brand_id: int) -> Dict[str, Any]:
        """
        GET /api/brands/{id}/products
        Get all products for a brand
        """
        try:
            brand = self.brand_service.get_brand_by_id(brand_id)
            if not brand:
                return jsonify({'error': 'Brand not found'}), 404
            
            all_products, collections_data = self.product_service.get_brand_products(brand)
            
            # Convert to API response format
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
    
    def add_product_favorite(self, product_id: int) -> Dict[str, Any]:
        """
        POST /api/products/{id}/favorite
        Add a product to favorites
        """
        try:
            data = request.get_json()
            notes = data.get('notes', '')
            
            result = self.product_service.add_product_favorite(product_id, notes)
            return jsonify(result)
            
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    def get_brand_collections(self, brand_id: int) -> Dict[str, Any]:
        """
        GET /api/brands/{id}/collections
        Get only collection information for a brand (no products)
        """
        try:
            brand = self.brand_service.get_brand_by_id(brand_id)
            if not brand:
                return jsonify({'error': 'Brand not found'}), 404
            
            collections = self.product_service.get_brand_collections_only(brand)
            
            return jsonify({
                'brand': brand.to_dict(),
                'collections': collections,
                'total_collections': len(collections)
            })
            
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    def get_collection_products(self, brand_id: int, collection_slug: str) -> Dict[str, Any]:
        """
        GET /api/brands/{id}/collections/{collection_slug}/products
        Get products for a specific collection of a brand
        """
        try:
            brand = self.brand_service.get_brand_by_id(brand_id)
            if not brand:
                return jsonify({'error': 'Brand not found'}), 404
            
            # Convert slug back to collection name
            collection_name = collection_slug.replace('-', ' ').title()
            
            products = self.product_service.get_products_by_collection(brand, collection_name)
            
            if not products:
                # Try exact match with original naming
                brand_products = self.product_service.collection_manager.get_brand_products(brand.slug)
                for original_name in brand_products.keys():
                    if original_name.lower().replace(' ', '-') == collection_slug:
                        collection_name = original_name
                        products = self.product_service.get_products_by_collection(brand, collection_name)
                        break
            
            return jsonify({
                'brand': brand.to_dict(),
                'collection': {
                    'name': collection_name,
                    'slug': collection_slug,
                    'count': len(products)
                },
                'products': [product.to_dict() for product in products]
            })
            
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    def get_brand_favorites(self) -> Dict[str, Any]:
        """
        GET /api/brand-favorites
        Get all favorite products from brands
        """
        try:
            favorites = self.product_service.get_brand_favorites()
            return jsonify({'favorites': favorites})
            
        except Exception as e:
            return jsonify({'error': str(e)}), 500


class ScrapingHandlers:
    """HTTP handlers for scraping-related endpoints"""
    
    def __init__(self):
        self.scraping_service = ScrapingService()
    
    def scrape_brand_products(self, brand_id: int) -> Dict[str, Any]:
        """
        POST /api/brands/{id}/scrape
        Scrape products for a brand (single collection or all)
        """
        try:
            data = request.get_json() or {}
            collection_url = data.get('collection_url')
            
            if collection_url:
                # Single collection scraping
                collection_name = data.get('collection_name', 'Unknown Collection')
                result = self.scraping_service.scrape_single_collection(brand_id, collection_url, collection_name)
                return jsonify(result)
            else:
                # Full brand scraping - not implemented in streaming version
                return jsonify({
                    'success': False,
                    'message': 'Use scrape-stream endpoint for full brand scraping'
                })
                
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    def scrape_brand_products_stream(self, brand_id: int) -> Response:
        """
        POST /api/brands/{id}/scrape-stream
        Stream brand products scraping with real-time progress
        """
        try:
            def generate():
                for data in self.scraping_service.scrape_brand_products_stream(brand_id):
                    yield data
            
            return Response(generate(), content_type='text/plain')
            
        except Exception as e:
            def error_response():
                import json
                yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"
            
            return Response(error_response(), content_type='text/plain')