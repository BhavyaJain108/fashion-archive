"""
API Detection for Product Pages

Detects whether a website uses API calls to fetch product data.
If APIs are found, extracts the patterns for automated extraction.
"""

import asyncio
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from dataclasses import dataclass, field
from typing import Optional

from playwright.async_api import async_playwright


@dataclass
class APIEndpoint:
    """Represents a detected API endpoint."""
    url: str
    method: str = "GET"
    content_type: str = ""
    response_size: int = 0
    has_product_data: bool = False
    product_fields: list = field(default_factory=list)
    sample_data: dict = field(default_factory=dict)


@dataclass
class DetectionResult:
    """Result of API detection."""
    has_api: bool = False
    confidence: str = "none"  # none, low, medium, high
    endpoints: list = field(default_factory=list)
    recommended_endpoint: Optional[APIEndpoint] = None
    product_id_pattern: Optional[str] = None
    notes: list = field(default_factory=list)


# Product-related field patterns to look for in API responses
PRODUCT_FIELD_PATTERNS = [
    'price', 'cost', 'amount',
    'size', 'sizes', 'sizeChart',
    'color', 'colors', 'colour',
    'stock', 'inventory', 'availability', 'inStock', 'outOfStock',
    'sku', 'productId', 'itemId', 'variantId',
    'name', 'title', 'productName',
    'description', 'details',
    'image', 'images', 'media', 'gallery',
    'variant', 'variants', 'options',
    'material', 'fabric', 'composition',
    'brand', 'designer',
    'category', 'collection'
]

# URL patterns that suggest API endpoints
API_URL_PATTERNS = [
    r'/api/',
    r'/v\d+/',
    r'/graphql',
    r'/rest/',
    r'/services/',
    r'/product[s]?/',
    r'/item[s]?/',
    r'/catalog/',
    r'\.json',
]

# Domains to ignore (tracking, analytics, etc.)
IGNORE_DOMAINS = [
    'google', 'facebook', 'analytics', 'tracking', 'pixel',
    'doubleclick', 'adsrvr', 'criteo', 'pinterest', 'snap',
    'tiktok', 'reddit', 'taboola', 'outbrain', 'cookielaw',
    'onetrust', 'cdn.', 'static.', 'assets.'
]


def is_tracking_domain(url: str) -> bool:
    """Check if URL is from a tracking/analytics domain."""
    domain = urlparse(url).netloc.lower()
    return any(ignore in domain for ignore in IGNORE_DOMAINS)


def looks_like_api_url(url: str) -> bool:
    """Check if URL looks like an API endpoint."""
    return any(re.search(pattern, url, re.IGNORECASE) for pattern in API_URL_PATTERNS)


def find_product_fields(obj, prefix="", found=None) -> list:
    """Recursively find product-related fields in a JSON object."""
    if found is None:
        found = []

    if isinstance(obj, dict):
        for key, value in obj.items():
            full_key = f"{prefix}.{key}" if prefix else key
            key_lower = key.lower()

            # Check if key matches product patterns
            for pattern in PRODUCT_FIELD_PATTERNS:
                if pattern in key_lower:
                    found.append(full_key)
                    break

            # Recurse into nested objects (limit depth)
            if prefix.count('.') < 3:
                find_product_fields(value, full_key, found)

    elif isinstance(obj, list) and obj:
        # Check first item of arrays
        find_product_fields(obj[0], f"{prefix}[0]", found)

    return found


def extract_product_id_from_url(page_url: str) -> Optional[str]:
    """Try to extract product ID from the page URL."""
    # Common patterns
    patterns = [
        r'/products?/([A-Za-z0-9_-]+)',
        r'/p/([A-Za-z0-9_-]+)',
        r'/item/([A-Za-z0-9_-]+)',
        r'/([A-Z0-9]{5,})-',  # Like E450314-000
        r'[?&]id=([A-Za-z0-9_-]+)',
        r'[?&]productId=([A-Za-z0-9_-]+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, page_url)
        if match:
            return match.group(1)
    return None


def score_endpoint(endpoint: APIEndpoint) -> int:
    """Score an endpoint based on how useful it seems for product extraction."""
    score = 0

    # Has product-related fields
    score += len(endpoint.product_fields) * 10

    # Larger responses often have more data
    if endpoint.response_size > 1000:
        score += 5
    if endpoint.response_size > 5000:
        score += 10

    # Prefer JSON
    if 'json' in endpoint.content_type:
        score += 15

    # Penalize tracking endpoints
    if is_tracking_domain(endpoint.url):
        score -= 100

    # Boost if URL contains product-related terms
    url_lower = endpoint.url.lower()
    for term in ['product', 'item', 'price', 'stock', 'inventory', 'variant']:
        if term in url_lower:
            score += 20

    return score


async def detect_apis(url: str, timeout: int = 10000) -> DetectionResult:
    """
    Load a product page and detect API calls.

    Returns DetectionResult with:
    - has_api: Whether product APIs were detected
    - confidence: How confident we are
    - endpoints: List of detected API endpoints
    - recommended_endpoint: Best endpoint to use
    - product_id_pattern: How product ID appears in API URLs
    """
    result = DetectionResult()
    captured_responses = []

    product_id = extract_product_id_from_url(url)
    if product_id:
        result.notes.append(f"Detected product ID from URL: {product_id}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        async def capture_response(response):
            """Capture JSON API responses."""
            req_url = response.url
            content_type = response.headers.get('content-type', '')

            # Skip non-JSON and tracking
            if 'json' not in content_type:
                return
            if is_tracking_domain(req_url):
                return

            try:
                body = await response.json()
                body_str = json.dumps(body)

                endpoint = APIEndpoint(
                    url=req_url,
                    content_type=content_type,
                    response_size=len(body_str),
                    sample_data=body if len(body_str) < 50000 else {"_truncated": True}
                )

                # Find product-related fields
                endpoint.product_fields = find_product_fields(body)
                endpoint.has_product_data = len(endpoint.product_fields) >= 3

                captured_responses.append(endpoint)

            except Exception:
                pass

        page.on('response', capture_response)

        try:
            await page.goto(url, wait_until='domcontentloaded', timeout=30000)
            await page.wait_for_timeout(timeout)  # Wait for API calls
        except Exception as e:
            result.notes.append(f"Page load issue: {str(e)[:100]}")

        await browser.close()

    # Analyze captured responses
    if not captured_responses:
        result.confidence = "none"
        result.notes.append("No JSON API responses captured")
        return result

    # Filter to endpoints with product data
    product_endpoints = [e for e in captured_responses if e.has_product_data]

    if not product_endpoints:
        result.confidence = "low"
        result.endpoints = captured_responses[:5]  # Return top 5 anyway
        result.notes.append(f"Found {len(captured_responses)} API calls but none with clear product data")
        return result

    # Score and sort endpoints
    for endpoint in product_endpoints:
        endpoint._score = score_endpoint(endpoint)

    product_endpoints.sort(key=lambda e: e._score, reverse=True)

    # Set results
    result.has_api = True
    result.endpoints = product_endpoints[:10]
    result.recommended_endpoint = product_endpoints[0]

    # Determine confidence
    best_score = product_endpoints[0]._score
    if best_score >= 50:
        result.confidence = "high"
    elif best_score >= 25:
        result.confidence = "medium"
    else:
        result.confidence = "low"

    # Try to find product ID pattern in API URLs
    if product_id:
        for endpoint in product_endpoints:
            if product_id in endpoint.url:
                result.product_id_pattern = endpoint.url.replace(product_id, "{PRODUCT_ID}")
                result.notes.append(f"Product ID appears in API URL")
                break

    result.notes.append(f"Found {len(product_endpoints)} endpoints with product data")

    return result


def print_result(result: DetectionResult):
    """Pretty print detection results."""
    print(f"\n{'='*60}")
    print("API DETECTION RESULT")
    print('='*60)

    print(f"\nHas API: {result.has_api}")
    print(f"Confidence: {result.confidence}")

    if result.notes:
        print(f"\nNotes:")
        for note in result.notes:
            print(f"  - {note}")

    if result.product_id_pattern:
        print(f"\nProduct ID Pattern:")
        print(f"  {result.product_id_pattern}")

    if result.recommended_endpoint:
        print(f"\nRecommended Endpoint:")
        print(f"  URL: {result.recommended_endpoint.url[:100]}...")
        print(f"  Product fields: {result.recommended_endpoint.product_fields[:10]}")

    if result.endpoints:
        print(f"\nAll Product Endpoints ({len(result.endpoints)}):")
        for i, ep in enumerate(result.endpoints[:5]):
            print(f"\n  [{i+1}] {ep.url[:80]}...")
            print(f"      Fields: {ep.product_fields[:5]}...")
            print(f"      Size: {ep.response_size} bytes")


async def main():
    if len(sys.argv) < 2:
        print("Usage: python api_detector.py <product_url>")
        sys.exit(1)

    url = sys.argv[1]
    print(f"Detecting APIs for: {url}")

    result = await detect_apis(url)
    print_result(result)

    # Save detailed results
    domain = urlparse(url).netloc.replace('www.', '').split('.')[0]
    output_dir = Path(__file__).parent / 'explorations' / domain
    output_dir.mkdir(parents=True, exist_ok=True)

    # Convert to JSON-serializable format
    output = {
        'has_api': result.has_api,
        'confidence': result.confidence,
        'product_id_pattern': result.product_id_pattern,
        'notes': result.notes,
        'endpoints': [
            {
                'url': ep.url,
                'product_fields': ep.product_fields,
                'response_size': ep.response_size,
                'sample_data': ep.sample_data
            }
            for ep in result.endpoints
        ]
    }

    with open(output_dir / 'api_detection.json', 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\nSaved to: {output_dir / 'api_detection.json'}")


if __name__ == '__main__':
    asyncio.run(main())
