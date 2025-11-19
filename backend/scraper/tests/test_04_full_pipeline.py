#!/usr/bin/env python3
"""
Test 4: Full Pipeline Test
==========================

Tests the complete brand scraping pipeline from homepage to all products.
Single function call does everything: navigation → patterns → multi-page extraction.
"""

import sys
import os
import json
import time

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brand import Brand
from test_utils import TestLogger, test_timer, run_test_multiple_times
from rich.table import Table
from rich.console import Console


class PipelineTracker:
    """Track pipeline results for summary reporting"""

    def __init__(self):
        self.results = []

    def _format_time(self, seconds: float) -> str:
        """Format time in appropriate units"""
        if seconds < 60:
            return f"{seconds:.1f}s"
        else:
            minutes = int(seconds // 60)
            remaining_seconds = seconds % 60
            return f"{minutes}m {remaining_seconds:.1f}s"

    def add_result(self, brand_name: str, success: bool, categories_found: int,
                   products_found: int, images_downloaded: int, extraction_time: float,
                   category_details: dict = None, image_stats: dict = None, pattern_info: dict = None):
        """Add pipeline results for a brand"""
        self.results.append({
            'brand': brand_name,
            'success': success,
            'categories': categories_found,
            'products': products_found,
            'images': images_downloaded,
            'time': self._format_time(extraction_time),
            'category_details': category_details or {},
            'image_stats': image_stats or {},
            'pattern_info': pattern_info or {}
        })
    
    def print_summary(self):
        """Print pipeline results summary"""
        if not self.results:
            return

        console = Console()
        table = Table(title="Full Pipeline Results Summary")

        table.add_column("Brand", style="cyan")
        table.add_column("Categories", justify="center")
        table.add_column("Products", justify="center")
        table.add_column("Images", justify="center")
        table.add_column("Time", justify="right")
        table.add_column("Status", justify="center")

        for result in self.results:
            status = "✅" if result['success'] else "❌"
            table.add_row(
                result['brand'],
                str(result['categories']),
                str(result['products']),
                str(result['images']),
                result['time'],
                status
            )

        console.print(table)

        # Print detailed category breakdown for each brand
        for result in self.results:
            if result.get('category_details'):
                console.print(f"\n[cyan bold]Category Breakdown for {result['brand']}:[/cyan bold]")

                # Create detailed category table
                cat_table = Table(show_header=True, header_style="bold magenta")
                cat_table.add_column("Category URL", style="dim", no_wrap=False)
                cat_table.add_column("Products", justify="center", style="green")
                cat_table.add_column("Images Downloaded", justify="center", style="blue")
                cat_table.add_column("Images Failed", justify="center", style="red")
                cat_table.add_column("Pattern Used", justify="center", style="yellow")

                # Get image stats by category
                image_stats = result.get('image_stats', {})
                pattern_info = result.get('pattern_info', {})

                # Sort categories by product count (descending)
                sorted_categories = sorted(
                    result['category_details'].items(),
                    key=lambda x: x[1],
                    reverse=True
                )

                for category_url, product_count in sorted_categories:
                    # Get image stats for this category
                    cat_img_stats = image_stats.get(category_url, {})
                    downloaded = cat_img_stats.get('downloaded', 0)
                    failed = cat_img_stats.get('failed', 0)

                    # Get pattern info for this category
                    pattern = pattern_info.get(category_url, "Unknown")

                    cat_table.add_row(
                        category_url,
                        str(product_count),
                        str(downloaded),
                        str(failed) if failed > 0 else "-",
                        pattern
                    )

                console.print(cat_table)


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


def test_full_pipeline_single(brand_key: str, tracker: PipelineTracker = None, verbose: bool = False, direct_url: str = None):
    """Test complete pipeline for a single brand"""

    print(f"\n🚀 FULL PIPELINE EXTRACTION:")

    # Check if using direct URL
    if direct_url:
        print(f"   🌐 Direct URL Mode: {direct_url}")
        homepage_url = direct_url
        brand_name = direct_url.split('/')[2]  # Extract domain as brand name
    else:
        print(f"   🌐 Brand: {brand_key}")

        # Load brand data
        brand_data = load_brand_from_json(brand_key)
        if not brand_data:
            print(f"   ❌ Brand '{brand_key}' not found in brands.json")
            return {'success': False, 'error': 'Brand not found'}

        brand_name = brand_data.get("name", brand_key)
        homepage_url = brand_data.get("homepage_url")

        if not homepage_url:
            print(f"   ❌ No homepage_url found for {brand_name}")
            return {'success': False, 'error': 'No homepage URL'}
    
    print(f"   🏠 Homepage: {homepage_url}")
    
    try:
        # Initialize brand instance with test_mode=True to save images in tests/results
        print(f"   🔧 Initializing brand instance...")
        brand = Brand(homepage_url, test_mode=True)

        # THE SINGLE FUNCTION CALL THAT DOES EVERYTHING
        start_time = time.time()
        pipeline_results = brand.run_full_extraction_pipeline()
        total_time = time.time() - start_time

        # Extract summary data
        success = pipeline_results.get("success", False)
        summary = pipeline_results.get("summary", {})
        categories_count = summary.get("total_categories", 0)
        products_count = summary.get("total_products", 0)
        images_count = summary.get("total_images", 0)

        print(f"\n📊 PIPELINE COMPLETE:")
        print(f"   ✅ Success: {success}")
        print(f"   📁 Categories: {categories_count}")
        print(f"   📦 Products: {products_count}")
        print(f"   🖼️  Images: {images_count}")
        print(f"   ⏱️  Time: {total_time:.1f}s")

        # Wait for all image downloads to complete
        download_start = time.time()

        # Check if there are still downloads pending
        with brand.image_stats_lock:
            images_queued = brand.image_stats["total_queued"]
            images_processed = brand.image_stats["total_downloaded"] + brand.image_stats["total_failed"]

        if images_processed < images_queued:
            print(f"\n⏳ Waiting for all image downloads to complete ({images_processed}/{images_queued})...")

            # Poll until all downloads are complete (with timeout)
            max_wait = 300  # 5 minutes max
            poll_interval = 0.5  # Check every 0.5 seconds
            elapsed = 0

            while elapsed < max_wait:
                with brand.image_stats_lock:
                    images_processed = brand.image_stats["total_downloaded"] + brand.image_stats["total_failed"]

                if images_processed >= images_queued:
                    break

                time.sleep(poll_interval)
                elapsed += poll_interval
        else:
            print(f"\n✅ All image downloads already complete!")

        download_time = time.time() - download_start

        # Get final image stats
        with brand.image_stats_lock:
            final_images_downloaded = brand.image_stats["total_downloaded"]
            final_images_failed = brand.image_stats["total_failed"]
            images_by_category = dict(brand.image_stats["by_category"])

        if download_time > 0.1:
            print(f"   ✅ All downloads complete in {download_time:.1f}s")
        print(f"   📥 {final_images_downloaded} downloaded, {final_images_failed} failed")

        # Extract category details and pattern info for detailed reporting
        category_details = {}
        pattern_info = {}
        if pipeline_results.get("categories"):
            if verbose:
                print(f"\n📋 CATEGORY BREAKDOWN:")
            for category_url, category_data in pipeline_results["categories"].items():
                products = len(category_data.get("products", []))
                category_details[category_url] = products

                # Extract pattern information
                pattern_used = category_data.get("pattern_used", {})
                if pattern_used:
                    pattern_type = pattern_used.get("type", "Unknown")
                    pattern_source = pattern_used.get("source", "")
                    if pattern_type == "reused":
                        pattern_info[category_url] = f"Reused ({pattern_source})"
                    elif pattern_type == "discovered":
                        pattern_info[category_url] = "Discovered"
                    else:
                        pattern_info[category_url] = pattern_type.capitalize()
                else:
                    pattern_info[category_url] = "Unknown"

                if verbose:
                    name = category_data.get("name", "Unknown")
                    print(f"   • {name}: {products} products")

        # Track results with final image stats and pattern info
        if tracker:
            tracker.add_result(brand_name, success, categories_count, products_count,
                             final_images_downloaded, total_time, category_details,
                             images_by_category, pattern_info)
        
        return {
            'success': success,
            'categories': categories_count,
            'products': products_count,
            'images': final_images_downloaded,
            'images_failed': final_images_failed,
            'time': total_time,
            'download_time': download_time,
            'results': pipeline_results
        }
        
    except Exception as e:
        print(f"   ❌ Pipeline failed: {e}")
        if tracker:
            tracker.add_result(brand_name, False, 0, 0, 0,
                             time.time() - start_time if 'start_time' in locals() else 0, {}, {}, {})
        return {'success': False, 'error': str(e)}


def test_all_brands(tracker: PipelineTracker = None, verbose: bool = False):
    """Test pipeline for all brands with homepage_url in brands.json"""
    
    # Load brands.json
    brands_json_path = os.path.join(os.path.dirname(__file__), "brands.json")
    try:
        with open(brands_json_path, 'r') as f:
            brands_data = json.load(f)
    except:
        print("❌ Failed to load brands.json")
        return False
    
    results = {}
    
    for brand_key, brand_info in brands_data.items():
        # Skip brands without homepage_url
        if not brand_info.get("homepage_url"):
            continue
            
        print(f"\n{'='*80}")
        result = test_full_pipeline_single(brand_key, tracker, verbose)
        results[brand_key] = result
    
    return True


if __name__ == "__main__":
    from test_logger import capture_test_output

    # Build command string for logging
    command = f"python {os.path.basename(__file__)} {' '.join(sys.argv[1:])}"

    with capture_test_output("Full Pipeline Test", command):
        # Initialize tracker
        tracker = PipelineTracker()

        # Check for verbose flag
        verbose = '-v' in sys.argv
        if verbose:
            sys.argv.remove('-v')

        # Check for direct URL flag
        direct_url = None
        if '--url' in sys.argv:
            url_index = sys.argv.index('--url')
            if url_index + 1 < len(sys.argv):
                direct_url = sys.argv[url_index + 1]
                sys.argv.pop(url_index)  # Remove --url
                sys.argv.pop(url_index)  # Remove the URL value

        def run_single_test():
            if direct_url:
                # Test with direct URL
                result = test_full_pipeline_single("direct_url", tracker, verbose, direct_url=direct_url)

                # Print tracker summary
                tracker.print_summary()
                return result.get('success', False)
            elif len(sys.argv) > 1:
                # Test specific brand
                brand_key = sys.argv[1]
                result = test_full_pipeline_single(brand_key, tracker, verbose)

                # Print tracker summary
                tracker.print_summary()
                return result.get('success', False)
            else:
                # Test all brands
                result = test_all_brands(tracker, verbose)

                # Print tracker summary
                tracker.print_summary()
                return result

        # Run test multiple times if -N flag is specified
        run_test_multiple_times(run_single_test)