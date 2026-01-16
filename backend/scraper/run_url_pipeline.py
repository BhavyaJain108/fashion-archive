#!/usr/bin/env python3
"""
Full extraction pipeline runner.

Extracts:
1. Navigation tree from brand website
2. Product URLs from all categories
3. Full product details using prod_page_v2

Usage:
    python run_url_pipeline.py <url>
    python run_url_pipeline.py https://www.eckhauslatta.com
    python run_url_pipeline.py https://www.eckhauslatta.com --output results.json
    python run_url_pipeline.py https://www.eckhauslatta.com --sequential
    python run_url_pipeline.py https://www.eckhauslatta.com --urls-only  # Skip product extraction
"""

import sys
import json
import asyncio
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse
from typing import Dict, List

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "prod_page_v2"))

from brand import Brand
from url_extractor import extract_urls_from_navigation_tree
from extractor import ProductExtractor


async def extract_products(url_results: Dict, domain: str) -> Dict:
    """
    Run prod_page_v2 on extracted URLs.

    Args:
        url_results: Output from extract_urls_from_navigation_tree()
        domain: Brand domain (e.g., "eckhauslatta.com")

    Returns:
        Dict with product extraction results
    """
    # Flatten and dedupe all product URLs (products in multiple categories only processed once)
    seen = set()
    all_urls = []
    for cat_data in url_results.get("categories", {}).values():
        for product_url in cat_data.get("product_urls", []):
            url = product_url.get("url") if isinstance(product_url, dict) else product_url.url
            if url and url not in seen:
                seen.add(url)
                all_urls.append(url)

    if len(all_urls) < 2:
        print("Need at least 2 product URLs for discovery")
        return {"success": False, "error": "Insufficient URLs"}

    print(f"\n{'='*60}")
    print(f"PRODUCT EXTRACTION PHASE")
    print(f"{'='*60}")
    print(f"   URLs to process: {len(all_urls)}")
    print(f"   Discovery URLs: {all_urls[0][:60]}...")
    print(f"                   {all_urls[1][:60]}...")

    extractor = ProductExtractor()

    # Discovery + verification with first 2 URLs
    config = await extractor.discover_and_verify(domain, all_urls[:2])

    if not config:
        print("Discovery/verification failed")
        return {"success": False, "error": "Discovery failed"}

    # Batch extract remaining URLs (high parallelism)
    if len(all_urls) > 2:
        results = await extractor.extract_batch(config, all_urls[2:], concurrency=8)
    else:
        results = []

    # Save products
    products_saved = []
    for result in results:
        if result.success and result.product:
            filepath = extractor.save_product(result.product)
            products_saved.append(str(filepath))

    return {
        "success": True,
        "config": config.to_dict(),
        "products_extracted": len(results),
        "products_successful": sum(1 for r in results if r.success),
        "products_saved": products_saved
    }


async def main_async():
    if len(sys.argv) < 2:
        print("Usage: python run_url_pipeline.py <url> [options]")
        print("Options:")
        print("  --output <file>  : Save results to JSON file")
        print("  --sequential     : Process categories sequentially (default: parallel)")
        print("  --urls-only      : Skip product extraction (only extract URLs)")
        sys.exit(1)

    url = sys.argv[1]

    # Parse options
    output_file = None
    parallel = True
    urls_only = False

    for i, arg in enumerate(sys.argv[2:], start=2):
        if arg == "--output" and i + 1 < len(sys.argv):
            output_file = sys.argv[i + 1]
        elif arg == "--sequential":
            parallel = False
        elif arg == "--urls-only":
            urls_only = True

    # Extract domain from URL
    parsed = urlparse(url)
    domain = parsed.netloc.replace('www.', '')

    print(f"\n{'='*60}")
    print(f"FULL EXTRACTION PIPELINE")
    print(f"{'='*60}")
    print(f"URL: {url}")
    print(f"Domain: {domain}")
    print(f"Parallel: {parallel}")
    print(f"URLs only: {urls_only}")
    print(f"Output: {output_file or 'auto'}")
    print(f"{'='*60}\n")

    try:
        # Create brand instance
        brand = Brand(url, test_mode=False)

        # Step 1: Extract navigation tree
        print("Step 1: Extracting navigation tree...")
        navigation_tree = brand._extract_navigation_tree()

        if not navigation_tree or not navigation_tree.get("category_tree"):
            print("Failed to extract navigation tree")
            sys.exit(1)

        leaf_count = len(brand._extract_all_leaf_urls(navigation_tree))
        print(f"   Navigation tree extracted: {leaf_count} categories found")

        # Step 2: Extract URLs from all categories
        print("\nStep 2: Extracting product URLs from all categories...")
        results = extract_urls_from_navigation_tree(
            navigation_tree,
            brand_instance=brand,
            parallel=parallel
        )

        # Add navigation tree to results
        results["navigation_tree"] = navigation_tree

        # Print URL extraction summary
        print(f"\n{'='*60}")
        print("URL EXTRACTION SUMMARY")
        print(f"{'='*60}")

        summary = results.get('summary', {})
        print(f"Success: {results.get('success')}")
        print(f"Categories processed: {summary.get('successful_categories', 0)}/{summary.get('total_categories', 0)}")
        print(f"Total product URLs: {summary.get('total_urls', 0)}")
        print(f"Unique product URLs: {summary.get('unique_urls', 0)}")
        print(f"Extraction time: {summary.get('extraction_time', 0):.1f}s")
        print(f"LLM calls: {summary.get('llm_calls', 0)}")
        print(f"Estimated cost: ${summary.get('estimated_cost_usd', 0):.4f}")

        # Show per-category breakdown
        print(f"\n{'='*60}")
        print("PER-CATEGORY BREAKDOWN")
        print(f"{'='*60}")

        categories = results.get('categories', {})
        for cat_url, cat_data in categories.items():
            cat_name = cat_data.get('category_name', 'Unknown')
            url_count = len(cat_data.get('product_urls', []))
            pages = cat_data.get('pages_processed', 1)
            errors = cat_data.get('errors', [])

            status = "+" if not errors else "!"
            print(f"   {status} {cat_name}: {url_count} URLs ({pages} pages)")

            if errors:
                for err in errors:
                    print(f"      ERROR: {err}")

        # Step 3: Product extraction (unless --urls-only)
        if not urls_only and results.get('success'):
            print("\nStep 3: Extracting full product details...")
            product_results = await extract_products(results, domain)
            results["product_extraction"] = product_results

            # Print product extraction summary
            if product_results.get("success"):
                print(f"\n{'='*60}")
                print("PRODUCT EXTRACTION SUMMARY")
                print(f"{'='*60}")
                print(f"Products extracted: {product_results.get('products_extracted', 0)}")
                print(f"Products successful: {product_results.get('products_successful', 0)}")
                print(f"Products saved: {len(product_results.get('products_saved', []))}")
            else:
                print(f"\nProduct extraction failed: {product_results.get('error')}")

        # Save results
        if output_file:
            output_path = Path(output_file)
        else:
            # Default: save to tests/results/
            output_path = Path(__file__).parent / "tests" / "results" / f"{domain.replace('.', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w') as f:
            json.dump(results, f, indent=2, default=str)

        print(f"\nResults saved to: {output_path}")

    except Exception as e:
        print(f"\nPipeline failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
