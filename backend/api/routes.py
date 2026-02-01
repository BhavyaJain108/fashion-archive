"""
Unified Premium Scraper API
===========================

Comprehensive API endpoints for brand scraping, product queries, and more.
Uses the unified storage layer for all data operations.
"""

from flask import jsonify, request, send_file, Response
from typing import Dict, Any, Tuple
import os
import sys
import json
import queue
import threading
import time
from urllib.parse import unquote
from datetime import datetime

# Import storage
from backend.storage import get_storage

# Get storage instance
storage = get_storage()


# =============================================================================
# BRANDS API
# =============================================================================

def get_brands():
    """GET /api/brands - List all brands"""
    try:
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))
        sort_by = request.args.get('sort_by', 'name')
        order = request.args.get('order', 'asc')

        brands, total = storage.list_brands(limit, offset, sort_by, order)

        return jsonify({
            "brands": brands,
            "pagination": {
                "total": total,
                "limit": limit,
                "offset": offset,
                "has_more": offset + limit < total
            }
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def get_brand(brand_id):
    """GET /api/brands/{brand_id} - Get brand details"""
    try:
        brand = storage.get_brand(brand_id)

        if not brand:
            return jsonify({"error": "Brand not found"}), 404

        return jsonify(brand)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def normalize_url(url: str) -> tuple[str, str]:
    """
    Normalize a URL and extract domain for brand identification.

    Returns:
        tuple: (normalized_url, domain)
    """
    from urllib.parse import urlparse, urlunparse

    # Add https if no scheme
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    parsed = urlparse(url)

    # Remove www. prefix for consistency
    domain = parsed.netloc.replace('www.', '')

    # Reconstruct normalized URL
    normalized = urlunparse((
        'https',  # Always use https
        domain,
        parsed.path or '/',
        parsed.params,
        parsed.query,
        parsed.fragment
    ))

    return normalized, domain


def validate_brand():
    """POST /api/brands/validate - Validate brand URL before creation"""
    try:
        data = request.get_json()
        homepage_url = data.get('homepage_url', '').strip()

        if not homepage_url:
            return jsonify({"error": "homepage_url is required"}), 400

        # Normalize the URL
        normalized_url, domain = normalize_url(homepage_url)

        # Check if brand already exists by domain
        brand_id = domain.replace('.', '_')
        existing_brand = storage.get_brand(brand_id)

        if existing_brand:
            return jsonify({
                "success": True,
                "exists": True,
                "brand_id": brand_id,
                "brand": existing_brand,
                "message": f"Brand already exists: {existing_brand.get('name', brand_id)}"
            })

        # Perform LLM validation
        try:
            from backend.scraper.brand import Brand
            from backend.scraper.prompts.brand_validation import get_brand_validation_prompt

            # Create brand instance to access LLM handler
            temp_brand = Brand(normalized_url)

            # Get page title and sample content for better validation
            # (In a real implementation, you might want to fetch the page)
            validation_data = get_brand_validation_prompt(
                url=normalized_url,
                page_title="",
                page_content_sample=""
            )

            # Call LLM for validation
            llm_response = temp_brand.llm_handler.call(
                validation_data['prompt'],
                expected_format="json",
                response_model=validation_data['model']
            )

            if not llm_response.get("success"):
                return jsonify({
                    "success": False,
                    "error": "Brand validation failed",
                    "message": "Could not validate the brand URL"
                }), 400

            validation_result = llm_response.get("data", {})

            if not validation_result.get("valid"):
                return jsonify({
                    "success": False,
                    "valid": False,
                    "reasoning": validation_result.get("reasoning", "Brand validation failed"),
                    "message": validation_result.get("reasoning", "This does not appear to be a legitimate clothing/apparel brand")
                }), 400

            # Validation successful
            return jsonify({
                "success": True,
                "valid": True,
                "exists": False,
                "brand_name": validation_result.get("brand_name", ""),
                "domain": domain,
                "normalized_url": normalized_url,
                "confidence": validation_result.get("confidence", "medium"),
                "message": "Brand validated successfully"
            })

        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({
                "success": False,
                "error": f"Validation error: {str(e)}"
            }), 500

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def create_brand():
    """POST /api/brands - Add new brand (with optional validation)"""
    try:
        data = request.get_json()

        name = data.get('name', '').strip()
        homepage_url = data.get('homepage_url', '').strip()
        skip_validation = data.get('skip_validation', False)

        if not homepage_url:
            return jsonify({"error": "homepage_url is required"}), 400

        # Normalize URL and extract domain
        normalized_url, domain = normalize_url(homepage_url)

        # Generate brand_id from domain — use full domain with dots replaced by underscores
        # e.g. devi-clothing.com -> devi-clothing_com (matches extraction folder name)
        brand_id = domain.replace('.', '_')

        # Check if brand already exists
        existing_brand = storage.get_brand(brand_id)
        if existing_brand:
            return jsonify({
                "success": False,
                "error": "Brand already exists",
                "brand_id": brand_id,
                "brand": existing_brand
            }), 409

        # Use provided name or extract from validation
        brand_name = name
        if not brand_name and not skip_validation:
            # Run validation to get brand name
            try:
                from backend.scraper.brand import Brand
                from backend.scraper.prompts.brand_validation import get_brand_validation_prompt

                temp_brand = Brand(normalized_url)
                validation_data = get_brand_validation_prompt(url=normalized_url)
                llm_response = temp_brand.llm_handler.call(
                    validation_data['prompt'],
                    expected_format="json",
                    response_model=validation_data['model']
                )

                if llm_response.get("success"):
                    validation_result = llm_response.get("data", {})
                    brand_name = validation_result.get("brand_name", brand_id.replace('_', ' ').title())
            except:
                brand_name = brand_id.replace('_', ' ').title()
        elif not brand_name:
            brand_name = brand_id.replace('_', ' ').title()

        # Create brand data (without favicon initially)
        brand_data = {
            "brand_id": brand_id,
            "name": brand_name,
            "homepage_url": normalized_url,
            "domain": domain,
            "favicon_path": None,  # Will be updated after brand creation
            "status": {
                "last_scrape_run_id": None,
                "last_scrape_at": None,
                "last_scrape_status": None,
                "total_products": 0,
                "total_categories": 0
            },
            "metadata": {
                "added_at": datetime.utcnow().isoformat() + "Z",
                "total_scrape_runs": 0,
                "scraper_version": "1.0"
            },
            "data_path": f"extractions/{domain.replace('.', '_')}"
        }

        # Create brand first (this creates the directory structure)
        success = storage.create_brand(brand_id, brand_data)

        if not success:
            return jsonify({"error": "Failed to create brand"}), 500

        # Now download favicon (directory already exists from create_brand)
        try:
            from backend.scraper.favicon_downloader import FaviconDownloader
            print(f"📥 Downloading favicon for {brand_name}...")
            favicon_path = FaviconDownloader.download_favicon(normalized_url, brand_id)

            if favicon_path:
                # Update brand data with favicon path
                brand_data["favicon_path"] = favicon_path
                storage.update_brand(brand_id, brand_data)
        except Exception as e:
            print(f"⚠️  Favicon download failed: {e}")

        return jsonify({
            "success": True,
            "brand_id": brand_id,
            "brand": brand_data,
            "message": "Brand created successfully"
        }), 201

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


def update_brand(brand_id):
    """PUT /api/brands/{brand_id} - Update brand"""
    try:
        brand = storage.get_brand(brand_id)
        if not brand:
            return jsonify({"error": "Brand not found"}), 404

        data = request.get_json()

        # Update fields
        if 'name' in data:
            brand['name'] = data['name']
        if 'homepage_url' in data:
            brand['homepage_url'] = data['homepage_url']

        storage.update_brand(brand_id, brand)

        return jsonify({
            "success": True,
            "message": "Brand updated successfully"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def delete_brand(brand_id):
    """DELETE /api/brands/{brand_id} - Delete brand"""
    try:
        success = storage.delete_brand(brand_id)

        if not success:
            return jsonify({"error": "Brand not found"}), 404

        return jsonify({
            "success": True,
            "message": "Brand and all associated data deleted"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# PRODUCTS API
# =============================================================================

def get_products():
    """GET /api/products - Query products with filters"""
    try:
        filters = {}
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))

        # Basic filters
        if request.args.get('brand_id'):
            filters['brand_id'] = request.args.get('brand_id')

        if request.args.get('search'):
            filters['search'] = request.args.get('search')

        # Classification filters
        if request.args.get('classification_url'):
            filters['classification_url'] = request.args.get('classification_url')

        if request.args.get('classification_type'):
            filters['classification_type'] = request.args.get('classification_type')

        if request.args.get('classification_name'):
            filters['classification_name'] = request.args.get('classification_name')

        # Attribute filters (attribute.key=value)
        for key in request.args:
            if key.startswith('attribute.'):
                attr_key = key.replace('attribute.', '')
                filters[f'attribute_{attr_key}'] = request.args.get(key)

        # Query products
        products, total = storage.query_products(filters, limit, offset)

        return jsonify({
            "products": products,
            "pagination": {
                "total": total,
                "limit": limit,
                "offset": offset,
                "has_more": offset + limit < total
            },
            "applied_filters": filters
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def get_product(product_url_encoded):
    """GET /api/products/{product_url} - Get single product"""
    try:
        product_url = unquote(product_url_encoded)
        product = storage.get_product(product_url)

        if not product:
            return jsonify({"error": "Product not found"}), 404

        return jsonify(product)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def aggregate_products():
    """GET /api/products/aggregate - Aggregate products"""
    try:
        brand_id = request.args.get('brand_id')
        group_by = request.args.get('group_by')

        if not brand_id or not group_by:
            return jsonify({"error": "brand_id and group_by are required"}), 400

        groups = storage.aggregate_products(brand_id, group_by)

        return jsonify({
            "groups": groups,
            "total_groups": len(groups),
            "total_products": sum(g['count'] for g in groups)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def get_product_counts():
    """GET /api/products/counts - Get product counts by classification URL for a brand"""
    try:
        brand_id = request.args.get('brand_id')

        if not brand_id:
            return jsonify({"error": "brand_id is required"}), 400

        counts = storage.get_product_counts_by_url(brand_id)

        return jsonify({
            "brand_id": brand_id,
            "counts": counts,
            "total_categories": len(counts)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def search_products():
    """GET /api/products/search - Full-text search"""
    try:
        query = request.args.get('q', '').strip()
        brand_id = request.args.get('brand_id')
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))

        if not query:
            return jsonify({"error": "Search query 'q' is required"}), 400

        filters = {'search': query}
        if brand_id:
            filters['brand_id'] = brand_id

        products, total = storage.query_products(filters, limit, offset)

        return jsonify({
            "query": query,
            "products": products,
            "pagination": {
                "total": total,
                "limit": limit,
                "offset": offset,
                "has_more": offset + limit < total
            },
            "total_results": total
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# CLASSIFICATIONS API
# =============================================================================

def get_classifications(brand_id):
    """GET /api/brands/{brand_id}/classifications - Get all classifications"""
    try:
        classification_type = request.args.get('type')

        classifications = storage.get_all_classifications(brand_id)

        if not classifications:
            return jsonify({"error": "Brand not found or no products"}), 404

        # Filter by type if requested
        if classification_type:
            classifications = {
                classification_type: classifications.get(classification_type, [])
            }

        return jsonify({
            "brand_id": brand_id,
            "classifications": classifications,
            "total_classifications": sum(len(v) for v in classifications.values())
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _prune_empty_leaves(tree, product_urls):
    """Remove leaf nodes that have no products (URL not in product_urls) and
    are not parent categories with children that have products."""
    if not tree:
        return []

    pruned = []
    for node in tree:
        children = node.get("children", [])
        if children:
            # Recurse into children first
            node["children"] = _prune_empty_leaves(children, product_urls)
            # Keep parent if it still has children after pruning
            if node["children"]:
                pruned.append(node)
        else:
            # Leaf node — keep only if it has products
            url = node.get("url")
            if url and url in product_urls:
                pruned.append(node)

    return pruned


def _collapse_single_child_nodes(tree):
    """Collapse nodes that are the sole child of their parent.

    E.g. Brand → Shop → [Tops, Bottoms] becomes Brand → [Tops, Bottoms]
    when Shop either has no URL or is a pass-through.
    """
    if not tree:
        return tree

    # If there's exactly one node and it has children, promote the children
    while (len(tree) == 1 and tree[0].get("children")):
        tree = tree[0]["children"]

    # Recurse into each node's children
    for node in tree:
        if node.get("children"):
            node["children"] = _collapse_single_child_nodes(node["children"])

    return tree


def get_category_hierarchy(brand_id):
    """GET /api/brands/{brand_id}/categories/hierarchy - Get category tree"""
    try:
        navigation = storage.get_navigation(brand_id)

        if not navigation:
            return jsonify({"error": "Brand not found or no navigation data"}), 404

        hierarchy = navigation.get("category_tree", [])

        # Get product counts so we can prune empty categories
        product_counts = storage.get_product_counts_by_url(brand_id)

        # 1. Prune leaves with zero products
        hierarchy = _prune_empty_leaves(hierarchy, set(product_counts.keys()))

        # 2. Collapse single-child wrapper nodes
        hierarchy = _collapse_single_child_nodes(hierarchy)

        return jsonify({
            "brand_id": brand_id,
            "hierarchy": hierarchy
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# ATTRIBUTES API
# =============================================================================

def get_attributes(brand_id):
    """GET /api/brands/{brand_id}/attributes - Discover attributes"""
    try:
        attributes = storage.get_all_attributes(brand_id)

        if not attributes:
            return jsonify({"error": "Brand not found or no products"}), 404

        return jsonify({
            "brand_id": brand_id,
            "attributes": attributes,
            "total_attributes": len(attributes)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def get_attribute_values(brand_id, attribute_key):
    """GET /api/brands/{brand_id}/attributes/{key}/values - Get attribute values"""
    try:
        attributes = storage.get_all_attributes(brand_id)

        if not attributes or attribute_key not in attributes:
            return jsonify({"error": "Attribute not found"}), 404

        attr_data = attributes[attribute_key]

        # Build values with counts
        # (This is simplified - would need to actually count)
        values = [
            {"value": v, "product_count": 0}  # TODO: Count products
            for v in attr_data.get("unique_values", [])
        ]

        return jsonify({
            "attribute_key": attribute_key,
            "values": values,
            "total_values": len(values),
            "total_products_with_attribute": attr_data.get("products_with_attribute", 0)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# SCRAPING API
# =============================================================================

# Global job tracker
scraping_jobs = {}
job_lock = threading.Lock()

# Shared product stream queues: brand_id -> list of Queue objects (one per SSE listener)
product_stream_listeners: Dict[str, list] = {}
product_stream_lock = threading.Lock()


def start_scrape(brand_id):
    """POST /api/brands/{brand_id}/scrape - Start scraping job

    Query params:
        mode: 'full' (default) - re-scrape nav + products
              'products_only' - skip nav, re-extract products from existing urls.json
    """
    try:
        brand = storage.get_brand(brand_id)
        if not brand:
            return jsonify({"error": "Brand not found"}), 404

        mode = request.args.get('mode', 'full')

        # Create job ID
        job_id = f"scrape_{int(time.time() * 1000)}"

        # Store job status
        with job_lock:
            scraping_jobs[job_id] = {
                "job_id": job_id,
                "brand_id": brand_id,
                "status": "running",
                "progress": 0,
                "start_time": datetime.utcnow().isoformat() + "Z",
                "current_action": "Initializing..."
            }

        # Start scrape in background thread
        def run_scrape():
            try:
                from backend.stages.navigation import extract_navigation
                from backend.stages.storage import get_domain, load_navigation
                from backend.stages.streaming import StreamingOrchestrator

                homepage_url = brand['homepage_url']
                domain = get_domain(homepage_url).replace('.', '_')

                if mode == 'products_only':
                    # Skip navigation, use existing nav tree
                    nav_tree = load_navigation(domain)
                    if not nav_tree:
                        raise Exception("No existing navigation tree found — run a full scrape first")

                    with job_lock:
                        scraping_jobs[job_id]["current_action"] = "Re-extracting products from existing URLs..."
                        scraping_jobs[job_id]["progress"] = 30

                    # Notify frontend nav is already ready
                    broadcast_event(brand_id, "nav_ready")
                else:
                    # Stage 1: Navigation
                    with job_lock:
                        scraping_jobs[job_id]["current_action"] = "Stage 1: Extracting navigation..."
                        scraping_jobs[job_id]["progress"] = 10

                    nav_result = extract_navigation(homepage_url)
                    if not nav_result:
                        raise Exception("Navigation extraction failed")

                    nav_tree = load_navigation(domain)
                    if not nav_tree:
                        raise Exception("Failed to load navigation tree")

                    # Notify frontend that navigation is ready
                    broadcast_event(brand_id, "nav_ready")

                # Stages 2+3: Streaming URL + Product extraction
                with job_lock:
                    scraping_jobs[job_id]["current_action"] = "Stage 2+3: Extracting products..."
                    scraping_jobs[job_id]["progress"] = 30

                def on_product(product_dict, category_path="", category_url=""):
                    broadcast_product(brand_id, product_dict, category_path, category_url)

                orchestrator = StreamingOrchestrator(
                    domain, nav_tree,
                    product_callback=on_product,
                )
                result = orchestrator.run()

                if not result.success:
                    raise Exception("Product extraction failed")

                # Update job status
                with job_lock:
                    scraping_jobs[job_id]["status"] = "completed"
                    scraping_jobs[job_id]["end_time"] = datetime.utcnow().isoformat() + "Z"
                    scraping_jobs[job_id]["progress"] = 100
                    scraping_jobs[job_id]["current_action"] = "Complete"

            except Exception as e:
                import traceback
                print(f"❌ Scraping failed for brand {brand_id}: {e}")
                traceback.print_exc()
                with job_lock:
                    scraping_jobs[job_id]["status"] = "failed"
                    scraping_jobs[job_id]["error"] = str(e)
            finally:
                broadcast_done(brand_id)

        thread = threading.Thread(target=run_scrape, daemon=True)
        thread.start()

        return jsonify({
            "success": True,
            "job_id": job_id,
            "message": "Scraping job started",
            "estimated_time_seconds": 120
        }), 202

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def get_scrape_status(brand_id):
    """GET /api/brands/{brand_id}/scrape/status - Get scrape status"""
    try:
        # Find latest job for this brand
        brand_jobs = [j for j in scraping_jobs.values() if j['brand_id'] == brand_id]

        if not brand_jobs:
            return jsonify({"error": "No scraping jobs found"}), 404

        # Return most recent
        latest_job = max(brand_jobs, key=lambda x: x['start_time'])

        return jsonify(latest_job)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def get_scrape_history(brand_id):
    """GET /api/brands/{brand_id}/scrape/history - Get scrape history"""
    try:
        limit = int(request.args.get('limit', 10))
        offset = int(request.args.get('offset', 0))

        runs, total = storage.get_scrape_runs(brand_id, limit, offset)

        return jsonify({
            "runs": runs,
            "pagination": {
                "total": total,
                "limit": limit,
                "offset": offset,
                "has_more": offset + limit < total
            }
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def broadcast_product(brand_id: str, product_dict: dict, category_path: str = "", category_url: str = ""):
    """Push a product to all SSE listeners for this brand. Called from streaming pipeline."""
    # Include category info in the streamed data so frontend can update tree counters
    enriched = {**product_dict, "_category_path": category_path, "_category_url": category_url}
    with product_stream_lock:
        listeners = product_stream_listeners.get(brand_id, [])
        for q in listeners:
            q.put(enriched)


def broadcast_event(brand_id: str, event_name: str, data: dict = None):
    """Send a named SSE event to all listeners for this brand."""
    with product_stream_lock:
        listeners = product_stream_listeners.get(brand_id, [])
        for q in listeners:
            q.put({"_event": event_name, "_data": data or {}})


def broadcast_done(brand_id: str):
    """Signal all SSE listeners that scraping is complete."""
    with product_stream_lock:
        listeners = product_stream_listeners.get(brand_id, [])
        for q in listeners:
            q.put(None)  # None = done sentinel


def stream_products(brand_id):
    """GET /api/brands/{brand_id}/scrape/stream - SSE stream of extracted products"""
    q = queue.Queue()

    with product_stream_lock:
        if brand_id not in product_stream_listeners:
            product_stream_listeners[brand_id] = []
        product_stream_listeners[brand_id].append(q)

    def generate():
        try:
            while True:
                try:
                    product = q.get(timeout=120)  # 2 min timeout
                except queue.Empty:
                    # Keep-alive
                    yield ": keepalive\n\n"
                    continue

                if product is None:
                    # Done
                    yield "event: done\ndata: {}\n\n"
                    break

                # Named events (e.g. nav_ready)
                if isinstance(product, dict) and "_event" in product:
                    event_name = product["_event"]
                    event_data = product.get("_data", {})
                    yield f"event: {event_name}\ndata: {json.dumps(event_data)}\n\n"
                    continue

                yield f"data: {json.dumps(product)}\n\n"
        finally:
            with product_stream_lock:
                listeners = product_stream_listeners.get(brand_id, [])
                if q in listeners:
                    listeners.remove(q)

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


def get_scraping_intelligence(brand_id):
    """GET /api/brands/{brand_id}/scraping-intelligence - Get patterns"""
    try:
        intel = storage.get_scraping_intel(brand_id)

        if not intel:
            return jsonify({"error": "No scraping intelligence found"}), 404

        return jsonify(intel)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def analyze_brand():
    """POST /api/brands/analyze - Analyze if brand is scrapable"""
    try:
        data = request.get_json()
        url = data.get('url', '').strip()

        if not url:
            return jsonify({"error": "url is required"}), 400

        # Import analyzer
        from backend.scraper.brand import Brand

        # Quick analysis
        brand = Brand(url)
        links = brand.extract_page_links_with_context(url, expand_navigation_menus=True)

        if not links:
            return jsonify({
                "success": False,
                "is_scrapable": False,
                "message": "Could not extract links from website"
            })

        # Estimate categories (simplified)
        category_count = len([l for l in links if '/collection' in l.get('href', '') or '/product' in l.get('href', '')])

        return jsonify({
            "success": True,
            "is_scrapable": category_count > 0,
            "analysis": {
                "category_pages_found": category_count,
                "categories": [],  # TODO: Extract names
                "confidence": "high" if category_count > 3 else "medium",
                "estimated_time_seconds": category_count * 5
            },
            "message": f"Found approximately {category_count} product pages"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# IMAGES API
# =============================================================================

def serve_image(brand_id, category_slug, filename):
    """GET /api/images/{brand}/{category}/{filename} - Serve image"""
    # Local image storage is deprecated - products now use remote URLs
    return jsonify({"error": "Local image storage not available. Use product image URLs directly."}), 404


def get_product_images(product_url_encoded):
    """GET /api/products/{product_url}/images - Get product images"""
    try:
        product_url = unquote(product_url_encoded)
        product = storage.get_product(product_url)

        if not product:
            return jsonify({"error": "Product not found"}), 404

        # Return images as-is (products now use remote URLs)
        images = product.get("images", [])

        return jsonify({
            "product_url": product_url,
            "images": images
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# ROUTE REGISTRATION HELPER
# =============================================================================

def register_routes(app):
    """Register all routes with Flask app"""

    # Brands
    app.add_url_rule('/api/brands', 'get_brands', get_brands, methods=['GET'])
    app.add_url_rule('/api/brands/<brand_id>', 'get_brand', get_brand, methods=['GET'])
    app.add_url_rule('/api/brands/validate', 'validate_brand', validate_brand, methods=['POST'])
    app.add_url_rule('/api/brands', 'create_brand', create_brand, methods=['POST'])
    app.add_url_rule('/api/brands/<brand_id>', 'update_brand', update_brand, methods=['PUT'])
    app.add_url_rule('/api/brands/<brand_id>', 'delete_brand', delete_brand, methods=['DELETE'])

    # Products
    app.add_url_rule('/api/products', 'get_products', get_products, methods=['GET'])
    app.add_url_rule('/api/products/counts', 'get_product_counts', get_product_counts, methods=['GET'])
    app.add_url_rule('/api/products/<path:product_url_encoded>', 'get_product', get_product, methods=['GET'])
    app.add_url_rule('/api/products/aggregate', 'aggregate_products', aggregate_products, methods=['GET'])
    app.add_url_rule('/api/products/search', 'search_products', search_products, methods=['GET'])

    # Classifications
    app.add_url_rule('/api/brands/<brand_id>/classifications', 'get_classifications', get_classifications, methods=['GET'])
    app.add_url_rule('/api/brands/<brand_id>/categories/hierarchy', 'get_category_hierarchy', get_category_hierarchy, methods=['GET'])

    # Attributes
    app.add_url_rule('/api/brands/<brand_id>/attributes', 'get_attributes', get_attributes, methods=['GET'])
    app.add_url_rule('/api/brands/<brand_id>/attributes/<attribute_key>/values', 'get_attribute_values', get_attribute_values, methods=['GET'])

    # Scraping
    app.add_url_rule('/api/brands/<brand_id>/scrape', 'start_scrape', start_scrape, methods=['POST'])
    app.add_url_rule('/api/brands/<brand_id>/scrape/status', 'get_scrape_status', get_scrape_status, methods=['GET'])
    app.add_url_rule('/api/brands/<brand_id>/scrape/history', 'get_scrape_history', get_scrape_history, methods=['GET'])
    app.add_url_rule('/api/brands/<brand_id>/scrape/stream', 'stream_products', stream_products, methods=['GET'])
    app.add_url_rule('/api/brands/<brand_id>/scraping-intelligence', 'get_scraping_intelligence', get_scraping_intelligence, methods=['GET'])
    app.add_url_rule('/api/brands/analyze', 'analyze_brand', analyze_brand, methods=['POST'])

    # Images
    app.add_url_rule('/api/images/<brand_id>/<category_slug>/<filename>', 'serve_image', serve_image, methods=['GET'])
    app.add_url_rule('/api/products/<path:product_url_encoded>/images', 'get_product_images', get_product_images, methods=['GET'])

    print("✅ Unified API endpoints registered (22 endpoints)")
