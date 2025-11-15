"""
Integration Test
================

Test the complete storage and API integration.
"""

import requests
import json


def test_brand_api():
    """Test brand API endpoints"""
    base_url = "http://localhost:8081/api"

    print("Testing Brand API...")

    # 1. List brands
    print("\n1. GET /brands")
    response = requests.get(f"{base_url}/brands")
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)[:200]}...")

    # 2. Create brand
    print("\n2. POST /brands")
    response = requests.post(f"{base_url}/brands", json={
        "name": "Test Brand",
        "homepage_url": "https://testbrand.com"
    })
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")

    if response.status_code in [200, 201]:
        brand_id = response.json().get('brand_id')

        # 3. Get brand
        print(f"\n3. GET /brands/{brand_id}")
        response = requests.get(f"{base_url}/brands/{brand_id}")
        print(f"Status: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)[:200]}...")

        # 4. Get products (should be empty)
        print(f"\n4. GET /products?brand_id={brand_id}")
        response = requests.get(f"{base_url}/products", params={"brand_id": brand_id})
        print(f"Status: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")

        # 5. Delete brand
        print(f"\n5. DELETE /brands/{brand_id}")
        response = requests.delete(f"{base_url}/brands/{brand_id}")
        print(f"Status: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")


def test_storage_direct():
    """Test storage layer directly"""
    print("\nTesting Storage Layer Directly...")

    from storage import get_storage

    storage = get_storage(mode="files")

    # Create test brand
    brand_data = {
        "brand_id": "test_direct",
        "name": "Test Direct",
        "homepage_url": "https://test.com",
        "domain": "test.com",
        "status": {},
        "metadata": {},
        "data_path": "data/brands/test_direct"
    }

    success = storage.create_brand("test_direct", brand_data)
    print(f"Create brand: {success}")

    # Read brand
    brand = storage.get_brand("test_direct")
    print(f"Read brand: {brand['name'] if brand else 'None'}")

    # List brands
    brands, total = storage.list_brands()
    print(f"List brands: {total} total")

    # Delete brand
    success = storage.delete_brand("test_direct")
    print(f"Delete brand: {success}")


if __name__ == "__main__":
    print("=" * 60)
    print("INTEGRATION TEST")
    print("=" * 60)

    # Test storage layer
    test_storage_direct()

    print("\n" + "=" * 60)
    print("API TEST (requires server running)")
    print("=" * 60)

    try:
        test_brand_api()
    except requests.exceptions.ConnectionError:
        print("\n⚠️  API server not running. Start with: python clean_api.py")

    print("\n" + "=" * 60)
    print("✅ INTEGRATION TEST COMPLETE")
    print("=" * 60)
