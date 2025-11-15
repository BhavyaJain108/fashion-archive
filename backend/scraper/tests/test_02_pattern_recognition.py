#!/usr/bin/env python3
"""
Pattern Recognition Test
========================

Tests product pattern discovery and extraction using navigation tree URLs.
"""

import sys
import os
import time
import json
import re
from typing import Dict, List, Optional
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
# No need for BeautifulSoup - we use existing extraction logic
from urllib.parse import urljoin, urlparse

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brand import Brand
from page_extractor import extract_products_from_page
from rich.table import Table
from rich.console import Console


class LatencyTracker:
    """Track latency for different pipeline steps"""
    
    def __init__(self):
        self.results: List[Dict] = []
    
    def _format_time(self, ms: float) -> str:
        """Format time in appropriate units (ms/s/m:s)"""
        if ms < 1000:
            return f"{round(ms, 1)}ms"
        elif ms < 60000:
            return f"{round(ms/1000, 2)}s"
        else:
            minutes = int(ms // 60000)
            seconds = round((ms % 60000) / 1000, 1)
            return f"{minutes}m {seconds}s"
    
    def add_result(self, brand_name: str, analyze_pattern_ms: float, 
                   extract_products_ms: float, total_ms: float, success: bool):
        """Add timing results for a brand"""
        self.results.append({
            'brand': brand_name,
            'analyze_pattern': self._format_time(analyze_pattern_ms),
            'extract_products': self._format_time(extract_products_ms), 
            'total': self._format_time(total_ms),
            'success': success
        })
    
    def print_summary(self):
        """Print latency summary in table format"""
        if not self.results:
            return
            
        console = Console()
        table = Table(title="Latency Summary")
        
        table.add_column("Brand", style="cyan")
        table.add_column("analyze_product_pattern", justify="right")
        table.add_column("extract_products_from_page", justify="right") 
        table.add_column("Total", justify="right")
        table.add_column("Status", justify="center")
        
        for result in self.results:
            status = "✅" if result['success'] else "❌"
            table.add_row(
                result['brand'],
                result['analyze_pattern'],
                result['extract_products'],
                result['total'],
                status
            )
        
        console.print(table)


# Import from production
from page_extractor import get_first_leaf_url


def extract_name_from_url(url: str) -> str:
    """Extract product name from URL using same logic as page_extractor.py"""
    if not url:
        return 'Unknown'
    
    # Clean and split the URL path
    path = urlparse(url).path
    segments = [seg for seg in path.split('/') if seg]
    
    if not segments:
        return 'Unknown'
    
    # Get the last segment (usually the product slug)
    product_segment = segments[-1]
    
    # Clean up the segment
    # Remove common suffixes and prefixes
    cleaned = re.sub(r'^(product-|item-|p-)', '', product_segment)
    cleaned = re.sub(r'(-p\d+|-item|-product)$', '', cleaned)
    
    # Convert dashes/underscores to spaces and title case
    name = cleaned.replace('-', ' ').replace('_', ' ').strip()
    name = ' '.join(word.capitalize() for word in name.split() if word)
    
    return name if name else 'Unknown'


def validate_pattern_against_static_html(brand_key: str, pattern: dict, brands_data: dict) -> dict:
    """
    Validate discovered pattern against static HTML file using existing extraction logic.
    
    Args:
        brand_key: Brand identifier (e.g., 'gullylabs')
        pattern: Discovered pattern with selectors
        brands_data: Full brands data dictionary
        
    Returns:
        dict: Validation results with success status and detailed metrics
    """
    validation_result = {
        'success': False,
        'containers_found': 0,
        'products_extracted': [],
        'errors': [],
        'details': {}
    }
    
    # Build path to HTML file
    test_dir = os.path.dirname(__file__)
    html_file_path = os.path.join(test_dir, 'product_html', f'{brand_key}.html')
    
    # Check if HTML file exists
    if not os.path.exists(html_file_path):
        validation_result['errors'].append(f"HTML file not found: {html_file_path}")
        return validation_result
    
    # Check if file has content
    try:
        with open(html_file_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        if not html_content.strip():
            validation_result['errors'].append("HTML file is empty")
            return validation_result
    except Exception as e:
        validation_result['errors'].append(f"Error reading HTML file: {e}")
        return validation_result
    
    try:
        # Use the existing extract_products_from_page function with file:// URL
        file_url = f"file://{html_file_path}"
        brand_name = brands_data.get(brand_key, {}).get('name', brand_key)
        
        # Call the existing extraction function
        extraction_result = extract_products_from_page(
            file_url,
            [pattern],  # Pass the pattern as a list
            brand_name,
            allow_pattern_discovery=False  # Don't try to discover new patterns
        )
        
        # Process the results
        if extraction_result.get('success', False):
            products = extraction_result.get('products', [])
            validation_result['products_extracted'] = products
            validation_result['containers_found'] = len(products)  # Each product represents a container
            validation_result['success'] = len(products) > 0
            
            # Add detailed information
            validation_result['details'] = {
                'total_containers': len(products),
                'valid_products': len(products),
                'pattern_selectors': {
                    'container': pattern.get('container_selector', ''),
                    'image': pattern.get('image_selector', ''),
                    'name': pattern.get('name_selector', ''),
                    'link': pattern.get('link_selector', '')
                },
                'extraction_metrics': extraction_result.get('metrics', {})
            }
        else:
            # Extraction failed
            error_msg = extraction_result.get('error', 'Unknown extraction error')
            validation_result['errors'].append(f"Extraction failed: {error_msg}")
            validation_result['success'] = False
            
    except Exception as e:
        validation_result['errors'].append(f"Validation error: {e}")
        validation_result['success'] = False
    
    return validation_result


def test_pattern_recognition_simple(brand_key: str, brands_data: dict, 
                                  latency_tracker: LatencyTracker = None, 
                                  update_pattern: bool = False):
    """Simple pattern recognition test: discover pattern and extract products"""
    
    total_start = time.time()
    
    if brand_key not in brands_data:
        print(f"Brand '{brand_key}' not found in brands.json")
        return False
    
    brand_info = brands_data[brand_key]
    navigation = brand_info.get('navigation')
    
    # Check if brand has navigation tree
    if not navigation:
        print(f"{brand_info['name']} - ⚠️  NO NAVIGATION TREE\n")
        return False
    
    # Get first leaf URL from navigation tree
    first_leaf_url = get_first_leaf_url(navigation)
    if not first_leaf_url:
        print(f"{brand_info['name']} - ❌ FAILURE")
        print("REASON: No leaf URLs found in navigation tree")
        print()
        return False
    
    # Print clear test information
    print(f"\n{'='*60}")
    print(f"🔍 TESTING BRAND: {brand_info['name']}")
    print(f"🌐 HOMEPAGE: {brand_info['homepage_url']}")
    print(f"🎯 PATTERN DISCOVERY URL: {first_leaf_url}")
    print(f"{'='*60}")
    
    # Create brand and set up for pattern analysis
    brand = Brand(brand_info['homepage_url'])
    brand.starting_pages_queue = [first_leaf_url]
    brand.product_pages = [first_leaf_url]
    
    # Time pattern analysis (show debug output for reasoning)
    pattern_start = time.time()
    pattern_result = brand.analyze_product_pattern()
    analyze_pattern_ms = (time.time() - pattern_start) * 1000
    
    extract_products_ms = 0.0
    
    if not pattern_result or not pattern_result.get("extraction_pattern"):
        print(f"{brand_info['name']} - ❌ PATTERN NOT FOUND")
        error_msg = pattern_result.get("error", "No consistent product containers detected")
        print(f"  Error: {error_msg}")
        print()
        
        # Record timing for failure
        total_ms = (time.time() - total_start) * 1000
        if latency_tracker:
            latency_tracker.add_result(brand_info['name'], analyze_pattern_ms, 
                                     extract_products_ms, total_ms, False)
        return False
    
    # Pattern found - display details
    extraction_pattern = pattern_result.get("extraction_pattern", {})
    print(f"\n✅ PATTERN DISCOVERY SUCCESSFUL")
    print(f"📋 DISCOVERED SELECTORS:")
    print(f"   📦 Container: {extraction_pattern.get('container_selector', 'N/A')}")
    print(f"   🖼️  Image: {extraction_pattern.get('image_selector', 'N/A')}")
    print(f"   🔗 Link: {extraction_pattern.get('link_selector', 'N/A')}")
    print(f"   📝 Name: {extraction_pattern.get('name_selector', 'N/A')}")
    
    # CRITICAL: Validate pattern against static HTML before proceeding
    validation_result = validate_pattern_against_static_html(brand_key, extraction_pattern, brands_data)
    
    if validation_result['success']:
        print(f"  📄 STATIC VALIDATION: ✅ PASSED")
        print(f"    - Found {validation_result['containers_found']} product(s)")
        
        # Show first extracted product as example
        if validation_result['products_extracted']:
            first_product = validation_result['products_extracted'][0]
            print(f"    - Product URL: {first_product.get('product_url', 'N/A')}")
            print(f"    - Product Name: \"{first_product.get('product_name', 'N/A')}\"")
            images = first_product.get('images', [])
            if images:
                print(f"    - Images Found: {len(images)}")
                for i, img in enumerate(images, 1):
                    print(f"      {i}. {img.get('src', 'N/A')}")
            else:
                print(f"    - Images Found: 0")
    else:
        print(f"  📄 STATIC VALIDATION: ❌ FAILED")
        for error in validation_result['errors']:
            print(f"    - {error}")
        
        # If static validation fails, the pattern is fundamentally broken
        print(f"  ❌ PATTERN REJECTED - Cannot extract required fields from static HTML")
        print()
        
        # Record timing for failure
        total_ms = (time.time() - total_start) * 1000
        if latency_tracker:
            latency_tracker.add_result(brand_info['name'], analyze_pattern_ms, 
                                     extract_products_ms, total_ms, False)
        return False
    
    # Time product extraction (suppress debug output)
    print(f"\n🚀 EXTRACTING PRODUCTS FROM LIVE URL:")
    print(f"   🌐 {first_leaf_url}")
    
    extract_start = time.time()
    with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
        extraction_result = extract_products_from_page(
            first_leaf_url,
            [extraction_pattern],
            brand_info['name']
        )
    extract_products_ms = (time.time() - extract_start) * 1000
    
    # Display extracted products with full validation
    products = extraction_result.get("products", [])
    all_products_valid = True
    
    if products:
        print(f"  Products Found ({min(len(products), 3)}):")
        for i, product in enumerate(products[:3]):
            name = product.get('product_name', '').strip()
            images = product.get('images', [])
            product_url = product.get('product_url', '').strip()
            
            # Check if all required fields are present and valid
            missing_fields = []
            if not name or name == 'N/A':
                missing_fields.append('name')
            if not images or len(images) == 0:
                missing_fields.append('images')
            if not product_url or product_url == 'N/A':
                missing_fields.append('url')
            
            if missing_fields:
                print(f"    {i+1}. ❌ INCOMPLETE - Missing: {', '.join(missing_fields)}")
                print(f"        Name: {name if name else '[MISSING]'}")
                print(f"        Images: {len(images)} found" if images else '[MISSING]')
                print(f"        URL: {product_url if product_url else '[MISSING]'}")
                all_products_valid = False
            else:
                print(f"    {i+1}. ✅ {name}")
                print(f"        Images: {len(images)} found")
                if images:
                    for j, img in enumerate(images, 1):
                        print(f"          {j}. {img.get('src', 'N/A')}")
                print(f"        URL: {product_url}")
        
        # If any products are incomplete, this is a pattern failure
        if not all_products_valid:
            print(f"  ❌ PATTERN INCOMPLETE - Cannot extract all required fields")
            return False
    else:
        print(f"  Products Found (0): No products extracted")
        all_products_valid = False
    
    # Auto-update pattern if null or update flag is set
    if brand_info.get('pattern') is None or update_pattern:
        brands_data[brand_key]['pattern'] = extraction_pattern
        print(f"  📝 Updated pattern data for {brand_info['name']}")
    
    print()  # Empty line between brands
    
    # Record timing
    total_ms = (time.time() - total_start) * 1000
    success = len(products) > 0 and all_products_valid
    if latency_tracker:
        latency_tracker.add_result(brand_info['name'], analyze_pattern_ms, 
                                 extract_products_ms, total_ms, success)
    
    return success


if __name__ == "__main__":
    from test_logger import capture_test_output
    
    # Build command string for logging
    command = f"python {os.path.basename(__file__)} {' '.join(sys.argv[1:])}"
    
    with capture_test_output("Pattern Recognition Test", command):
        # Load brands.json
        brands_file = os.path.join(os.path.dirname(__file__), 'brands.json')
        with open(brands_file, 'r') as f:
            brands_data = json.load(f)
        
        # Initialize latency tracker
        latency_tracker = LatencyTracker()
        
        # Check for update-pattern flag
        update_pattern = '--update-pattern' in sys.argv
        if update_pattern:
            sys.argv.remove('--update-pattern')
        
        if len(sys.argv) > 1:
            # Test specific brands
            test_brands = sys.argv[1:]
            for brand_key in test_brands:
                test_pattern_recognition_simple(brand_key, brands_data, latency_tracker, update_pattern)
            
            # Print latency summary
            latency_tracker.print_summary()
        else:
            # Test all brands with navigation trees
            test_brands = [key for key, data in brands_data.items() 
                          if data.get('navigation') is not None]
            
            if not test_brands:
                print("No brands with navigation trees found in brands.json")
            else:
                print(f"Testing {len(test_brands)} brands with navigation trees...")
                print()
                
                for brand_key in test_brands:
                    test_pattern_recognition_simple(brand_key, brands_data, latency_tracker, update_pattern)
                
                print()  # Empty line before summary
                # Print latency summary
                latency_tracker.print_summary()
        
        # Save updated brands.json
        with open(brands_file, 'w') as f:
            json.dump(brands_data, f, indent=2)
        print(f"💾 Saved brands.json")