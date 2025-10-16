#!/usr/bin/env python3
"""
API Routes
==========

Flask URL route definitions for My Brands API.
"""

from .handlers import BrandHandlers, ProductHandlers, ScrapingHandlers


def register_brands_endpoints(app, brands_api=None):
    """
    Register My Brands endpoints with existing Flask app
    
    This maintains backward compatibility with the existing registration function
    """
    # Initialize handlers
    brand_handlers = BrandHandlers()
    product_handlers = ProductHandlers()
    scraping_handlers = ScrapingHandlers()
    
    # Brand management endpoints
    app.add_url_rule('/api/brands', methods=['POST'], 
                     view_func=brand_handlers.add_brand, endpoint='add_brand')
    app.add_url_rule('/api/brands', methods=['GET'], 
                     view_func=brand_handlers.get_brands, endpoint='get_brands')
    app.add_url_rule('/api/brands/<int:brand_id>', methods=['GET'], 
                     view_func=brand_handlers.get_brand_details, endpoint='get_brand_details')
    app.add_url_rule('/api/brands/<int:brand_id>/discover', methods=['POST'], 
                     view_func=brand_handlers.discover_brand_collections, endpoint='discover_brand_collections')
    
    # Product endpoints
    app.add_url_rule('/api/brands/<int:brand_id>/products', methods=['GET'], 
                     view_func=product_handlers.get_brand_products, endpoint='get_brand_products')
    
    # New hierarchical collection endpoints
    app.add_url_rule('/api/brands/<int:brand_id>/collections', methods=['GET'], 
                     view_func=product_handlers.get_brand_collections, endpoint='get_brand_collections')
    app.add_url_rule('/api/brands/<int:brand_id>/collections/<string:collection_slug>/products', methods=['GET'], 
                     view_func=product_handlers.get_collection_products, endpoint='get_collection_products')
    
    app.add_url_rule('/api/products/<int:product_id>/favorite', methods=['POST'], 
                     view_func=product_handlers.add_product_favorite, endpoint='add_product_favorite')
    app.add_url_rule('/api/brand-favorites', methods=['GET'], 
                     view_func=product_handlers.get_brand_favorites, endpoint='get_brand_favorites')
    
    # Scraping endpoints
    app.add_url_rule('/api/brands/<int:brand_id>/scrape', methods=['POST'], 
                     view_func=scraping_handlers.scrape_brand_products, endpoint='scrape_brand')
    app.add_url_rule('/api/brands/<int:brand_id>/scrape-stream', methods=['POST'], 
                     view_func=scraping_handlers.scrape_brand_products_stream, endpoint='scrape_brand_stream')
    
    # Stats and analysis endpoints
    app.add_url_rule('/api/brands/stats', methods=['GET'], 
                     view_func=brand_handlers.get_brand_stats, endpoint='get_brand_stats')
    app.add_url_rule('/api/brands/analyze', methods=['POST'], 
                     view_func=brand_handlers.analyze_brand_url, endpoint='analyze_brand')
    app.add_url_rule('/api/brands/resolve-name', methods=['POST'], 
                     view_func=brand_handlers.resolve_brand_name, endpoint='resolve_brand_name')
    
    print("✅ Modular My Brands API endpoints registered")


# For backward compatibility, also export the handlers directly
__all__ = ['register_brands_endpoints', 'BrandHandlers', 'ProductHandlers', 'ScrapingHandlers']