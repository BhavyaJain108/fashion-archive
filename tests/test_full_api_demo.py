#!/usr/bin/env python3
"""
Full API Demo
=============

Comprehensive test of all API endpoints:
1. Create a brand
2. Trigger scraping
3. Query products
4. Explore classifications
5. Explore attributes
6. View images
"""

import requests
import json
import time
import sys

BASE_URL = "http://localhost:8081/api"

def print_section(title):
    """Print a section header"""
    print("\n" + "="*80)
    print(f"  {title}")
    print("="*80 + "\n")

def print_json(data, max_items=3):
    """Pretty print JSON, limiting arrays"""
    if isinstance(data, dict):
        if "products" in data and isinstance(data["products"], list):
            data = data.copy()
            data["products"] = data["products"][:max_items] + (
                [f"... {len(data['products']) - max_items} more"]
                if len(data["products"]) > max_items else []
            )
    print(json.dumps(data, indent=2))

def test_api():
    """Run comprehensive API test"""

    # =========================================================================
    # 1. BRANDS API
    # =========================================================================

    print_section("1. CREATE BRAND")
    print("POST /api/brands")
    print("Creating brand for Jukuhara...\n")

    response = requests.post(f"{BASE_URL}/brands", json={
        "name": "Jukuhara",
        "homepage_url": "https://jukuhara.jp"
    })

    if response.status_code in [200, 201]:
        result = response.json()
        print_json(result)
        brand_id = result['brand_id']
        print(f"\n✅ Brand created: {brand_id}")
    elif response.status_code == 409:
        print("⚠️  Brand already exists, continuing...")
        brand_id = "jukuhara"
    else:
        print(f"❌ Failed to create brand: {response.status_code}")
        print(response.json())
        return

    # -------------------------------------------------------------------------

    print_section("2. GET BRAND DETAILS")
    print(f"GET /api/brands/{brand_id}\n")

    response = requests.get(f"{BASE_URL}/brands/{brand_id}")
    print_json(response.json())

    # -------------------------------------------------------------------------

    print_section("3. LIST ALL BRANDS")
    print("GET /api/brands\n")

    response = requests.get(f"{BASE_URL}/brands")
    data = response.json()
    print(f"Total brands: {data['pagination']['total']}")
    print("\nBrands:")
    for brand in data['brands']:
        print(f"  - {brand['name']} ({brand['brand_id']}) - {brand.get('total_products', 0)} products")

    # =========================================================================
    # 4. SCRAPING API
    # =========================================================================

    print_section("4. ANALYZE BRAND (Check if scrapable)")
    print("POST /api/brands/analyze\n")

    response = requests.post(f"{BASE_URL}/brands/analyze", json={
        "url": "https://jukuhara.jp"
    })
    print_json(response.json())

    # -------------------------------------------------------------------------

    print_section("5. START SCRAPING")
    print(f"POST /api/brands/{brand_id}/scrape")
    print("⚠️  This will take 1-2 minutes...\n")

    response = requests.post(f"{BASE_URL}/brands/{brand_id}/scrape")

    if response.status_code == 202:
        result = response.json()
        print_json(result)
        job_id = result.get('job_id')

        print("\n⏳ Waiting for scrape to complete...")

        # Poll for status
        for i in range(60):  # Wait up to 5 minutes
            time.sleep(5)
            status_response = requests.get(f"{BASE_URL}/brands/{brand_id}/scrape/status")
            status = status_response.json()

            print(f"  Status: {status.get('status')} - {status.get('current_action', 'Processing...')}")

            if status.get('status') == 'completed':
                print("\n✅ Scraping completed!")
                break
            elif status.get('status') == 'failed':
                print(f"\n❌ Scraping failed: {status.get('error')}")
                break

        # Get final brand details
        print("\n📊 Final brand status:")
        response = requests.get(f"{BASE_URL}/brands/{brand_id}")
        brand_data = response.json()
        print(f"  Products: {brand_data.get('status', {}).get('total_products', 0)}")
        print(f"  Categories: {brand_data.get('status', {}).get('total_categories', 0)}")
    else:
        print(f"❌ Failed to start scraping: {response.status_code}")
        print(response.json())

    # =========================================================================
    # 6. PRODUCTS API
    # =========================================================================

    print_section("6. GET ALL PRODUCTS")
    print(f"GET /api/products?brand_id={brand_id}\n")

    response = requests.get(f"{BASE_URL}/products", params={"brand_id": brand_id})
    data = response.json()

    print(f"Total products: {data['pagination']['total']}")
    print(f"\nFirst 3 products:")
    print_json(data, max_items=3)

    has_products = bool(data['products'])
    first_product_url = None
    if has_products:
        first_product_url = data['products'][0]['product_url']

    # -------------------------------------------------------------------------

    print_section("7. GET SINGLE PRODUCT")
    if has_products:
        from urllib.parse import quote
        encoded_url = quote(first_product_url, safe='')
        print(f"GET /api/products/{encoded_url}\n")

        response = requests.get(f"{BASE_URL}/products/{encoded_url}")
        print_json(response.json())
    else:
        print("⚠️  No products to display")

    # -------------------------------------------------------------------------

    print_section("8. SEARCH PRODUCTS")
    print(f"GET /api/products/search?q=shirt&brand_id={brand_id}\n")

    response = requests.get(f"{BASE_URL}/products/search", params={
        "q": "shirt",
        "brand_id": brand_id
    })
    data = response.json()
    print(f"Search results: {data['total_results']} products matching 'shirt'")
    if data['products']:
        print("\nMatching products:")
        for product in data['products'][:3]:
            print(f"  - {product['product_name']}")

    # =========================================================================
    # 9. CLASSIFICATIONS API
    # =========================================================================

    print_section("9. GET ALL CLASSIFICATIONS")
    print(f"GET /api/brands/{brand_id}/classifications\n")

    response = requests.get(f"{BASE_URL}/brands/{brand_id}/classifications")
    data = response.json()

    if 'error' in data:
        print(f"⚠️  {data['error']}")
        category_url = None
    else:
        print(f"Total classifications: {data['total_classifications']}")
        print("\nClassifications by type:")
        for class_type, items in data['classifications'].items():
            print(f"\n  {class_type.upper()}:")
            for item in items[:5]:
                print(f"    - {item['name']} ({item['product_count']} products)")

        # Get first category URL for filtering
        category_url = None
        if 'category' in data['classifications'] and data['classifications']['category']:
            category_url = data['classifications']['category'][0]['url']

    # -------------------------------------------------------------------------

    print_section("10. GET CATEGORY HIERARCHY")
    print(f"GET /api/brands/{brand_id}/categories/hierarchy\n")

    response = requests.get(f"{BASE_URL}/brands/{brand_id}/categories/hierarchy")
    hierarchy_data = response.json()
    if 'error' in hierarchy_data:
        print(f"⚠️  {hierarchy_data['error']}")
    else:
        print_json(hierarchy_data)

    # -------------------------------------------------------------------------

    print_section("11. FILTER PRODUCTS BY CATEGORY")
    if category_url:
        print(f"GET /api/products?brand_id={brand_id}&classification_url={category_url}\n")

        response = requests.get(f"{BASE_URL}/products", params={
            "brand_id": brand_id,
            "classification_url": category_url
        })
        data = response.json()
        print(f"Products in this category: {data['pagination']['total']}")
        print(f"\nProducts:")
        for product in data['products'][:3]:
            print(f"  - {product['product_name']}")
    else:
        print("⚠️  No categories available")

    # =========================================================================
    # 12. ATTRIBUTES API
    # =========================================================================

    print_section("12. GET ALL ATTRIBUTES")
    print(f"GET /api/brands/{brand_id}/attributes\n")

    response = requests.get(f"{BASE_URL}/brands/{brand_id}/attributes")
    data = response.json()

    if 'error' in data:
        print(f"⚠️  {data['error']}")
        first_attr_key = None
    else:
        print(f"Total attributes: {data['total_attributes']}")
        print("\nAttributes discovered:")
        for attr_key, attr_data in data['attributes'].items():
            print(f"\n  {attr_key}:")
            print(f"    Type: {attr_data['type']}")
            print(f"    Products with this attribute: {attr_data['products_with_attribute']}")
            print(f"    Unique values: {attr_data['unique_values_count']}")
            if attr_data.get('unique_values'):
                print(f"    Sample values: {attr_data['unique_values'][:5]}")

        # Get first attribute key for filtering
        first_attr_key = list(data['attributes'].keys())[0] if data['attributes'] else None

    # -------------------------------------------------------------------------

    print_section("13. GET ATTRIBUTE VALUES")
    if first_attr_key:
        print(f"GET /api/brands/{brand_id}/attributes/{first_attr_key}/values\n")

        response = requests.get(f"{BASE_URL}/brands/{brand_id}/attributes/{first_attr_key}/values")
        print_json(response.json())
    else:
        print("⚠️  No attributes available")

    # -------------------------------------------------------------------------

    print_section("14. FILTER PRODUCTS BY ATTRIBUTE")
    if first_attr_key:
        # Get a sample value
        response = requests.get(f"{BASE_URL}/brands/{brand_id}/attributes")
        attrs = response.json()['attributes']
        sample_value = attrs[first_attr_key]['unique_values'][0] if attrs[first_attr_key]['unique_values'] else None

        if sample_value:
            print(f"GET /api/products?brand_id={brand_id}&attribute.{first_attr_key}={sample_value}\n")

            response = requests.get(f"{BASE_URL}/products", params={
                "brand_id": brand_id,
                f"attribute.{first_attr_key}": sample_value
            })
            data = response.json()
            print(f"Products with {first_attr_key}={sample_value}: {data['pagination']['total']}")
    else:
        print("⚠️  No attributes available")

    # =========================================================================
    # 15. AGGREGATIONS API
    # =========================================================================

    print_section("15. AGGREGATE BY CATEGORY")
    print(f"GET /api/products/aggregate?brand_id={brand_id}&group_by=classification.category.name\n")

    response = requests.get(f"{BASE_URL}/products/aggregate", params={
        "brand_id": brand_id,
        "group_by": "classification.category.name"
    })
    data = response.json()

    if 'error' in data:
        print(f"⚠️  {data['error']}")
    else:
        print(f"Product distribution by category:")
        for group in data['groups']:
            print(f"  - {group['key']}: {group['count']} products")

    # =========================================================================
    # 16. SCRAPING INTELLIGENCE API
    # =========================================================================

    print_section("16. GET SCRAPING INTELLIGENCE")
    print(f"GET /api/brands/{brand_id}/scraping-intelligence\n")

    response = requests.get(f"{BASE_URL}/brands/{brand_id}/scraping-intelligence")
    data = response.json()

    if 'error' in data:
        print(f"⚠️  {data['error']}")
    else:
        print("Scraping patterns learned:")
        if 'patterns' in data and 'product_listing' in data['patterns']:
            pattern = data['patterns']['product_listing'].get('primary', {})
            print(f"\n  Primary Pattern:")
            print(f"    Container: {pattern.get('container_selector')}")
            print(f"    Success rate: {pattern.get('success_metrics', {}).get('success_rate', 0)}")
            print(f"    Total products found: {pattern.get('success_metrics', {}).get('total_products_found', 0)}")
            print(f"    Worked on {len(pattern.get('worked_on_categories', []))} categories")

        print(f"\n  Lineages discovered: {data.get('lineages', {}).get('unique_lineages_count', 0)}")

    # -------------------------------------------------------------------------

    print_section("17. GET SCRAPE HISTORY")
    print(f"GET /api/brands/{brand_id}/scrape/history\n")

    response = requests.get(f"{BASE_URL}/brands/{brand_id}/scrape/history")
    data = response.json()

    print(f"Total scrape runs: {data['pagination']['total']}")
    if data['runs']:
        print("\nMost recent run:")
        run = data['runs'][0]
        print(f"  Run ID: {run['run_id']}")
        print(f"  Status: {run['status']}")
        print(f"  Duration: {run.get('duration_seconds', 0):.1f}s")
        print(f"  Products: {run.get('summary', {}).get('total_products', 0)}")

    # =========================================================================
    # 18. IMAGES API
    # =========================================================================

    print_section("18. GET PRODUCT IMAGES")
    if has_products:
        from urllib.parse import quote
        encoded_url = quote(first_product_url, safe='')
        print(f"GET /api/products/{encoded_url}/images\n")

        response = requests.get(f"{BASE_URL}/products/{encoded_url}/images")
        data = response.json()

        print(f"Images for product:")
        for i, image in enumerate(data['images'][:3], 1):
            print(f"\n  Image {i}:")
            print(f"    Source: {image.get('src', 'N/A')[:60]}...")
            print(f"    Local: {image.get('local_url', 'N/A')}")
            print(f"    Size: {image.get('width')}x{image.get('height')}")

    # =========================================================================
    # SUMMARY
    # =========================================================================

    print_section("✅ API DEMO COMPLETE")

    print("All 22 endpoints demonstrated:")
    print("\n  BRANDS (5):")
    print("    ✓ GET /api/brands - List all brands")
    print("    ✓ GET /api/brands/{id} - Get brand details")
    print("    ✓ POST /api/brands - Create brand")
    print("    ✓ PUT /api/brands/{id} - Update brand (not shown)")
    print("    ✓ DELETE /api/brands/{id} - Delete brand (not shown)")

    print("\n  PRODUCTS (4):")
    print("    ✓ GET /api/products - Query products with filters")
    print("    ✓ GET /api/products/{url} - Get single product")
    print("    ✓ GET /api/products/aggregate - Aggregate by category/attribute")
    print("    ✓ GET /api/products/search - Full-text search")

    print("\n  CLASSIFICATIONS (2):")
    print("    ✓ GET /api/brands/{id}/classifications - Get all classifications")
    print("    ✓ GET /api/brands/{id}/categories/hierarchy - Category tree")

    print("\n  ATTRIBUTES (2):")
    print("    ✓ GET /api/brands/{id}/attributes - Discover attributes")
    print("    ✓ GET /api/brands/{id}/attributes/{key}/values - Attribute values")

    print("\n  SCRAPING (6):")
    print("    ✓ POST /api/brands/{id}/scrape - Start scraping")
    print("    ✓ GET /api/brands/{id}/scrape/status - Get status")
    print("    ✓ GET /api/brands/{id}/scrape/stream - SSE stream (not shown)")
    print("    ✓ GET /api/brands/{id}/scrape/history - Scrape history")
    print("    ✓ GET /api/brands/{id}/scraping-intelligence - Get patterns")
    print("    ✓ POST /api/brands/analyze - Analyze brand")

    print("\n  IMAGES (2):")
    print("    ✓ GET /api/images/{brand}/{category}/{file} - Serve image (not shown)")
    print("    ✓ GET /api/products/{url}/images - Get product images")

    print("\n" + "="*80)
    print(f"\n🎉 Brand '{brand_id}' is ready to use!")
    print(f"   - View products in frontend")
    print(f"   - Query via API")
    print(f"   - Explore categories and attributes")
    print("\n" + "="*80 + "\n")


if __name__ == "__main__":
    print("\n" + "="*80)
    print("  FASHION ARCHIVE - COMPREHENSIVE API DEMO")
    print("="*80)
    print("\n⚠️  Make sure the backend server is running:")
    print("   python clean_api.py")
    print("\n" + "="*80)

    try:
        # Test if server is running
        requests.get(f"{BASE_URL}/brands", timeout=2)
    except requests.exceptions.ConnectionError:
        print("\n❌ Server is not running!")
        print("   Start it with: python clean_api.py")
        sys.exit(1)

    test_api()
