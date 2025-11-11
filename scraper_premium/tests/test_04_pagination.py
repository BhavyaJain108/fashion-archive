#!/usr/bin/env python3
"""


Test 4: Pagination Pipeline Testing
===================================

Tests the complete pagination pipeline including LLM detection and navigation simulation.
Validates pagination type detection and navigation behavior without product scraping.
"""

import sys
import os
import time
from urllib.parse import urljoin
from typing import Dict, Any, Optional

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brand import Brand, PaginationType
from playwright.sync_api import sync_playwright
from modal_bypass_engine import ModalBypassEngine, bypass_blocking_modals_only
from test_utils import (
    load_brands_json, 
    load_brand_from_json, 
    get_test_data_for_brand,
    get_brands_with_test_type,
    print_test_results_table,
    TestLogger,
    test_timer,
    LatencyTracker
)


class PaginationNavigationSimulator:
    """Simulates pagination navigation without product scraping"""
    
    def __init__(self):
        self.browser = None
        self.page = None
    
    def simulate_load_more(self, url: str, selector: str, max_clicks: int = 20) -> Dict[str, Any]:
        """
        Simulate load more button clicking until exhausted
        
        Returns:
            {
                'clicks_performed': int,
                'final_state': str,
                'success': bool,
                'error': str
            }
        """
        result = {
            'clicks_performed': 0,
            'final_state': 'unknown',
            'success': False,
            'error': None,
            'modals_handled': {'detected': 0, 'bypassed': 0, 'success': True}
        }
        
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                
                print(f"     🌐 Loading page: {url}")
                
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(2000)
                
                # Only apply modal bypass for load_more buttons (not needed for link navigation)
                print("     🚫 Checking for blocking modals before button clicks...")
                modal_results = bypass_blocking_modals_only(page, url)
                
                if modal_results["modals_detected"] > 0:
                    print(f"     ✅ Removed {modal_results['modals_bypassed']}/{modal_results['modals_detected']} blocking modals")
                    result['modals_handled'] = modal_results
                else:
                    print("     ℹ️  No blocking modals detected")
                    result['modals_handled'] = {'detected': 0, 'bypassed': 0, 'success': True}
                
                clicks = 0
                while clicks < max_clicks:
                    # Quick check for new blocking modals before each click attempt
                    if clicks > 0:  # Skip for first iteration since we already did it above
                        quick_modal_results = bypass_blocking_modals_only(page, url)
                        if quick_modal_results["modals_detected"] > 0:
                            print(f"     🚫 Removed {quick_modal_results['modals_bypassed']} new blocking modals before click #{clicks + 1}")
                    
                    # Check if load more button exists and is visible
                    button = page.locator(selector)
                    
                    if not button.count():
                        result['final_state'] = 'button_not_found'
                        break
                        
                    if not button.is_visible():
                        result['final_state'] = 'button_hidden'
                        break
                        
                    if button.is_disabled():
                        result['final_state'] = 'button_disabled'
                        break
                    
                    # Attempt to click the button
                    print(f"     🖱️  Clicking load more button (click #{clicks + 1})")
                    try:
                        button.click(timeout=5000)
                        clicks += 1
                        print(f"     ✅ Click #{clicks} successful")
                    except Exception as click_error:
                        print(f"     ❌ Click #{clicks + 1} failed: {str(click_error)}")
                        # Try emergency blocking modal bypass and retry once
                        emergency_modal_results = bypass_blocking_modals_only(page, url)
                        if emergency_modal_results["modals_detected"] > 0:
                            print(f"     🆘 Emergency bypass: {emergency_modal_results['modals_bypassed']} blocking modals removed")
                            try:
                                button.click(timeout=5000)
                                clicks += 1
                                print(f"     ✅ Retry click #{clicks} successful after modal bypass")
                            except Exception as retry_error:
                                print(f"     ❌ Retry failed: {str(retry_error)}")
                                result['final_state'] = f'click_failed: {str(retry_error)}'
                                break
                        else:
                            result['final_state'] = f'click_failed: {str(click_error)}'
                            break
                    
                    # Wait for content to load and scroll to reveal next button
                    page.wait_for_timeout(3000)
                    
                    # Scroll to bottom to reveal the next load more button
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(1000)
                
                if clicks >= max_clicks:
                    result['final_state'] = 'max_clicks_reached'
                
                result['clicks_performed'] = clicks
                result['success'] = True
                browser.close()
                
        except Exception as e:
            result['error'] = str(e)
            result['success'] = False
            
        return result
    
    def simulate_page_links(self, base_url: str, pagination_config: Dict[str, Any], max_pages: int = 15) -> Dict[str, Any]:
        """
        Simulate page navigation using URL template generation
        
        Returns:
            {
                'pages_found': int,
                'final_state': str,
                'success': bool,
                'error': str,
                'urls_tested': List[str]
            }
        """
        from page_extractor import generate_pagination_url
        
        result = {
            'pages_found': 1,  # Start with page 1
            'final_state': 'unknown',
            'success': False,
            'error': None,
            'urls_tested': [base_url]
        }
        
        try:
            page_number = 2  # Start testing from page 2
            
            # Convert our pagination config to the format expected by generate_pagination_url
            url_template = pagination_config.get('url_template', '')
            
            # Extract pattern from full URL template (e.g., "https://site.com/rings?page=X" -> "?page=X")
            if 'X' in url_template:
                if '?page=X' in url_template:
                    template_pattern = '?page=X'
                elif '/page/X/' in url_template:
                    template_pattern = '/page/X/'
                elif '/page/X' in url_template:
                    template_pattern = '/page/X'
                else:
                    # Try to extract pattern around X
                    x_index = url_template.find('X')
                    if x_index > 0:
                        # Find the pattern around X (look for common delimiters)
                        start = max(0, url_template.rfind('/', 0, x_index), url_template.rfind('?', 0, x_index))
                        template_pattern = url_template[start:x_index+1]
                    else:
                        template_pattern = url_template
            else:
                template_pattern = url_template
            
            legacy_config = {
                'type': 'numbered',  # Our page_links maps to numbered
                'template': template_pattern
            }
            
            while page_number <= max_pages:
                # Generate next page URL using legacy format
                next_url = generate_pagination_url(base_url, legacy_config, page_number)
                
                if not next_url:
                    result['final_state'] = 'url_generation_failed'
                    break
                
                print(f"     🌐 Testing page {page_number}: {next_url}")
                result['urls_tested'].append(next_url)
                
                # Quick check if page exists and has content
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    page = browser.new_page()
                    
                    try:
                        response = page.goto(next_url, wait_until="domcontentloaded", timeout=10000)
                        
                        if response and response.status >= 400:
                            result['final_state'] = f'http_error_{response.status}'
                            browser.close()
                            break
                        
                        # No modal bypass needed for page_links - just URL navigation
                        
                        # Quick check for error indicators
                        page.wait_for_timeout(1000)
                        
                        # Check for common "no results" or "404" indicators
                        error_indicators = [
                            'No products found',
                            'Page not found', 
                            '404',
                            'Sorry, no results',
                            'No items to display'
                        ]
                        
                        page_content = page.content().lower()
                        if any(indicator.lower() in page_content for indicator in error_indicators):
                            result['final_state'] = 'no_content_found'
                            browser.close()
                            break
                        
                        result['pages_found'] = page_number
                        page_number += 1
                        browser.close()
                        
                    except Exception as e:
                        result['final_state'] = f'page_load_error: {str(e)}'
                        browser.close()
                        break
            
            if page_number > max_pages:
                result['final_state'] = 'max_pages_reached'
            
            result['success'] = True
            
        except Exception as e:
            result['error'] = str(e)
            result['success'] = False
            
        return result
    
    def simulate_next_button(self, url: str, next_selector: str, max_pages: int = 15) -> Dict[str, Any]:
        """
        Simulate next button navigation until end
        
        Returns:
            {
                'pages_traversed': int,
                'final_state': str, 
                'success': bool,
                'error': str,
                'urls_visited': List[str]
            }
        """
        result = {
            'pages_traversed': 1,  # Start with page 1
            'final_state': 'unknown',
            'success': False,
            'error': None,
            'urls_visited': [url]
        }
        
        try:
            current_url = url
            pages = 1
            
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                
                while pages < max_pages:
                    print(f"     🌐 Checking page {pages}: {current_url}")
                    page.goto(current_url, wait_until="domcontentloaded", timeout=15000)
                    page.wait_for_timeout(2000)
                    
                    # No modal bypass needed for next_button - just href navigation
                    
                    # Find next button
                    next_button = page.locator(next_selector)
                    
                    if not next_button.count():
                        result['final_state'] = 'next_button_not_found'
                        break
                        
                    if not next_button.is_visible():
                        result['final_state'] = 'next_button_hidden'
                        break
                        
                    if next_button.is_disabled():
                        result['final_state'] = 'next_button_disabled'
                        break
                    
                    # Extract next page URL
                    href = next_button.get_attribute('href')
                    if not href:
                        result['final_state'] = 'next_button_no_href'
                        break
                    
                    # Convert relative URL to absolute
                    if href.startswith('/'):
                        next_url = urljoin(current_url, href)
                    elif href.startswith('http'):
                        next_url = href
                    else:
                        next_url = urljoin(current_url, href)
                    
                    print(f"     ⏭️  Found next page: {next_url}")
                    current_url = next_url
                    result['urls_visited'].append(current_url)
                    pages += 1
                
                if pages >= max_pages:
                    result['final_state'] = 'max_pages_reached'
                
                result['pages_traversed'] = pages
                result['success'] = True
                browser.close()
                
        except Exception as e:
            result['error'] = str(e)
            result['success'] = False
            
        return result


def test_pagination_pipeline(brand_key: str, test_url: str, latency_tracker: LatencyTracker = None):
    """
    Test the complete pagination pipeline for a brand
    
    Args:
        brand_key: Brand identifier from brands.json
        test_url: Category URL to test pagination on
    """
    # Setup logger and latency tracking
    logger = TestLogger(f"Pagination Pipeline - {brand_key}")
    logger.header("Testing pagination pipeline")
    
    if not latency_tracker:
        latency_tracker = LatencyTracker()
    
    # Load brand data from brands.json
    brand_data = load_brand_from_json(brand_key)
    if not brand_data:
        logger.error(f"Brand '{brand_key}' not found in brands.json")
        return logger.result(False, "Brand not found", {'detected_type': None})
    
    logger.info(f"Brand: {brand_data.get('name', brand_key)}")
    logger.info(f"Homepage: {brand_data.get('homepage_url', 'N/A')}")
    logger.info(f"Test URL: {test_url}")
    logger.info("🔍 Discovering pagination type and testing navigation...")
    
    try:
        # STEP 1: Create Brand Instance and Analyze Pagination Only
        logger.step("Pagination Analysis")
        analysis_start = time.time()
        
        homepage_url = brand_data.get('homepage_url', test_url)
        brand = Brand(homepage_url)
        
        # Run pagination-only analysis (scrolls to bottom first)
        pagination_result = brand.analyze_pagination_only(test_url)
        
        analysis_duration = time.time() - analysis_start
        latency_tracker.add_operation("pagination_analysis", analysis_duration)
        
        if not pagination_result['success']:
            logger.error(f"❌ Pagination analysis failed: {pagination_result.get('error', 'Unknown error')}")
            return logger.result(False, "Pagination analysis failed", {'detected_type': None})
        
        # Display LLM Analysis Results
        detected_type = pagination_result['pagination_type']
        pagination_config = {'config': pagination_result['pagination_config']}
        
        logger.data("LLM Pagination Analysis", {
            "Detected Type": detected_type,
            "Analysis Time": f"{analysis_duration:.2f}s",
            "Config": pagination_config['config']
        })
        
        # STEP 2: Navigation Simulation
        logger.step("Navigation Simulation")
        simulation_start = time.time()
        
        simulator = PaginationNavigationSimulator()
        navigation_result = {}
        
        if detected_type == 'load_more':
            selector = pagination_result['pagination_config'].get('load_more_selector')
            if selector:
                print(f"   🔘 Simulating LOAD_MORE with selector: {selector}")
                navigation_result = simulator.simulate_load_more(test_url, selector)
            else:
                navigation_result = {'success': False, 'error': 'No load_more_selector found'}
                
        elif detected_type == 'page_links':
            print(f"   🔗 Simulating PAGE_LINKS pagination")
            navigation_result = simulator.simulate_page_links(test_url, pagination_result['pagination_config'])
            
        elif detected_type == 'next_button':
            selector = pagination_result['pagination_config'].get('next_selector')
            if selector:
                print(f"   ⏭️  Simulating NEXT_BUTTON with selector: {selector}")
                navigation_result = simulator.simulate_next_button(test_url, selector)
            else:
                navigation_result = {'success': False, 'error': 'No next_selector found'}
                
        else:  # none
            print(f"   📄 NO_PAGINATION detected - single page")
            navigation_result = {
                'success': True,
                'pages_found': 1,
                'final_state': 'single_page'
            }
        
        simulation_duration = time.time() - simulation_start
        latency_tracker.add_operation("navigation_simulation", simulation_duration)
        
        # Extract navigation metrics
        if detected_type == 'load_more':
            actual_count = navigation_result.get('clicks_performed', 0)
            metric_name = "Button Clicks"
        else:
            actual_count = navigation_result.get('pages_traversed', navigation_result.get('pages_found', 1))
            metric_name = "Pages Found"
        
        # Include modal handling results if available
        nav_data = {
            metric_name: actual_count,
            "Final State": navigation_result.get('final_state', 'unknown'),
            "Simulation Time": f"{simulation_duration:.2f}s",
            "Success": navigation_result.get('success', False)
        }
        
        # Add modal information if any were handled
        modal_info = navigation_result.get('modals_handled', {})
        if modal_info.get('detected', 0) > 0:
            nav_data["Modals Handled"] = f"{modal_info.get('bypassed', 0)}/{modal_info.get('detected', 0)}"
        
        logger.data("Navigation Simulation", nav_data)
        
        # STEP 3: Overall Result
        logger.step("Test Results")
        
        navigation_success = navigation_result.get('success', False)
        
        if navigation_success:
            logger.success(f"✅ SUCCESS - Found {detected_type.upper()} pagination with {actual_count} {metric_name.lower()}")
        else:
            error_msg = navigation_result.get('error', 'unknown error')
            logger.error(f"❌ NAVIGATION FAILED - {error_msg}")
        
        # Display concise findings
        logger.info(f"📊 RESULT: {detected_type.upper()} pagination - {actual_count} {metric_name.lower()}")
        
        pagination_config = pagination_result['pagination_config']
        if detected_type == 'load_more' and 'load_more_selector' in pagination_config:
            logger.info(f"   🎯 Selector: {pagination_config['load_more_selector']}")
        elif detected_type == 'page_links' and 'url_template' in pagination_config:
            logger.info(f"   🎯 Template: {pagination_config['url_template']}")
        elif detected_type == 'next_button' and 'next_selector' in pagination_config:
            logger.info(f"   🎯 Selector: {pagination_config['next_selector']}")
        
        overall_success = navigation_success
        
        # Compact summary
        logger.info(f"📊 Total time: {analysis_duration:.1f}s analysis + {simulation_duration:.1f}s simulation")
        
        return logger.result(overall_success, f"{detected_type.upper()} pagination detected", {
            'type': detected_type, 'count': actual_count, 'success': overall_success
        })
        
    except Exception as e:
        logger.error(f"Exception during pagination pipeline test: {e}")
        return logger.result(False, f"Exception occurred: {e}", {'detected_type': None})


def test_all_brands():
    """Test pagination pipeline for all brands with pagination_test data"""
    
    print(f"\n{'🔄' * 20} TESTING PAGINATION PIPELINE {'🔄' * 20}")
    
    # Initialize latency tracker for all tests
    latency_tracker = LatencyTracker()
    
    # Get all brands with pagination_test data
    brands_with_pagination = get_brands_with_test_type('pagignation_test')
    if not brands_with_pagination:
        print("❌ No brands found with pagination_test data")
        return False
    
    print(f"🔍 Found {len(brands_with_pagination)} brands with pagination tests")
    
    results = []
    successful_tests = 0
    
    for brand_key in brands_with_pagination:
        # Get brand data directly since pagignation_test only has URL
        brand_data = load_brand_from_json(brand_key)
        if not brand_data or 'pagignation_test' not in brand_data:
            continue
        
        pagination_test_data = brand_data['pagignation_test']
        if not pagination_test_data or len(pagination_test_data) == 0:
            continue
            
        test_url = pagination_test_data[0]  # Get the URL
        
        print(f"\n{'—' * 80}")
        result = test_pagination_pipeline(brand_key, test_url, latency_tracker)
        
        # Extract result data for summary
        success = result if isinstance(result, bool) else False
        
        if success:
            successful_tests += 1
        
        # Get brand info for display
        brand_data = load_brand_from_json(brand_key)
        brand_name = brand_data.get('name', brand_key) if brand_data else brand_key
        
        results.append({
            'brand': brand_name,
            'test_url': test_url,
            'success': success
        })
    
    # Print overall latency summary
    print(f"\n{'⏱️' * 20} OVERALL LATENCY SUMMARY {'⏱️' * 20}")
    summary = latency_tracker.get_summary()
    print(f"📊 Total test duration: {summary['total_duration']:.2f}s")
    print(f"📊 Total operations: {summary['operation_count']}")
    
    # Show key operation metrics
    for op_name, metrics in summary['operations'].items():
        duration = metrics['duration']
        print(f"   {op_name}: {duration:.2f}s")
    
    # Print summary table
    print(f"\n{'📊' * 20} SUMMARY {'📊' * 20}")
    print_test_results_table(results, "Pagination Pipeline Results")
    
    print(f"\nTests Passed: {successful_tests}/{len(brands_with_pagination)}")
    return successful_tests == len(brands_with_pagination)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Test specific brand
        brand_key = sys.argv[1]
        
        # Get brand data
        brand_data = load_brand_from_json(brand_key)
        if not brand_data or 'pagignation_test' not in brand_data:
            print(f"❌ Brand '{brand_key}' not found or has no pagination_test data")
            exit(1)
        
        # Get brand data directly since pagignation_test only has URL
        pagination_test_data = brand_data['pagignation_test']
        if not pagination_test_data or len(pagination_test_data) == 0:
            print(f"❌ Brand '{brand_key}' has no pagination_test URL")
            exit(1)
        
        test_url = pagination_test_data[0]  # Get the URL
        test_pagination_pipeline(brand_key, test_url)
    else:
        # Test all brands from brands.json
        test_all_brands()