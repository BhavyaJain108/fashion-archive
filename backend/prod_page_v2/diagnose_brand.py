"""
Diagnostic tool for tracing extraction on a single brand.

Usage:
    python diagnose_brand.py <url>
    python diagnose_brand.py "https://www.eckhauslatta.com/products/the-snap-green"
"""

import asyncio
import json
import sys
from urllib.parse import urlparse

from page_loader import load_page
from extractor import ProductExtractor


def section(title):
    print(f"\n{'='*60}")
    print(f" {title}")
    print('='*60)


def subsection(title):
    print(f"\n--- {title} ---")


async def diagnose(url: str):
    domain = urlparse(url).netloc.replace('www.', '')

    section(f"DIAGNOSING: {domain}")
    print(f"URL: {url}")

    # Step 1: Load Page
    section("STEP 1: PAGE LOADING")
    print("Loading page with Playwright...")

    page_data = await load_page(url, wait_time=5000)

    subsection("Results")
    print(f"  HTML size: {len(page_data.html):,} bytes")
    print(f"  JSON APIs captured: {len(page_data.json_responses)}")
    print(f"  Images captured: {len(page_data.image_urls)}")

    if page_data.json_responses:
        subsection("API Responses")
        for api_url, data in page_data.json_responses.items():
            short_url = api_url.split('?')[0][-50:]
            size = len(json.dumps(data))
            print(f"  {short_url}: {size:,} bytes")

    # Step 2: Check page content
    section("STEP 2: PAGE CONTENT CHECK")
    html = page_data.html

    checks = {
        'LD+JSON exists': 'application/ld+json' in html,
        'Product LD+JSON': '"@type":"Product"' in html or '"@type": "Product"' in html,
        'Shopify indicators': 'shopify' in html.lower() or 'cdn.shopify' in html.lower(),
        '__NEXT_DATA__': '__NEXT_DATA__' in html,
        'Price keyword': '"price"' in html.lower(),
        'Variants keyword': '"variants"' in html.lower(),
    }

    for check, result in checks.items():
        status = "✓" if result else "✗"
        print(f"  {status} {check}")

    # Get page title
    import re
    title_match = re.search(r'<title>([^<]+)</title>', html)
    if title_match:
        print(f"\n  Page title: {title_match.group(1)[:60]}")

    # Step 3: Run each strategy
    section("STEP 3: STRATEGY RESULTS")

    extractor = ProductExtractor()

    for strategy in extractor.strategies:
        name = strategy.strategy_type.value
        subsection(f"{name}")

        can_handle = strategy.can_handle(url, page_data)
        print(f"  can_handle: {can_handle}")

        if can_handle:
            try:
                result = await strategy.extract(url, page_data)

                if result.success and result.product:
                    p = result.product
                    print(f"  SUCCESS (score: {result.score})")
                    print(f"    name: {p.name[:50] if p.name else 'None'}")
                    print(f"    price: {p.price} {p.currency}")
                    print(f"    images: {len(p.images)}")
                    print(f"    variants: {len(p.variants)}")
                    if p.variants:
                        print(f"    first variant: {p.variants[0].size}")
                else:
                    print(f"  FAILED: {result.error}")
            except Exception as e:
                print(f"  ERROR: {e}")
        else:
            print(f"  SKIPPED (can_handle=False)")

    # Step 4: Final merged result
    section("STEP 4: FINAL MERGED RESULT")

    final = await extractor.extract_single(url)

    if final.success and final.product:
        p = final.product
        print(f"  Score: {final.score}")
        print(f"  Name: {p.name}")
        print(f"  Price: {p.price} {p.currency}")
        print(f"  Brand: {p.brand}")
        print(f"  Images: {len(p.images)}")
        print(f"  Variants: {len(p.variants)}")

        if p.missing_fields:
            missing = p.missing_fields.to_list()
            if missing:
                print(f"  Missing: {missing}")
    else:
        print(f"  FAILED: {final.error}")

    section("DIAGNOSIS COMPLETE")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python diagnose_brand.py <url>")
        sys.exit(1)

    url = sys.argv[1]
    asyncio.run(diagnose(url))
