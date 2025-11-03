#!/usr/bin/env python3
"""
My Brands API Endpoints
======================

Flask endpoints for the My Brands feature that integrate with the existing clean_api.py
These endpoints handle brand validation, scraping, and product management.
"""

from flask import jsonify, request
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import json
import traceback
from typing import Dict, Any, List
import sys
import os
import hashlib

# Add parent directory to path for config import
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import config

from .llm_client import create_my_brands_llm
# Direct import of working scraper_premium functions
try:
    import sys
    import os
    scraper_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scraper_premium')
    if scraper_path not in sys.path:
        sys.path.append(scraper_path)
    
    SCRAPER_PREMIUM_AVAILABLE = True
except ImportError as e:
    print(f"⚠️ scraper_premium not available: {e}")
    SCRAPER_PREMIUM_AVAILABLE = False
from .brand_collection_manager import BrandCollectionManager
from .brand_url_resolver import BrandURLResolver


class BrandsAPI:
    """API endpoints for My Brands feature"""
    
    def __init__(self):
        self.llm = create_my_brands_llm()
        self.url_resolver = BrandURLResolver()
        # Direct use of scraper_premium
        self.collection_manager = BrandCollectionManager()  # New organized storage
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
    
    def _generate_brand_id(self, slug: str) -> int:
        """Generate consistent brand ID from slug using stable hash"""
        return int(hashlib.md5(slug.encode()).hexdigest()[:8], 16) % 10000
    
    def add_brand(self) -> Dict[str, Any]:
        """
        POST /api/brands
        Add and validate a new brand
        """
        try:
            data = request.get_json()
            url = data.get('url', '').strip()
            provided_name = data.get('name') or ''  # Handle None values
            if provided_name:
                provided_name = provided_name.strip()
            
            if not url:
                return jsonify({'success': False, 'message': 'URL is required'}), 400
            
            # Quick domain validation
            domain_result = self._check_blocked_domains(url)
            if not domain_result['allowed']:
                return jsonify({
                    'success': False,
                    'message': domain_result['reason']
                })
            
            # Check if brand already exists in new storage
            existing_brands = self.collection_manager.list_brands()
            for brand in existing_brands:
                if brand['url'] == url:
                    return jsonify({
                        'success': False,
                        'message': 'Brand already exists in your collection'
                    })
            
            # Fetch website content for analysis
            website_content = self._fetch_website_content(url)
            if not website_content:
                return jsonify({
                    'success': False,
                    'message': 'Unable to access website. Please check the URL.'
                })
            
            # AI validation and scraping analysis (with brand name for validation)
            analysis = self.llm.analyze_brand_website(url, website_content, provided_name)
            
            if not analysis.is_valid_brand:
                return jsonify({
                    'success': False,
                    'message': f'Brand validation failed: {analysis.reason}',
                    'details': {
                        'confidence': analysis.confidence,
                        'issues': analysis.issues,
                        'brand_type': analysis.brand_type
                    }
                })
            
            # Add brand to new collection storage
            brand_name = analysis.brand_name or self._extract_domain_name(url)
            brand_slug = self.collection_manager.create_brand(brand_name, url)
            
            # Generate consistent ID for API compatibility
            brand_id = self._generate_brand_id(brand_slug)
            
            return jsonify({
                'success': True,
                'message': f'Successfully added {brand_name}!',
                'brand': {
                    'id': brand_id,
                    'slug': brand_slug,
                    'name': brand_name,
                    'url': url,
                    'validation_status': 'approved',
                    'scraping_strategy': analysis.scraping_strategy,
                    'is_scrapable': analysis.is_scrapable
                }
            })
            
        except Exception as e:
            print(f"Error adding brand: {e}")
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': f'Error adding brand: {str(e)}'
            }), 500
    
    def get_brands(self) -> Dict[str, Any]:
        """
        GET /api/brands
        Get all brands from organized collection storage
        """
        try:
            # Get brands from new collection manager
            brands_data = self.collection_manager.list_brands()
            
            # Convert to expected format for UI compatibility
            brands = []
            for brand_data in brands_data:
                # Use last_scraped or provide default date
                date_added = brand_data.get('last_scraped') or '2025-01-01T00:00:00Z'
                last_scraped = brand_data.get('last_scraped') or '2025-01-01T00:00:00Z'
                
                brand = {
                    'id': self._generate_brand_id(brand_data['slug']),  # Generate consistent ID from slug
                    'slug': brand_data['slug'],
                    'name': brand_data['name'],
                    'url': brand_data['url'],
                    'validation_status': 'approved',  # All brands in collection are approved
                    'scraping_strategy': 'premium_scraper',
                    'date_added': date_added,
                    'product_count': brand_data.get('products_count', 0),
                    'collections_count': brand_data.get('collections_count', 0),
                    'last_scraped': last_scraped,
                    'status': brand_data.get('status', 'active')
                }
                brands.append(brand)
            
            return jsonify({
                'brands': brands,
                'count': len(brands)
            })
            
        except Exception as e:
            print(f"Error getting brands from collection manager: {e}")
            return jsonify({'error': str(e)}), 500
    
    def get_brand_details(self, brand_id: int) -> Dict[str, Any]:
        """
        GET /api/brands/{id}
        Get detailed information about a specific brand
        """
        try:
            # Find brand by ID in collection manager
            brands_data = self.collection_manager.list_brands()
            target_brand = None
            
            for brand_data in brands_data:
                if self._generate_brand_id(brand_data['slug']) == brand_id:
                    target_brand = brand_data
                    break
            
            if not target_brand:
                return jsonify({'error': 'Brand not found'}), 404
            
            # Get products from collection manager
            brand_products = self.collection_manager.get_brand_products(target_brand['slug'])
            
            # Flatten products from all collections
            products = []
            for collection_name, collection_products in brand_products.items():
                for product in collection_products:
                    formatted_product = {
                        'id': int(hashlib.md5(f"{product.get('url', '')}{product.get('name', '')}".encode()).hexdigest()[:8], 16) % 10000,
                        'name': product.get('name', 'Unknown Product'),
                        'url': product.get('url', ''),
                        'image_url': product.get('image_url', ''),
                        'price': product.get('price'),
                        'collection': collection_name
                    }
                    products.append(formatted_product)
            
            return jsonify({
                'brand': {
                    'id': brand_id,
                    'name': target_brand['name'],
                    'url': target_brand['url'],
                    'slug': target_brand['slug'],
                    'status': target_brand.get('status', 'active')
                },
                'products': products,
                'scraping_config': {},  # No longer used
                'product_count': len(products)
            })
            
        except Exception as e:
            print(f"Error getting brand details: {e}")
            return jsonify({'error': str(e)}), 500
    
    def discover_brand_collections(self, brand_id: int) -> Dict[str, Any]:
        """
        POST /api/brands/{id}/discover
        Discover collections for a brand without scraping products
        """
        try:
            # Find brand by ID in collection manager
            brands_data = self.collection_manager.list_brands()
            target_brand = None
            
            for brand_data in brands_data:
                if self._generate_brand_id(brand_data['slug']) == brand_id:
                    target_brand = brand_data
                    break
            
            if not target_brand:
                return jsonify({'error': 'Brand not found'}), 404
            
            # Get scraping strategy - using default for collection discovery
            # Note: This functionality may need updating for new storage system
            
            # Simple collection discovery by returning existing collections
            brand_products = self.collection_manager.get_brand_products(target_brand['slug'])
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
                    'type': 'navigation',
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
                
        except Exception as e:
            print(f"Error discovering collections: {str(e)}")
            traceback.print_exc()
            return {
                'success': False,
                'message': f'Collection discovery failed: {str(e)}'
            }
    
    def scrape_brand_products_stream(self, brand_id: int) -> Dict[str, Any]:
        """
        POST /api/brands/{id}/scrape-stream
        Stream products scraping with real-time progress updates using new storage system
        """
        from flask import Response
        import json
        import time
        
        def generate_scraping_stream():
            try:
                # Find brand in new storage system
                brands_data = self.collection_manager.list_brands()
                target_brand = None
                
                for brand_data in brands_data:
                    if self._generate_brand_id(brand_data['slug']) == brand_id:
                        target_brand = brand_data
                        break
                
                if not target_brand:
                    yield f"data: {json.dumps({'error': 'Brand not found in collection storage'})}\n\n"
                    return

                yield f"data: {json.dumps({'status': 'starting', 'message': 'Setting up scraping with new storage system...'})}\n\n"
                
                # Use working scraper_premium test function directly
                yield f"data: {json.dumps({'status': 'analyzing', 'message': 'AI analyzing website structure (Premium Scraper)...'})}\n\n"
                
                if not SCRAPER_PREMIUM_AVAILABLE:
                    yield f"data: {json.dumps({'status': 'error', 'error': 'Premium scraper not available'})}\n\n"
                    return
                
                # Use working scraper_premium components directly
                import time
                start_time = time.time()
                print(f"🚀 [{time.strftime('%H:%M:%S')}] Starting scrape for {target_brand['name']}")
                
                from scraper_premium.brand import Brand
                from scraper_premium.page_extractor import extract_category_name, get_first_leaf_url, extract_all_urls_from_navigation_tree
                from scraper_premium.prompts import PromptManager
                
                print(f"⏱️ [{time.strftime('%H:%M:%S')}] Imports loaded in {time.time() - start_time:.2f}s")
                
                brand_init_start = time.time()
                brand = Brand(target_brand['url'])
                print(f"⏱️ [{time.strftime('%H:%M:%S')}] Brand initialized in {time.time() - brand_init_start:.2f}s")
                
                # Step 1: Navigation Analysis - Get navigation tree
                yield f"data: {json.dumps({'status': 'navigation', 'message': 'Analyzing brand navigation structure...'})}\n\n"
                
                nav_start = time.time()
                print(f"🔍 [{time.strftime('%H:%M:%S')}] Extracting page links with context...")
                links_with_context = brand.extract_page_links_with_context(target_brand['url'])
                print(f"⏱️ [{time.strftime('%H:%M:%S')}] Links with context extracted in {time.time() - nav_start:.2f}s - Found {len(links_with_context) if links_with_context else 0} links")
                
                if not links_with_context:
                    yield f"data: {json.dumps({'status': 'error', 'error': 'No links found on brand website'})}\n\n"
                    return
                
                # Get LLM navigation analysis using proper prompt
                llm_start = time.time()
                print(f"🤖 [{time.strftime('%H:%M:%S')}] Building navigation analysis prompt...")
                prompt_data = PromptManager.get_navigation_analysis_prompt(target_brand['url'], links_with_context)
                print(f"🤖 [{time.strftime('%H:%M:%S')}] Calling LLM for navigation analysis...")
                llm_response = brand.llm_handler.call(prompt_data['prompt'], expected_format="json", response_model=prompt_data['model'])
                print(f"⏱️ [{time.strftime('%H:%M:%S')}] LLM navigation analysis completed in {time.time() - llm_start:.2f}s")
                
                if not llm_response.get("success", False):
                    yield f"data: {json.dumps({'status': 'error', 'error': 'Navigation analysis failed'})}\n\n"
                    return
                
                # Extract navigation tree from LLM response
                navigation_tree = llm_response.get("data", {}).get("category_tree", [])
                if not navigation_tree:
                    yield f"data: {json.dumps({'status': 'error', 'error': 'No navigation tree structure found'})}\n\n"
                    return
                
                print(f"✅ [{time.strftime('%H:%M:%S')}] Navigation tree extracted with {len(navigation_tree)} top-level categories")
                yield f"data: {json.dumps({'status': 'navigation_found', 'message': f'Found navigation tree with {len(navigation_tree)} categories'})}\n\n"
                
                # Step 2: Store Navigation Tree
                print(f"💾 [{time.strftime('%H:%M:%S')}] Creating fresh brand directory...")
                brand_slug = self.collection_manager.create_brand_fresh(
                    target_brand['name'], 
                    target_brand['url']
                )
                
                print(f"💾 [{time.strftime('%H:%M:%S')}] Saving navigation tree...")
                navigation_saved = self.collection_manager.save_navigation_tree(brand_slug, navigation_tree)
                if not navigation_saved:
                    yield f"data: {json.dumps({'status': 'error', 'error': 'Failed to save navigation tree'})}\n\n"
                    return
                
                yield f"data: {json.dumps({'status': 'navigation_saved', 'message': 'Navigation tree saved successfully'})}\n\n"
                
                # Step 3: Pattern Discovery using first leaf URL
                yield f"data: {json.dumps({'status': 'pattern', 'message': 'Discovering product pattern...'})}\n\n"
                
                pattern_start = time.time()
                print(f"🔍 [{time.strftime('%H:%M:%S')}] Finding first leaf URL for pattern discovery...")
                first_leaf_url = get_first_leaf_url(navigation_tree)
                
                if not first_leaf_url:
                    yield f"data: {json.dumps({'status': 'error', 'error': 'No leaf URLs found in navigation tree'})}\n\n"
                    return
                
                print(f"🔍 [{time.strftime('%H:%M:%S')}] Using {first_leaf_url} for pattern discovery")
                brand.starting_pages_queue = [first_leaf_url]
                print(f"🤖 [{time.strftime('%H:%M:%S')}] Starting product pattern analysis...")
                pattern_analysis = brand.analyze_product_pattern()
                print(f"⏱️ [{time.strftime('%H:%M:%S')}] Pattern analysis completed in {time.time() - pattern_start:.2f}s")
                
                if not pattern_analysis or not brand.product_extraction_pattern:
                    yield f"data: {json.dumps({'status': 'error', 'error': 'Failed to detect product pattern'})}\n\n"
                    return
                
                extraction_pattern = brand.product_extraction_pattern
                print(f"✅ [{time.strftime('%H:%M:%S')}] Pattern discovered: {extraction_pattern.get('container_selector', 'N/A')}")
                yield f"data: {json.dumps({'status': 'pattern_found', 'message': 'Product pattern detected'})}\n\n"
                
                # Step 4: Create Hierarchical Collections Structure
                yield f"data: {json.dumps({'status': 'creating_structure', 'message': 'Creating hierarchical collections structure...'})}\n\n"
                
                structure_start = time.time()
                print(f"🗂️ [{time.strftime('%H:%M:%S')}] Creating hierarchical folder structure...")
                url_to_path_mapping = self.collection_manager.create_hierarchical_collections(brand_slug, navigation_tree)
                print(f"⏱️ [{time.strftime('%H:%M:%S')}] Structure created in {time.time() - structure_start:.2f}s")
                
                if not url_to_path_mapping:
                    yield f"data: {json.dumps({'status': 'error', 'error': 'Failed to create collection structure'})}\n\n"
                    return
                
                yield f"data: {json.dumps({'status': 'structure_created', 'message': f'Created {len(url_to_path_mapping)} collection folders'})}\n\n"
                
                # Step 5: Extract ALL URLs for Parallel Processing
                print(f"🔍 [{time.strftime('%H:%M:%S')}] Extracting all URLs from navigation tree...")
                all_category_urls = extract_all_urls_from_navigation_tree(navigation_tree)
                print(f"✅ [{time.strftime('%H:%M:%S')}] Found {len(all_category_urls)} URLs to process")
                
                if not all_category_urls:
                    yield f"data: {json.dumps({'status': 'error', 'error': 'No URLs found in navigation tree'})}\n\n"
                    return
                
                # Set up brand for parallel processing using built-in capabilities
                brand.starting_pages_queue = all_category_urls
                
                yield f"data: {json.dumps({'status': 'parallel_setup', 'message': f'Starting parallel processing of {len(all_category_urls)} categories...'})}\n\n"
                
                # Step 6: Use Brand's Built-in Parallel Processing
                total_products = 0
                
                processing_start = time.time()
                print(f"🚀 [{time.strftime('%H:%M:%S')}] Starting parallel processing using Brand's built-in capabilities...")
                
                # Use Brand's built-in parallel processing
                total_products_discovered = brand.process_all_starting_pages()
                
                processing_time = time.time() - processing_start
                print(f"⏱️ [{time.strftime('%H:%M:%S')}] Parallel processing completed in {processing_time:.2f}s")
                print(f"✅ [{time.strftime('%H:%M:%S')}] Total products discovered: {total_products_discovered}")
                
                yield f"data: {json.dumps({'status': 'processing_complete', 'message': f'Parallel processing complete: {total_products_discovered} products discovered'})}\n\n"
                
                # Step 7: Store Results in Hierarchical Structure
                yield f"data: {json.dumps({'status': 'storing_results', 'message': 'Storing results in hierarchical structure...'})}\n\n"
                
                storage_start = time.time()
                collections_stored = 0
                
                # Process results from brand's product queue and store hierarchically
                print(f"💾 [{time.strftime('%H:%M:%S')}] Processing brand's product queue for storage...")
                
                # Group products by their source URL for hierarchical storage
                products_by_url = {}
                while not brand.product_queue.empty():
                    try:
                        product = brand.product_queue.get_nowait()
                        source_url = getattr(product, 'source_url', None)
                        
                        if source_url and source_url in all_category_urls:
                            if source_url not in products_by_url:
                                products_by_url[source_url] = []
                            
                            # Convert Product object to dict format expected by storage
                            product_dict = {
                                "name": getattr(product, 'title', 'Unknown'),
                                "url": getattr(product, 'href', ''),
                                "image_url": getattr(product, 'image_url', ''),
                                "price": getattr(product, 'price', ''),
                                "discovered_at": datetime.now().isoformat(),
                                "brand": target_brand['name']
                            }
                            products_by_url[source_url].append(product_dict)
                    except:
                        break
                
                # Store each collection's results
                for collection_url, products in products_by_url.items():
                    if products:
                        collection_name = extract_category_name(collection_url)
                        
                        success = self.collection_manager.store_collection_results(
                            brand_slug=brand_slug,
                            collection_url=collection_url,
                            collection_name=collection_name,
                            products=products,
                            extraction_pattern=extraction_pattern,
                            url_to_path_mapping=url_to_path_mapping
                        )
                        
                        if success:
                            collections_stored += 1
                            total_products += len(products)
                            print(f"✅ [{time.strftime('%H:%M:%S')}] Stored {len(products)} products for {collection_name}")
                            yield f"data: {json.dumps({'status': 'collection_stored', 'message': f'Stored {collection_name}: {len(products)} products'})}\n\n"
                
                storage_time = time.time() - storage_start
                print(f"⏱️ [{time.strftime('%H:%M:%S')}] Storage completed in {storage_time:.2f}s")
                print(f"📊 [{time.strftime('%H:%M:%S')}] Final results: {total_products} products across {collections_stored} collections")
                
                yield f"data: {json.dumps({'status': 'completed', 'message': f'Successfully scraped {collections_stored} collections with {total_products} products', 'success': True, 'total_products': total_products, 'collections_stored': collections_stored})}\n\n"
                
            except Exception as e:
                yield f"data: {json.dumps({'status': 'error', 'error': str(e)})}\n\n"

        return Response(generate_scraping_stream(), mimetype='text/event-stream')

    def scrape_brand_products(self, brand_id: int) -> Dict[str, Any]:
        """
        POST /api/brands/{id}/scrape
        Non-streaming version - just redirects to stream for now
        """
        return jsonify({
            'success': False,
            'message': 'Please use the streaming endpoint /scrape-stream for better progress tracking'
        })
    
    def get_brand_categories(self, brand_id: int) -> Dict[str, Any]:
        """
        GET /api/brands/{id}/categories
        Get categories/collections for a brand (without products for clean UX)
        """
        try:
            # Find brand by ID in collection manager
            brands_data = self.collection_manager.list_brands()
            target_brand = None
            
            for brand_data in brands_data:
                if self._generate_brand_id(brand_data['slug']) == brand_id:
                    target_brand = brand_data
                    break
            
            if not target_brand:
                return jsonify({'error': 'Brand not found'}), 404
            
            # Get brand info to check if scraped
            brand_info = self.collection_manager.get_brand_info(target_brand['slug'])
            if not brand_info:
                return jsonify({'error': 'Brand info not found'}), 404
            
            # Get collections without loading products
            collections_data = {}
            total_products = 0
            
            for collection in brand_info.get('collections', []):
                collections_data[collection['name']] = {
                    'name': collection['name'],
                    'slug': collection['slug'], 
                    'url': collection['url'],
                    'count': collection['products_count'],
                    'last_updated': collection['last_updated']
                }
                total_products += collection['products_count']
            
            return jsonify({
                'brand': {
                    'id': brand_id,
                    'name': target_brand['name'],
                    'url': target_brand['url'],
                    'slug': target_brand['slug'],
                    'status': target_brand.get('status', 'active'),
                    'last_scraped': brand_info.get('stats', {}).get('last_scraped')
                },
                'categories': collections_data,
                'total_categories': len(collections_data),
                'total_products': total_products,
                'is_scraped': len(collections_data) > 0
            })
            
        except Exception as e:
            print(f"Error getting brand categories: {e}")
            return jsonify({'error': str(e)}), 500
    
    def get_category_products(self, brand_id: int, category_name: str) -> Dict[str, Any]:
        """
        GET /api/brands/{id}/categories/{category_name}/products  
        Get products for a specific category within a brand
        """
        try:
            # Find brand by ID
            brands_data = self.collection_manager.list_brands()
            target_brand = None
            
            for brand_data in brands_data:
                if self._generate_brand_id(brand_data['slug']) == brand_id:
                    target_brand = brand_data
                    break
            
            if not target_brand:
                return jsonify({'error': 'Brand not found'}), 404
            
            # Get products from collection manager for this specific category
            brand_products = self.collection_manager.get_brand_products(target_brand['slug'])
            
            if category_name not in brand_products:
                return jsonify({'error': f'Category "{category_name}" not found'}), 404
            
            # Format products for this category only
            category_products = brand_products[category_name]
            formatted_products = []
            
            for product in category_products:
                formatted_product = {
                    'id': int(hashlib.md5(f"{product.get('url', '')}{product.get('name', '')}".encode()).hexdigest()[:8], 16) % 10000,
                    'name': product.get('name', 'Unknown Product'),
                    'url': product.get('url', ''),
                    'image_url': product.get('image_url', ''),
                    'price': product.get('price'),
                    'collection': category_name,
                    'images': [product.get('image_url', '')] if product.get('image_url') else [],
                    'metadata': {
                        'collection_name': category_name,
                        'discovered_at': product.get('discovered_at'),
                        'brand': target_brand['name']
                    }
                }
                formatted_products.append(formatted_product)
            
            return jsonify({
                'brand': {
                    'id': brand_id,
                    'name': target_brand['name'],
                    'url': target_brand['url'],
                    'slug': target_brand['slug']
                },
                'category': {
                    'name': category_name,
                    'count': len(formatted_products)
                },
                'products': formatted_products,
                'count': len(formatted_products)
            })
            
        except Exception as e:
            print(f"Error getting category products: {e}")
            return jsonify({'error': str(e)}), 500

    def get_brand_products(self, brand_id: int) -> Dict[str, Any]:
        """
        GET /api/brands/{id}/products
        Get products for a specific brand from collection storage (LEGACY - use categories endpoints)
        """
        try:
            # First try to find brand by ID in collection manager
            # Since collection manager uses slugs, we need to find the right brand
            brands_data = self.collection_manager.list_brands()
            target_brand = None
            
            for brand_data in brands_data:
                if self._generate_brand_id(brand_data['slug']) == brand_id:
                    target_brand = brand_data
                    break
            
            if not target_brand:
                return jsonify({'error': 'Brand not found'}), 404
            
            # Get products from collection manager
            brand_products = self.collection_manager.get_brand_products(target_brand['slug'])
            
            # Convert to grouped format for UI with category navigation
            collections_data = {}
            all_products = []
            
            for collection_name, collection_products in brand_products.items():
                formatted_products = []
                for product in collection_products:
                    formatted_product = {
                        'id': int(hashlib.md5(f"{product.get('url', '')}{product.get('name', '')}".encode()).hexdigest()[:8], 16) % 10000,
                        'name': product.get('name', 'Unknown Product'),
                        'url': product.get('url', ''),
                        'image_url': product.get('image_url', ''),
                        'price': product.get('price'),
                        'collection': collection_name,
                        'images': [product.get('image_url', '')] if product.get('image_url') else [],
                        'metadata': {
                            'collection_name': collection_name,
                            'discovered_at': product.get('discovered_at')
                        }
                    }
                    formatted_products.append(formatted_product)
                    all_products.append(formatted_product)
                
                collections_data[collection_name] = {
                    'name': collection_name,
                    'products': formatted_products,
                    'count': len(formatted_products)
                }
            
            # Format brand info to match expected structure
            brand_info = {
                'id': brand_id,
                'name': target_brand['name'],
                'url': target_brand['url'],
                'slug': target_brand['slug'],
                'status': target_brand.get('status', 'active')
            }
            
            return jsonify({
                'brand': brand_info,
                'products': all_products,  # All products for backward compatibility
                'collections': collections_data,  # Grouped by collection for new UI
                'count': len(all_products)
            })
            
        except Exception as e:
            print(f"Error getting brand products: {e}")
            return jsonify({'error': str(e)}), 500
    
    def add_product_favorite(self, product_id: int) -> Dict[str, Any]:
        """
        POST /api/products/{id}/favorite
        Add a product to favorites - Not implemented with new storage system
        """
        try:
            return jsonify({
                'success': False,
                'message': 'Favorites not yet implemented with new storage system'
            })
            
        except Exception as e:
            print(f"Error adding favorite: {e}")
            return jsonify({'error': str(e)}), 500
    
    def get_brand_favorites(self) -> Dict[str, Any]:
        """
        GET /api/brand-favorites
        Get all favorite products from brands - Not implemented with new storage system
        """
        try:
            return jsonify({'favorites': []})
            
        except Exception as e:
            print(f"Error getting favorites: {e}")
            return jsonify({'error': str(e)}), 500
    
    def get_brand_stats(self) -> Dict[str, Any]:
        """
        GET /api/brands/stats  
        Get statistics about brands collection
        """
        try:
            brands_data = self.collection_manager.list_brands()
            
            total_brands = len(brands_data)
            total_products = sum(brand.get('products_count', 0) for brand in brands_data)
            total_collections = sum(brand.get('collections_count', 0) for brand in brands_data)
            
            # Get status breakdown
            active_brands = len([b for b in brands_data if b.get('status', 'active') == 'active'])
            
            # Get last updated date safely
            last_scraped_dates = [b.get('last_scraped') for b in brands_data if b.get('last_scraped')]
            last_updated = max(last_scraped_dates) if last_scraped_dates else '2025-01-01T00:00:00Z'
            
            stats = {
                'total_brands': total_brands,
                'active_brands': active_brands,
                'total_products': total_products,
                'total_collections': total_collections,
                'last_updated': last_updated
            }
            
            return jsonify({'stats': stats})
            
        except Exception as e:
            print(f"Error getting stats: {e}")
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
            
            # Domain check
            domain_result = self._check_blocked_domains(url)
            if not domain_result['allowed']:
                return jsonify({
                    'analysis': {
                        'is_valid': False,
                        'reason': domain_result['reason'],
                        'domain_blocked': True
                    }
                })
            
            # Fetch content
            website_content = self._fetch_website_content(url)
            if not website_content:
                return jsonify({
                    'analysis': {
                        'is_valid': False,
                        'reason': 'Website not accessible',
                        'accessibility_issue': True
                    }
                })
            
            # AI analysis
            analysis = self.llm.analyze_brand_website(url, website_content)
            
            # Scraping capability analysis
            scraping_analysis = analyze_brand_website_scraping(url)
            
            return jsonify({
                'analysis': {
                    'is_valid': analysis.is_valid_brand,
                    'brand_name': analysis.brand_name,
                    'brand_type': analysis.brand_type,
                    'confidence': analysis.confidence,
                    'reason': analysis.reason,
                    'issues': analysis.issues,
                    'scraping': {
                        'is_scrapable': scraping_analysis.is_scrapable,
                        'strategy': scraping_analysis.primary_strategy,
                        'difficulty': scraping_analysis.difficulty,
                        'estimated_products': scraping_analysis.estimated_products,
                        'challenges': scraping_analysis.challenges
                    }
                }
            })
            
        except Exception as e:
            print(f"Error analyzing brand URL: {e}")
            return jsonify({'error': str(e)}), 500
    
    def resolve_brand_name(self) -> Dict[str, Any]:
        """
        POST /api/brands/resolve-name
        Resolve a brand name to its official website URL
        """
        try:
            data = request.get_json()
            brand_name = data.get('brand_name', '').strip()
            
            # Basic validation
            if not brand_name:
                return jsonify({
                    'success': False,
                    'message': 'Brand name is required'
                }), 400
            
            print(f"🔍 Resolving brand name: {brand_name}")
            
            # Use the URL resolver to find the official website
            resolved_url = self.url_resolver.resolve_brand_name_to_url(brand_name)
            
            if resolved_url:
                return jsonify({
                    'success': True,
                    'url': resolved_url,
                    'brand_name': brand_name,
                    'message': f'Found official website for {brand_name}'
                })
            else:
                return jsonify({
                    'success': False,
                    'message': f'Could not find official website for "{brand_name}". Please try entering the URL directly.',
                    'brand_name': brand_name
                })
                
        except Exception as e:
            print(f"Error resolving brand name: {e}")
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': f'Error resolving brand name: {str(e)}'
            }), 500
    
    def serve_cached_image(self, image_path: str):
        """Serve cached brand images from both new and legacy storage"""
        from flask import send_file
        from pathlib import Path
        
        try:
            # Try new brand collections structure first
            collections_path = Path(config.BRAND_COLLECTIONS_DIR) / image_path
            if collections_path.exists() and collections_path.is_file():
                # Security check - ensure path is within brand collections directory
                if str(collections_path.resolve()).startswith(str(Path(config.BRAND_COLLECTIONS_DIR).resolve())):
                    return send_file(collections_path)
            
            # Fall back to legacy cache structure
            legacy_path = Path(image_path)
            
            # Security check - ensure path is within brands cache directory
            if not str(legacy_path).startswith(config.BRANDS_CACHE_DIR):
                print(f"❌ Invalid path - not in allowed directories: {image_path}")
                return jsonify({'error': 'Invalid image path'}), 403
            
            if not legacy_path.exists():
                print(f"❌ Image file not found in either location: {image_path}")
                return jsonify({'error': 'Image not found'}), 404
            
            return send_file(legacy_path)
            
        except Exception as e:
            print(f"Error serving cached image: {e}")
            return jsonify({'error': 'Error serving image'}), 500
    
    def cleanup_cache(self) -> Dict[str, Any]:
        """Clean up old cached images (for app startup)"""
        import shutil
        from pathlib import Path
        
        try:
            cache_root = Path(config.BRANDS_CACHE_DIR)
            if cache_root.exists():
                shutil.rmtree(cache_root)
                print("🧹 Cleaned up image cache")
            
            return jsonify({
                'success': True,
                'message': 'Cache cleaned successfully'
            })
            
        except Exception as e:
            print(f"Error cleaning cache: {e}")
            return jsonify({
                'success': False,
                'message': f'Cache cleanup error: {str(e)}'
            }), 500
    
    def _check_blocked_domains(self, url: str) -> Dict[str, Any]:
        """Check if URL contains blocked domains"""
        blocked_domains = {
            'amazon.com', 'amazon.co.uk', 'amazon.de', 'amazon.fr',
            'ebay.com', 'aliexpress.com', 'wish.com', 'temu.com',
            'walmart.com', 'target.com', 'kohls.com', 'macys.com',
            'nordstrom.com', 'saksfifthavenue.com', 'bergdorfgoodman.com',
            'farfetch.com', 'net-a-porter.com', 'theoutnet.com',
            'ssense.com', 'matchesfashion.com', 'mytheresa.com',
            'zalando.com', 'asos.com', 'boohoo.com', 'shein.com',
            'hm.com', 'zara.com', 'uniqlo.com', 'gap.com'
        }
        
        url_lower = url.lower()
        for domain in blocked_domains:
            if domain in url_lower:
                return {
                    'allowed': False,
                    'reason': f'Blocked domain: {domain} (large retailer/marketplace)'
                }
        
        return {'allowed': True, 'reason': ''}
    
    def _fetch_website_content(self, url: str) -> str:
        """Fetch and clean website content"""
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Remove unwanted elements
            for element in soup(['script', 'style', 'nav', 'footer']):
                element.decompose()
            
            # Get clean text
            text = soup.get_text()
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            clean_text = ' '.join(chunk for chunk in chunks if chunk)
            
            return clean_text[:8000]  # Limit for LLM processing
            
        except Exception as e:
            print(f"Error fetching website content: {e}")
            return ''
    
    def _extract_domain_name(self, url: str) -> str:
        """Extract a clean domain name for brand naming"""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            # Remove www and common prefixes
            domain = domain.replace('www.', '').replace('shop.', '').replace('store.', '')
            # Remove TLD for cleaner name
            domain_parts = domain.split('.')
            if len(domain_parts) > 1:
                return domain_parts[0].title()
            return domain.title()
        except:
            return 'Unknown Brand'
    
    def _setup_brand_cache_folder(self, brand_id: int):
        """Setup brand-specific cache folder for persistent image storage"""
        from pathlib import Path
        
        cache_path = Path(config.BRANDS_CACHE_DIR) / f"brand_{brand_id}"
        cache_path.mkdir(parents=True, exist_ok=True)
        print(f"📁 Setup brand cache folder: {cache_path}")
        return cache_path
    
    def _get_cached_images(self, cache_path):
        """Check if brand already has cached images"""
        from pathlib import Path
        
        if not cache_path.exists():
            return []
        
        # Look for image files in cache
        image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp']
        cached_files = []
        
        for ext in image_extensions:
            cached_files.extend(cache_path.glob(f"*{ext}"))
        
        return cached_files
    
    def _clear_downloads_folder(self):
        """Clear the downloads folder like the test script"""
        import shutil
        from pathlib import Path
        
        downloads_path = Path(config.DOWNLOADS_DIR)
        if downloads_path.exists():
            shutil.rmtree(downloads_path)
        downloads_path.mkdir(exist_ok=True)
        print("🗑️  Cleared and recreated downloads folder")
    
    def _clear_brand_products(self, brand_id: int):
        """Clear existing products for a brand - handled by collection manager"""
        # Products are handled by collection manager now
        print("🗑️  Product clearing handled by collection manager")
    
    def _download_product_images(self, products, cache_path=None) -> List[str]:
        """Download product images to brand cache folder using parallel processing"""
        import asyncio
        import aiohttp
        import aiofiles
        from pathlib import Path
        from PIL import Image
        import time
        
        # Use provided cache path or fallback to downloads
        if cache_path:
            downloads_path = cache_path
        else:
            downloads_path = Path(config.DOWNLOADS_DIR)
            downloads_path.mkdir(exist_ok=True)
        
        # Always try to use parallel download
        try:
            # Check if we're in an async context
            try:
                asyncio.get_running_loop()
                # We're in an async context - run in separate thread with own event loop
                print("🚀 Running parallel download in separate thread...")
                import concurrent.futures
                
                def run_async_download():
                    import asyncio
                    return asyncio.run(self._parallel_download_async(products, downloads_path))
                
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(run_async_download)
                    return future.result()
                    
            except RuntimeError:
                # No running loop - we can use async directly
                print("🚀 Using parallel async download...")
                return asyncio.run(self._parallel_download_async(products, downloads_path))
                
        except Exception as e:
            print(f"⚠️  Parallel download failed ({e}), falling back to synchronous")
            return self._download_product_images_sync(products, cache_path)
    
    async def _parallel_download_async(self, products, downloads_path) -> List[str]:
        """Async parallel image downloading"""
        semaphore = asyncio.Semaphore(5)  # Limit concurrent downloads
        downloaded_images = []
        
        print(f"🚀 Starting parallel download of {len(products)} images...")
        start_time = time.time()
        
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers=self.session.headers
        ) as session:
            tasks = []
            for i, product in enumerate(products, 1):
                if product.image_url:
                    task = self._download_single_image_async(
                        session, semaphore, product, i, downloads_path
                    )
                    tasks.append(task)
            
            # Execute all downloads in parallel - order is preserved
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Preserve exact order - use None for failed downloads
            for i, result in enumerate(results):
                if isinstance(result, str):  # Successful download returns filepath
                    downloaded_images.append(result)
                elif isinstance(result, Exception):
                    downloaded_images.append(None)  # Keep the index aligned
                    print(f"   ❌ Download error for product {i+1}: {result}")
                else:
                    downloaded_images.append(None)  # Keep the index aligned
        
        elapsed = time.time() - start_time
        print(f"📥 Downloaded {len(downloaded_images)} images in {elapsed:.1f}s (parallel)")
        return downloaded_images
    
    async def _download_single_image_async(self, session, semaphore, product, index, downloads_path):
        """Download a single image asynchronously"""
        async with semaphore:  # Limit concurrent downloads
            try:
                print(f"📥 [{index:02d}] Downloading: {product.title[:25]}...")
                
                # Download image
                async with session.get(product.image_url) as response:
                    response.raise_for_status()
                    image_data = await response.read()
                
                # Create filename
                safe_title = "".join(c for c in product.title if c.isalnum() or c in (' ', '-', '_')).rstrip()
                safe_title = safe_title[:30]
                
                # Get file extension
                try:
                    ext = product.image_url.split('.')[-1].lower()
                    if ext not in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
                        ext = 'jpg'
                except:
                    ext = 'jpg'
                
                filename = f"{index:03d}_{safe_title}.{ext}"
                filepath = downloads_path / filename
                
                # Save image asynchronously
                import aiofiles
                async with aiofiles.open(filepath, 'wb') as f:
                    await f.write(image_data)
                
                # Convert image if needed (sync operation)
                await asyncio.get_event_loop().run_in_executor(
                    None, self._process_image_file, filepath, index, safe_title
                )
                
                print(f"   ✅ [{index:02d}] Saved: {filepath.name}")
                return str(filepath)
                
            except Exception as e:
                print(f"   ❌ [{index:02d}] Error downloading {product.image_url}: {e}")
                return None
    
    def _process_image_file(self, filepath, index, safe_title):
        """Process and convert image file (sync operation for thread executor)"""
        try:
            from PIL import Image
            from pathlib import Path
            
            downloads_path = filepath.parent
            
            with Image.open(filepath) as img:
                # Convert to RGB if needed and save as JPG for consistency
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                jpg_filepath = downloads_path / f"{index:03d}_{safe_title}.jpg"
                img.save(jpg_filepath, 'JPEG', quality=95)
                
                if filepath != jpg_filepath:
                    filepath.unlink()  # Remove original if we converted
                    return jpg_filepath
                return filepath
                
        except Exception as img_error:
            print(f"   ⚠️  [{index:02d}] Image processing error: {img_error}")
            if filepath.exists():
                filepath.unlink()
            return None
    
    def _download_product_images_sync(self, products, cache_path=None) -> List[str]:
        """Fallback synchronous image downloading"""
        import time
        from pathlib import Path
        from PIL import Image
        
        # Use provided cache path or fallback to downloads
        if cache_path:
            downloads_path = cache_path
        else:
            downloads_path = Path(config.DOWNLOADS_DIR)
            downloads_path.mkdir(exist_ok=True)
        
        downloaded_images = []
        print(f"📥 Downloading {len(products)} images (synchronous fallback)...")
        
        for i, product in enumerate(products, 1):
            try:
                if not product.image_url:
                    continue
                    
                print(f"📥 [{i:02d}/{len(products)}] {product.title[:25]}...")
                
                # Download image
                response = self.session.get(product.image_url, timeout=10)
                response.raise_for_status()
                
                # Create filename
                safe_title = "".join(c for c in product.title if c.isalnum() or c in (' ', '-', '_')).rstrip()
                safe_title = safe_title[:30]
                
                # Get file extension
                try:
                    ext = product.image_url.split('.')[-1].lower()
                    if ext not in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
                        ext = 'jpg'
                except:
                    ext = 'jpg'
                
                filename = f"{i:03d}_{safe_title}.{ext}"
                filepath = downloads_path / filename
                
                # Save image
                with open(filepath, 'wb') as f:
                    f.write(response.content)
                
                # Process image
                processed_path = self._process_image_file(filepath, i, safe_title)
                if processed_path:
                    downloaded_images.append(str(processed_path))
                    print(f"   ✅ [{i:02d}] Saved: {processed_path.name}")
                
            except Exception as e:
                print(f"   ❌ [{i:02d}] Error downloading {product.image_url}: {e}")
                continue
        
        print(f"📥 Downloaded {len(downloaded_images)} product images to downloads folder")
        return downloaded_images


# Extension function to add these endpoints to existing Flask app
def register_brands_endpoints(app, brands_api=None):
    """Register My Brands endpoints with existing Flask app"""
    if brands_api is None:
        brands_api = BrandsAPI()
    
    # Brand management endpoints
    app.add_url_rule('/api/brands', methods=['POST'], view_func=brands_api.add_brand, endpoint='add_brand')
    app.add_url_rule('/api/brands', methods=['GET'], view_func=brands_api.get_brands, endpoint='get_brands')
    app.add_url_rule('/api/brands/<int:brand_id>', methods=['GET'], view_func=brands_api.get_brand_details, endpoint='get_brand_details')
    app.add_url_rule('/api/brands/<int:brand_id>/discover', methods=['POST'], view_func=brands_api.discover_brand_collections, endpoint='discover_brand_collections')
    app.add_url_rule('/api/brands/<int:brand_id>/scrape', methods=['POST'], view_func=brands_api.scrape_brand_products, endpoint='scrape_brand')
    app.add_url_rule('/api/brands/<int:brand_id>/scrape-stream', methods=['POST'], view_func=brands_api.scrape_brand_products_stream, endpoint='scrape_brand_stream')
    
    # NEW: Clean category-first endpoints for better UX
    app.add_url_rule('/api/brands/<int:brand_id>/categories', methods=['GET'], view_func=brands_api.get_brand_categories, endpoint='get_brand_categories')
    app.add_url_rule('/api/brands/<int:brand_id>/categories/<string:category_name>/products', methods=['GET'], view_func=brands_api.get_category_products, endpoint='get_category_products')
    
    # LEGACY: Keep for backward compatibility
    app.add_url_rule('/api/brands/<int:brand_id>/products', methods=['GET'], view_func=brands_api.get_brand_products, endpoint='get_brand_products')
    
    # Product favorites
    app.add_url_rule('/api/products/<int:product_id>/favorite', methods=['POST'], view_func=brands_api.add_product_favorite, endpoint='add_product_favorite')
    app.add_url_rule('/api/brand-favorites', methods=['GET'], view_func=brands_api.get_brand_favorites, endpoint='get_brand_favorites')
    
    # Stats and analysis
    app.add_url_rule('/api/brands/stats', methods=['GET'], view_func=brands_api.get_brand_stats, endpoint='get_brand_stats')
    app.add_url_rule('/api/brands/analyze', methods=['POST'], view_func=brands_api.analyze_brand_url, endpoint='analyze_brand')
    app.add_url_rule('/api/brands/resolve-name', methods=['POST'], view_func=brands_api.resolve_brand_name, endpoint='resolve_brand_name')
    
    # Image serving and cache management  
    def serve_image_route(image_path):
        return brands_api.serve_cached_image(image_path)
    
    app.add_url_rule('/api/brands/image/<path:image_path>', methods=['GET'], view_func=serve_image_route, endpoint='serve_cached_image')
    app.add_url_rule('/api/brands/cleanup-cache', methods=['POST'], view_func=brands_api.cleanup_cache, endpoint='cleanup_cache')