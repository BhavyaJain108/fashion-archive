#!/usr/bin/env python3
"""
Full Pipeline Test
==================

Complete brand scraping pipeline that:
1. Analyzes brand navigation to find all product category pages
2. Extracts product pattern from first category page
3. Scrapes all products from all category pages in parallel
4. Saves results in structured format
"""

import sys
import os
import time
import json
import csv
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
from typing import List, Dict, Any

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brand import Brand
from page_extractor import extract_products_from_page


def extract_category_name(url: str) -> str:
    """Extract a readable category name from URL"""
    parsed = urlparse(url)
    path_parts = [p for p in parsed.path.split('/') if p and p != 'collections']
    
    if path_parts:
        # Take the last meaningful part and clean it up
        name = path_parts[-1].replace('-', ' ').replace('_', ' ').title()
        return name
    
    return "Main Collection"


def scrape_category_page(category_url: str, patterns: List[dict], brand_name: str, 
                        images_dir: str = None, download_images: bool = False) -> Dict[str, Any]:
    """
    Scrape a single category page using multi-pattern approach with fallback
    Optionally download images immediately after extraction
    
    Returns:
        Dict with category info and extracted products
    """
    # Use the pure function from page_extractor
    result = extract_products_from_page(category_url, patterns, brand_name)
    
    # Start image downloads for this category immediately if requested
    if download_images and images_dir and result["success"] and result["products"]:
        from concurrent.futures import ThreadPoolExecutor
        import requests
        from pathlib import Path
        
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
            img_executor.map(download_product_image, result["products"])
    
    # Convert to the format expected by the pipeline
    return {
        "category_name": result["category_name"],
        "category_url": result["page_url"],
        "products_found": len(result["products"]),
        "extraction_time": result["metrics"]["extraction_time"],
        "products": result["products"],
        "success": result["success"],
        "error": result.get("error"),
        "pattern_used": result.get("pattern_used"),
        "new_pattern": result.get("new_pattern")
    }


def save_results(brand_name: str, all_products: List[Dict], category_results: List[Dict], 
                patterns: List[Dict], scrape_start_time: datetime, total_time: float, 
                results_dir: str = None) -> str:
    """
    Save results in time-based folder structure
    """
    # Use provided results_dir or create new one
    if not results_dir:
        timestamp = scrape_start_time.strftime("%Y-%m-%d_%H-%M-%S")
        results_dir = f"tests/results/{timestamp}"
        os.makedirs(results_dir, exist_ok=True)
    
    brand_slug = brand_name.lower().replace(' ', '_').replace('-', '_')
    
    # File paths
    csv_path = f"{results_dir}/{brand_slug}_products.csv"
    json_path = f"{results_dir}/{brand_slug}_summary.json"
    log_path = f"{results_dir}/scrape_log.txt"
    
    # Save CSV with all product data
    if all_products:
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            if all_products:
                writer = csv.DictWriter(f, fieldnames=all_products[0].keys())
                writer.writeheader()
                writer.writerows(all_products)
    
    # Create summary data
    successful_categories = [r for r in category_results if r.get('success', False)]
    failed_categories = [r for r in category_results if not r.get('success', False)]
    
    summary = {
        "brand": brand_name,
        "scrape_timestamp": scrape_start_time.isoformat(),
        "total_products": len(all_products),
        "categories_scraped": len(successful_categories),
        "categories_failed": len(failed_categories),
        "categories": [
            {
                "name": r["category_name"],
                "url": r["category_url"], 
                "products_found": r["products_found"],
                "extraction_time": round(r["extraction_time"], 2),
                "success": r["success"]
            }
            for r in category_results
        ],
        "patterns_used": patterns,
        "performance": {
            "total_time": round(total_time, 2),
            "avg_products_per_second": round(len(all_products) / total_time, 2) if total_time > 0 else 0,
            "successful_categories": len(successful_categories),
            "failed_categories": len(failed_categories)
        }
    }
    
    # Save JSON summary
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    
    # Save log
    with open(log_path, 'w', encoding='utf-8') as f:
        f.write(f"Brand Scraping Log - {brand_name}\n")
        f.write(f"Timestamp: {scrape_start_time.isoformat()}\n")
        f.write(f"Total Time: {total_time:.2f}s\n")
        f.write(f"Total Products: {len(all_products)}\n\n")
        
        f.write("Product Patterns Used:\n")
        for i, pattern in enumerate(patterns):
            f.write(f"   Pattern {i}:\n")
            f.write(f"      Container: {pattern.get('container_selector', 'N/A')}\n")
            f.write(f"      Link:      {pattern.get('link_selector', 'N/A')}\n")
            f.write(f"      Name:      {pattern.get('name_selector', 'N/A')}\n")
            f.write(f"      Image:     {pattern.get('image_selector', 'N/A')}\n")
        f.write("\n")
        
        f.write("Category Results:\n")
        for r in category_results:
            status = "✅" if r.get('success', False) else "❌"
            f.write(f"{status} {r['category_name']}: {r['products_found']} products ({r['extraction_time']:.1f}s)\n")
            f.write(f"   URL: {r['category_url']}\n")
            if not r.get('success', False):
                f.write(f"   Error: {r.get('error', 'Unknown error')}\n")
            f.write("\n")
    
    # Images are already downloaded during category processing, just count them
    if os.path.exists(f"{results_dir}/images"):
        import glob
        image_files = glob.glob(f"{results_dir}/images/*")
        image_count = len(image_files)
        print(f"\n📸 Image Downloads Complete")
        print(f"   ✅ {image_count} images saved")
    
    print(f"\n📁 Results saved to: {results_dir}")
    print(f"   📄 Products CSV: {brand_slug}_products.csv")
    print(f"   📊 Summary JSON: {brand_slug}_summary.json")
    print(f"   📝 Log file: scrape_log.txt")
    print(f"   🖼️  Images folder: images/")
    
    return results_dir


def test_full_brand_scrape(brand_url: str, brand_name: str = None) -> Dict[str, Any]:
    """
    Complete brand scraping pipeline
    
    Args:
        brand_url: Brand homepage URL
        brand_name: Optional brand name (will extract from URL if not provided)
        
    Returns:
        Dict with complete scrape results
    """
    scrape_start_time = datetime.now()
    
    # Extract brand name from URL if not provided
    if not brand_name:
        parsed = urlparse(brand_url)
        brand_name = parsed.netloc.replace('www.', '').split('.')[0].title()
    
    print(f"\n{'='*80}")
    print(f"🏢 FULL BRAND SCRAPE: {brand_name}")
    print(f"{'='*80}")
    print(f"🌐 Homepage: {brand_url}")
    print(f"🕐 Started: {scrape_start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)
    
    try:
        # Step 1: Brand Analysis - Get all starting pages
        print("\n📍 STEP 1: Navigation Analysis")
        print("-" * 40)
        
        brand = Brand(brand_url)
        
        # Extract links from homepage
        links = brand.extract_page_links(brand_url)
        if not links:
            raise Exception("Failed to extract any links from the homepage")
        
        # Build navigation prompt and get LLM analysis
        prompt = brand._build_navigation_prompt(links)
        llm_response = brand.llm_handler.call(prompt, expected_format="json")
        
        if not llm_response.get("success", False):
            raise Exception(f"LLM navigation analysis failed: {llm_response.get('error', 'Unknown error')}")
        
        # Extract starting pages from LLM response
        analysis = llm_response.get("data", {})
        included_urls = analysis.get("included_urls", [])
        
        starting_pages = []
        for url_obj in included_urls:
            url = url_obj.get("url", "") if isinstance(url_obj, dict) else url_obj
            if url.startswith('/'):
                # Convert relative URL to absolute
                from urllib.parse import urljoin
                starting_pages.append(urljoin(brand_url, url))
            elif url.startswith('http'):
                starting_pages.append(url)
        
        if not starting_pages:
            raise Exception("No product category pages found")
        
        print(f"✅ Found {len(starting_pages)} category pages:")
        for i, page in enumerate(starting_pages[:5], 1):  # Show first 5
            category_name = extract_category_name(page)
            print(f"   {i}. {category_name}")
        if len(starting_pages) > 5:
            print(f"   ... and {len(starting_pages) - 5} more")
        
        # Step 2: Pattern Detection - Use first page as template
        print(f"\n📍 STEP 2: Pattern Detection")
        print("-" * 40)
        
        # Set the starting pages queue so analyze_product_pattern can use them
        brand.starting_pages_queue = starting_pages
        
        pattern_result = brand.analyze_product_pattern()
        if not pattern_result or not brand.product_extraction_pattern:
            raise Exception("Failed to extract product pattern")
        
        initial_pattern = brand.product_extraction_pattern
        print(f"✅ Pattern extracted from sample page")
        print(f"   Container: {initial_pattern.get('container_selector', 'N/A')}")
        
        # Initialize patterns list with the first discovered pattern
        brand_patterns = [initial_pattern]
        
        # Create results directory early for image downloads
        timestamp = scrape_start_time.strftime("%Y-%m-%d_%H-%M-%S")
        results_dir = f"tests/results/{timestamp}"
        images_dir = f"{results_dir}/images"
        os.makedirs(images_dir, exist_ok=True)
        
        # Step 3: Parallel Product Extraction
        print(f"\n📍 STEP 3: Product Extraction with Image Downloads")
        print("-" * 40)
        print(f"Processing {len(starting_pages)} categories in parallel...")
        print(f"Images will be saved to: {images_dir}")
        
        all_products = []
        category_results = []
        
        # Process categories in parallel (max 3 concurrent) with image downloads
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {}
            
            for page_url in starting_pages:
                # Each thread gets a copy of current patterns and downloads images immediately
                future = executor.submit(scrape_category_page, page_url, brand_patterns.copy(), brand_name,
                                       images_dir=images_dir, download_images=True)
                futures[future] = page_url
            
            # Collect results as they complete
            for future in as_completed(futures):
                result = future.result()
                category_results.append(result)
                
                if result['success']:
                    all_products.extend(result['products'])
                    
                    # If a new pattern was discovered, add it to our collection
                    if result.get('new_pattern'):
                        brand_patterns.append(result['new_pattern'])
                        print(f"  🔍 New pattern discovered for {result['category_name']}")
        
        # Sort patterns by success rate (most successful first)
        pattern_usage = {}
        new_pattern_count = 0
        for result in category_results:
            pattern_id = result.get('pattern_used')
            if pattern_id is not None:
                if pattern_id == "new":
                    new_pattern_count += 1
                else:
                    pattern_usage[pattern_id] = pattern_usage.get(pattern_id, 0) + 1
        
        print(f"\n📊 Pattern Usage Summary:")
        print(f"   Pattern 0 (initial): {pattern_usage.get(0, 0)} pages")
        # Count for newly discovered patterns
        if new_pattern_count > 0:
            print(f"   Pattern 1 (discovered): {new_pattern_count} pages")
        
        # Step 4: Results Summary
        total_time = (datetime.now() - scrape_start_time).total_seconds()
        successful_categories = len([r for r in category_results if r.get('success', False)])
        
        print(f"\n📊 EXTRACTION COMPLETE")
        print("-" * 40)
        print(f"✅ Total Products: {len(all_products)}")
        print(f"✅ Successful Categories: {successful_categories}/{len(starting_pages)}")
        print(f"⏱️  Total Time: {total_time:.1f}s")
        print(f"⚡ Rate: {len(all_products)/total_time:.1f} products/second")
        
        # Step 5: Save Results
        print(f"\n📁 SAVING RESULTS")
        print("-" * 40)
        
        # Note: results_dir was already created earlier for image downloads
        save_results(
            brand_name, all_products, category_results, 
            brand_patterns, scrape_start_time, total_time, results_dir
        )
        
        return {
            "success": True,
            "brand": brand_name,
            "total_products": len(all_products),
            "successful_categories": successful_categories,
            "total_categories": len(starting_pages),
            "total_time": total_time,
            "results_dir": results_dir,
            "products": all_products
        }
        
    except Exception as e:
        total_time = (datetime.now() - scrape_start_time).total_seconds()
        print(f"\n❌ SCRAPE FAILED: {e}")
        
        return {
            "success": False,
            "brand": brand_name,
            "error": str(e),
            "total_time": total_time
        }


def test_multiple_brands():
    """Test full pipeline on multiple brands"""
    
    test_brands = [
        {
            "name": "Entire Studios",
            "url": "https://www.entirestudios.com"
        },
        # Add more brands here as needed
    ]
    
    print("\n" + "="*80)
    print("🏭 MULTI-BRAND FULL PIPELINE TEST")
    print("="*80)
    
    all_results = []
    
    for brand_info in test_brands:
        result = test_full_brand_scrape(
            brand_url=brand_info["url"],
            brand_name=brand_info["name"]
        )
        all_results.append(result)
        
        # Brief pause between brands
        if len(test_brands) > 1:
            time.sleep(5)
    
    # Final summary
    print("\n" + "="*80)
    print("🎯 FINAL SUMMARY")
    print("="*80)
    
    successful = sum(1 for r in all_results if r.get("success", False))
    total_products = sum(r.get("total_products", 0) for r in all_results)
    
    print(f"✅ Successful Brands: {successful}/{len(all_results)}")
    print(f"🛍️  Total Products Scraped: {total_products}")
    
    print(f"\n📊 Brand Results:")
    print(f"{'Brand':<20} {'Products':<10} {'Categories':<12} {'Time (s)':<10} {'Status':<10}")
    print("-" * 70)
    
    for result in all_results:
        brand = result.get("brand", "Unknown")[:20]
        products = result.get("total_products", 0)
        categories = f"{result.get('successful_categories', 0)}/{result.get('total_categories', 0)}"
        total_time = result.get("total_time", 0)
        status = "✅ Success" if result.get("success") else "❌ Failed"
        
        print(f"{brand:<20} {products:<10} {categories:<12} {total_time:<10.1f} {status:<10}")
    
    return all_results


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        # Test a specific brand passed as argument
        brand_url = sys.argv[1]
        brand_name = sys.argv[2] if len(sys.argv) > 2 else None
        test_full_brand_scrape(brand_url, brand_name)
    else:
        # Run default test suite
        test_multiple_brands()