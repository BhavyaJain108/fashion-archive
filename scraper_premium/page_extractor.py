"""
Page Product Extractor
=====================

Pure functions for extracting products from individual pages.
No shared state, designed for parallel processing.
"""

import sys
import os
import time
import re
from typing import Dict, List, Any
from datetime import datetime
from urllib.parse import urljoin, urlparse
from playwright.sync_api import sync_playwright


def _apply_image_transform(image_url: str, transform: str) -> str:
    """Apply image URL transformation using regex pattern"""
    if not image_url or not transform:
        return image_url
    
    # Transform format: "pattern -> replacement"
    if ' -> ' in transform:
        pattern_regex, replacement = transform.split(' -> ', 1)
        try:
            return re.sub(pattern_regex, replacement, image_url)
        except re.error:
            # If regex is invalid, return original URL
            return image_url
    
    return image_url


def extract_products_from_page(page_url: str, patterns: List[Dict[str, str]], brand_name: str = None, allow_pattern_discovery: bool = True) -> Dict[str, Any]:
    """
    Extract all products from a single page using multiple patterns with fallback.
    
    Args:
        page_url: URL of the page to scrape
        patterns: List of product extraction patterns (tries in order)
        brand_name: Optional brand name for metadata
        allow_pattern_discovery: Whether to attempt pattern discovery if all patterns fail (default: True)
        
    Returns:
        Dict containing:
        - page_url: Source page URL
        - category_name: Extracted category name
        - products: List of product dictionaries
        - success: Boolean success status
        - error: Error message if failed
        - pattern_used: Which pattern worked (or None)
        - new_pattern: Newly discovered pattern (if any)
        - metrics: Extraction metrics
    """
    start_time = time.time()
    
    # Extract category name from URL
    category_name = extract_category_name(page_url)
    
    # Extract brand name from URL if not provided
    if not brand_name:
        parsed = urlparse(page_url)
        brand_name = parsed.netloc.replace('www.', '').split('.')[0]
    
    result = {
        "page_url": page_url,
        "category_name": category_name,
        "products": [],
        "success": False,
        "error": None,
        "pattern_used": None,
        "new_pattern": None,
        "metrics": {
            "start_time": start_time,
            "extraction_time": 0,
            "patterns_tried": 0,
            "products_extracted": 0
        }
    }
    
    try:
        # Try existing patterns first
        for i, pattern in enumerate(patterns):
            result["metrics"]["patterns_tried"] += 1
            
            try:
                products = _extract_with_scrolling(page_url, pattern, brand_name, category_name)
                
                # Pattern worked if no exception was thrown (products is a list, even if empty)
                result["products"] = products
                result["success"] = True
                result["pattern_used"] = i
                result["metrics"]["products_extracted"] = len(products)
                break
                    
            except Exception as pattern_error:
                # This pattern failed, try next one
                continue
        
        # If all patterns failed, try to discover new pattern (only on first pages)
        if not result["success"] and allow_pattern_discovery:
            try:
                new_pattern = _discover_pattern_from_page(page_url, brand_name)
                if new_pattern:
                    # Try the newly discovered pattern
                    products = _extract_with_scrolling(page_url, new_pattern, brand_name, category_name)
                    
                    if products:
                        result["products"] = products
                        result["success"] = True
                        result["pattern_used"] = "new"
                        result["new_pattern"] = new_pattern
                        result["metrics"]["products_extracted"] = len(products)
                    else:
                        result["error"] = "New pattern discovered but no products extracted"
                else:
                    result["error"] = "All patterns failed and no new pattern could be discovered"
                    
            except Exception as discovery_error:
                result["error"] = f"Pattern discovery failed: {discovery_error}"
        elif not result["success"] and not allow_pattern_discovery:
            result["error"] = "All patterns failed and pattern discovery disabled for non-first pages"
        
    except Exception as e:
        result["error"] = str(e)
        result["success"] = False
    
    # Update final metrics
    result["metrics"]["extraction_time"] = time.time() - start_time
    
    return result


def _extract_with_scrolling(page_url: str, pattern: Dict[str, str], brand_name: str, category_name: str) -> List[Dict[str, Any]]:
    """
    Internal function to handle the actual scrolling and extraction logic.
    """
    products = []
    seen_urls = set()  # Page-local deduplication only
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            ignore_https_errors=True,
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        )
        page = context.new_page()
        
        try:
            # Navigate to page
            page.goto(page_url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(2000)  # Initial wait
            
            # Get selectors from pattern
            container_selector = pattern.get('container_selector', '')
            link_selector = pattern.get('link_selector', 'a')
            name_selector = pattern.get('name_selector', '')
            image_selector = pattern.get('image_selector', 'img')
            
            if not container_selector:
                raise Exception("No container selector in pattern")
            
            # Wait for containers to appear - longer timeout for dynamic loading
            try:
                page.wait_for_selector(container_selector, timeout=15000)
            except:
                # Check if any containers exist after timeout
                container_count = page.locator(container_selector).count()
                if container_count == 0:
                    raise Exception(f"No containers found with selector: {container_selector}")
                # If containers exist but wait_for_selector failed, continue anyway
            
            # Scroll and extract
            last_height = 0
            scroll_count = 0
            max_scrolls = 20
            
            while scroll_count < max_scrolls:
                # Extract products from current page state
                new_products = _extract_products_from_current_state(
                    page, page_url, pattern, brand_name, category_name, seen_urls
                )
                products.extend(new_products)
                
                # Check if we've reached the bottom
                current_height = page.evaluate("document.body.scrollHeight")
                if current_height == last_height:
                    break
                
                # Scroll down and wait
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2000)
                
                last_height = current_height
                scroll_count += 1
            
        finally:
            browser.close()
    
    return products


def _extract_products_from_current_state(page, page_url: str, pattern: Dict[str, str], 
                                       brand_name: str, category_name: str, seen_urls: set) -> List[Dict[str, Any]]:
    """
    Extract products from the current state of the page.
    """
    products = []
    
    # Get selectors
    container_selector = pattern.get('container_selector', '')
    link_selector = pattern.get('link_selector', 'a')
    name_selector = pattern.get('name_selector', '')
    image_selector = pattern.get('image_selector', 'img')
    
    # Use JavaScript to extract product data - safely escape selectors
    import json
    container_selector_escaped = json.dumps(container_selector)
    link_selector_escaped = json.dumps(link_selector)
    name_selector_escaped = json.dumps(name_selector)
    image_selector_escaped = json.dumps(image_selector)
    
    extraction_result = page.evaluate(f"""
        () => {{
            const containers = document.querySelectorAll({container_selector_escaped});
            const products = [];
            
            containers.forEach(container => {{
                // Extract product URL - trust LLM selector completely
                let href = null;
                if ({link_selector_escaped} === {container_selector_escaped}) {{
                    // Container itself is the link
                    href = container.getAttribute('href');
                }} else if ({link_selector_escaped}) {{
                    const linkEl = container.querySelector({link_selector_escaped});
                    href = linkEl ? linkEl.getAttribute('href') : null;
                }} else {{
                    // If no link_selector provided, assume container itself is the link
                    href = container.getAttribute('href');
                }}
                
                // Extract product name - trust LLM selector completely
                let name = 'Unknown';
                if ({name_selector_escaped}) {{
                    const nameEl = container.querySelector({name_selector_escaped});
                    if (nameEl) {{
                        name = nameEl.innerText || nameEl.textContent || 'Unknown';
                    }}
                }}
                
                // Extract image - trust LLM selector but check common image attributes
                let imageSrc = '';
                if ({image_selector_escaped}) {{
                    const imgEl = container.querySelector({image_selector_escaped});
                    if (imgEl) {{
                        // Check common attributes where image URLs are stored
                        imageSrc = imgEl.getAttribute('src') || 
                                  imgEl.getAttribute('data-src') || 
                                  imgEl.getAttribute('data-lazy-src') || 
                                  imgEl.getAttribute('data-original') ||
                                  imgEl.getAttribute('data-srcset')?.split(',')[0]?.split(' ')[0] || 
                                  '';
                    }}
                }}
                
                if (href) {{
                    products.push({{
                        href: href,
                        name: name.trim(),
                        image: imageSrc
                    }});
                }}
            }});
            
            return products;
        }}
    """)
    
    # Process extracted data
    for product_data in extraction_result:
        try:
            href = product_data.get('href', '')
            if not href:
                continue
            
            # Normalize URL
            if href.startswith('/'):
                product_url = urljoin(page_url, href)
            elif href.startswith('http'):
                product_url = href
            else:
                product_url = urljoin(page_url, href)
            
            # Skip if already seen on this page
            if product_url in seen_urls:
                continue
            
            seen_urls.add(product_url)
            
            # Normalize image URL
            image_url = product_data.get('image', '')
            if image_url and not image_url.startswith('http'):
                image_url = urljoin(page_url, image_url)
            
            # Apply image transforms if specified in pattern
            if image_url and pattern.get('image_url_transform'):
                image_url = _apply_image_transform(image_url, pattern.get('image_url_transform'))
            
            # Create product record
            product = {
                "brand": brand_name,
                "category_url": page_url,
                "category_name": category_name,
                "product_name": product_data.get('name', 'Unknown'),
                "product_url": product_url,
                "product_id": product_url.split('/')[-1] if '/' in product_url else product_url,
                "image_url": image_url,
                "price": "",  # Could be extracted if pattern includes it
                "availability": "Unknown",
                "discovered_at": datetime.now().isoformat(),
                "extraction_time": time.time()
            }
            
            products.append(product)
            
        except Exception as e:
            # Skip problematic products but continue
            continue
    
    return products


def extract_category_name(url: str) -> str:
    """Extract a readable category name from URL"""
    parsed = urlparse(url)
    path_parts = [p for p in parsed.path.split('/') if p and p not in ['collections', 'collection']]
    
    # Handle query parameters for category names
    if 'tag:' in url:
        tag_part = url.split('tag:')[-1].split('&')[0]
        return tag_part.replace('-', ' ').title()
    
    if path_parts:
        # Take the last meaningful part and clean it up
        name = path_parts[-1].replace('-', ' ').replace('_', ' ').title()
        return name
    
    return "Main Collection"


def _discover_pattern_from_page(page_url: str, brand_name: str) -> Dict[str, str]:
    """
    Discover a new product extraction pattern by analyzing the page.
    Uses the same logic as the Brand.analyze_product_pattern method.
    """
    try:
        # Import here to avoid circular imports
        sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from brand import Brand
        
        # Create a temporary Brand instance for pattern discovery
        parsed = urlparse(page_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        
        temp_brand = Brand(base_url)
        temp_brand.starting_pages_queue = [page_url]
        
        # Use existing pattern detection logic
        pattern_result = temp_brand.analyze_product_pattern()
        
        if pattern_result and temp_brand.product_extraction_pattern:
            return temp_brand.product_extraction_pattern
        else:
            return None
            
    except Exception as e:
        print(f"⚠️  Pattern discovery failed for {page_url}: {e}")
        return None


def generate_pagination_url(base_url: str, pagination_pattern: Dict[str, Any], page_number: int) -> str:
    """
    Generate pagination URL based on discovered pattern
    
    Args:
        base_url: Base category URL
        pagination_pattern: Pagination pattern from brand analysis
        page_number: Page number to generate
        
    Returns:
        Generated page URL or None if pattern not supported
    """
    if not pagination_pattern or pagination_pattern.get("type") == "none":
        return None
    
    # Clean base URL (remove existing page parameters)
    if "?" in base_url:
        base_url = base_url.split("?")[0]
    if base_url.endswith("/"):
        base_url = base_url.rstrip("/")
    
    pattern_type = pagination_pattern.get("type", "none")
    template = pagination_pattern.get("template", "")
    
    if pattern_type == "numbered" or pattern_type == "mixed":
        if "?page=X" in template:
            return f"{base_url}?page={page_number}"
        elif "/page/X/" in template:
            return f"{base_url}/page/{page_number}/"
        elif "/page/X" in template:
            return f"{base_url}/page/{page_number}"
        elif "?p=X" in template:
            return f"{base_url}?p={page_number}"
        else:
            # Custom pattern - replace X with page number
            return base_url + template.replace("X", str(page_number))
    
    elif pattern_type == "next_button":
        # For next button pagination, URL needs to be extracted from current page
        # This will be handled in the extraction logic
        return None
    
    return None


def extract_next_button_url(current_page_html: str, pagination_pattern: Dict[str, Any], current_page_url: str) -> str:
    """
    Extract next page URL from current page HTML for next-button pagination
    
    Args:
        current_page_html: HTML content of current page
        pagination_pattern: Pagination pattern with next_selector
        current_page_url: Current page URL for relative URL resolution
        
    Returns:
        Next page URL or None if no next button found
    """
    try:
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin
        
        soup = BeautifulSoup(current_page_html, 'html.parser')
        next_selector = pagination_pattern.get("next_selector", "")
        
        if not next_selector:
            # Try common next button selectors
            next_selectors = [
                "a[aria-label*='next' i]",
                "a[title*='next' i]", 
                ".next a",
                ".pagination-next a",
                "a:contains('Next')",
                "a:contains('→')",
                "a:contains('>')"
            ]
        else:
            next_selectors = [next_selector]
        
        for selector in next_selectors:
            try:
                next_link = soup.select_one(selector)
                if next_link and next_link.get('href'):
                    href = next_link.get('href')
                    # Convert relative URL to absolute
                    if href.startswith('/'):
                        return urljoin(current_page_url, href)
                    elif href.startswith('http'):
                        return href
                    else:
                        return urljoin(current_page_url, href)
            except:
                continue
        
        return None
        
    except Exception as e:
        print(f"      ⚠️  Error extracting next button URL: {e}")
        return None


def extract_multiple_pages(page_urls: List[str], patterns: List[Dict[str, str]], brand_name: str = None) -> List[Dict[str, Any]]:
    """
    Extract products from multiple pages sequentially.
    
    Args:
        page_urls: List of page URLs to extract from
        pattern: Product extraction pattern
        brand_name: Optional brand name
        
    Returns:
        List of extraction results, one per page
    """
    results = []
    
    for page_url in page_urls:
        print(f"  🔄 Processing: {extract_category_name(page_url)}")
        result = extract_products_from_page(page_url, pattern, brand_name, allow_pattern_discovery=True)
        results.append(result)
        
        status = "✅" if result["success"] else "❌"
        products_count = len(result["products"])
        extraction_time = result["metrics"]["extraction_time"]
        
        print(f"  {status} {result['category_name']}: {products_count} products in {extraction_time:.1f}s")
        
        if not result["success"]:
            print(f"     Error: {result['error']}")
    
    return results


def scrape_category_page(category_url: str, patterns: List[Dict[str, str]], brand_name: str, 
                        pagination_pattern: Dict[str, Any] = None, images_dir: str = None, download_images: bool = False) -> Dict[str, Any]:
    """
    Scrape category page with pagination using provided pagination pattern
    Uses pre-discovered pagination pattern to process all pages until no products found
    
    Returns:
        Dict with category info and extracted products from ALL pages
    """
    import time
    from concurrent.futures import ThreadPoolExecutor
    import requests
    from pathlib import Path
    
    print(f"🔄 Processing category: {category_url}")
    
    all_category_products = []
    pages_processed = 0
    
    # Start with the initial category page
    current_page_url = category_url
    page_number = 1
    
    # Show pagination strategy
    if pagination_pattern and pagination_pattern.get("type") != "none":
        print(f"   🔍 Using pagination: {pagination_pattern.get('type')} - {pagination_pattern.get('template')}")
    else:
        print(f"   📝 Single page category - no pagination")
    
    while current_page_url:
        print(f"   📄 Processing page {page_number}: {current_page_url}")
        
        # Extract products from current page (only allow pattern discovery on first page)
        page_result = extract_products_from_page(current_page_url, patterns, brand_name, allow_pattern_discovery=(page_number == 1))
        
        if page_result["success"] and page_result["products"]:
            pages_processed += 1  # Only count productive pages
            print(f"      ✅ Found {len(page_result['products'])} products")
            all_category_products.extend(page_result["products"])
            
            # GENERATE NEXT PAGE URL using provided pagination pattern
            if pagination_pattern and pagination_pattern.get("type") != "none":
                page_number += 1
                
                if pagination_pattern.get("type") == "next_button":
                    # Extract next button URL from current page HTML
                    current_page_html = page_result.get("html_content", "")
                    next_page_url = extract_next_button_url(current_page_html, pagination_pattern, current_page_url)
                else:
                    # Generate numbered pagination URL
                    next_page_url = generate_pagination_url(category_url, pagination_pattern, page_number)
                
                current_page_url = next_page_url
                if next_page_url:
                    print(f"      ➡️  Next page: {next_page_url}")
                else:
                    print(f"      ⏹️  No more pages found")
                    current_page_url = None
            else:
                # No pagination pattern - single page category
                current_page_url = None
                
        else:
            print(f"      ⏹️  No products found - stopping pagination")
            current_page_url = None
    
    print(f"   ✅ Category complete: {len(all_category_products)} products from {pages_processed} pages")
    
    # Create final result - success is based on total products found, not last page
    final_result = page_result.copy() if 'page_result' in locals() else {
        "category_name": extract_category_name(category_url),
        "page_url": category_url
    }
    
    # Update result to reflect all products from all pages
    final_result["products"] = all_category_products
    final_result["pages_processed"] = pages_processed
    final_result["pagination_detected"] = pagination_pattern is not None and pagination_pattern.get("type") != "none"
    # SUCCESS IS BASED ON TOTAL PRODUCTS FOUND, NOT LAST PAGE RESULT
    final_result["success"] = len(all_category_products) > 0
    
    # Start image downloads for this category immediately if requested
    if download_images and images_dir and final_result["success"] and final_result["products"]:
        
        def download_product_image(product):
            """Download a single product image"""
            try:
                image_url = product.get('image_url', '')
                if not image_url or not image_url.startswith('http'):
                    return False
                
                # Create safe filename
                product_name = product.get('product_name', 'unknown')
                product_id = product.get('product_id', '')
                safe_name = ''.join(c for c in product_name if c.isalnum() or c in ' -_.')[:50]
                safe_id = ''.join(c for c in product_id if c.isalnum() or c in '-_.')[:20]
                
                # Get extension
                ext = '.webp' if '.webp' in image_url else ('.png' if '.png' in image_url else '.jpg')
                filename = f"{safe_name}_{safe_id}{ext}".replace(' ', '_')
                filepath = Path(images_dir) / filename
                
                if filepath.exists():
                    return True
                
                # Download
                response = requests.get(image_url, timeout=10, headers={
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
                })
                response.raise_for_status()
                
                with open(filepath, 'wb') as f:
                    f.write(response.content)
                return True
                
            except:
                return False
        
        # Download images for this category in parallel (fire and forget)
        with ThreadPoolExecutor(max_workers=3) as img_executor:
            img_executor.map(download_product_image, final_result["products"])
    
    # Return final result with all products from all pages
    return {
        "category_name": final_result.get("category_name", extract_category_name(category_url)),
        "category_url": category_url,
        "products_found": len(final_result["products"]),
        "pages_processed": final_result["pages_processed"],
        "pagination_detected": final_result["pagination_detected"],
        "extraction_time": time.time(),  # Will be calculated properly by pipeline
        "products": final_result["products"],
        "success": final_result["success"],
        "error": final_result.get("error"),
        "pattern_used": final_result.get("pattern_used"),
        "new_pattern": final_result.get("new_pattern")
    }


def extract_category_name(url: str) -> str:
    """Extract category name from URL"""
    parsed = urlparse(url)
    path_parts = [p for p in parsed.path.split('/') if p and p not in ['collections', 'collection']]
    
    if path_parts:
        name = path_parts[-1].replace('-', ' ').replace('_', ' ').title()
        return name
    
    return "Main Collection"