#!/usr/bin/env python3
"""
Scraping Service
================

Business logic for product scraping operations.
"""

import time
import json
from typing import Dict, Any, Generator, Callable
from ..models.brand import Brand
from ..services.brand_service import BrandService
from ..services.product_service import ProductService

# Import scraper premium functions (proper location, not test files)
try:
    import sys
    import os
    sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from scraper_premium.brand import Brand as ScraperBrand
    from scraper_premium.page_extractor import scrape_category_page
    SCRAPER_PREMIUM_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import scraper_premium functions: {e}")
    ScraperBrand = None
    scrape_category_page = None
    SCRAPER_PREMIUM_AVAILABLE = False


class ScrapingService:
    """Service class for scraping operations"""
    
    def __init__(self):
        self.brand_service = BrandService()
        self.product_service = ProductService()
    
    def scrape_brand_products_stream(self, brand_id: int, progress_callback: Callable = None) -> Generator[str, None, Dict[str, Any]]:
        """
        Stream brand products scraping with real-time progress
        
        Uses proper scraper_premium API (not test files)
        """
        if not SCRAPER_PREMIUM_AVAILABLE:
            yield f"data: {json.dumps({'status': 'error', 'message': 'Scraper premium not available'})}\n\n"
            return {'success': False, 'message': 'Scraper premium not available'}
        
        brand = self.brand_service.get_brand_by_id(brand_id)
        if not brand:
            yield f"data: {json.dumps({'status': 'error', 'message': 'Brand not found'})}\n\n"
            return {'success': False, 'message': 'Brand not found'}
        
        try:
            # Step 1: Initialize scraper brand
            yield f"data: {json.dumps({'status': 'starting', 'message': 'Initializing brand scraper...'})}\n\n"
            
            scraper_brand = ScraperBrand(brand.url)
            yield f"data: {json.dumps({'status': 'scraping_started', 'message': 'Analyzing brand website...'})}\n\n"
            
            # Step 2: Analyze page and extract patterns
            pattern_analysis = scraper_brand.analyze_category_patterns()
            
            if not pattern_analysis or not pattern_analysis.get("success"):
                yield f"data: {json.dumps({'status': 'error', 'message': 'Failed to analyze brand patterns'})}\n\n"
                return {'success': False, 'message': 'Pattern analysis failed'}
            
            categories = pattern_analysis.get("categories", [])
            if not categories:
                yield f"data: {json.dumps({'status': 'error', 'message': 'No product categories found'})}\n\n"
                return {'success': False, 'message': 'No categories found'}
            
            yield f"data: {json.dumps({'status': 'products_found', 'count': len(categories), 'collections': len(categories)})}\n\n"
            
            extraction_pattern = pattern_analysis["extraction_pattern"]
            yield f"data: {json.dumps({'status': 'pattern_found', 'message': 'Product pattern detected'})}\n\n"
            
            # Step 2.5: Discover pagination pattern
            yield f"data: {json.dumps({'status': 'pagination', 'message': 'Analyzing pagination pattern...'})}\n\n"
            
            pagination_start = time.time()
            pagination_pattern = scraper_brand.analyze_pagination_pattern()
            
            if pagination_pattern:
                pagination_type = pagination_pattern.get('type', 'none')
                yield f"data: {json.dumps({'status': 'pagination_found', 'message': f'Pagination pattern: {pagination_type}', 'pagination_type': pagination_type})}\n\n"
            else:
                pagination_pattern = {"type": "none"}
                yield f"data: {json.dumps({'status': 'pagination_found', 'message': 'Single page categories - no pagination', 'pagination_type': 'none'})}\n\n"
            
            # Step 3: Create fresh brand directory
            brand_slug = self.brand_service.collection_manager.create_brand_fresh(
                brand.name,
                brand.url,
                extraction_pattern=extraction_pattern
            )
            
            # Step 4: Prepare for parallel scraping
            from concurrent.futures import ThreadPoolExecutor, as_completed
            import os
            
            included_urls = {cat['url']: cat['name'] for cat in categories}
            collection_images_dirs = {}
            
            downloads_dir = os.path.expanduser("~/Downloads")
            brand_images_dir = os.path.join(downloads_dir, brand_slug)
            os.makedirs(brand_images_dir, exist_ok=True)
            
            for collection_url, collection_name in included_urls.items():
                collection_slug = self.brand_service.collection_manager._generate_collection_slug(collection_name, collection_url)
                collection_images_dir = os.path.join(brand_images_dir, collection_slug)
                os.makedirs(collection_images_dir, exist_ok=True)
                collection_images_dirs[collection_url] = collection_images_dir
            
            # Step 5: Parallel scraping
            total_products = 0
            collections_scraped = 0
            
            pagination_msg = f" with {pagination_pattern.get('type', 'no')} pagination" if pagination_pattern.get('type') != 'none' else ""
            yield f"data: {json.dumps({'status': 'parallel_scraping', 'message': f'Starting parallel scraping of {len(included_urls)} collections{pagination_msg}...'})}\n\n"
            
            category_results = []
            
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = {}
                
                # Submit all collections for parallel processing
                for collection_url, collection_name in included_urls.items():
                    future = executor.submit(
                        scrape_category_page,
                        collection_url,
                        [extraction_pattern],
                        brand.name,
                        pagination_pattern,
                        collection_images_dirs[collection_url],
                        True  # download_images=True
                    )
                    futures[future] = (collection_url, collection_name)
                
                # Process completed futures
                for future in as_completed(futures):
                    collection_url, collection_name = futures[future]
                    try:
                        result = future.result()
                        category_results.append(result)
                        
                        products_count = result.get('products_found', 0)
                        pages_processed = result.get('pages_processed', 1)
                        pagination_detected = result.get('pagination_detected', False)
                        
                        pages_msg = f" from {pages_processed} pages" if pages_processed > 1 else ""
                        
                        yield f"data: {json.dumps({'status': 'collection_completed', 'message': f'{collection_name}: {products_count} products{pages_msg}', 'pages_processed': pages_processed, 'pagination_detected': pagination_detected})}\n\n"
                        
                        if result.get("success", False):
                            products = result.get("products", [])
                            
                            # Store in collection manager
                            collection_slug = self.brand_service.collection_manager._generate_collection_slug(collection_name, collection_url)
                            self.brand_service.collection_manager.store_collection_products(
                                brand_slug,
                                collection_slug,
                                collection_name,
                                collection_url,
                                products,
                                extraction_pattern
                            )
                            
                            total_products += len(products)
                            collections_scraped += 1
                        
                    except Exception as e:
                        yield f"data: {json.dumps({'status': 'collection_error', 'message': f'{collection_name}: Error - {str(e)}'})}\n\n"
            
            # Final results
            yield f"data: {json.dumps({'status': 'storing_progress', 'message': f'Stored {total_products} products from {collections_scraped} collections'})}\n\n"
            
            # Get collections data for response
            collections_data = {}
            brand_products = self.brand_service.collection_manager.get_brand_products(brand_slug)
            for collection_name, products in brand_products.items():
                collections_data[collection_name] = {
                    'name': collection_name,
                    'products': products,
                    'count': len(products)
                }
            
            final_result = {
                'status': 'completed',
                'total_products': total_products,
                'collections': collections_data,
                'message': f'Successfully scraped {total_products} products from {collections_scraped} collections'
            }
            
            yield f"data: {json.dumps(final_result)}\n\n"
            return final_result
            
        except Exception as e:
            error_msg = f"Scraping failed: {str(e)}"
            yield f"data: {json.dumps({'status': 'error', 'message': error_msg})}\n\n"
            return {'success': False, 'message': error_msg}
    
    def scrape_single_collection(self, brand_id: int, collection_url: str, collection_name: str) -> Dict[str, Any]:
        """Scrape a single collection for a brand"""
        if scrape_category_page is None:
            return {'success': False, 'message': 'Scraper premium not available'}
        
        brand = self.brand_service.get_brand_by_id(brand_id)
        if not brand:
            return {'success': False, 'message': 'Brand not found'}
        
        try:
            # This would contain the single collection scraping logic
            # For now, return a placeholder
            return {
                'success': True,
                'message': f'Single collection scraping not yet implemented for {collection_name}',
                'products': []
            }
        except Exception as e:
            return {'success': False, 'message': f'Scraping failed: {str(e)}'}