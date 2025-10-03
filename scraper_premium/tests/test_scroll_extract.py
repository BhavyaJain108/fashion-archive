#!/usr/bin/env python3
"""
Test Scroll and Extract
========================

Takes a product page URL and:
1. Detects the product pattern
2. Scrolls through the page incrementally
3. Extracts products from each scroll chunk
4. Reports detailed metrics
"""

import sys
import os
import time
from typing import Dict, Any

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brand import Brand
from page_extractor import extract_products_from_page
from urllib.parse import urlparse


def test_scroll_and_extract(page_url: str, brand_name: str = None) -> Dict[str, Any]:
    """
    Test scrolling and product extraction on a single page.
    
    Args:
        page_url: URL of the product listing page
        brand_name: Optional brand name for context
        
    Returns:
        Dict with test results and metrics
    """
    # Extract base URL for brand initialization
    parsed = urlparse(page_url)
    brand_url = f"{parsed.scheme}://{parsed.netloc}"
    
    if not brand_name:
        brand_name = parsed.netloc.replace('www.', '').split('.')[0]
    
    print(f"\n{'='*80}")
    print(f"SCROLL & EXTRACT TEST: {brand_name}")
    print(f"{'='*80}")
    print(f"Page URL: {page_url}")
    print(f"Base URL: {brand_url}")
    print("="*80)
    
    # Initialize brand and pattern
    brand = Brand(brand_url)
    brand.starting_pages_queue = [page_url]
    
    # Step 1: Detect pattern
    print("\n📍 STEP 1: Pattern Detection")
    print("-"*40)
    start_time = time.time()
    
    pattern_result = brand.analyze_product_pattern()
    pattern_time = time.time() - start_time
    
    if not pattern_result or not brand.product_extraction_pattern:
        print(f"❌ Pattern detection failed after {pattern_time:.2f}s")
        return {"success": False, "error": "Pattern detection failed"}
    
    pattern = brand.product_extraction_pattern
    print(f"✅ Pattern detected in {pattern_time:.2f}s")
    
    # Step 2: Scroll and extract products
    print(f"\n📍 STEP 2: Scrolling & Extraction")
    print("-"*40)
    
    results = {
        "brand": brand_name,
        "url": page_url,
        "pattern": pattern,
        "chunks": [],
        "products": [],
        "metrics": {}
    }
    
    try:
        print(f"Loading page...")
        
        # Use the new stateless extraction function
        result = extract_products_from_page(page_url, [pattern], brand_name)
        
        if result["success"]:
            products = result["products"]
            extraction_time = result["metrics"]["extraction_time"]
            patterns_tried = result["metrics"]["patterns_tried"]
            
            print(f"✅ Extraction complete: {len(products)} products in {extraction_time:.1f}s (tried {patterns_tried} patterns)")
            
            # Convert to expected format
            results["products"] = products
            results["chunks"] = [{
                "scroll": 1,
                "new_products": len(products),
                "cumulative_products": len(products),
                "time": extraction_time
            }]
            
            scroll_count = 1  # Simplified for new architecture
            
        else:
            print(f"❌ Extraction failed: {result.get('error', 'Unknown error')}")
            scroll_count = 0
            
    except Exception as e:
        print(f"❌ Error during scrolling: {e}")
        results["error"] = str(e)
    
    # Step 3: Summary
    total_products = len(results["products"])
    unique_products = total_products  # No deduplication in new architecture
    
    print(f"\n✅ Extraction Complete: {unique_products} unique products from {scroll_count} scrolls")
    
    # Store metrics without detailed breakdown
    
    # Store metrics without printing
    
    results["success"] = True
    results["metrics"] = {
        "total_scrolls": scroll_count,
        "total_products": total_products,
        "unique_products": unique_products,
        "pattern_detection_time": pattern_time,
        "total_time": time.time() - start_time
    }
    
    return results


def test_multiple_pages():
    """Test multiple product pages"""
    

    
    test_pages = [
        {
            "name": "Jukuhara - T-Shirts",
            "url": "https://jukuhara.jp/collections/t-shirts-compressions"
        },
        {
            "name": "Entire Studios - AW25 Pre",
            "url": "https://www.entirestudios.com/uniform/all"
        },
        {
            "name": "Iconaclub - Crewnecks",
            "url": "https://iconaclub.com/collections/crewnecks"
        }
    ]
    
    print("\n" + "="*80)
    print("MULTI-PAGE SCROLL & EXTRACT TEST")
    print("="*80)
    
    all_results = []
    
    for test_page in test_pages:
        result = test_scroll_and_extract(
            page_url=test_page["url"],
            brand_name=test_page["name"]
        )
        all_results.append(result)
        
        # Brief pause between tests
        time.sleep(2)
    
    # Final summary
    print("\n" + "="*80)
    print("FINAL SUMMARY")
    print("="*80)
    
    successful = sum(1 for r in all_results if r.get("success", False))
    print(f"✅ Successful: {successful}/{len(all_results)}")
    
    print("\n📊 Results Overview:")
    print(f"{'Brand':<30} {'Products':<10} {'Scrolls':<10} {'Time (s)':<10}")
    print("-"*60)
    
    for result in all_results:
        if result.get("success"):
            brand = result["brand"][:30]
            products = result["metrics"]["unique_products"]
            scrolls = result["metrics"]["total_scrolls"]
            total_time = result["metrics"]["total_time"]
            print(f"{brand:<30} {products:<10} {scrolls:<10} {total_time:<10.2f}")
        else:
            brand = result.get("brand", "Unknown")[:30]
            print(f"{brand:<30} {'FAILED':<10} {'-':<10} {'-':<10}")
    
    return all_results


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        # Test a specific URL passed as argument
        url = sys.argv[1]
        brand = sys.argv[2] if len(sys.argv) > 2 else None
        test_scroll_and_extract(url, brand)
    else:
        # Run default test suite
        test_multiple_pages()