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

# Add parent directory to path for config import
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import config

from .brands_db import brands_db
from .llm_client import create_my_brands_llm
from .scraping.scraping_detector import analyze_brand_website_scraping
from .scraping.scraping_strategies import get_scraping_strategy
from .brand_url_resolver import BrandURLResolver


class BrandsAPI:
    """API endpoints for My Brands feature"""
    
    def __init__(self):
        self.llm = create_my_brands_llm()
        self.url_resolver = BrandURLResolver()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
    
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
            
            # Check if brand already exists
            existing_brands = brands_db.get_all_brands()
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
            
            # Add brand to database
            brand_id = brands_db.add_brand(
                name=analysis.brand_name or self._extract_domain_name(url),
                url=url,
                description=f"Independent fashion brand - {analysis.brand_type}"
            )
            
            # Update validation status
            brands_db.update_brand_validation(
                brand_id=brand_id,
                status='approved',
                reason=analysis.reason
            )
            
            # Store scraping configuration
            scraping_config = {
                'strategy': analysis.scraping_strategy,
                'confidence': analysis.scraping_confidence,
                'is_scrapable': analysis.is_scrapable,
                'detected_by': 'ai_analysis'
            }
            
            brands_db.update_brand_scraping_config(
                brand_id=brand_id,
                strategy=analysis.scraping_strategy,
                config=scraping_config
            )
            
            return jsonify({
                'success': True,
                'message': f'Successfully added {analysis.brand_name}!',
                'brand': {
                    'id': brand_id,
                    'name': analysis.brand_name,
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
        Get all brands in the collection
        """
        try:
            brands = brands_db.get_all_brands()
            
            # Add additional stats for each brand
            for brand in brands:
                products = brands_db.get_brand_products(brand['id'])
                brand['product_count'] = len(products)
                
                # Parse scraping config if available
                if brand.get('scraping_config'):
                    try:
                        brand['scraping_config'] = json.loads(brand['scraping_config'])
                    except:
                        brand['scraping_config'] = {}
            
            return jsonify({'brands': brands})
            
        except Exception as e:
            print(f"Error getting brands: {e}")
            return jsonify({'error': str(e)}), 500
    
    def get_brand_details(self, brand_id: int) -> Dict[str, Any]:
        """
        GET /api/brands/{id}
        Get detailed information about a specific brand
        """
        try:
            brand = brands_db.get_brand_by_id(brand_id)
            if not brand:
                return jsonify({'error': 'Brand not found'}), 404
            
            # Get products for this brand
            products = brands_db.get_brand_products(brand_id)
            
            # Parse scraping config
            scraping_config = {}
            if brand.get('scraping_config'):
                try:
                    scraping_config = json.loads(brand['scraping_config'])
                except:
                    pass
            
            return jsonify({
                'brand': brand,
                'products': products,
                'scraping_config': scraping_config,
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
            brand = brands_db.get_brand_by_id(brand_id)
            if not brand:
                return jsonify({'error': 'Brand not found'}), 404
            
            # Get scraping strategy
            strategy = get_scraping_strategy(brand.get('scraping_strategy', 'homepage-all-products'))
            
            # Parse scraping config
            scraping_config = {}
            if brand.get('scraping_config'):
                try:
                    scraping_config = json.loads(brand['scraping_config'])
                except:
                    pass
            
            # Perform navigation discovery
            result = strategy.scrape(brand['url'], scraping_config)
            
            # Check if we got collections or products
            collections = []
            if result.success and result.products:
                for item in result.products:
                    if item.detection_method == "navigation_discovery":
                        collections.append({
                            'name': item.title.replace('Collection: ', ''),
                            'url': item.product_url,
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
                # This is a direct product page, not a navigation page
                return {
                    'success': True,
                    'type': 'products',
                    'product_count': result.total_found if result.success else 0,
                    'message': 'Direct product page - no collections found'
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
        Stream products scraping with real-time progress updates
        """
        from flask import Response
        import json
        import time
        
        # Parse request data OUTSIDE the generator to avoid context issues
        try:
            data = request.get_json() or {}
            collection_url = data.get('collection_url')
        except:
            collection_url = None
        
        def generate_scraping_stream():
            try:
                brand = brands_db.get_brand_by_id(brand_id)
                if not brand:
                    yield f"data: {json.dumps({'error': 'Brand not found'})}\n\n"
                    return

                if not brand.get('scraping_strategy'):
                    yield f"data: {json.dumps({'error': 'No scraping strategy configured'})}\n\n"
                    return

                # Setup and initial status
                yield f"data: {json.dumps({'status': 'starting', 'message': 'Setting up scraping...'})}\n\n"
                
                brand_cache_path = self._setup_brand_cache_folder(brand_id)
                cached_images = self._get_cached_images(brand_cache_path)
                
                if cached_images:
                    yield f"data: {json.dumps({'status': 'cache_found', 'cached_images': len(cached_images)})}\n\n"
                    self._clear_brand_products(brand_id)
                else:
                    yield f"data: {json.dumps({'status': 'fresh_scrape', 'message': 'No cache found, downloading fresh images'})}\n\n"
                    self._clear_brand_products(brand_id)

                # Use new LLM scraper
                scrape_url = collection_url if collection_url else brand['url']
                yield f"data: {json.dumps({'status': 'scraping_started', 'url': scrape_url})}\n\n"
                
                # Import and run SIMPLE LLM scraper
                import asyncio
                from .scraping.llm_scraper.simple_scraper import SimpleLLMScraper
                
                async def run_simple_scraping():
                    scraper = SimpleLLMScraper()
                    result = await scraper.scrape(scrape_url)
                    return result
                
                yield f"data: {json.dumps({'status': 'analyzing', 'message': 'AI analyzing website structure (SIMPLE method)...'})}\n\n"
                scraping_result = asyncio.run(run_simple_scraping())
                
                if not scraping_result.success:
                    yield f"data: {json.dumps({'status': 'error', 'error': f'Scraping failed: {scraping_result.errors}'})}\n\n"
                    return
                
                unique_products = scraping_result.products
                yield f"data: {json.dumps({'status': 'found_products', 'count': len(unique_products)})}\n\n"
                
                # Simple scraper with streaming downloads already downloaded images in parallel!
                if cached_images:
                    yield f"data: {json.dumps({'status': 'using_cache', 'message': f'Using {len(cached_images)} cached images'})}\n\n"
                    downloaded_images = [str(img) for img in cached_images]
                else:
                    # Extract download paths from simple scraper results (products already downloaded by streaming workers)
                    downloaded_images = []
                    for product in unique_products:
                        if hasattr(product, 'download_path') and product.download_path:
                            downloaded_images.append(product.download_path)
                        else:
                            downloaded_images.append(None)  # Keep alignment
                    
                    downloaded_count = sum(1 for img in downloaded_images if img is not None)
                    yield f"data: {json.dumps({'status': 'streaming_downloads_complete', 'message': f'Streaming workers downloaded {downloaded_count}/{len(unique_products)} images during scraping'})}\n\n"
                
                # Store products in database with cached image paths
                yield f"data: {json.dumps({'status': 'storing', 'message': f'Storing {len(unique_products)} products in database...'})}\n\n"
                from pathlib import Path
                stored_products = []
                for i, product in enumerate(unique_products):
                    if i % 10 == 0 and i > 0:
                        yield f"data: {json.dumps({'status': 'storing_progress', 'message': f'Stored {i}/{len(unique_products)} products'})}\n\n"
                    try:
                        # Use cached image path if available, otherwise use original URL
                        cached_image_path = None
                        image_url = product.image_url  # Default to original URL
                        
                        if cached_images and i < len(cached_images):
                            cached_image_path = str(cached_images[i])
                            # Convert absolute path to relative path for API endpoint
                            relative_path = cached_image_path.replace(str(Path.cwd()) + "/", "")
                            image_url = config.get_image_url(relative_path)
                        elif downloaded_images and i < len(downloaded_images) and downloaded_images[i]:
                            cached_image_path = downloaded_images[i]
                            # Convert absolute path to relative path for API endpoint  
                            relative_path = cached_image_path.replace(str(Path.cwd()) + "/", "")
                            image_url = config.get_image_url(relative_path)
                        else:
                            # Use original image URL if no downloaded/cached version
                            image_url = product.image_url
                            if image_url and image_url.startswith('//'):
                                image_url = 'https:' + image_url
                        
                        # Store in database
                        product_id = brands_db.add_product(
                            brand_id=brand_id,
                            name=product.title,
                            url=product.product_url or '',
                            price='',  # Could extract from product if available
                            currency='',
                            category=product.collection_name or 'Default',
                            description=f'Scraped via {product.detection_method}',
                            images=[image_url] if image_url else [],
                            metadata={
                                'confidence': product.confidence,
                                'detection_method': product.detection_method,
                                'collection_name': product.collection_name,
                                'collection_url': product.collection_url,
                                'cached_image_path': cached_image_path,
                                'original_image_url': product.image_url,
                                'extraction_order': i  # ✅ Explicit ordering field
                            }
                        )
                        
                        stored_products.append({
                            'id': product_id,
                            'title': product.title,
                            'image_url': image_url,
                            'collection_name': product.collection_name or 'Default'
                        })
                        
                    except Exception as e:
                        print(f"Error storing product {product.title}: {e}")
                        continue
                
                yield f"data: {json.dumps({'status': 'grouping', 'message': f'Grouping {len(stored_products)} products by collections...'})}\n\n"
                
                # Group by collections for final result
                collections = {}
                for product in stored_products:
                    collection_name = product['collection_name']
                    if collection_name not in collections:
                        collections[collection_name] = []
                    collections[collection_name].append(product)
                
                yield f"data: {json.dumps({'status': 'finalizing', 'message': f'Found {len(collections)} collections'})}\n\n"
                
                # Final streaming result
                yield f"data: {json.dumps({'status': 'completed', 'collections': collections, 'total_products': len(stored_products)})}\n\n"
                
            except Exception as e:
                yield f"data: {json.dumps({'status': 'error', 'error': str(e)})}\n\n"

        return Response(generate_scraping_stream(), mimetype='text/event-stream')

    def scrape_brand_products(self, brand_id: int) -> Dict[str, Any]:
        """
        POST /api/brands/{id}/scrape
        Scrape products for a specific brand and download images
        """
        try:
            brand = brands_db.get_brand_by_id(brand_id)
            if not brand:
                return jsonify({'error': 'Brand not found'}), 404
            
            if not brand.get('scraping_strategy'):
                return jsonify({
                    'success': False,
                    'message': 'No scraping strategy configured for this brand'
                })
            
            # Setup brand-specific cache folder for persistent storage
            brand_cache_path = self._setup_brand_cache_folder(brand_id)
            
            # Check if we already have cached images for this brand
            cached_images = self._get_cached_images(brand_cache_path)
            if cached_images:
                print(f"📋 Found {len(cached_images)} cached images for brand {brand_id}")
                # Still clear products to refresh metadata, but keep images
                self._clear_brand_products(brand_id)
            else:
                print(f"🔄 No cached images found, will download fresh images")
                # Clear existing products for this brand to avoid accumulation
                self._clear_brand_products(brand_id)
            
            # Use new LLM scraper
            # Check if collection_url is provided in request body
            data = request.get_json() or {}
            collection_url = data.get('collection_url')
            
            # Determine URL to scrape
            scrape_url = collection_url if collection_url else brand['url']
            print(f"🎯 Scraping URL: {scrape_url}")
            
            # Import and run LLM scraper
            import asyncio
            from .scraping.llm_scraper.scraper import LLMScraper
            
            async def run_llm_scraping():
                scraper = LLMScraper()
                result = await scraper.scrape(scrape_url)
                return result
            
            print("🤖 Starting AI-powered scraping...")
            scraping_result = asyncio.run(run_llm_scraping())
            
            if not scraping_result.success:
                return jsonify({
                    'success': False,
                    'message': f'Scraping failed: {scraping_result.errors}'
                })
            
            unique_products = scraping_result.products
            print(f"✅ Found {len(unique_products)} products")
            
            # Handle image storage (streaming downloads already completed during scraping)
            if cached_images:
                print(f"♻️  Using {len(cached_images)} cached images (no download needed)")
                downloaded_images = [str(img) for img in cached_images]
            else:
                # Extract download paths from simple scraper results (already downloaded by streaming workers)
                downloaded_images = []
                for product in unique_products:
                    if hasattr(product, 'download_path') and product.download_path:
                        downloaded_images.append(product.download_path)
                    else:
                        downloaded_images.append(None)  # Keep alignment
                
                downloaded_count = sum(1 for img in downloaded_images if img is not None)
                print(f"✅ Streaming workers downloaded {downloaded_count}/{len(unique_products)} images during scraping")
            
            # Store products in database with cached image paths
            from pathlib import Path
            stored_products = []
            for i, product in enumerate(unique_products):
                try:
                    # Use cached image path if available, otherwise use original URL
                    cached_image_path = None
                    image_url = product.image_url  # Default to original URL
                    
                    if cached_images and i < len(cached_images):
                        cached_image_path = str(cached_images[i])
                        # Convert absolute path to relative path for API endpoint
                        relative_path = cached_image_path.replace(str(Path.cwd()) + "/", "")
                        image_url = config.get_image_url(relative_path)
                    elif downloaded_images and i < len(downloaded_images):
                        cached_image_path = downloaded_images[i]
                        # Convert absolute path to relative path for API endpoint  
                        relative_path = cached_image_path.replace(str(Path.cwd()) + "/", "")
                        image_url = config.get_image_url(relative_path)
                    else:
                        # Use original image URL if no downloaded/cached version
                        image_url = product.image_url
                        if image_url and image_url.startswith('//'):
                            image_url = 'https:' + image_url
                    
                    # Store in database
                    product_id = brands_db.add_product(
                        brand_id=brand_id,
                        name=product.title,
                        url=product.product_url or '',
                        price='',  # Could extract from product if available
                        currency='',
                        category=product.collection_name or 'Default',
                        description=f'Scraped via {product.detection_method}',
                        images=[image_url] if image_url else [],
                        metadata={
                            'confidence': product.confidence,
                            'detection_method': product.detection_method,
                            'collection_name': product.collection_name,
                            'collection_url': product.collection_url,
                            'cached_image_path': cached_image_path,
                            'original_image_url': product.image_url
                        }
                    )
                    
                    stored_products.append({
                        'id': product_id,
                        'title': product.title,
                        'image_url': image_url,  # Use the processed image URL (cached or original)
                        'product_url': product.product_url,
                        'confidence': product.confidence,
                        'collection_name': product.collection_name or 'Default',
                        'collection_url': product.collection_url
                    })
                    
                except Exception as product_error:
                    print(f"Error storing product: {product_error}")
                    continue
            
            # Update last scraped timestamp
            brands_db._update_last_scraped(brand_id)
            
            # Group products by collection for UI display
            collections_summary = {}
            ungrouped_products = []
            
            for product in stored_products:
                collection_name = product.get('collection_name')
                if collection_name:
                    if collection_name not in collections_summary:
                        collections_summary[collection_name] = {
                            'name': collection_name,
                            'product_count': 0,
                            'url': product.get('collection_url'),
                            'products': []
                        }
                    collections_summary[collection_name]['products'].append(product)
                    collections_summary[collection_name]['product_count'] += 1
                else:
                    ungrouped_products.append(product)
            
            # Convert to list for easier UI handling
            collections_list = list(collections_summary.values())
            
            return jsonify({
                'success': True,
                'message': f'Successfully scraped {len(stored_products)} products from {len(collections_list)} collections',
                'products': stored_products,
                'collections': collections_list,  # Organized by collection
                'ungrouped_products': ungrouped_products,  # Products not in a collection
                'strategy_used': scraping_result.strategy_used,
                'total_found': scraping_result.total_found,
                'confidence': scraping_result.confidence,
                'images_downloaded': len(downloaded_images),
                'collections_count': len(collections_list),
                'has_collections': len(collections_list) > 0
            })
            
        except Exception as e:
            print(f"Error scraping brand: {e}")
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': f'Scraping error: {str(e)}'
            }), 500
    
    def get_brand_products(self, brand_id: int) -> Dict[str, Any]:
        """
        GET /api/brands/{id}/products
        Get products for a specific brand
        """
        try:
            brand = brands_db.get_brand_by_id(brand_id)
            if not brand:
                return jsonify({'error': 'Brand not found'}), 404
            
            products = brands_db.get_brand_products(brand_id)
            
            # Parse JSON fields
            for product in products:
                if product.get('images'):
                    try:
                        product['images'] = json.loads(product['images'])
                    except:
                        product['images'] = []
                
                if product.get('metadata'):
                    try:
                        product['metadata'] = json.loads(product['metadata'])
                    except:
                        product['metadata'] = {}
            
            return jsonify({
                'brand': brand,
                'products': products,
                'count': len(products)
            })
            
        except Exception as e:
            print(f"Error getting brand products: {e}")
            return jsonify({'error': str(e)}), 500
    
    def add_product_favorite(self, product_id: int) -> Dict[str, Any]:
        """
        POST /api/products/{id}/favorite
        Add a product to favorites
        """
        try:
            data = request.get_json()
            notes = data.get('notes', '')
            
            favorite_id = brands_db.add_favorite_product(product_id, notes)
            
            return jsonify({
                'success': True,
                'message': 'Added to favorites',
                'favorite_id': favorite_id
            })
            
        except Exception as e:
            print(f"Error adding favorite: {e}")
            return jsonify({'error': str(e)}), 500
    
    def get_brand_favorites(self) -> Dict[str, Any]:
        """
        GET /api/brand-favorites
        Get all favorite products from brands
        """
        try:
            favorites = brands_db.get_favorite_products()
            
            # Parse JSON fields
            for favorite in favorites:
                if favorite.get('images'):
                    try:
                        favorite['images'] = json.loads(favorite['images'])
                    except:
                        favorite['images'] = []
            
            return jsonify({'favorites': favorites})
            
        except Exception as e:
            print(f"Error getting favorites: {e}")
            return jsonify({'error': str(e)}), 500
    
    def get_brand_stats(self) -> Dict[str, Any]:
        """
        GET /api/brands/stats  
        Get statistics about brands collection
        """
        try:
            stats = brands_db.get_stats()
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
        """Serve cached brand images"""
        from flask import send_file
        from pathlib import Path
        
        try:
            
            # Build full path from current working directory
            full_path = Path(image_path)
            
            # Security check - ensure path is within brands cache directory
            if not str(full_path).startswith(config.BRANDS_CACHE_DIR):
                print(f"❌ Invalid path - not in my_brands_cache: {image_path}")
                return jsonify({'error': 'Invalid image path'}), 403
            
            if not full_path.exists():
                print(f"❌ Image file not found: {full_path}")
                return jsonify({'error': 'Image not found'}), 404
            
            return send_file(full_path)
            
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
        """Clear existing products for a brand to avoid accumulation"""
        try:
            existing_products = brands_db.get_brand_products(brand_id)
            if existing_products:
                print(f"🗑️  Clearing {len(existing_products)} existing products for brand")
                brands_db._clear_brand_products(brand_id)
        except Exception as e:
            print(f"Warning: Could not clear existing products: {e}")
    
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