#!/usr/bin/env python3
"""
Test Scroll Extract with Image Downloads
=========================================

Tests product extraction and image downloading together.
Verifies that:
1. Products are extracted with image URLs
2. Images can be successfully downloaded
3. Downloaded images are valid
"""

import sys
import os
import time
import requests
from typing import Dict, Any
from datetime import datetime
from pathlib import Path

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brand import Brand
from page_extractor import extract_products_from_page


def test_scroll_extract_with_images(page_url: str, brand_name: str = None) -> Dict[str, Any]:
    """
    Test scrolling, extraction, and image downloading on a single page.
    
    Args:
        page_url: URL of the product listing page
        brand_name: Optional brand name for context
        
    Returns:
        Dict with test results including image download metrics
    """
    from urllib.parse import urlparse
    
    # Extract base URL for brand initialization
    parsed = urlparse(page_url)
    brand_url = f"{parsed.scheme}://{parsed.netloc}"
    
    if not brand_name:
        brand_name = parsed.netloc.replace('www.', '').split('.')[0]
    
    print(f"\n{'='*80}")
    print(f"SCROLL, EXTRACT & IMAGE DOWNLOAD TEST: {brand_name}")
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
    print(f"   Container: {pattern.get('container_selector', 'N/A')}")
    print(f"   Image: {pattern.get('image_selector', 'N/A')}")
    
    # Step 2: Extract products
    print(f"\n📍 STEP 2: Product Extraction")
    print("-"*40)
    
    extraction_start = time.time()
    result = extract_products_from_page(page_url, [pattern], brand_name)
    extraction_time = time.time() - extraction_start
    
    if not result["success"]:
        print(f"❌ Extraction failed: {result.get('error', 'Unknown error')}")
        return {"success": False, "error": result.get('error')}
    
    products = result["products"]
    print(f"✅ Extracted {len(products)} products in {extraction_time:.1f}s")
    
    # Step 3: Analyze image URLs
    print(f"\n📍 STEP 3: Image URL Analysis")
    print("-"*40)
    
    products_with_images = 0
    products_without_images = 0
    image_urls_seen = set()
    
    for product in products:
        image_url = product.get('image_url', '')
        if image_url and image_url.startswith('http'):
            products_with_images += 1
            image_urls_seen.add(image_url)
        else:
            products_without_images += 1
    
    print(f"📊 Image URL Statistics:")
    print(f"   ✅ Products with images: {products_with_images}")
    print(f"   ❌ Products without images: {products_without_images}")
    print(f"   🔗 Unique image URLs: {len(image_urls_seen)}")
    
    if products_with_images == 0:
        print(f"\n⚠️  WARNING: No image URLs found!")
        print("   This might indicate an issue with image extraction")
        if products[:3]:
            print("\n   Sample products (first 3):")
            for i, p in enumerate(products[:3], 1):
                print(f"   {i}. {p.get('product_name', 'Unknown')}")
                print(f"      URL: {p.get('product_url', 'N/A')}")
                print(f"      Image: {p.get('image_url', 'MISSING')}")
    else:
        # Show sample products with images
        print(f"\n📦 Sample Products with Images (first 3):")
        sample_count = 0
        for product in products:
            if product.get('image_url', '').startswith('http'):
                sample_count += 1
                print(f"   {sample_count}. {product.get('product_name', 'Unknown')}")
                print(f"      Image: {product['image_url'][:80]}...")
                if sample_count >= 3:
                    break
    
    # Step 4: Test image downloads
    print(f"\n📍 STEP 4: Image Download Test")
    print("-"*40)
    
    # Create test directory for images
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    test_dir = f"tests/test_images/{timestamp}_{brand_name.lower()}"
    os.makedirs(test_dir, exist_ok=True)
    
    print(f"Downloading images to: {test_dir}")
    
    # Test downloading first 10 images
    test_limit = min(10, products_with_images)
    download_success = 0
    download_failed = 0
    
    if test_limit > 0:
        print(f"Testing download of first {test_limit} images...")
        
        image_count = 0
        for product in products:
            if image_count >= test_limit:
                break
                
            image_url = product.get('image_url', '')
            if not image_url or not image_url.startswith('http'):
                continue
                
            image_count += 1
            product_name = product.get('product_name', 'unknown')
            product_id = product.get('product_id', f'product_{image_count}')
            
            # Create safe filename
            safe_name = ''.join(c for c in product_name if c.isalnum() or c in ' -_.')[:30]
            safe_id = ''.join(c for c in product_id if c.isalnum() or c in '-_.')[:20]
            
            # Get extension
            ext = '.webp' if '.webp' in image_url else ('.png' if '.png' in image_url else '.jpg')
            filename = f"{safe_name}_{safe_id}{ext}".replace(' ', '_')
            filepath = Path(test_dir) / filename
            
            try:
                # Download image
                response = requests.get(image_url, timeout=10, headers={
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
                })
                response.raise_for_status()
                
                # Save image
                with open(filepath, 'wb') as f:
                    f.write(response.content)
                
                # Verify file was created and has content
                if filepath.exists() and filepath.stat().st_size > 0:
                    download_success += 1
                    print(f"   ✅ {filename} ({filepath.stat().st_size:,} bytes)")
                else:
                    download_failed += 1
                    print(f"   ❌ {filename} (empty file)")
                    
            except Exception as e:
                download_failed += 1
                print(f"   ❌ {filename} ({str(e)[:50]})")
    
    # Step 5: Final Summary
    print(f"\n📊 FINAL SUMMARY")
    print("-"*40)
    print(f"✅ Pattern Detection: Success ({pattern_time:.1f}s)")
    print(f"✅ Product Extraction: {len(products)} products ({extraction_time:.1f}s)")
    print(f"📷 Image URLs: {products_with_images}/{len(products)} products have images")
    if test_limit > 0:
        print(f"💾 Image Downloads: {download_success}/{test_limit} successful")
    print(f"📁 Test images saved to: {test_dir}")
    
    success_rate = (products_with_images / len(products) * 100) if products else 0
    
    return {
        "success": True,
        "brand": brand_name,
        "url": page_url,
        "pattern": pattern,
        "products_extracted": len(products),
        "products_with_images": products_with_images,
        "products_without_images": products_without_images,
        "unique_images": len(image_urls_seen),
        "image_coverage": f"{success_rate:.1f}%",
        "downloads_tested": test_limit,
        "downloads_successful": download_success,
        "downloads_failed": download_failed,
        "test_directory": test_dir,
        "total_time": time.time() - start_time
    }


def test_multiple_brands():
    """Test multiple brands for image extraction"""
    
    test_pages = [
        {
            "name": "Entire Studios - AW25 Collection",
            "url": "https://www.entirestudios.com/collection/aw25-pre/tag:aw25pre"
        },
        {
            "name": "Entire Studios - Uniform",
            "url": "https://www.entirestudios.com/uniform/all"
        },
        {
            "name": "Jukuhara - T-Shirts", 
            "url": "https://jukuhara.jp/collections/t-shirts-compressions"
        },
        {
            "name": "Iconaclub - Crewnecks",
            "url": "https://iconaclub.com/collections/crewnecks"
        }
    ]
    
    print("\n" + "="*80)
    print("MULTI-BRAND IMAGE EXTRACTION TEST")
    print("="*80)
    
    all_results = []
    
    for test_page in test_pages:
        result = test_scroll_extract_with_images(
            page_url=test_page["url"],
            brand_name=test_page["name"]
        )
        all_results.append(result)
        time.sleep(2)  # Brief pause between tests
    
    # Final summary
    print("\n" + "="*80)
    print("🎯 TEST SUITE SUMMARY")
    print("="*80)
    
    successful = sum(1 for r in all_results if r.get("success", False))
    total_products = sum(r.get("products_extracted", 0) for r in all_results)
    total_with_images = sum(r.get("products_with_images", 0) for r in all_results)
    
    print(f"✅ Successful Tests: {successful}/{len(all_results)}")
    print(f"📦 Total Products Extracted: {total_products}")
    print(f"📷 Total Products with Images: {total_with_images}")
    
    print(f"\n📊 Detailed Results:")
    print(f"{'Brand':<30} {'Products':<10} {'With Images':<12} {'Coverage':<10} {'Downloads':<10}")
    print("-" * 80)
    
    for result in all_results:
        if result.get("success"):
            brand = result["brand"][:30]
            products = result.get("products_extracted", 0)
            with_images = result.get("products_with_images", 0)
            coverage = result.get("image_coverage", "0%")
            downloads = f"{result.get('downloads_successful', 0)}/{result.get('downloads_tested', 0)}"
            
            print(f"{brand:<30} {products:<10} {with_images:<12} {coverage:<10} {downloads:<10}")
        else:
            brand = result.get("brand", "Unknown")[:30]
            print(f"{brand:<30} {'FAILED':<10} {'-':<12} {'-':<10} {'-':<10}")
    
    return all_results


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        # Test a specific URL passed as argument
        url = sys.argv[1]
        brand = sys.argv[2] if len(sys.argv) > 2 else None
        test_scroll_extract_with_images(url, brand)
    else:
        # Run default test suite
        test_multiple_brands()