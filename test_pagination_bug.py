#!/usr/bin/env python3
"""
Test Pagination Bug
===================

Simple script to reproduce the pagination infinite loop bug with Gully Labs
"""

import sys
import os

# Add scraper_premium to path
sys.path.append('scraper_premium')
sys.path.append('scraper_premium/tests')

def test_gully_labs_pagination():
    """Test the problematic Gully Labs URL that causes infinite loop"""
    
    from test_single_category_pagination import test_single_category_with_pagination
    
    print("🐛 Testing Gully Labs pagination bug...")
    print("URL: https://gullylabs.com/collections/everyday-wear-sneakers-women")
    print("This should reproduce the infinite loop where it keeps going to empty pages")
    print("-" * 80)
    
    try:
        result = test_single_category_with_pagination(
            "https://gullylabs.com/collections/everyday-wear-sneakers-women", 
            "Gully Labs"
        )
        
        print(f"\n🧪 TEST RESULT: {'✅ SUCCESS' if result['success'] else '❌ FAILED'}")
        if result['success']:
            print(f"   📄 {result['total_pages']} pages processed")
            print(f"   📦 {result['total_products']} products extracted")
            print(f"   🔄 Pagination detected: {result['pagination_detected']}")
            if result['pagination_detected']:
                print(f"   📋 Pattern: {result['pagination_pattern']}")
        
        return result
        
    except KeyboardInterrupt:
        print("\n⚠️  Test interrupted by user (likely infinite loop)")
        return {"success": False, "error": "Interrupted - infinite loop detected"}
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    print("=" * 80)
    print("🐛 PAGINATION BUG REPRODUCTION TEST")
    print("=" * 80)
    
    result = test_gully_labs_pagination()
    
    print(f"\n📋 Final Result: {result}")