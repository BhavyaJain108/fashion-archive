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
# Import modal bypass for load more functionality
try:
    from tests.modal_bypass_engine import bypass_blocking_modals_only
except ImportError:
    try:
        from modal_bypass_engine import bypass_blocking_modals_only
    except ImportError:
        # Define a dummy function if modal bypass is not available
        def bypass_blocking_modals_only(page, url):
            return {"modals_detected": 0, "modals_bypassed": 0, "success": True}


def extract_products_from_page(page_url: str, patterns: List[Dict[str, str]], brand_name: str = None, allow_pattern_discovery: bool = True, brand_instance=None) -> Dict[str, Any]:
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
        
        extraction_result = _extract_with_scrolling(page_url, pattern, brand_name, category_name, brand_instance)
        products = extraction_result["products"]
        pagination_triggers_found = extraction_result.get("pagination_triggers_found", [])
        
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
        result["pagination_triggers_found"] = pagination_triggers_found
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


def _extract_with_scrolling(page_url: str, pattern: Dict[str, str], brand_name: str, category_name: str, brand_instance=None) -> Dict[str, Any]:
    """
    Internal function to handle the actual scrolling and extraction logic.
    """
    products = []
    seen_urls = set()  # Page-local deduplication only
    pagination_triggers_found = []  # Track what pagination triggers were found
    
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
            
            # Detect pagination elements once at the beginning
            pagination_element_detected = _detect_pagination_element(page)
            if pagination_element_detected:
                print(f"   🎯 Pagination element detected: {pagination_element_detected}")
                print(f"   📍 Will scroll to pagination element first, then to bottom")
                pagination_triggers_found.append(pagination_element_detected)
            else:
                print(f"   📄 No pagination elements detected - using standard bottom scroll")
            
            # Scroll to bottom first, then extract all products
            last_height = 0
            scroll_count = 0
            no_change_count = 0
            
            # Optimize attempts based on loading mechanism knowledge
            if brand_instance and brand_instance.load_more_loading_mechanism:
                max_no_change_attempts = 1  # Only 1 attempt if we know site uses load more
                print(f"   🔄 Scrolling to load content (optimized for load more): {page_url}")
            else:
                max_no_change_attempts = 2  # Standard attempts for unknown loading mechanism
                print(f"   🔄 Scrolling to load all content for: {page_url}")
            
            # Step 1: If pagination detected, chase it first
            if pagination_element_detected:
                # Pagination-based scrolling: keep chasing the pagination element
                _scroll_using_pagination_element(page, pagination_element_detected, pagination_triggers_found)
                
                # After pagination chasing, do normal bottom scrolling
                print(f"   📄 Pagination chasing complete, now scrolling to bottom...")
            
            # Step 2: Always do traditional height-based scrolling to bottom (either standalone or after pagination)
            while True:
                # Get current height before scrolling
                current_height = page.evaluate("document.body.scrollHeight")
                scroll_count += 1
                
                # Scroll to bottom first
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2000)  # Wait for scroll and potential loading
                
                # Get new height after scrolling and waiting
                new_height = page.evaluate("document.body.scrollHeight")
                
                print(f"   📏 Scroll #{scroll_count}: height {current_height} → {new_height}")
                
                # Check if height changed after scroll
                if new_height == current_height:
                    no_change_count += 1
                    print(f"   ⏳ No height change (attempt {no_change_count}/{max_no_change_attempts})")
                    
                    if no_change_count >= max_no_change_attempts:
                        break  # Exit traditional scrolling loop
                    else:
                        # Wait longer when no change detected to allow lazy loading (3 second wait)
                        print(f"   ⏳ Waiting for potential lazy loading...")
                        page.wait_for_timeout(3000)  # 3 second wait as specified
                else:
                    # Height changed, reset the no-change counter
                    no_change_count = 0
                
                # Update last height for next iteration
                last_height = new_height
            
            # Always check for load more after scrolling is complete (regardless of scrolling method)
            print(f"   🔍 Scrolling complete, checking for load more buttons...")
            load_more_clicked = _handle_load_more_button(page, page_url, brand_instance)
            
            # If load more was found and clicked, keep chasing it like pagination elements
            if load_more_clicked:
                print(f"   🎯 Load more button found and clicked, chasing load more until exhausted...")
                
                load_more_click_count = 1
                no_load_more_attempts = 0
                max_load_more_attempts = 2  # Similar to scrolling attempts
                
                while load_more_click_count < 20:  # Reasonable limit to prevent infinite loops
                    # Scroll to bottom first to see if more content loaded
                    current_height = page.evaluate("document.body.scrollHeight")
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(3000)  # Wait for content to load
                    
                    new_height = page.evaluate("document.body.scrollHeight")
                    print(f"   📏 After load more #{load_more_click_count}: height {current_height} → {new_height}")
                    
                    # Try to click load more again
                    additional_click = _handle_load_more_button(page, page_url, brand_instance)
                    
                    if additional_click:
                        load_more_click_count += 1
                        no_load_more_attempts = 0  # Reset attempts counter
                        print(f"   🎯 Load more button clicked again (click #{load_more_click_count})")
                    else:
                        no_load_more_attempts += 1
                        print(f"   ⏳ No load more button found (attempt {no_load_more_attempts}/{max_load_more_attempts})")
                        
                        if no_load_more_attempts >= max_load_more_attempts:
                            print(f"   ✅ No more load more buttons found after {load_more_click_count} clicks")
                            break
                        else:
                            # Wait longer and try again (like traditional scrolling)
                            print(f"   ⏳ Waiting longer for potential load more button...")
                            page.wait_for_timeout(3000)  # Extra wait before retry
            
            # Extract all products once after scrolling complete
            products = _extract_products_from_current_state(
                page, page_url, pattern, brand_name, category_name, seen_urls
            )
            
        finally:
            browser.close()
    
    return {
        "products": products,
        "pagination_triggers_found": list(set(pagination_triggers_found))  # Remove duplicates
    }


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
        
        # Create sorted list for easy indexing by number
        sorted_lineages = sorted(lineage_counter.items(), key=lambda x: x[1], reverse=True)
        
        for i, (lineage, count) in enumerate(sorted_lineages, 1):
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
        if not result or 'valid_lineage_numbers' not in result:
            print(f"   ❌ LLM response missing valid_lineage_numbers - keeping all products")
            return []
        
        valid_lineage_numbers = result['valid_lineage_numbers']
        
        # Convert numbers back to lineage strings using our sorted list
        valid_lineages = []
        for num in valid_lineage_numbers:
            if 1 <= num <= len(sorted_lineages):  # Check bounds
                lineage, count = sorted_lineages[num - 1]  # Convert 1-indexed to 0-indexed
                valid_lineages.append(lineage)
        
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


def _handle_load_more_button(page, page_url: str, brand_instance) -> bool:
    """
    Handle load more button detection and clicking with smart caching.
    
    Args:
        page: Playwright page object
        page_url: Current page URL
        brand_instance: Brand instance to store load more info
        
    Returns:
        bool: True if load more button was clicked, False otherwise
    """
    if not brand_instance:
        return False
    
    # Check brand instance state
    if brand_instance.load_more_detected is None:
        # First time - run detection
        return _detect_and_click_load_more(page, page_url, brand_instance)
    elif brand_instance.load_more_detected == True:
        # Use stored info to click button
        return _click_stored_load_more(page, page_url, brand_instance)
    else:
        # load_more_detected == False - no button found, skip
        return False


def _detect_and_click_load_more(page, page_url: str, brand_instance) -> bool:
    """
    Detect load more button for the first time and store info.
    """
    try:
        print(f"   🔍 First-time load more detection...")
        
        # Common load more button selectors
        load_more_selectors = [
            'button:has-text("Load More")',
            'button:has-text("Show More")',
            'button:has-text("View More")',
            'a:has-text("Load More")',
            'a:has-text("Show More")',
            '[data-action*="load"]',
            '[class*="load-more"]',
            '[class*="show-more"]',
            '[id*="load-more"]',
            '.load-more-button',
            '.show-more-button',
            'button[onclick*="load"]'
        ]
        
        detected_selector = None
        
        # Try each selector
        for selector in load_more_selectors:
            try:
                elements = page.locator(selector)
                if elements.count() > 0 and elements.first.is_visible():
                    detected_selector = selector
                    print(f"   ✅ Load more button found: {selector}")
                    break
            except:
                continue
        
        if detected_selector:
            # Detect any modals that might interfere
            modal_results = bypass_blocking_modals_only(page, page_url)
            
            # Try to click the button first to verify it works
            click_successful = _click_load_more_button(page, detected_selector)
            
            # Only save if click was successful AND this is first time detection
            if click_successful and brand_instance.load_more_detected is None:
                brand_instance.save_load_more_info(detected_selector, modal_results)
                
                # Mark modals as applied since we just applied them
                if modal_results.get('modals_detected', 0) > 0:
                    brand_instance.load_more_modals_applied = True
                
                return True
            elif click_successful:
                # Click worked but we already have load more info - don't overwrite
                print(f"   ✅ Load more button clicked but info already stored - not overwriting")
                return True
            else:
                # Click failed - don't save anything if this is first detection
                if brand_instance.load_more_detected is None:
                    print(f"   ⚠️  Load more button detection failed - selector matches but not clickable")
                    brand_instance.mark_no_load_more()
                return False
        else:
            # No button found - mark as checked
            brand_instance.mark_no_load_more()
            return False
            
    except Exception as e:
        print(f"   ❌ Error during load more detection: {e}")
        brand_instance.mark_no_load_more()
        return False


def _click_stored_load_more(page, page_url: str, brand_instance) -> bool:
    """
    Click load more button using stored information.
    """
    try:
        print(f"   🎯 Using stored load more info...")
        
        # Apply stored modal bypasses only once per session
        if (brand_instance.load_more_modal_bypasses.get('modals_detected', 0) > 0 and 
            not brand_instance.load_more_modals_applied):
            print(f"   🚫 Applying {brand_instance.load_more_modal_bypasses['modals_detected']} stored modal bypasses (first time)...")
            bypass_blocking_modals_only(page, page_url)
            brand_instance.load_more_modals_applied = True
        elif brand_instance.load_more_modals_applied:
            print(f"   ✅ Modal bypasses already applied this session")
        
        # Click the stored button selector
        return _click_load_more_button(page, brand_instance.load_more_button_selector)
        
    except Exception as e:
        print(f"   ❌ Error clicking stored load more button: {e}")
        return False


def _click_load_more_button(page, selector: str) -> bool:
    """
    Actually click the load more button.
    """
    try:
        button = page.locator(selector)
        
        # Verify button still exists and is visible
        if not button.count() or not button.is_visible():
            print(f"   ⚠️  Load more button no longer visible: {selector}")
            return False
            
        if button.is_disabled():
            print(f"   ⚠️  Load more button is disabled: {selector}")
            return False
        
        # Click the button
        button.click(timeout=5000)
        print(f"   ✅ Load more button clicked successfully")
        return True
        
    except Exception as e:
        print(f"   ❌ Failed to click load more button: {e}")
        return False


def _smart_scroll_to_pagination_or_bottom(page):
    """
    Smart scrolling that finds ONE pagination trigger, scrolls to it, then to page bottom.
    This handles sites that have lazy loading pagination triggers in the middle with footer content below.
    Has nothing to do with load more buttons - this is purely for lazy loading triggers.
    
    Returns:
        str or None: The selector of the pagination trigger found, or None if none found
    """
    try:
        # Define common lazy loading pagination trigger selectors
        pagination_trigger_selectors = [
            # Common pagination containers (triggers lazy loading when visible)
            '.pagination',
            '.pager', 
            '.page-navigation',
            '[class*="pagination"]',
            '[class*="pager"]',
            
            # Infinite scroll triggers
            '.infinite-scroll',
            '.scroll-trigger', 
            '[class*="infinite"]',
            '[class*="scroll-trigger"]',
            '[data-infinite]',
            
            # Generic navigation containers
            'nav[role="navigation"]',
            '[role="navigation"]',
            '.nav-pagination',
            '.pagination-wrapper'
        ]
        
        # Find the FIRST pagination trigger
        for selector in pagination_trigger_selectors:
            try:
                elements = page.locator(selector)
                if elements.count() > 0:
                    # Get the last element (usually closest to more content)
                    trigger_element = elements.last
                    if trigger_element.is_visible():
                        # Step 1: Scroll to trigger to activate lazy loading
                        trigger_element.scroll_into_view()
                        page.wait_for_timeout(1000)  # Wait for lazy loading activation
                        
                        # Step 2: Then scroll to the very bottom
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        
                        return selector  # Return the found trigger
            except:
                continue
        
        # No pagination triggers found - just scroll to bottom
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        return None
            
    except Exception:
        # Fallback to normal scroll on any error
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        return None


def _detect_pagination_element(page):
    """
    Detect if pagination elements exist on the page (one-time detection).
    
    Returns:
        str or None: The selector of the first pagination element found, or None
    """
    try:
        pagination_trigger_selectors = [
            '.pagination',
            '.pager', 
            '.page-navigation',
            '[class*="pagination"]',
            '[class*="pager"]',
            '.infinite-scroll',
            '.scroll-trigger', 
            '[class*="infinite"]',
            '[class*="scroll-trigger"]',
            '[data-infinite]',
            'nav[role="navigation"]',
            '[role="navigation"]',
            '.nav-pagination',
            '.pagination-wrapper'
        ]
        
        # Find the FIRST pagination element
        for selector in pagination_trigger_selectors:
            try:
                elements = page.locator(selector)
                if elements.count() > 0 and elements.last.is_visible():
                    return selector  # Return the first found selector
            except:
                continue
        
        return None
    except Exception:
        return None


def _scroll_using_pagination_element(page, pagination_selector, pagination_triggers_found):
    """
    Pagination-based scrolling: Keep scrolling to pagination element until it stops moving.
    """
    try:
        scroll_count = 0
        last_pagination_position = None
        stable_count = 0
        max_stable_attempts = 3
        
        print(f"   🎯 Using pagination element as scroll target: {pagination_selector}")
        
        while True:
            scroll_count += 1
            
            # Get pagination element position before scrolling
            pagination_element = page.locator(pagination_selector).last
            if not pagination_element.is_visible():
                print(f"   ❌ Pagination element no longer visible after {scroll_count} scrolls")
                break
                
            pagination_position = pagination_element.bounding_box()
            if not pagination_position:
                print(f"   ❌ Cannot get pagination element position after {scroll_count} scrolls")
                break
                
            current_pagination_y = pagination_position['y'] + pagination_position['height']
            page_bottom = page.evaluate("document.body.scrollHeight")
            
            print(f"   📏 Scroll #{scroll_count}: Pagination at {current_pagination_y:.0f}px, page bottom {page_bottom}px")
            
            # Check if pagination element has stopped moving
            if last_pagination_position is not None:
                position_diff = abs(current_pagination_y - last_pagination_position)
                if position_diff < 10:  # Element hasn't moved significantly
                    stable_count += 1
                    print(f"   ⏸️  Pagination element stable (attempt {stable_count}/{max_stable_attempts})")
                    if stable_count >= max_stable_attempts:
                        print(f"   ✅ Pagination element stopped moving after {scroll_count} scrolls")
                        break
                else:
                    stable_count = 0  # Reset if element moved
            
            # Scroll to pagination element
            pagination_element.scroll_into_view_if_needed()
            page.wait_for_timeout(2000)  # Wait for content to load
            
            last_pagination_position = current_pagination_y
            
            # Safety check to prevent infinite loops
            if scroll_count > 50:
                print(f"   ⚠️  Reached maximum scroll attempts ({scroll_count})")
                break
                
    except Exception as e:
        print(f"   ❌ Error in pagination scrolling: {e}")


def _scroll_to_pagination_element(page, pagination_selector):
    """
    Scroll to pagination element and STOP there. 
    The pagination element becomes our scrolling target instead of page bottom.
    """
    try:
        # Scroll to pagination element
        pagination_element = page.locator(pagination_selector).last
        if pagination_element.is_visible():
            # Get pagination element position
            pagination_position = pagination_element.bounding_box()
            if pagination_position:
                page_bottom = page.evaluate("document.body.scrollHeight")
                pagination_y = pagination_position['y'] + pagination_position['height']
                distance_to_bottom = page_bottom - pagination_y
                print(f"   📍 Pagination element at {pagination_y:.0f}px, page bottom at {page_bottom}px")
                print(f"   📏 Distance from pagination to bottom: {distance_to_bottom:.0f}px")
                
                # ONLY scroll to pagination element - DO NOT scroll to bottom  
                pagination_element.scroll_into_view_if_needed()
                page.wait_for_timeout(1000)  # Wait for lazy loading activation
                
                # Check if scrolling to pagination triggered new content
                new_page_bottom = page.evaluate("document.body.scrollHeight")
                if new_page_bottom != page_bottom:
                    print(f"   🎯 Scrolling to pagination triggered content: {page_bottom} → {new_page_bottom}")
                else:
                    print(f"   📄 Scrolling to pagination - no new content triggered")
            else:
                # If we can't get position, just scroll to the element
                pagination_element.scroll_into_view()
        else:
            # Fallback to bottom if pagination element not visible
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    except Exception:
        # Fallback to normal scroll
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")