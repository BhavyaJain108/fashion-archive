#!/usr/bin/env python3
"""
Simple Navigation Test
======================

Tests if LLM finds exact URLs from brands.json
"""

import sys
import os
import time
import json
from typing import Dict, List

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brand import Brand
from prompts import PromptManager
from rich.tree import Tree
from rich.console import Console
from rich.table import Table


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
    
    def add_result(self, brand_name: str, url_extraction_ms: float, 
                   llm_call_ms: float, total_ms: float, success: bool):
        """Add timing results for a brand"""
        self.results.append({
            'brand': brand_name,
            'url_extraction': self._format_time(url_extraction_ms),
            'llm_call': self._format_time(llm_call_ms), 
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
        table.add_column("URL Extraction", justify="right")
        table.add_column("LLM Call", justify="right") 
        table.add_column("Total", justify="right")
        table.add_column("Status", justify="center")
        
        for result in self.results:
            status = "✅" if result['success'] else "❌"
            table.add_row(
                result['brand'],
                result['url_extraction'],
                result['llm_call'],
                result['total'],
                status
            )
        
        console.print(table)


def build_rich_tree(category_nodes, parent_tree=None, extra_urls=None):
    """Build a rich Tree from CategoryNode list (handles both objects and dicts)"""
    if parent_tree is None:
        tree = Tree("🏪 Navigation Structure")
        root = tree
    else:
        root = parent_tree
    
    if extra_urls is None:
        extra_urls = set()
    
    for node in category_nodes:
        # Handle both Pydantic objects and dict format
        if isinstance(node, dict):
            name = node.get('name', 'Unknown')
            url = node.get('url')
            children = node.get('children', [])
        else:
            name = node.name
            url = node.url
            children = node.children or []
        
        # Create node label with URL info, highlight if extra
        if url:
            if url in extra_urls:
                label = f"[bold blue]{name}[/bold blue] ([red bold]{url}[/red bold]) [red]← EXTRA[/red]"
            else:
                label = f"[bold blue]{name}[/bold blue] ([green]{url}[/green])"
        else:
            label = f"[bold]{name}[/bold] [dim](organization)[/dim]"
        
        branch = root.add(label)
        
        # Add children if they exist
        if children:
            build_rich_tree(children, branch, extra_urls)
    
    return tree if parent_tree is None else root


# Import from production
from page_extractor import flatten_dict_tree, flatten_dict_tree_all_urls


def test_navigation_simple(brand_key: str, brands_data: dict, latency_tracker: LatencyTracker = None, update_navigation: bool = False, verbose: bool = False):
    """Simple navigation test: LLM set must match brands.json set"""

    total_start = time.time()

    if brand_key not in brands_data:
        print(f"Brand '{brand_key}' not found in brands.json")
        return False

    brand_info = brands_data[brand_key]
    collections = brand_info.get('collections')

    # Handle brands with no collections to test against
    if collections is None or not collections:
        print(f"{brand_info['name']} - ⚠️  NO COLLECTIONS TO TEST")

        # Still run the LLM analysis to see what it finds
        brand = Brand(brand_info['homepage_url'])

        # Time URL extraction (with menu expansion for navigation analysis)
        url_start = time.time()
        links_with_context = brand.extract_page_links_with_context(brand.url, expand_navigation_menus=True)
        url_extraction_ms = (time.time() - url_start) * 1000

        # Print all links if verbose
        if verbose:
            print(f"\n📋 All {len(links_with_context)} links found:")
            for i, link_info in enumerate(links_with_context, 1):
                print(f"   {i}. {link_info['url']}")
            print()

            # Print tree-formatted links
            from prompts.navigation_analysis import _format_links_as_tree
            tree_text = _format_links_as_tree(links_with_context)
            print(f"🌳 Links as tree structure:")
            print(tree_text)
            print()

        prompt_data = PromptManager.get_navigation_analysis_prompt(brand.url, links_with_context)
        
        # Time LLM call
        llm_start = time.time()
        llm_response = brand.llm_handler.call(
            prompt_data['prompt'], 
            expected_format="json", 
            response_model=prompt_data['model'],
            max_tokens=15000
        )
        llm_call_ms = (time.time() - llm_start) * 1000
        
        if llm_response.get("success"):
            nav_analysis = llm_response.get("data", {})
            console = Console()
            if isinstance(nav_analysis, dict) and 'category_tree' in nav_analysis:
                tree = build_rich_tree(nav_analysis['category_tree'])
                console.print(tree)
                
                # Auto-update navigation if it's null or update flag is set
                if brand_info.get('navigation') is None or update_navigation:
                    brands_data[brand_key]['navigation'] = nav_analysis['category_tree']
                    print(f"📝 Updated navigation data for {brand_info['name']}")
            else:
                print("No category_tree found in LLM response")
        else:
            print(f"REASON: LLM analysis failed - {llm_response.get('error', 'Unknown error')}")
        
        # Record timing
        total_ms = (time.time() - total_start) * 1000
        if latency_tracker:
            latency_tracker.add_result(brand_info['name'], url_extraction_ms, 
                                     llm_call_ms, total_ms, llm_response.get("success", False))
        
        return True  # Not a failure, just no collections to test
    
    expected_urls = set(collections.keys())
    
    # Create brand and extract links with HTML context
    brand = Brand(brand_info['homepage_url'])
    
    # Time URL extraction (with menu expansion for navigation analysis)
    url_start = time.time()
    links_with_context = brand.extract_page_links_with_context(brand.url, expand_navigation_menus=True)
    url_extraction_ms = (time.time() - url_start) * 1000

    # Print all links if verbose
    if verbose:
        print(f"\n📋 All {len(links_with_context)} links found:")
        for i, link_info in enumerate(links_with_context, 1):
            print(f"   {i}. {link_info['url']}")
        print()

        # Print tree-formatted links
        from prompts.navigation_analysis import _format_links_as_tree
        tree_text = _format_links_as_tree(links_with_context)
        print(f"🌳 Links as tree structure:")
        print(tree_text)
        print()

    # Extract just URLs for the set comparison
    all_links = [link_info['url'] for link_info in links_with_context]
    all_links_set = set(all_links)
    
    # Get LLM analysis using HTML elements
    prompt_data = PromptManager.get_navigation_analysis_prompt(brand.url, links_with_context)
    
    # Time LLM call
    llm_start = time.time()
    llm_response = brand.llm_handler.call(
        prompt_data['prompt'], 
        expected_format="json", 
        response_model=prompt_data['model'],
        max_tokens=15000
    )
    llm_call_ms = (time.time() - llm_start) * 1000
    
    if not llm_response.get("success"):
        print(f"{brand_info['name']} - ❌ FAILURE")
        print(f"REASON: LLM analysis failed - {llm_response.get('error', 'Unknown error')}")
        print()
        
        # Record timing 
        total_ms = (time.time() - total_start) * 1000
        if latency_tracker:
            latency_tracker.add_result(brand_info['name'], url_extraction_ms, 
                                     llm_call_ms, total_ms, False)
        return False
    
    # Extract LLM URLs (now from hierarchical tree)
    nav_analysis = llm_response.get("data", {})
    
    # Flatten the tree structure to get URLs
    try:
        if hasattr(nav_analysis, 'get_flat_urls'):
            # Pydantic object format
            llm_urls = set(nav_analysis.get_flat_urls())
        elif isinstance(nav_analysis, dict) and 'category_tree' in nav_analysis:
            # Dict format from LLM
            if not nav_analysis['category_tree']:
                print(f"{brand_info['name']} - ❌ FAILURE")
                print("REASON: LLM returned empty category tree")
                print()
                return False
            
            flat_urls = flatten_dict_tree(nav_analysis['category_tree'])
            llm_urls = set(flat_urls)
            
            # Get ALL URLs from LLM tree for missing URL analysis
            all_llm_urls = flatten_dict_tree_all_urls(nav_analysis['category_tree'])
            all_llm_urls_set = set(all_llm_urls)
            
        else:
            # Fallback for old format
            included_urls = nav_analysis.get("included_urls", [])
            llm_urls = set()
            for url_item in included_urls:
                if isinstance(url_item, dict):
                    url = url_item.get('url')
                    if url:
                        llm_urls.add(url)
        
        if not llm_urls:
            print(f"{brand_info['name']} - ❌ FAILURE")
            print("REASON: No valid URLs extracted from LLM response")
            print()
            
            # Record timing
            total_ms = (time.time() - total_start) * 1000
            if latency_tracker:
                latency_tracker.add_result(brand_info['name'], url_extraction_ms, 
                                         llm_call_ms, total_ms, False)
            return False
            
        
    except Exception as e:
        print(f"{brand_info['name']} - ❌ FAILURE")
        print(f"REASON: Error processing LLM response - {str(e)}")
        print()
        
        # Record timing
        total_ms = (time.time() - total_start) * 1000
        if latency_tracker:
            latency_tracker.add_result(brand_info['name'], url_extraction_ms, 
                                     llm_call_ms, total_ms, False)
        return False
    
    # Check if sets match
    if llm_urls == expected_urls:
        print(f"{brand_info['name']} - ✅ SUCCESS")
        
        # Display the tree structure even on success
        console = Console()
        if isinstance(nav_analysis, dict) and 'category_tree' in nav_analysis:
            tree = build_rich_tree(nav_analysis['category_tree'])
            console.print(tree)
            
            # Auto-update navigation if it's null or update flag is set
            if brand_info.get('navigation') is None or update_navigation:
                brands_data[brand_key]['navigation'] = nav_analysis['category_tree']
                print(f"📝 Updated navigation data for {brand_info['name']}")
        else:
            print("No category_tree found in LLM response")
        
        # Record timing
        total_ms = (time.time() - total_start) * 1000
        if latency_tracker:
            latency_tracker.add_result(brand_info['name'], url_extraction_ms, 
                                     llm_call_ms, total_ms, True)
        return True
    
    # Print failures
    print(f"{brand_info['name']} - ❌ FAILURE")
        
    # Calculate extra and missing URLs
    extra_urls = llm_urls - expected_urls
    
    # Use all URLs (not just leaves) for missing URL analysis
    if 'all_llm_urls_set' in locals():
        missing_urls = expected_urls - all_llm_urls_set
    else:
        missing_urls = expected_urls - llm_urls
    
    # Show summary without listing extra URLs (they're highlighted in tree)
    if extra_urls:
        print(f"1. Extra URLs in LLM: {len(extra_urls)}")
    else:
        print(f"1. Extra URLs in LLM: ✅ SUCCESS")
    
    # 2. URLs in brands.json but not in LLM set
    if missing_urls:
        print(f"2. Missing URLs from LLM ({len(missing_urls)}):")
        for url in sorted(missing_urls):
            print(f"   {url}")
        
        # 2a/2b. Check if missing URLs were in the LLM's full tree (including branch nodes)
        if 'all_llm_urls_set' in locals():
            missing_in_llm_tree = missing_urls & all_llm_urls_set
            missing_not_in_llm_tree = missing_urls - all_llm_urls_set
            
            if missing_not_in_llm_tree:
                # These URLs were not in LLM tree at all, check if they were in extracted links
                missing_in_extracted = missing_not_in_llm_tree & all_links_set
                missing_not_extracted = missing_not_in_llm_tree - all_links_set
                
                if missing_not_extracted:
                    print(f"2b. FALSE: Missing URLs not in extracted links ({len(missing_not_extracted)}):")
                    for url in sorted(missing_not_extracted):
                        print(f"   {url}")
        else:
            # Fallback to old logic
            missing_in_extracted = missing_urls & all_links_set
            missing_not_extracted = missing_urls - all_links_set
            
            if missing_not_extracted:
                print(f"2b. FALSE: Missing URLs not in extracted links ({len(missing_not_extracted)}):")
                for url in sorted(missing_not_extracted):
                    print(f"   {url}")
    else:
        print(f"2. Missing URLs from LLM: ✅ SUCCESS")
    
    # Display the tree structure with extra URLs highlighted
    console = Console()
    if isinstance(nav_analysis, dict) and 'category_tree' in nav_analysis:
        tree = build_rich_tree(nav_analysis['category_tree'], extra_urls=extra_urls)
        console.print(tree)
        
        # Auto-update navigation even on test failure if it's null or update flag is set
        if brand_info.get('navigation') is None or update_navigation:
            brands_data[brand_key]['navigation'] = nav_analysis['category_tree']
            print(f"📝 Updated navigation data for {brand_info['name']}")
    else:
        print("No category_tree found in LLM response")
    
    # Record timing for failure cases
    total_ms = (time.time() - total_start) * 1000
    if latency_tracker:
        latency_tracker.add_result(brand_info['name'], url_extraction_ms, 
                                 llm_call_ms, total_ms, False)
    
    return False


def test_direct_url(url: str, verbose: bool = True):
    """Test navigation analysis on a direct URL without brands.json"""
    total_start = time.time()

    print(f"🔍 Testing URL: {url}")

    # Create brand and extract links with HTML context
    brand = Brand(url)

    # Time URL extraction
    url_start = time.time()
    links_with_context = brand.extract_page_links_with_context(brand.url, expand_navigation_menus=True)
    url_extraction_ms = (time.time() - url_start) * 1000

    print(f"🔗 Found {len(links_with_context)} links on page")
    print(f"⏱️  URL extraction took {url_extraction_ms:.1f}ms")

    # Print all links if verbose
    if verbose:
        print(f"\n📋 All {len(links_with_context)} links found:")
        for i, link_info in enumerate(links_with_context, 1):
            print(f"   {i}. {link_info['url']}")
        print()

        # Print tree-formatted links
        from prompts.navigation_analysis import _format_links_as_tree
        tree_text = _format_links_as_tree(links_with_context)
        print(f"🌳 Links as tree structure:")
        print(tree_text)
        print()

    # Get LLM analysis using HTML elements
    prompt_data = PromptManager.get_navigation_analysis_prompt(brand.url, links_with_context)

    # Time LLM call
    llm_start = time.time()
    llm_response = brand.llm_handler.call(
        prompt_data['prompt'],
        expected_format="json",
        response_model=prompt_data['model'],
        max_tokens=15000
    )
    llm_call_ms = (time.time() - llm_start) * 1000

    print(f"⏱️  LLM call took {llm_call_ms:.1f}ms")

    if not llm_response.get("success"):
        print(f"❌ FAILURE")
        print(f"REASON: LLM analysis failed - {llm_response.get('error', 'Unknown error')}")
        total_ms = (time.time() - total_start) * 1000
        print(f"⏱️  Total time: {total_ms:.1f}ms")
        return False

    # Extract LLM URLs (from hierarchical tree)
    nav_analysis = llm_response.get("data", {})

    # Display the tree structure
    console = Console()
    if isinstance(nav_analysis, dict) and 'category_tree' in nav_analysis:
        if not nav_analysis['category_tree']:
            print(f"❌ FAILURE")
            print("REASON: LLM returned empty category tree")
            return False

        tree = build_rich_tree(nav_analysis['category_tree'])
        console.print(tree)

        # Extract and display all URLs found
        flat_urls = flatten_dict_tree(nav_analysis['category_tree'])
        print(f"\n📊 Found {len(flat_urls)} category URLs:")
        for i, url_found in enumerate(flat_urls, 1):
            print(f"   {i}. {url_found}")

        print(f"\n✅ SUCCESS")
    else:
        print("❌ No category_tree found in LLM response")
        return False

    total_ms = (time.time() - total_start) * 1000
    print(f"\n⏱️  Total time: {total_ms:.1f}ms")
    print(f"   - URL extraction: {url_extraction_ms:.1f}ms")
    print(f"   - LLM analysis: {llm_call_ms:.1f}ms")

    return True


if __name__ == "__main__":
    # Check for --verbose flag (default is True, can disable with --no-verbose)
    verbose = True
    if '--no-verbose' in sys.argv:
        verbose = False
        sys.argv.remove('--no-verbose')
    elif '--verbose' in sys.argv:
        verbose = True
        sys.argv.remove('--verbose')
    elif '-v' in sys.argv:
        verbose = True
        sys.argv.remove('-v')

    # Check for --url flag first
    url_flag_index = None
    direct_url = None

    if '--url' in sys.argv:
        url_flag_index = sys.argv.index('--url')
        if url_flag_index + 1 < len(sys.argv):
            direct_url = sys.argv[url_flag_index + 1]
            # Remove both --url and the URL value
            sys.argv.pop(url_flag_index)  # Remove --url
            sys.argv.pop(url_flag_index)  # Remove URL (now at same index)

    # If direct URL provided, test it and exit
    if direct_url:
        test_direct_url(direct_url, verbose=verbose)
        sys.exit(0)

    # Otherwise, continue with normal brands.json testing
    # Load brands.json
    brands_file = os.path.join(os.path.dirname(__file__), 'brands.json')
    with open(brands_file, 'r') as f:
        brands_data = json.load(f)

    # Initialize latency tracker
    latency_tracker = LatencyTracker()

    # Check for flags
    null_only = '--null-only' in sys.argv
    if null_only:
        sys.argv.remove('--null-only')  # Remove flag from args

    update_navigation = '--update-navigation' in sys.argv
    if update_navigation:
        sys.argv.remove('--update-navigation')  # Remove flag from args

    # Track if any navigation data was updated
    navigation_updated = False

    if len(sys.argv) > 1:
        # Test specific brand (ignore flags when specific brand is provided)
        brand_key = sys.argv[1]
        test_navigation_simple(brand_key, brands_data, latency_tracker, update_navigation, verbose=verbose)

        # Print latency summary
        latency_tracker.print_summary()
    else:
        # Test brands based on filter (only when no specific brand provided)
        if null_only:
            # Only test brands with null collections
            test_brands = [key for key, data in brands_data.items()
                          if data.get('collections') is None]
            print(f"Testing {len(test_brands)} brands with null collections...")
        else:
            # Test all brands
            test_brands = list(brands_data.keys())

        for brand_key in test_brands:
            test_navigation_simple(brand_key, brands_data, latency_tracker, update_navigation, verbose=verbose)
            print()  # Line break between brands

        # Print latency summary
        latency_tracker.print_summary()

    # Save updated brands.json
    with open(brands_file, 'w') as f:
        json.dump(brands_data, f, indent=2)
    print(f"💾 Saved brands.json")