#!/usr/bin/env python3

import sys
import os
from playwright.sync_api import sync_playwright
import json

def test_entire_studios_timing():
    """Test if waiting longer reduces the number of 'Unknown' products"""
    
    url = "https://www.entirestudios.com/collection/aw25/tag:aw25main"
    pattern = {
        "container_selector": "div.es-character",
        "image_selector": ".es-character-garment img, .es-character-on-model img", 
        "name_selector": ".es-product-uniform-garment-title",
        "link_selector": "a.es-character-inner"
    }
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            ignore_https_errors=True,
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        )
        page = context.new_page()
        
        print(f"Loading page: {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        
        print("Waiting 10 seconds for content to fully load...")
        page.wait_for_timeout(10000)  # Wait 10 seconds instead of 2
        
        # Check containers
        container_selector = pattern["container_selector"]
        name_selector = pattern["name_selector"]
        
        containers = page.locator(container_selector)
        container_count = containers.count()
        print(f"Found {container_count} product containers")
        
        if container_count == 0:
            print("❌ No containers found - selector might be wrong")
            browser.close()
            return
        
        # Count products with and without names
        products_with_names = 0
        products_without_names = 0
        
        # Use JavaScript to extract all product data at once
        extraction_result = page.evaluate(f"""
            () => {{
                const containers = document.querySelectorAll("{container_selector}");
                const results = [];
                
                containers.forEach((container, index) => {{
                    // Check for name element
                    const nameEl = container.querySelector("{name_selector}");
                    const hasName = nameEl && nameEl.innerText && nameEl.innerText.trim() !== '';
                    const nameText = hasName ? nameEl.innerText.trim() : 'Unknown';
                    
                    // Get product URL for reference
                    const linkEl = container.querySelector("{pattern['link_selector']}");
                    const href = linkEl ? linkEl.getAttribute('href') : 'No link';
                    
                    results.push({{
                        index: index + 1,
                        hasName: hasName,
                        nameText: nameText,
                        href: href
                    }});
                }});
                
                return results;
            }}
        """)
        
        # Analyze results
        for result in extraction_result:
            if result['hasName']:
                products_with_names += 1
            else:
                products_without_names += 1
        
        print(f"\n📊 Results after 10-second wait:")
        print(f"   ✅ Products with names: {products_with_names}")
        print(f"   ❌ Products without names (Unknown): {products_without_names}")
        print(f"   📈 Success rate: {(products_with_names/container_count)*100:.1f}%")
        
        # Show some examples of each type
        print(f"\n📋 Examples of products WITH names:")
        with_names = [r for r in extraction_result if r['hasName']][:3]
        for example in with_names:
            print(f"   {example['index']}. '{example['nameText']}' - {example['href']}")
            
        print(f"\n📋 Examples of products WITHOUT names (Unknown):")
        without_names = [r for r in extraction_result if not r['hasName']][:3]
        for example in without_names:
            print(f"   {example['index']}. 'Unknown' - {example['href']}")
        
        browser.close()
        
        # Compare with original results (78 unknowns out of 104)
        original_unknowns = 78
        original_total = 104
        original_success_rate = ((original_total - original_unknowns) / original_total) * 100
        
        print(f"\n🔄 Comparison:")
        print(f"   Original (2s wait): {original_total - original_unknowns}/{original_total} = {original_success_rate:.1f}% success")
        print(f"   New (10s wait): {products_with_names}/{container_count} = {(products_with_names/container_count)*100:.1f}% success")
        
        improvement = (products_with_names/container_count)*100 - original_success_rate
        if improvement > 0:
            print(f"   📈 Improvement: +{improvement:.1f}% success rate")
        else:
            print(f"   📉 Change: {improvement:.1f}% success rate")

if __name__ == "__main__":
    test_entire_studios_timing()