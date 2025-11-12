#!/usr/bin/env python3
"""
Test 3: Product Extraction with Scroll
======================================

Tests product extraction with scrolling to get all products on a single page.
"""

import sys
import os
import json

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from page_extractor import extract_products_from_page
from brand import Brand
from test_utils import TestLogger, test_timer, assert_with_logging, run_test_multiple_times
from rich.table import Table
from rich.console import Console


class LatencyTracker:
    """Track latency for different pipeline steps"""
    
    def __init__(self):
        self.results = []
    
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
    
    def add_result(self, brand_name: str, scroll_extraction_ms: float, 
                   lineage_filtering_ms: float, total_ms: float, success: bool, 
                   products_found: int = 0, products_after_filtering: int = 0, 
                   load_more_detected: bool = False, pagination_detected: dict = None):
        """Add timing results for a brand"""
        
        # Format pagination detection info
        pagination_info = "➖"  # Default: no pagination
        if pagination_detected and pagination_detected.get("pagination_found", False):
            pattern = pagination_detected.get("url_pattern", "?")
            max_page = pagination_detected.get("max_page_detected")
            if max_page:
                pagination_info = f"📊{pattern}(1-{max_page})"
            else:
                pagination_info = f"🔗{pattern}(seq)"
        
        self.results.append({
            'brand': brand_name,
            'scroll_extraction': self._format_time(scroll_extraction_ms),
            'lineage_filtering': self._format_time(lineage_filtering_ms),
            'total': self._format_time(total_ms),
            'products_found': products_found,
            'products_after_filtering': products_after_filtering,
            'load_more_detected': load_more_detected,
            'pagination_detected': pagination_info,
            'success': success
        })
    
    def print_summary(self):
        """Print latency summary in table format"""
        if not self.results:
            return
            
        console = Console()
        table = Table(title="Scroll Extraction Latency Summary")
        
        table.add_column("Brand", style="cyan")
        table.add_column("Scroll Extraction", justify="right")
        table.add_column("Lineage Filtering", justify="right")
        table.add_column("Products Found", justify="center")
        table.add_column("After Filtering", justify="center")
        table.add_column("Load More", justify="center")
        table.add_column("More Links", justify="center")
        table.add_column("Total", justify="right")
        table.add_column("Status", justify="center")
        
        for result in self.results:
            status = "✅" if result['success'] else "❌"
            load_more_status = "🔘" if result.get('load_more_detected', False) else "➖"
            pagination_status = result.get('pagination_detected', "➖")
            table.add_row(
                result['brand'],
                result['scroll_extraction'],
                result['lineage_filtering'],
                str(result['products_found']),
                str(result['products_after_filtering']),
                load_more_status,
                pagination_status,
                result['total'],
                status
            )
        
        console.print(table)


def load_brand_from_json(brand_key: str):
    """Load brand data from brands.json file"""
    brands_json_path = os.path.join(os.path.dirname(__file__), "brands.json")
    
    try:
        with open(brands_json_path, 'r') as f:
            brands_data = json.load(f)
        return brands_data.get(brand_key)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return None




def get_navigation_leaf_urls(navigation_tree):
    """Extract leaf URLs from navigation tree"""
    urls = []
    
    for node in navigation_tree:
        if isinstance(node, dict):
            children = node.get('children', [])
            
            if children:
                # Has children - recurse into children
                urls.extend(get_navigation_leaf_urls(children))
            else:
                # No children - this is a leaf node
                url = node.get('url')
                if url:
                    urls.append(url)
    
    return urls


def test_all_brands(latency_tracker: LatencyTracker = None, verbose: bool = False):
    """Test scroll extraction for all brands with scroll_test data"""
    
    # Load brands.json
    brands_data = load_brands_json()
    if not brands_data:
        print("Failed to load brands.json")
        return False
    
    results = {}
    brand_results = []
    
    for brand_key, brand_info in brands_data.items():
        # Skip brands without patterns
        if not brand_info.get("pattern"):
            continue
            
        # Skip brands without scroll_test
        scroll_test = brand_info.get('scroll_test')
        if not scroll_test:
            continue
        
        test_url = scroll_test[0]
        expected_products = scroll_test[1]
        
        test_key = brand_key
        result = test_scroll_extraction_url(brand_key, test_url, expected_products, latency_tracker, verbose)
        results[test_key] = result
        
        # Store brand results for summary table
        brand_results.append({
            'brand': brand_info.get('name', brand_key),
            'products_found': result.get('products_found', 0) if isinstance(result, dict) else 0
        })
    
    # Print brand results table
    console = Console()
    table = Table(title="Scroll Extraction Results")
    table.add_column("Brand", style="cyan")
    table.add_column("Products Found", justify="center")
    
    for brand_result in brand_results:
        table.add_row(
            brand_result['brand'],
            str(brand_result['products_found'])
        )
    
    console.print(table)
    
    return True


def load_brands_json():
    """Load brands.json file"""
    brands_json_path = os.path.join(os.path.dirname(__file__), "brands.json")
    
    try:
        with open(brands_json_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return None


def test_scroll_extraction_url(brand_key: str, category_url: str, expected_products: int, 
                              latency_tracker: LatencyTracker = None, verbose: bool = False):
    """Test product extraction with scrolling on a specific URL"""
    
    # Setup
    total_start = time.time()
    
    # Load brand data from brands.json
    brand_data = load_brand_from_json(brand_key)
    if not brand_data:
        if latency_tracker:
            latency_tracker.add_result(brand_key, 0.0, 0.0, (time.time() - total_start) * 1000, False, 0, 0, False)
        return {'products_found': 0}
    
    # Check if brand has a pattern
    if not brand_data.get("pattern"):
        if latency_tracker:
            latency_tracker.add_result(brand_data.get("name", brand_key), 0.0, 0.0, (time.time() - total_start) * 1000, False, 0, 0, False)
        return {'products_found': 0}
    
    try:
        # Use pattern from brands.json
        brand_pattern = brand_data["pattern"]
        patterns = [brand_pattern]
        
        # Create Brand instance for load more functionality
        homepage_url = brand_data.get('homepage_url', category_url)
        brand_instance = Brand(homepage_url)
        
        # Extract Products with Scrolling
        print(f"\n🚀 EXTRACTING PRODUCTS WITH SCROLLING:")
        print(f"   🌐 URL: {category_url}")
        print(f"   📦 Using pattern: {brand_pattern.get('container_selector', 'N/A')}")
        
        scroll_start = time.time()
        extraction_result = extract_products_from_page(
            category_url,
            patterns,
            brand_data["name"],
            allow_pattern_discovery=False,
            brand_instance=brand_instance
        )
        scroll_extraction_ms = (time.time() - scroll_start) * 1000
        
        products = extraction_result.get("products", [])
        pagination_triggers = extraction_result.get("pagination_triggers_found", [])
        pagination_detected = extraction_result.get("pagination_detected", {})
        
        # Extract lineage filtering metrics
        metrics = extraction_result.get("metrics", {})
        lineage_filtering_ms = metrics.get("lineage_filtering_time", 0) * 1000  # Convert to ms
        products_before_filtering = metrics.get("products_before_filtering", len(products))
        
        # Deduplicate products by product name
        seen_names = set()
        unique_products = []
        for product in products:
            name = product.get("product_name", "").strip()
            if name and name != "N/A" and name not in seen_names:
                seen_names.add(name)
                unique_products.append(product)
        
        products = unique_products
        
        # Print product table if verbose
        if verbose and products:
            console = Console()
            table = Table(title=f"{brand_data['name']} - Products Found (Deduplicated)", width=None)
            table.add_column("No.", justify="center", width=6)
            table.add_column("Scroll #", justify="center", width=8)
            table.add_column("Product Name", width=30)
            table.add_column("Product URL", no_wrap=False, overflow="fold")
            table.add_column("Images", width=20)
            
            for i, product in enumerate(products, 1):
                # Get first image from images array
                images = product.get("images", [])
                first_image = images[0].get("src", "N/A") if images else "N/A"
                image_count = f"{len(images)} images" if len(images) > 1 else first_image
                
                # All products are from single extraction now
                table.add_row(
                    str(i),
                    "1",
                    product.get("product_name", "N/A"),
                    product.get("product_url", "N/A"),
                    image_count
                )
            
            console.print(table, overflow="ignore", crop=False)
        
        # Validate against expected count
        products_found = len(products)
        success = products_found > 0
        
        if products_found != expected_products:
            print(f"⚠️  Expected {expected_products} products, found {products_found} for {brand_data['name']}")
            if products_found == 0:
                success = False
        else:
            print(f"✅ Found expected {expected_products} products for {brand_data['name']}")
        
        # Display pagination triggers found
        if pagination_triggers:
            print(f"🎯 Pagination Triggers Found: {', '.join(pagination_triggers)}")
        else:
            print(f"📄 No pagination triggers found - used standard bottom scroll")
        
        # Display More Links pagination detection results
        if pagination_detected.get("pagination_found", False):
            pattern = pagination_detected.get("url_pattern", "N/A")
            max_page = pagination_detected.get("max_page_detected")
            next_url = pagination_detected.get("next_page_url")
            reasoning = pagination_detected.get("reasoning", "")
            
            if max_page:
                print(f"📊 More Links: Multi-page pagination detected - Pattern: {pattern}, Max: {max_page}")
            elif next_url:
                print(f"📊 More Links: Sequential pagination detected - Pattern: {pattern}, Next: {next_url}")
            else:
                print(f"📊 More Links: Pagination detected - Pattern: {pattern}")
            print(f"   💡 Reasoning: {reasoning}")
        else:
            reasoning = pagination_detected.get("reasoning", "No pagination detected")
            print(f"📄 More Links: Single-page category - {reasoning}")
        
        # Display load more statistics
        if brand_instance.load_more_detected is not None:
            if brand_instance.load_more_detected == True:
                modals_count = brand_instance.load_more_modal_bypasses.get('modals_detected', 0)
                print(f"📝 Load More Detected: {brand_instance.load_more_button_selector}")
                if modals_count > 0:
                    print(f"🚫 Modal Bypasses Stored: {modals_count}")
            else:
                print(f"📝 Load More: None detected")
        
        # Record timing results
        total_ms = (time.time() - total_start) * 1000
        if latency_tracker:
            load_more_detected = brand_instance.load_more_detected == True
            latency_tracker.add_result(brand_data["name"], scroll_extraction_ms, 
                                     lineage_filtering_ms, total_ms, success, 
                                     products_before_filtering, products_found, 
                                     load_more_detected, pagination_detected)
        
        return {'products_found': products_found}
        
    except Exception as e:
        # Record timing for exception cases
        total_ms = (time.time() - total_start) * 1000
        if latency_tracker:
            latency_tracker.add_result(brand_data.get("name", brand_key), 0.0, 0.0, 
                                     total_ms, False, 0, 0, False, {})
        
        return {'products_found': 0}


if __name__ == "__main__":
    import time
    from test_logger import capture_test_output
    
    # Build command string for logging
    command = f"python {os.path.basename(__file__)} {' '.join(sys.argv[1:])}"
    
    with capture_test_output("Scroll Extraction Test", command):
        # Initialize latency tracker
        latency_tracker = LatencyTracker()
        
        # Check for verbose flag
        verbose = '-v' in sys.argv
        if verbose:
            sys.argv.remove('-v')
        
        def run_single_test():
            if len(sys.argv) > 1:
                # Test specific brand
                brand_key = sys.argv[1]
                
                # Load brand data to get scroll_test
                brands_data = load_brands_json()
                if not brands_data or brand_key not in brands_data:
                    print(f"Brand '{brand_key}' not found in brands.json")
                    exit(1)
                
                brand_info = brands_data[brand_key]
                
                # Check if brand has pattern and scroll_test
                if not brand_info.get("pattern"):
                    print(f"Brand '{brand_key}' has no pattern - skipping")
                    exit(1)
                    
                scroll_test = brand_info.get('scroll_test')
                if not scroll_test:
                    print(f"Brand '{brand_key}' has no scroll_test - skipping")
                    exit(1)
                
                test_url = scroll_test[0]
                expected_products = scroll_test[1]
                
                result = test_scroll_extraction_url(brand_key, test_url, expected_products, latency_tracker, verbose)
                
                # Print latency summary
                latency_tracker.print_summary()
                return result
            else:
                # Test all brands from brands.json
                result = test_all_brands(latency_tracker, verbose)
                
                # Print latency summary
                latency_tracker.print_summary()
                return result
        
        # Run test multiple times if -N flag is specified
        run_test_multiple_times(run_single_test)