"""
Test URL extraction for a single category.
Useful for debugging extraction issues.

Usage:
    python test_category.py <url> [--target N] [--headless]

Examples:
    python test_category.py https://poolhousenewyork.com/collections/new-releases --target 239
    python test_category.py https://www.eckhauslatta.com/collections/bags --headless
"""

import sys
import argparse
sys.path.insert(0, '/Users/bhavyajain/Code/fashion_archive/backend/scraper')

from url_extractor import extract_urls_from_category
from brand import Brand
from urllib.parse import urlparse


def test_category(url: str, target: int = None, headless: bool = False):
    # Parse domain from URL
    parsed = urlparse(url)
    domain = parsed.netloc

    print(f"\n{'='*60}")
    print(f"TESTING URL EXTRACTION")
    print(f"{'='*60}")
    print(f"URL: {url}")
    print(f"Mode: {'headless' if headless else 'HEADFUL (visible browser)'}")
    if target:
        print(f"Target: {target} products")
    print(f"{'='*60}\n")

    # Create a Brand instance to enable load more detection
    brand = Brand(url=f"https://{domain}/")

    # Run extraction with brand_instance
    result = extract_urls_from_category(url, brand_instance=brand, quiet=False)

    print(f"\n{'='*60}")
    print(f"RESULTS")
    print(f"{'='*60}")
    print(f"Products found: {len(result.product_urls)}")
    print(f"Extraction time: {result.extraction_time:.2f}s")

    if target:
        diff = len(result.product_urls) - target
        if diff == 0:
            print(f"Target: {target} ✅ MATCHED")
        elif diff > 0:
            print(f"Target: {target} (+{diff} extra)")
        else:
            print(f"Target: {target} ({diff} missing) ❌")

    if result.product_urls:
        print(f"\nFirst 5 products:")
        for p in result.product_urls[:5]:
            print(f"  - {p.url}")

        if len(result.product_urls) > 5:
            print(f"\nLast 5 products:")
            for p in result.product_urls[-5:]:
                print(f"  - {p.url}")

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test URL extraction for a single category")
    parser.add_argument("url", help="Category URL to test")
    parser.add_argument("--target", "-t", type=int, help="Expected product count")
    parser.add_argument("--headless", action="store_true", help="Run in headless mode (default: headful)")

    args = parser.parse_args()

    # Set headless mode via environment variable (read by url_extractor)
    import os
    os.environ['EXTRACTOR_HEADLESS'] = '1' if args.headless else '0'

    test_category(args.url, args.target, args.headless)
