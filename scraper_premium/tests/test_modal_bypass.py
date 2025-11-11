"""
Test Modal Bypass Engine
========================

Simple test script to verify modal detection and bypassing functionality.
"""

import json
import sys
import os
from playwright.sync_api import sync_playwright

# Add current directory to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

from modal_bypass_engine import ModalBypassEngine
from brand import Brand


def test_modal_detection():
    """Test modal detection on a page with known modals"""
    
    # Sample brand data with known modal bypasses
    brand_data = {
        "modal_bypasses": {
            "subscription": [
                "display: none !important;",
                "visibility: hidden !important;"
            ],
            "cookie_consent": [
                "z-index: -9999 !important;",
                "opacity: 0 !important;"
            ],
            "last_updated": "2024-11-06"
        }
    }
    
    # Test URLs that commonly have modals
    test_urls = [
        "https://gullylabs.com",
        "https://www.entirestudios.com",
        "https://iconaclub.com"
    ]
    
    print("🔍 Testing Modal Bypass Engine")
    print("=" * 50)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # Non-headless to see results
        page = browser.new_page()
        
        engine = ModalBypassEngine(brand_data)
        
        for url in test_urls:
            print(f"\n🌐 Testing: {url}")
            try:
                # Load page
                page.goto(url, wait_until="domcontentloaded", timeout=10000)
                page.wait_for_timeout(3000)  # Wait for modals to appear
                
                # Test modal detection and bypass
                results = engine.bypass_modals(page, url)
                
                print(f"   Modals detected: {results['modals_detected']}")
                print(f"   Modals bypassed: {results['modals_bypassed']}")
                print(f"   Success: {results['success']}")
                print(f"   Time taken: {results['total_time']:.2f}s")
                
                if results['successful_attacks']:
                    print(f"   Successful attacks:")
                    for attack in results['successful_attacks']:
                        print(f"     - {attack['modal_type']}: {attack['css_rule']}")
                
                # Wait to see results
                page.wait_for_timeout(2000)
                
            except Exception as e:
                print(f"   ❌ Error: {str(e)}")
        
        print(f"\n📋 Final brand data with learned attacks:")
        print(json.dumps(brand_data.get("modal_bypasses", {}), indent=2))
        
        browser.close()


def test_brand_integration():
    """Test modal bypass integration with Brand class"""
    
    print("\n🔗 Testing Brand Integration")
    print("=" * 50)
    
    # Create brand instance
    brand = Brand("https://gullylabs.com")
    
    # Load sample brand data
    brand_data = {
        "modal_bypasses": {
            "subscription": ["display: none !important;"],
            "cookie_consent": ["opacity: 0 !important;"],
            "last_updated": "2024-11-06"
        }
    }
    brand.load_brand_data(brand_data)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        
        # Test page loading with automatic modal bypass
        page.goto("https://gullylabs.com", wait_until="domcontentloaded", timeout=10000)
        page.wait_for_timeout(2000)
        
        # Test modal bypass
        results = brand.bypass_page_modals(page, "https://gullylabs.com")
        
        print(f"Brand modal bypass results:")
        print(f"   Modals detected: {results['modals_detected']}")
        print(f"   Modals bypassed: {results['modals_bypassed']}")
        print(f"   Success: {results['success']}")
        
        # Save updated brand data
        brand.save_brand_data("test_brand_data.json")
        print(f"   ✅ Saved learned attacks to test_brand_data.json")
        
        browser.close()


if __name__ == "__main__":
    print("🚀 Starting Modal Bypass Engine Tests")
    print("=" * 60)
    
    # Test 1: Modal detection and bypass
    test_modal_detection()
    
    # Test 2: Brand integration
    test_brand_integration()
    
    print("\n✅ All tests completed!")
    print("Check the browser windows to see modal bypass in action.")