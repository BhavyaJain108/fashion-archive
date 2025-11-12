"""
Page Product Extractor
=====================

Pure functions for extracting products from individual pages.
No shared state, designed for parallel processing.
"""

import time
from typing import Dict, List, Any, Optional
from datetime import datetime
from urllib.parse import urljoin, urlparse
from playwright.sync_api import sync_playwright
from collections import Counter
from llm_handler import LLMHandler
from prompts import lineage_selection
from prompts import pagination_detection
# Import modal bypass for load more functionality
try:
    from scraper_premium.modal_bypass_engine import bypass_blocking_modals_only
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
        pagination_detected = extraction_result.get("pagination_detected", {})
        
        # Apply lineage filtering if we have multiple products
        lineage_filtering_start = time.time()
        products_before_filtering = len(products)
        if len(products) > 1:
            filtered_products = apply_lineage_filtering(products, page_url, category_name, brand_instance)
            if filtered_products:  # Only use filtered results if filtering succeeded
                # Store approved lineages in brand instance for cross-page filtering
                if brand_instance:
                    approved_lineages = {product.get("full_lineage") for product in filtered_products if product.get("full_lineage")}
                    brand_instance.store_lineage_memory(page_url, set(), approved_lineages)
                    print(f"   💾 Stored {len(approved_lineages)} approved lineage patterns for cross-page filtering")
                
                products = filtered_products
        lineage_filtering_time = time.time() - lineage_filtering_start
        
        result["products"] = products
        result["success"] = len(products) > 0
        result["pagination_triggers_found"] = pagination_triggers_found
        result["pagination_detected"] = pagination_detected
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


def _extract_with_scrolling(page_url: str, pattern: Dict[str, str], brand_name: str, category_name: str, brand_instance=None, skip_more_links_detection: bool = False) -> Dict[str, Any]:
    """
    Internal function to handle the actual scrolling and extraction logic.
    """
    products = []
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
            
            # Initialize scrolling variables
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
            
            # More Links: Detect pagination after all scrolling is complete (skip for pages 2+)
            if not skip_more_links_detection:
                pagination_detection_result = _detect_post_scroll_pagination(page, page_url)
            else:
                print(f"   ⏩ Skipping More Links detection for additional page")
                pagination_detection_result = {
                    "pagination_found": False,
                    "url_pattern": None,
                    "max_page_detected": None,
                    "next_page_url": None,
                    "reasoning": "Skipped for additional page"
                }
            
            # Extract all products once after scrolling complete
            products = _extract_products_from_current_state(
                page, page_url, pattern, brand_name, category_name
            )
            
        finally:
            browser.close()
    
    return {
        "products": products,
        "pagination_triggers_found": list(set(pagination_triggers_found)),  # Remove duplicates
        "pagination_detected": pagination_detection_result  # NEW: More Links output
    }


def extract_multi_page_products(page_url: str, pattern: Dict[str, str], brand_name: str, 
                               category_name: str = None, 
                               brand_instance = None, pagination_result: Dict = None) -> Dict[str, Any]:
    """
    Extract products from multiple pages after More Links detection
    
    Args:
        page_url: Base category URL (page 1)
        pattern: Product extraction pattern from page 1
        brand_name: Brand name for extraction
        category_name: Category name for extraction
        brand_instance: Brand instance with learned patterns from page 1
        pagination_result: More Links detection result from page 1
        
    Returns:
        Dict with aggregated products from all pages and extraction stats
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from urllib.parse import urlparse, parse_qs
    import time
    
    if not pagination_result or not pagination_result.get("pagination_found"):
        return {
            "products": [],
            "pages_extracted": 0,
            "total_products_found": 0,
            "per_page_stats": [],
            "lineage_memory": {"rejected_lineages": set()}
        }
    
    print(f"\n🔗 Multi-Page Extraction Starting...")
    
    # Generate page URLs
    page_urls = _generate_page_urls(page_url, pagination_result)
    if not page_urls:
        print(f"   📄 No additional pages to extract")
        return {
            "products": [],
            "pages_extracted": 0,
            "total_products_found": 0,
            "per_page_stats": [],
            "lineage_memory": {"rejected_lineages": set()}
        }
    
    print(f"   📊 Extracting from {len(page_urls)} additional pages: {page_urls}")
    
    # Initialize lineage memory (will be populated from page 1 results)
    lineage_memory = {
        "rejected_lineages": set(),
        "pattern_used": pattern
    }
    
    # Extract from all pages in parallel
    all_products = []
    per_page_stats = []
    
    start_time = time.time()
    
    # Concurrent extraction: Parallel (known pages) + Sequential (beyond max)
    max_workers = min(len(page_urls) + 3, 8)  # Allow extra workers for sequential fallback
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all known page extraction tasks (parallel)
        future_to_info = {}
        for i, url in enumerate(page_urls):
            future = executor.submit(
                _extract_single_additional_page,
                url, pattern, brand_name, category_name, brand_instance, 
                lineage_memory, i + 2  # Page numbers start from 2
            )
            future_to_info[future] = {"url": url, "page_num": i + 2, "source": "parallel"}
        
        # Submit sequential fallback task (concurrent with parallel)
        fallback_future = None
        if pagination_result.get("max_page_detected"):
            max_page_detected = pagination_result["max_page_detected"]
            fallback_future = executor.submit(
                _concurrent_sequential_fallback,
                page_url, pattern, brand_name, category_name, brand_instance,
                lineage_memory, pagination_result, max_page_detected
            )
            future_to_info[fallback_future] = {"source": "sequential_fallback"}
        
        # Collect results as they complete
        pages_with_products = 0
        parallel_complete = False
        
        for future in as_completed(future_to_info):
            info = future_to_info[future]
            source = info.get("source")
            
            try:
                if source == "parallel":
                    # Handle parallel extraction result
                    page_result = future.result()
                    products_found = len(page_result["products"])
                    page_num = info["page_num"]
                    url = info["url"]
                    
                    if products_found > 0:
                        all_products.extend(page_result["products"])
                        pages_with_products += 1
                        print(f"   ✅ Page {page_num}: {products_found} products extracted")
                    else:
                        print(f"   📄 Page {page_num}: 0 products detected")
                    
                    per_page_stats.append({
                        "page_num": page_num,
                        "url": url,
                        "products_found": products_found,
                        "extraction_time": page_result.get("extraction_time", 0),
                        "source": "parallel"
                    })
                    
                elif source == "sequential_fallback":
                    # Handle sequential fallback results
                    fallback_results = future.result()
                    if fallback_results:
                        print(f"   🔄 Sequential fallback completed: {len(fallback_results)} additional pages processed")
                        for result in fallback_results:
                            if result.get("products"):
                                all_products.extend(result["products"])
                        per_page_stats.extend(fallback_results)
                    
            except Exception as e:
                if source == "parallel":
                    page_num = info["page_num"]
                    url = info["url"]
                    print(f"   ❌ Page {page_num} extraction failed: {e}")
                    per_page_stats.append({
                        "page_num": page_num,
                        "url": url,
                        "products_found": 0,
                        "error": str(e),
                        "source": "parallel"
                    })
                else:
                    print(f"   ❌ Sequential fallback failed: {e}")
    
    total_time = time.time() - start_time
    
    # Deduplicate products by URL (products might appear on multiple pages)
    seen_urls = set()
    unique_products = []
    for product in all_products:
        product_url = product.get("product_url", "")
        if product_url and product_url not in seen_urls:
            seen_urls.add(product_url)
            unique_products.append(product)
    
    duplicates_removed = len(all_products) - len(unique_products)
    
    print(f"   📊 Multi-page extraction complete:")
    print(f"      • Pages processed: {len(per_page_stats)}")
    print(f"      • Total products: {len(all_products)} ({duplicates_removed} duplicates removed)")
    print(f"      • Unique products: {len(unique_products)}")
    print(f"      • Total time: {total_time:.2f}s")
    
    return {
        "products": unique_products,
        "pages_extracted": len(per_page_stats),
        "total_products_found": len(unique_products),
        "per_page_stats": per_page_stats,
        "lineage_memory": lineage_memory,
        "total_extraction_time": total_time,
        "duplicates_removed": duplicates_removed
    }


def _sequential_fallback_extraction(base_url: str, pattern: Dict[str, str], brand_name: str, 
                                   category_name: str, brand_instance, lineage_memory: Dict,
                                   pagination_result: Dict, highest_page_processed: int) -> List[Dict]:
    """
    Sequential fallback extraction: continue beyond detected max until 0 products or 404
    
    Args:
        base_url: Base category URL (page 1)
        pattern: Product extraction pattern
        brand_name: Brand name for extraction
        category_name: Category name for extraction
        brand_instance: Brand instance with learned patterns
        lineage_memory: Shared lineage memory from parallel extraction
        pagination_result: More Links detection result with url_pattern
        highest_page_processed: Highest page number from parallel phase
        
    Returns:
        List of page stats from sequential extraction
    """
    url_pattern = pagination_result.get("url_pattern")
    max_page_detected = pagination_result.get("max_page_detected")
    
    if not url_pattern or not max_page_detected:
        return []
    
    print(f"\n🔄 Sequential Fallback: Checking pages beyond detected max ({max_page_detected})...")
    
    fallback_stats = []
    current_page_num = highest_page_processed + 1
    consecutive_failures = 0
    max_consecutive_failures = 3
    
    while consecutive_failures < max_consecutive_failures:
        try:
            # Generate next page URL using same logic as _generate_page_urls
            if "?page=X" in url_pattern:
                next_page_url = base_url.split("?")[0] + f"?page={current_page_num}"
            elif "/page/X/" in url_pattern:
                next_page_url = base_url.rstrip("/") + f"/page/{current_page_num}/"
            elif "/page/X" in url_pattern:
                next_page_url = base_url.rstrip("/") + f"/page/{current_page_num}"
            elif "?p=X" in url_pattern:
                next_page_url = base_url.split("?")[0] + f"?p={current_page_num}"
            else:
                # Custom pattern - replace X with page number
                next_page_url = base_url + url_pattern.replace("X", str(current_page_num))
            
            print(f"   🔍 Testing page {current_page_num}: {next_page_url}")
            
            # Extract from this page using existing function
            page_result = _extract_single_additional_page(
                next_page_url, pattern, brand_name, category_name, 
                brand_instance, lineage_memory, current_page_num
            )
            
            products_found = len(page_result.get("products", []))
            
            if products_found > 0:
                print(f"   ✅ Page {current_page_num}: {products_found} products found - continuing")
                fallback_stats.append({
                    "page_num": current_page_num,
                    "url": next_page_url,
                    "products_found": products_found,
                    "extraction_time": page_result.get("extraction_time", 0),
                    "source": "sequential_fallback",
                    "products": page_result.get("products", [])  # Include products for aggregation
                })
                consecutive_failures = 0  # Reset failure counter
            else:
                print(f"   📄 Page {current_page_num}: 0 products - fallback complete")
                fallback_stats.append({
                    "page_num": current_page_num,
                    "url": next_page_url,
                    "products_found": 0,
                    "extraction_time": page_result.get("extraction_time", 0),
                    "source": "sequential_fallback"
                })
                break  # Stop when we hit a page with 0 products
                
        except Exception as e:
            print(f"   ❌ Page {current_page_num}: Failed ({str(e)[:50]}...) - counting as failure")
            consecutive_failures += 1
            fallback_stats.append({
                "page_num": current_page_num,
                "url": next_page_url if 'next_page_url' in locals() else f"page_{current_page_num}",
                "products_found": 0,
                "error": str(e),
                "source": "sequential_fallback"
            })
            
            # If it's a 404-like error, stop immediately
            if "404" in str(e) or "not found" in str(e).lower():
                print(f"   🚫 Page {current_page_num}: 404 detected - fallback complete")
                break
        
        current_page_num += 1
        
        # Safety limit: don't go beyond 50 pages beyond detected max
        if current_page_num > max_page_detected + 50:
            print(f"   🛑 Reached safety limit (page {current_page_num}) - stopping fallback")
            break
    
    if consecutive_failures >= max_consecutive_failures:
        print(f"   🛑 Sequential fallback stopped after {max_consecutive_failures} consecutive failures")
    
    return fallback_stats


def _concurrent_sequential_fallback(base_url: str, pattern: Dict[str, str], brand_name: str, 
                                   category_name: str, brand_instance, lineage_memory: Dict,
                                   pagination_result: Dict, max_page_detected: int) -> List[Dict]:
    """
    Concurrent sequential fallback: extract pages beyond detected max (thread-safe)
    
    This runs concurrently with parallel extraction of known pages.
    Starts from max_page_detected + 1 and continues until 0 products or 404.
    """
    url_pattern = pagination_result.get("url_pattern")
    
    if not url_pattern:
        return []
    
    print(f"   🔄 Starting concurrent sequential fallback from page {max_page_detected + 1}...")
    
    fallback_results = []
    current_page_num = max_page_detected + 1
    consecutive_failures = 0
    max_consecutive_failures = 3
    
    while consecutive_failures < max_consecutive_failures:
        try:
            # Generate next page URL
            if "?page=X" in url_pattern:
                next_page_url = base_url.split("?")[0] + f"?page={current_page_num}"
            elif "/page/X/" in url_pattern:
                next_page_url = base_url.rstrip("/") + f"/page/{current_page_num}/"
            elif "/page/X" in url_pattern:
                next_page_url = base_url.rstrip("/") + f"/page/{current_page_num}"
            elif "?p=X" in url_pattern:
                next_page_url = base_url.split("?")[0] + f"?p={current_page_num}"
            else:
                # Custom pattern - replace X with page number
                next_page_url = base_url + url_pattern.replace("X", str(current_page_num))
            
            print(f"   🔍 Fallback testing page {current_page_num}: {next_page_url}")
            
            # Extract from this page
            page_result = _extract_single_additional_page(
                next_page_url, pattern, brand_name, category_name, 
                brand_instance, lineage_memory, current_page_num
            )
            
            raw_products = page_result.get("products", [])
            products_before_filtering = len(raw_products)
            
            # Apply lineage filtering to validate these are real products (not recommendations)
            if raw_products:
                print(f"   🔍 Fallback page {current_page_num}: {products_before_filtering} raw products, applying lineage filtering...")
                
                # Extract category name for lineage filtering
                from urllib.parse import urlparse
                category_for_filtering = extract_category_name(next_page_url)
                
                # Filter using approved lineages from page 1
                if brand_instance and brand_instance.has_lineage_memory(base_url):
                    lineage_memory = brand_instance.get_lineage_memory(base_url)
                    approved_lineages = lineage_memory.get("approved_lineages", set())
                    
                    if approved_lineages:
                        # Only keep products with approved lineages
                        filtered_products = [
                            product for product in raw_products 
                            if product.get("full_lineage") in approved_lineages
                        ]
                        print(f"   🎯 Fallback page {current_page_num}: {len(filtered_products)}/{products_before_filtering} products match approved lineages")
                    else:
                        # No approved lineages stored, keep all products
                        filtered_products = raw_products
                        print(f"   ⚠️  Fallback page {current_page_num}: No approved lineages stored, keeping all products")
                else:
                    # No lineage memory, keep all products  
                    filtered_products = raw_products
                    print(f"   ⚠️  Fallback page {current_page_num}: No lineage memory, keeping all products")
                
                products_found = len(filtered_products)
                
                if products_found > 0:
                    print(f"   ✅ Fallback page {current_page_num}: {products_found}/{products_before_filtering} valid products after filtering - continuing")
                    fallback_results.append({
                        "page_num": current_page_num,
                        "url": next_page_url,
                        "products_found": products_found,
                        "products_before_filtering": products_before_filtering,
                        "extraction_time": page_result.get("extraction_time", 0),
                        "source": "concurrent_sequential",
                        "products": filtered_products
                    })
                    consecutive_failures = 0
                else:
                    print(f"   📄 Fallback page {current_page_num}: 0 valid products after lineage filtering - fallback complete")
                    fallback_results.append({
                        "page_num": current_page_num,
                        "url": next_page_url,
                        "products_found": 0,
                        "products_before_filtering": products_before_filtering,
                        "extraction_time": page_result.get("extraction_time", 0),
                        "source": "concurrent_sequential"
                    })
                    break
            else:
                print(f"   📄 Fallback page {current_page_num}: 0 products - fallback complete")
                fallback_results.append({
                    "page_num": current_page_num,
                    "url": next_page_url,
                    "products_found": 0,
                    "products_before_filtering": 0,
                    "extraction_time": page_result.get("extraction_time", 0),
                    "source": "concurrent_sequential"
                })
                break
                
        except Exception as e:
            print(f"   ❌ Fallback page {current_page_num}: Failed ({str(e)[:50]}...)")
            consecutive_failures += 1
            fallback_results.append({
                "page_num": current_page_num,
                "url": next_page_url if 'next_page_url' in locals() else f"page_{current_page_num}",
                "products_found": 0,
                "error": str(e),
                "source": "concurrent_sequential"
            })
            
            # If it's a 404-like error, stop immediately
            if "404" in str(e) or "not found" in str(e).lower():
                print(f"   🚫 Fallback page {current_page_num}: 404 detected - fallback complete")
                break
        
        current_page_num += 1
        
        # Safety limit: don't go beyond 50 pages beyond detected max
        if current_page_num > max_page_detected + 50:
            print(f"   🛑 Fallback reached safety limit (page {current_page_num}) - stopping")
            break
    
    return fallback_results


def _generate_page_urls(base_url: str, pagination_result: Dict) -> List[str]:
    """Generate URLs for additional pages based on More Links detection"""
    page_urls = []
    
    url_pattern = pagination_result.get("url_pattern")
    max_page = pagination_result.get("max_page_detected")
    next_page_url = pagination_result.get("next_page_url")
    
    if max_page and url_pattern:
        # Generate numbered pages 2 through max_page
        for page_num in range(2, max_page + 1):
            if "?page=X" in url_pattern:
                page_url = base_url.split("?")[0] + f"?page={page_num}"
            elif "/page/X/" in url_pattern:
                page_url = base_url.rstrip("/") + f"/page/{page_num}/"
            elif "/page/X" in url_pattern:
                page_url = base_url.rstrip("/") + f"/page/{page_num}"
            elif "?p=X" in url_pattern:
                page_url = base_url.split("?")[0] + f"?p={page_num}"
            else:
                # Custom pattern - replace X with page number
                page_url = base_url + url_pattern.replace("X", str(page_num))
            
            page_urls.append(page_url)
    
    elif next_page_url:
        # For sequential pagination, we'll only return the immediate next page
        # The extraction will continue sequentially until 0 products
        page_urls.append(next_page_url)
    
    return page_urls


def _extract_single_additional_page(page_url: str, pattern: Dict[str, str], brand_name: str, 
                                   category_name: str, brand_instance, lineage_memory: Dict, 
                                   page_num: int) -> Dict[str, Any]:
    """
    Extract products from a single additional page (reuses main extraction function)
    
    This function calls the main _extract_with_scrolling with optimizations for pages 2+
    """
    start_time = time.time()
    
    try:
        print(f"   🌐 Page {page_num}: Extracting from {page_url}")
        
        # Call the main extraction function with optimizations
        # This will include Phase 1 (pagination scrolling), Phase 2 (height), Phase 3 (load more)
        # But skip More Links detection
        result = _extract_with_scrolling(
            page_url, pattern, brand_name, category_name, 
            brand_instance=brand_instance,   # Use learned patterns
            skip_more_links_detection=True  # Skip More Links detection
        )
        
        products = result.get("products", [])
        
        # Apply lineage filtering if we have rejected lineages in memory
        if lineage_memory.get("rejected_lineages") and products:
            # TODO: Apply lineage filtering here using brand instance
            pass
        
        extraction_time = time.time() - start_time
        
        return {
            "products": products,
            "extraction_time": extraction_time
        }
        
    except Exception as e:
        print(f"   ❌ Page {page_num}: Extraction failed - {e}")
        return {
            "products": [],
            "extraction_time": time.time() - start_time,
            "error": str(e)
        }


def _extract_products_from_current_state(page, page_url: str, pattern: Dict[str, str], 
                                       brand_name: str, category_name: str) -> List[Dict[str, Any]]:
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
            
        except Exception:
            # Skip problematic products but continue
            continue
    
    return products


def apply_lineage_filtering(products: List[Dict[str, Any]], page_url: str, category_name: str, brand_instance=None) -> List[Dict[str, Any]]:
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
        # First, filter out any globally rejected lineages from brand memory
        if brand_instance:
            all_rejected_lineages = set()
            # Collect rejected lineages from all categories 
            for category_memory in brand_instance.lineage_memory.values():
                all_rejected_lineages.update(category_memory.get("rejected_lineages", set()))
            
            if all_rejected_lineages:
                initial_count = len(products)
                products = [
                    product for product in products 
                    if product.get('full_lineage') not in all_rejected_lineages
                ]
                filtered_count = len(products)
                if filtered_count < initial_count:
                    print(f"   🚫 Pre-filtered {initial_count - filtered_count} products with globally rejected lineages")
        
        # Count lineage frequencies from remaining products
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
        
        # Store rejected lineages globally in brand instance for future categories
        if brand_instance:
            all_lineages = set(lineage_counter.keys())
            rejected_lineages = all_lineages - valid_lineages_set
            if rejected_lineages:
                brand_instance.store_lineage_memory(page_url, rejected_lineages, valid_lineages_set)
                print(f"   💾 Stored {len(rejected_lineages)} rejected lineages globally for future categories")
        
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





def extract_multiple_pages(page_urls: List[str], patterns: List[Dict[str, str]], brand_name: str = None) -> List[Dict[str, Any]]:
    """
    Extract products from multiple pages sequentially.
    
    Args:
        page_urls: List of page URLs to extract from
        patterns: Product extraction patterns
        brand_name: Optional brand name
        
    Returns:
        List of extraction results, one per page
    """
    results = []
    
    for page_url in page_urls:
        print(f"  🔄 Processing: {extract_category_name(page_url)}")
        result = extract_products_from_page(page_url, patterns, brand_name, allow_pattern_discovery=True)
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


def _detect_post_scroll_pagination(page, page_url: str) -> Dict[str, Any]:
    """
    More Links: Detect pagination after all scrolling is complete (detection only)
    
    Args:
        page: Playwright page object (after all scrolling complete)
        page_url: Current category URL
        
    Returns:
        Dict containing:
        - pagination_found: bool
        - url_pattern: "?page=X" | "/page/X/" | None  
        - max_page_detected: int | None
        - next_page_url: str | None (if no max detected)
        - reasoning: str
    """
    result = {
        "pagination_found": False,
        "url_pattern": None,
        "max_page_detected": None, 
        "next_page_url": None,
        "reasoning": "No analysis performed"
    }
    
    try:
        print(f"   🔍 More Links: Detecting post-scroll pagination patterns...")
        
        # Extract bottom section links (last 30% of page)
        bottom_links = _extract_bottom_page_links(page, page_url)
        
        if not bottom_links:
            result["reasoning"] = "No links found in bottom section of page"
            print(f"   📄 No bottom links found - single page category")
            return result
            
        print(f"   📊 Analyzing {len(bottom_links)} bottom section links for pagination")
        
        # Debug: Print ALL bottom links for inspection
        print(f"   🔗 Complete bottom 30% links ({len(bottom_links)} total):")
        for i, link in enumerate(bottom_links):
            print(f"      {i+1}. {link}")
        
        # Filter links to only include those related to current category
        category_filtered_links = _filter_links_by_category(bottom_links, page_url)
        print(f"   🎯 Category-filtered links ({len(category_filtered_links)} remain after filtering):")
        for i, link in enumerate(category_filtered_links):
            print(f"      {i+1}. {link}")
        
        # Debug: Identify potential pagination candidates from filtered links
        pagination_candidates = []
        for link in category_filtered_links:
            if any(pattern in link.lower() for pattern in ['page=', '/page/', '?p=', 'next', 'prev']):
                pagination_candidates.append(link)
        
        if pagination_candidates:
            print(f"   🎯 Pagination candidates in category links ({len(pagination_candidates)} total):")
            for i, candidate in enumerate(pagination_candidates):
                print(f"      • {candidate}")
        else:
            print(f"   📄 No obvious pagination candidates found in category-filtered links")
        
        # Use LLM to analyze pagination pattern (using filtered links)
        from prompts.pagination_detection import get_prompt, get_response_model
        
        llm_handler = LLMHandler()
        prompt = get_prompt(page_url, category_filtered_links)
        llm_response = llm_handler.call(prompt, expected_format="json", response_model=get_response_model())
        
        if llm_response.get("success", False):
            data = llm_response.get("data", {})
            
            result.update({
                "pagination_found": data.get("pagination_found", False),
                "url_pattern": data.get("url_template"),
                "max_page_detected": data.get("max_page_detected"),
                "next_page_url": None,  # Will be set below if needed
                "reasoning": data.get("reasoning", "LLM analysis completed")
            })
            
            # If pagination found but no max detected, extract next page URL from filtered links
            if result["pagination_found"] and result["max_page_detected"] is None:
                next_url = _extract_next_page_url(category_filtered_links, page_url, result["url_pattern"])
                result["next_page_url"] = next_url
                
            # Print LLM reasoning for debugging
            reasoning = result.get("reasoning", "No reasoning provided")
            print(f"   🧠 LLM Analysis: {reasoning}")
            
            # Debug: Print the actual result structure
            print(f"   🔍 DEBUG: pagination_found={result.get('pagination_found')}, max_page={result.get('max_page_detected')}, pattern={result.get('url_pattern')}")
            
            # Logging based on detection results
            if result["pagination_found"]:
                if result["max_page_detected"]:
                    print(f"   ✅ Pagination detected: {result['url_pattern']} (max page: {result['max_page_detected']})")
                else:
                    print(f"   ✅ Pagination detected: {result['url_pattern']} (next: {result['next_page_url']})")
            else:
                print(f"   📄 No pagination detected - single page category")
                
        else:
            result["reasoning"] = f"LLM analysis failed: {llm_response.get('error', 'Unknown error')}"
            print(f"   ❌ LLM pagination analysis failed: {llm_response.get('error', 'Unknown error')}")
            
    except Exception as e:
        result["reasoning"] = f"Exception during pagination detection: {str(e)}"
        print(f"   ❌ More Links pagination detection failed: {e}")
        
    return result


def _extract_bottom_page_links(page, base_url: str) -> List[str]:
    """Extract links from bottom 30% section of page"""
    try:
        # Get page dimensions and extract bottom section links
        bottom_links = page.evaluate(f"""
            () => {{
                const pageHeight = document.body.scrollHeight;
                const bottomThreshold = pageHeight * 0.7; // Bottom 30%
                
                // Get all links in DOM order (querySelectorAll preserves document order)
                const allLinks = Array.from(document.querySelectorAll('a[href]'));
                
                // Filter for bottom 30% links while preserving DOM order
                const bottomLinksInOrder = [];
                allLinks.forEach(link => {{
                    const rect = link.getBoundingClientRect();
                    const absoluteTop = rect.top + window.scrollY;
                    
                    if (absoluteTop >= bottomThreshold) {{
                        const href = link.href;
                        if (href && !href.startsWith('javascript:') && !href.startsWith('#')) {{
                            bottomLinksInOrder.push(href);
                        }}
                    }}
                }});
                
                return bottomLinksInOrder;
            }}
        """)
        
        # Filter to same domain only
        from urllib.parse import urlparse
        base_domain = f"{urlparse(base_url).scheme}://{urlparse(base_url).netloc}"
        
        filtered_links = []
        for link in bottom_links:
            if link.startswith(base_domain) or link.startswith('/'):
                if link.startswith('/'):
                    link = urljoin(base_url, link)
                filtered_links.append(link)
        
        # Remove duplicates while preserving order
        seen = set()
        ordered_unique_links = []
        for link in filtered_links:
            if link not in seen:
                seen.add(link)
                ordered_unique_links.append(link)
        
        return ordered_unique_links
        
    except Exception as e:
        print(f"   ⚠️  Error extracting bottom links: {e}")
        return []


def _filter_links_by_category(bottom_links: List[str], current_page_url: str) -> List[str]:
    """Filter bottom links to only include those related to the current category"""
    try:
        from urllib.parse import urlparse, parse_qs
        
        # Parse current page URL to extract category path and parameters
        parsed_current = urlparse(current_page_url)
        current_path = parsed_current.path
        current_params = parse_qs(parsed_current.query)
        
        # Extract category base (remove page parameters)
        category_base_path = current_path
        
        # Build category base URL without page parameters
        category_params = {}
        for key, value in current_params.items():
            # Keep all parameters except pagination ones
            if key.lower() not in ['page', 'p', 'offset', 'start']:
                category_params[key] = value
        
        category_filtered = []
        
        for link in bottom_links:
            parsed_link = urlparse(link)
            
            # Must be same domain and same base path
            if (parsed_link.netloc == parsed_current.netloc and 
                parsed_link.path == category_base_path):
                
                # Check if it's the same category (has same non-pagination parameters)
                link_params = parse_qs(parsed_link.query)
                
                # Remove pagination parameters for comparison
                link_category_params = {}
                for key, value in link_params.items():
                    if key.lower() not in ['page', 'p', 'offset', 'start']:
                        link_category_params[key] = value
                
                # If category parameters match, it's the same category
                if link_category_params == category_params:
                    category_filtered.append(link)
        
        return category_filtered
        
    except Exception as e:
        print(f"   ⚠️  Error filtering category links: {e}")
        # Fallback: return original links
        return bottom_links


def _extract_next_page_url(bottom_links: List[str], current_url: str, url_pattern: str) -> Optional[str]:
    """Extract the actual next page URL when max page is unknown"""
    try:
        # Look for links that match the detected pattern and represent "page 2"
        for link in bottom_links:
            # Check if link matches the pattern for page 2
            if url_pattern == "?page=X" and "?page=2" in link:
                return link
            elif url_pattern == "/page/X/" and "/page/2/" in link:
                return link
            elif url_pattern == "/page/X" and "/page/2" in link and not "/page/2/" in link:
                return link
                
        # Fallback: look for any link with "page=2", "p=2", etc.
        page_2_indicators = ["page=2", "p=2", "/2/", "/2?", "/page/2"]
        for link in bottom_links:
            if any(indicator in link for indicator in page_2_indicators):
                return link
                
        return None
        
    except Exception:
        return None


def _scroll_using_pagination_element(page, pagination_selector, _pagination_triggers_found):
    """
    Pagination-based scrolling: Keep scrolling to pagination element until it stops moving.
    """
    try:
        scroll_count = 0
        last_pagination_position = None
        stable_count = 0
        max_stable_attempts = 2
        
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


