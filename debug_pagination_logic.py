#!/usr/bin/env python3
"""
Debug Pagination Logic
======================

Debug script to understand exactly what's happening in the pagination condition
"""

def test_pagination_condition_logic():
    """Test the exact logic used in pagination"""
    
    print("🔍 Testing pagination condition logic")
    print("=" * 50)
    
    # Simulate different page_result scenarios
    test_cases = [
        {
            "name": "Empty products list",
            "page_result": {
                "success": True,
                "products": []  # Empty list
            }
        },
        {
            "name": "None products",
            "page_result": {
                "success": True, 
                "products": None
            }
        },
        {
            "name": "Valid products",
            "page_result": {
                "success": True,
                "products": ["product1", "product2"]
            }
        },
        {
            "name": "Failed page load",
            "page_result": {
                "success": False,
                "products": []
            }
        },
        {
            "name": "Success but no products key",
            "page_result": {
                "success": True
                # No products key at all
            }
        }
    ]
    
    for test in test_cases:
        print(f"\n📋 Test: {test['name']}")
        page_result = test['page_result']
        
        # This is the exact condition from the pagination loop
        condition_result = page_result["success"] and page_result.get("products", [])
        
        print(f"   success: {page_result['success']}")
        print(f"   products: {page_result.get('products', 'KEY_MISSING')}")
        print(f"   condition result: {condition_result}")
        print(f"   would continue pagination: {'YES' if condition_result else 'NO'}")
        
        # Check the individual parts
        success_part = page_result["success"]
        products_part = page_result.get("products", [])
        
        print(f"   success_part: {success_part} (type: {type(success_part)})")
        print(f"   products_part: {products_part} (type: {type(products_part)})")
        print(f"   products_part truthiness: {bool(products_part)}")

if __name__ == "__main__":
    test_pagination_condition_logic()