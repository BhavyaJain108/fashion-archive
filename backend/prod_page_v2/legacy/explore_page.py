"""
Explore a product page to understand data sources.

Captures:
- Network requests (API calls, image loads)
- HTML structure
- ARIA snapshot
- Any JSON data embedded in page
"""

import asyncio
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright


async def explore_product_page(url: str, output_dir: Path = None):
    """Load a product page and capture all data sources."""

    domain = urlparse(url).netloc.replace('www.', '').split('.')[0]

    if output_dir is None:
        output_dir = Path(__file__).parent / 'explorations' / domain
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*70}")
    print(f"EXPLORING PRODUCT PAGE")
    print(f"{'='*70}")
    print(f"URL: {url}")
    print(f"Output: {output_dir}\n")

    # Collect network requests
    api_requests = []
    image_requests = []
    json_responses = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        # Intercept network requests
        async def handle_response(response):
            url = response.url
            content_type = response.headers.get('content-type', '')

            # Capture API/JSON responses
            if 'json' in content_type or '/api/' in url or 'graphql' in url.lower():
                try:
                    body = await response.json()
                    api_requests.append({
                        'url': url,
                        'status': response.status,
                        'content_type': content_type
                    })
                    # Store response body
                    key = urlparse(url).path.replace('/', '_')[:50]
                    json_responses[key] = body
                except:
                    pass

            # Capture image requests
            if 'image' in content_type or any(ext in url.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']):
                image_requests.append({
                    'url': url,
                    'content_type': content_type
                })

        page.on('response', handle_response)

        # Load page
        print("[1] Loading page...")
        await page.goto(url, wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(5000)  # Wait for dynamic content

        # Capture ARIA snapshot
        print("[2] Capturing ARIA snapshot...")
        aria = await page.accessibility.snapshot(interesting_only=False)

        # Capture HTML
        print("[3] Capturing HTML...")
        html = await page.content()

        # Look for embedded JSON (common patterns)
        print("[4] Extracting embedded JSON...")
        embedded_json = {}

        # Pattern 1: <script type="application/ld+json">
        ld_json_matches = re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL)
        for i, match in enumerate(ld_json_matches):
            try:
                embedded_json[f'ld_json_{i}'] = json.loads(match.strip())
            except:
                pass

        # Pattern 2: window.__PRELOADED_STATE__ or similar
        preload_patterns = [
            r'window\.__PRELOADED_STATE__\s*=\s*({.*?});',
            r'window\.__INITIAL_STATE__\s*=\s*({.*?});',
            r'window\.__NEXT_DATA__\s*=\s*({.*?})</script>',
            r'"props"\s*:\s*({.*?})\s*,\s*"page"',
        ]
        for pattern in preload_patterns:
            matches = re.findall(pattern, html, re.DOTALL)
            for i, match in enumerate(matches):
                try:
                    key = pattern.split('__')[1] if '__' in pattern else f'preload_{i}'
                    embedded_json[key] = json.loads(match)
                except:
                    pass

        # Take screenshot
        print("[5] Taking screenshot...")
        await page.screenshot(path=output_dir / 'screenshot.png', full_page=True)

        await browser.close()

    # Save results
    print("\n[6] Saving results...")

    # Save API requests list
    with open(output_dir / 'api_requests.json', 'w') as f:
        json.dump(api_requests, f, indent=2)
    print(f"    API requests: {len(api_requests)}")

    # Save image requests list
    with open(output_dir / 'image_requests.json', 'w') as f:
        json.dump(image_requests, f, indent=2)
    print(f"    Image requests: {len(image_requests)}")

    # Save JSON responses
    with open(output_dir / 'json_responses.json', 'w') as f:
        json.dump(json_responses, f, indent=2)
    print(f"    JSON responses: {len(json_responses)}")

    # Save embedded JSON
    with open(output_dir / 'embedded_json.json', 'w') as f:
        json.dump(embedded_json, f, indent=2)
    print(f"    Embedded JSON: {len(embedded_json)}")

    # Save ARIA
    with open(output_dir / 'aria.json', 'w') as f:
        json.dump(aria, f, indent=2)

    # Save HTML (truncated for review)
    with open(output_dir / 'page.html', 'w') as f:
        f.write(html)

    # Print summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")

    print(f"\nAPI Requests ({len(api_requests)}):")
    for req in api_requests[:10]:
        print(f"  - {req['url'][:80]}...")

    print(f"\nImage URLs ({len(image_requests)}):")
    # Group by domain/path pattern
    image_domains = {}
    for img in image_requests:
        domain = urlparse(img['url']).netloc
        if domain not in image_domains:
            image_domains[domain] = []
        image_domains[domain].append(img['url'])

    for domain, urls in image_domains.items():
        print(f"  {domain}: {len(urls)} images")
        for u in urls[:3]:
            print(f"    - {u[:70]}...")

    print(f"\nEmbedded JSON keys:")
    for key in embedded_json.keys():
        print(f"  - {key}")

    return {
        'api_requests': api_requests,
        'image_requests': image_requests,
        'json_responses': json_responses,
        'embedded_json': embedded_json,
        'output_dir': str(output_dir)
    }


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python explore_page.py <url>")
        sys.exit(1)

    url = sys.argv[1]
    asyncio.run(explore_product_page(url))
