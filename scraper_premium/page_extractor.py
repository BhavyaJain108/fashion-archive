"""
Page Product Extractor
=====================

Pure functions for extracting products from individual pages.
No shared state, designed for parallel processing.
"""

import sys
import os
import time
from typing import Dict, List, Any, Optional
from datetime import datetime
from urllib.parse import urljoin, urlparse
from playwright.sync_api import sync_playwright
from collections import Counter
from llm_handler import LLMHandler
from prompts import lineage_selection


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
        # Use only the first (primary) pattern
        if not patterns:
            result["error"] = "No patterns provided"
            return result
            
        pattern = patterns[0]
        result["metrics"]["patterns_tried"] = 1
        
        products = _extract_with_scrolling(page_url, pattern, brand_name, category_name)
        
        # Apply lineage filtering if we have multiple products
        lineage_filtering_start = time.time()
        products_before_filtering = len(products)
        if len(products) > 1:
            filtered_products = apply_lineage_filtering(products, page_url, category_name)
            if filtered_products:  # Only use filtered results if filtering succeeded
                products = filtered_products
        lineage_filtering_time = time.time() - lineage_filtering_start
        
        result["products"] = products
        result["success"] = len(products) > 0
        result["pattern_used"] = 0
        result["metrics"]["products_extracted"] = len(products)
        result["metrics"]["products_before_filtering"] = products_before_filtering
        result["metrics"]["lineage_filtering_time"] = lineage_filtering_time
        
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
            
            # Scroll to bottom first, then extract all products
            last_height = 0
            scroll_count = 0
            no_change_count = 0
            max_no_change_attempts = 3  # Try 1 time when height doesn't change
            
            print(f"   🔄 Scrolling to load all content for: {page_url}")
            
            while True:
                current_height = page.evaluate("document.body.scrollHeight")
                scroll_count += 1
                
                print(f"   📏 Scroll #{scroll_count}: height {last_height} → {current_height}")
                
                if current_height == last_height:
                    no_change_count += 1
                    print(f"   ⏳ No height change (attempt {no_change_count}/{max_no_change_attempts}), waiting longer...")
                    
                    if no_change_count >= max_no_change_attempts:
                        print(f"   ✅ Reached bottom after {scroll_count} scrolls and {no_change_count} confirmation attempts, extracting products...")
                        break
                    
                    # Wait longer when no change detected to allow lazy loading
                    page.wait_for_timeout(4000)  # Wait 4 seconds instead of 2
                else:
                    # Height changed, reset the no-change counter
                    no_change_count = 0
                    page.wait_for_timeout(2000)  # Normal wait time
                
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                last_height = current_height
            
            # Extract all products once after scrolling complete
            products = _extract_products_from_current_state(
                page, page_url, pattern, brand_name, category_name, seen_urls
            )
            
        finally:
            browser.close()
    
    return products


def _extract_products_from_current_state(page, page_url: str, pattern: Dict[str, str], 
                                       brand_name: str, category_name: str, seen_urls: set) -> List[Dict[str, Any]]:
    """
    Extract products from the current state of the page.
    """
    products = []
    products_by_url = {}  # Track products by URL to merge images from duplicates
    
    # Get selectors
    container_selector = pattern.get('container_selector', '')
    link_selector = pattern.get('link_selector', 'a')
    name_selector = pattern.get('name_selector', '')
    
    # Use JavaScript to extract product data - safely escape selectors
    import json
    container_selector_escaped = json.dumps(container_selector)
    link_selector_escaped = json.dumps(link_selector)
    name_selector_escaped = json.dumps(name_selector)
    
    extraction_result = page.evaluate(f"""
        () => {{
            // Helper function to extract product name from URL
            function extractNameFromUrl(url) {{
                try {{
                    // Extract filename from URL
                    const urlParts = url.split('/');
                    let filename = urlParts[urlParts.length - 1];
                    
                    // Remove query parameters
                    filename = filename.split('?')[0];
                    
                    // Remove file extension if it's an image
                    filename = filename.replace(/\\.(jpg|jpeg|png|webp|gif|svg)$/i, '');
                    
                    // Skip if filename is too short or looks like an ID
                    if (filename.length < 3 || /^[0-9a-f]+$/i.test(filename)) {{
                        return 'Unknown';
                    }}
                    
                    // Convert URL-friendly format to readable name
                    let productName = filename
                        .replace(/[-_]/g, ' ')  // Replace hyphens and underscores with spaces
                        .replace(/([a-z])([A-Z])/g, '$1 $2')  // Add space before capital letters
                        .replace(/\\s+/g, ' ')  // Normalize multiple spaces
                        .trim();
                    
                    // Capitalize first letter of each word
                    productName = productName.replace(/\\b\\w/g, l => l.toUpperCase());
                    
                    // Return the extracted name if it looks valid
                    if (productName.length > 2 && productName !== filename.toUpperCase()) {{
                        return productName;
                    }}
                    
                    return 'Unknown';
                }} catch (e) {{
                    return 'Unknown';
                }}
            }}
            
            // Helper function to validate if URL is a real image
            function isValidImageUrl(url) {{
                if (!url || url.length === 0) return false;
                
                // Remove query parameters and fragments to check the actual file extension
                const cleanUrl = url.split('?')[0].split('#')[0];
                
                // Check if it ends with a valid image extension
                const imageExtensions = ['.jpg', '.jpeg', '.png', '.webp', '.gif', '.svg', '.bmp', '.tiff'];
                
                return imageExtensions.some(ext => cleanUrl.toLowerCase().endsWith(ext));
            }}
            
            // Helper function to extract best image source from img element
            function getBestImageSrc(imgElement) {{
                const srcAttributes = [
                    'src',
                    'data-src', 
                    'data-lazy-src',
                    'data-original',
                    'data-lazy-original',
                    'data-srcset'
                ];
                
                for (const attr of srcAttributes) {{
                    const value = imgElement.getAttribute(attr);
                    if (value) {{
                        // Handle srcset format - take first URL
                        if (attr === 'data-srcset') {{
                            const firstUrl = value.split(',')[0]?.split(' ')[0];
                            if (firstUrl && isValidImageUrl(firstUrl)) return firstUrl;
                        }} else {{
                            if (isValidImageUrl(value)) return value;
                        }}
                    }}
                }}
                return '';
            }}
            
            // Helper function to extract all valid images from container
            function extractImagesFromContainer(container) {{
                const images = [];
                const imgElements = container.querySelectorAll('img');
                
                imgElements.forEach(img => {{
                    const src = getBestImageSrc(img);
                    if (src && isValidProductImage(img, src)) {{
                        images.push({{
                            src: src,
                            alt: img.alt || '',
                            width: parseInt(img.width) || 0,
                            height: parseInt(img.height) || 0
                        }});
                    }}
                }});
                
                return images;
            }}
            
            // Helper function to validate if image is likely a product image
            function isValidProductImage(imgElement, src) {{
                // Skip tiny images (likely icons)
                const width = parseInt(imgElement.width) || 0;
                const height = parseInt(imgElement.height) || 0;
                if (width > 0 && width < 50) return false;
                if (height > 0 && height < 50) return false;
                
                // Skip SVGs (usually icons)
                if (src.toLowerCase().includes('.svg')) return false;
                
                // Skip images with logo-related alt text
                const alt = (imgElement.alt || '').toLowerCase();
                if (alt.includes('logo') || alt.includes('icon')) return false;
                
                return true;
            }}
            
            const containers = document.querySelectorAll({container_selector_escaped});
            const products = [];
            
            containers.forEach(container => {{
                // Extract product URL
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
                
                // Extract lineage path (3 generations: container + 2 ancestors)
                function getFullLineage(element) {{
                    const path = [];
                    let current = element;
                    let depth = 0;
                    
                    while (current && current.tagName && current !== document.body && depth < 3) {{
                        let selector = current.tagName.toLowerCase();
                        
                        // Add classes if present
                        if (current.className && typeof current.className === 'string') {{
                            const classes = current.className.trim().replace(/\\s+/g, '.');
                            if (classes) {{
                                selector += '.' + classes;
                            }}
                        }}
                        
                        // Add ID if present
                        if (current.id) {{
                            selector += '#' + current.id;
                        }}
                        
                        path.unshift(selector);
                        current = current.parentElement;
                        depth++;
                    }}
                    
                    return path.join(' > ');
                }}
                
                const fullLineage = getFullLineage(container);
                
                // Extract all images from container
                const images = extractImagesFromContainer(container);
                
                // Extract product name - PRIORITY: product URL > CSS selector > image alt text
                let name = 'Unknown';
                
                // First try to extract from product URL (best source)
                if (href) {{
                    const extractedName = extractNameFromUrl(href);
                    if (extractedName && extractedName !== 'Unknown') {{
                        name = extractedName;
                    }}
                }}
                
                // Fallback to CSS selector if URL extraction failed
                if (name === 'Unknown' && {name_selector_escaped}) {{
                    const nameEl = container.querySelector({name_selector_escaped});
                    if (nameEl) {{
                        let selectorName = '';
                        
                        // If name selector points to an img element, check alt attribute first
                        if (nameEl.tagName.toLowerCase() === 'img') {{
                            selectorName = nameEl.getAttribute('alt') || nameEl.getAttribute('title') || '';
                        }} else {{
                            // For non-img elements, use text content
                            selectorName = nameEl.innerText || nameEl.textContent || '';
                        }}
                        
                        if (selectorName.trim()) {{
                            name = selectorName.trim();
                        }}
                    }}
                }}
                
                // Final fallback: extract from first image alt text
                if (name === 'Unknown' && images.length > 0) {{
                    const firstImageAlt = images[0].alt;
                    if (firstImageAlt && firstImageAlt.trim()) {{
                        name = firstImageAlt.trim();
                    }}
                }}
                
                if (href) {{
                    products.push({{
                        href: href,
                        name: name.trim(),
                        images: images,
                        full_lineage: fullLineage
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
            
            # Process and normalize image URLs
            images = product_data.get('images', [])
            normalized_images = []
            seen_image_urls = set()
            for img in images:
                img_src = img.get('src', '')
                if img_src:
                    # Normalize image URL
                    if img_src.startswith('//'):
                        img_src = 'https:' + img_src
                    elif img_src.startswith('/'):
                        img_src = urljoin(page_url, img_src)
                    elif not img_src.startswith('http'):
                        img_src = urljoin(page_url, img_src)
                    
                    # Only add if we haven't seen this image URL before
                    if img_src not in seen_image_urls:
                        seen_image_urls.add(img_src)
                        normalized_images.append({
                            "src": img_src,
                            "alt": img.get('alt', ''),
                            "width": img.get('width', 0),
                            "height": img.get('height', 0)
                        })
            
            # Check if we've seen this product URL before
            if product_url in products_by_url:
                # Merge images from duplicate product cards
                existing_product = products_by_url[product_url]
                existing_image_srcs = {img['src'] for img in existing_product['images']}
                
                # Add new unique images
                for img in normalized_images:
                    if img['src'] not in existing_image_srcs:
                        existing_product['images'].append(img)
                        existing_image_srcs.add(img['src'])
                
                # Update the product name if the current one is better (not 'Unknown')
                current_name = product_data.get('name', 'Unknown').strip()
                if current_name != 'Unknown' and existing_product['product_name'] == 'Unknown':
                    existing_product['product_name'] = current_name
                    
                continue  # Skip creating a new product entry
            
            # Create product record
            product = {
                "brand": brand_name,
                "category_url": page_url,
                "category_name": category_name,
                "product_name": product_data.get('name', 'Unknown'),
                "product_url": product_url,
                "product_id": product_url.split('/')[-1] if '/' in product_url else product_url,
                "images": normalized_images,
                "price": "",  # Could be extracted if pattern includes it
                "availability": "Unknown",
                "discovered_at": datetime.now().isoformat(),
                "extraction_time": time.time(),
                "full_lineage": product_data.get('full_lineage', 'Unknown')
            }
            
            # Track this product by URL and add to results
            products_by_url[product_url] = product
            products.append(product)
            
        except Exception as e:
            # Skip problematic products but continue
            continue
    
    return products


def apply_lineage_filtering(products: List[Dict[str, Any]], page_url: str, category_name: str) -> List[Dict[str, Any]]:
    """
    Apply lineage-based filtering using LLM to select best ancestry path.
    
    Args:
        products: List of extracted products with full_lineage
        page_url: Source page URL for context
        category_name: Category name for context
        
    Returns:
        Filtered list of products, or empty list if filtering fails
    """
    try:
        # Count lineage frequencies
        lineage_counter = Counter()
        for product in products:
            lineage = product.get('full_lineage', 'Unknown')
            if lineage != 'Unknown':
                lineage_counter[lineage] += 1
        
        # Print lineage analysis if verbose
        print(f"\n🔍 LINEAGE ANALYSIS:")
        print(f"   📊 Found {len(lineage_counter)} unique lineage patterns from {len(products)} products")
        for i, (lineage, count) in enumerate(sorted(lineage_counter.items(), key=lambda x: x[1], reverse=True), 1):
            print(f"   {i}. \"{lineage}\" ({count} products)")
        
        # Need at least 2 different lineages to make filtering worthwhile
        if len(lineage_counter) < 2:
            print(f"   ⏭️  Only 1 lineage pattern found - skipping filtering")
            return products
        
        # Convert counter to dict for prompt
        lineage_frequencies = dict(lineage_counter)
        
        # Get LLM selection
        llm_handler = LLMHandler()
        prompt = lineage_selection.get_prompt(page_url, category_name, lineage_frequencies)
        response_model = lineage_selection.get_response_model()
        
        print(f"   🤖 Asking LLM to select best lineage for '{category_name}'...")
        llm_result = llm_handler.call(prompt, response_model=response_model)
        print(f"   📝 LLM Response: {llm_result}")
        
        if not llm_result or not llm_result.get('success'):
            error_msg = llm_result.get('error', 'Unknown error') if llm_result else 'No response'
            print(f"   ❌ LLM failed to select lineage - {error_msg}")
            return []
        
        # Extract the actual data from the LLM response
        result = llm_result.get('data')
        if not result or 'valid_lineages' not in result:
            print(f"   ❌ LLM response missing valid_lineages - keeping all products")
            return []
        
        valid_lineages = result['valid_lineages']
        print(f"   ✅ LLM selected {len(valid_lineages)} valid lineages:")
        for i, lineage in enumerate(valid_lineages, 1):
            print(f"      {i}. \"{lineage}\"")
        print(f"   💭 LLM reasoning: {result.get('analysis', 'No reasoning provided')}")
        print(f"   🎯 LLM confidence: {result.get('confidence', 'Not specified')}")
        
        # Filter products to only include those with valid lineages
        valid_lineages_set = set(valid_lineages)
        filtered_products = [
            product for product in products 
            if product.get('full_lineage') in valid_lineages_set
        ]
        
        print(f"   📦 Filtered from {len(products)} to {len(filtered_products)} products")
        
        return filtered_products
        
    except Exception as e:
        # If lineage filtering fails, return original products
        print(f"Lineage filtering failed: {e}")
        return []


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
            return None
        
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


# Navigation Tree Utility Functions
# =================================

def get_first_leaf_url(navigation_tree: List[Dict]) -> Optional[str]:
    """
    Extract first leaf URL from navigation tree for pattern discovery.
    
    Args:
        navigation_tree: Navigation tree structure from LLM analysis
        
    Returns:
        First leaf URL found, or None if no leaf URLs exist
    """
    
    for node in navigation_tree:
        if isinstance(node, dict):
            children = node.get('children', [])
            
            if children:
                # Has children - recurse into children first
                child_url = get_first_leaf_url(children)
                if child_url:
                    return child_url
            else:
                # No children - this is a leaf node
                url = node.get('url')
                if url:
                    return url
    
    return None


def flatten_dict_tree(category_nodes):
    """
    Flatten tree structure to list of leaf URLs only.
    
    Args:
        category_nodes: Navigation tree nodes
        
    Returns:
        List of leaf URLs (nodes without children)
    """
    urls = []
    
    for node in category_nodes:
        if isinstance(node, dict):
            children = node.get('children', [])
            
            if children:
                # Has children - this is a branch node, recurse into children
                urls.extend(flatten_dict_tree(children))
            else:
                # No children - this is a leaf node, include its URL
                url = node.get('url')
                if url:
                    urls.append(url)
    
    return urls


def flatten_dict_tree_all_urls(category_nodes):
    """
    Flatten tree structure to list of all URLs (both branches and leaves).
    
    Args:
        category_nodes: Navigation tree nodes
        
    Returns:
        List of all URLs found in the tree
    """
    urls = []
    
    for node in category_nodes:
        if isinstance(node, dict):
            # Include this node's URL if it exists
            url = node.get('url')
            if url:
                urls.append(url)
            
            # Recurse into children regardless
            children = node.get('children', [])
            if children:
                urls.extend(flatten_dict_tree_all_urls(children))
    
    return urls


def extract_all_urls_from_navigation_tree(navigation_tree: List[Dict]) -> List[str]:
    """
    Extract ALL URLs from navigation tree for parallel processing.
    
    Args:
        navigation_tree: Complete navigation tree structure
        
    Returns:
        List of all URLs (both parent categories with URLs and leaf categories)
    """
    return flatten_dict_tree_all_urls(navigation_tree)


def extract_collection_hierarchy(navigation_tree: List[Dict]) -> List[Dict]:
    """
    Extract hierarchical structure information for folder creation.
    
    Args:
        navigation_tree: Navigation tree structure
        
    Returns:
        List of collection info with hierarchy paths
    """
    def extract_with_path(nodes, parent_path=""):
        collections = []
        
        for node in nodes:
            if isinstance(node, dict):
                name = node.get('name', 'Unknown')
                url = node.get('url')
                children = node.get('children', [])
                
                # Create current path
                current_path = f"{parent_path}/{name}" if parent_path else name
                
                collection_info = {
                    'name': name,
                    'url': url,
                    'path': current_path,
                    'has_children': bool(children),
                    'has_url': bool(url)
                }
                collections.append(collection_info)
                
                # Recurse into children
                if children:
                    collections.extend(extract_with_path(children, current_path))
        
        return collections
    
    return extract_with_path(navigation_tree)