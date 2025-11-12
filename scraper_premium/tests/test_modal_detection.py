#!/usr/bin/env python3
"""
Modal Detection Test Suite
==========================

Comprehensive test script for modal detection and bypassing across fashion brands.

Usage:
  cd scraper_premium/tests
  python test_modal_detection.py [brand_names...] [-update] [-v]

Examples:
  python test_modal_detection.py                    # Test all brands
  python test_modal_detection.py gullylabs         # Test only gullylabs
  python test_modal_detection.py gullylabs entire_studios -v  # Test specific brands with verbose logging
  python test_modal_detection.py -update           # Test all and update brands.json
  python test_modal_detection.py gullylabs -update -v  # Test gullylabs, update, with verbose

Flags:
  -update    Update brands.json with learned modal bypasses
  -v         Verbose logging (show all LLM calls and detailed output)
"""

import argparse
import json
import sys
import os
import time
import logging
from typing import Dict, List, Any, Optional
from playwright.sync_api import sync_playwright
import random

# Add parent directory to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from scraper_premium.modal_bypass_engine import ModalBypassEngine
from brand import Brand


class ModalTestResult:
    """Result of modal testing for a single brand"""
    def __init__(self, brand_name: str, url: str):
        self.brand_name = brand_name
        self.url = url
        self.modals_detected = 0
        self.modals_bypassed = 0
        self.successful_attacks = []
        self.proof_actions = []
        self.test_time = 0.0
        self.success = False
        self.error = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "brand_name": self.brand_name,
            "url": self.url,
            "modals_detected": self.modals_detected,
            "modals_bypassed": self.modals_bypassed,
            "successful_attacks": self.successful_attacks,
            "proof_actions": self.proof_actions,
            "test_time": self.test_time,
            "success": self.success,
            "error": self.error
        }


class ModalTester:
    """Comprehensive modal testing system"""
    
    def __init__(self, brands_file: str = "brands.json", verbose: bool = False):
        self.brands_file = brands_file
        self.verbose = verbose
        self.brands_data = {}
        self.test_results = []
        
        # Setup logging
        if verbose:
            logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        else:
            logging.basicConfig(level=logging.WARNING)
        
        self.logger = logging.getLogger(__name__)
        
        # Load brands data
        self._load_brands_data()

    def _load_brands_data(self):
        """Load brands data from JSON file"""
        try:
            with open(self.brands_file, 'r') as f:
                self.brands_data = json.load(f)
            if self.verbose:
                print(f"✅ Loaded {len(self.brands_data)} brands from {self.brands_file}")
        except Exception as e:
            print(f"❌ Error loading brands file: {str(e)}")
            sys.exit(1)

    def _save_brands_data(self):
        """Save updated brands data to JSON file"""
        try:
            with open(self.brands_file, 'w') as f:
                json.dump(self.brands_data, f, indent=2)
            print(f"✅ Updated brands data saved to {self.brands_file}")
        except Exception as e:
            print(f"❌ Error saving brands file: {str(e)}")

    def _get_brand_leaf_url(self, brand_data: Dict[str, Any]) -> Optional[str]:
        """Get a random leaf URL from brand's collections/navigation"""
        leaf_urls = []
        
        # Get collection URLs
        collections = brand_data.get("collections", {})
        if isinstance(collections, dict):
            leaf_urls.extend(collections.keys())
        
        # Get navigation leaf URLs
        navigation = brand_data.get("navigation", [])
        if isinstance(navigation, list):
            for nav_item in navigation:
                self._extract_leaf_urls(nav_item, leaf_urls)
        
        # Return random leaf URL or homepage as fallback
        if leaf_urls:
            return random.choice(leaf_urls)
        return brand_data.get("homepage_url")

    def _extract_leaf_urls(self, nav_item: Dict[str, Any], leaf_urls: List[str]):
        """Recursively extract leaf URLs from navigation structure"""
        if isinstance(nav_item, dict):
            url = nav_item.get("url")
            children = nav_item.get("children")
            
            if url and not children:  # Leaf node
                leaf_urls.append(url)
            elif children:  # Has children, recurse
                for child in children:
                    self._extract_leaf_urls(child, leaf_urls)

    def _test_page_interaction(self, page, url: str) -> List[str]:
        """Test that the page is interactive after modal bypass"""
        proof_actions = []
        
        try:
            # Test 1: Try to scroll the page
            initial_scroll = page.evaluate("window.pageYOffset")
            page.evaluate("window.scrollBy(0, 500)")
            page.wait_for_timeout(500)
            new_scroll = page.evaluate("window.pageYOffset")
            
            if new_scroll > initial_scroll:
                proof_actions.append("✅ Page scrolling works")
            else:
                proof_actions.append("⚠️ Page scrolling limited")
            
            # Test 2: Actually attempt to click elements that might be blocked by modals
            click_attempts = []
            
            # Try clicking common interactive elements
            click_targets = [
                # Navigation and menu items
                ('nav a:first-of-type', 'navigation link'),
                ('header a:first-of-type', 'header link'),
                ('.menu a:first-of-type', 'menu link'),
                
                # Product/shopping elements
                ('.product a:first-of-type', 'product link'),
                ('.item a:first-of-type', 'item link'),
                ('[data-product] a:first-of-type', 'product data link'),
                
                # Buttons
                ('button:not([disabled]):first-of-type', 'button'),
                ('.btn:first-of-type', 'btn class'),
                ('[role="button"]:first-of-type', 'role button'),
                
                # Search and forms
                ('input[type="search"]', 'search input'),
                ('input[type="text"]:first-of-type', 'text input'),
                
                # Common e-commerce elements
                ('.add-to-cart', 'add to cart'),
                ('.shop-now', 'shop now'),
                ('.view-product', 'view product')
            ]
            
            successful_clicks = 0
            for selector, description in click_targets:
                try:
                    element = page.query_selector(selector)
                    if element:
                        # Check if element is actually clickable
                        is_clickable = page.evaluate(f"""
                            () => {{
                                const el = document.querySelector('{selector}');
                                if (!el) return false;
                                const style = window.getComputedStyle(el);
                                const rect = el.getBoundingClientRect();
                                return style.display !== 'none' && 
                                       style.visibility !== 'hidden' && 
                                       style.pointerEvents !== 'none' &&
                                       rect.width > 0 && rect.height > 0 &&
                                       rect.top >= 0 && rect.left >= 0;
                            }}
                        """)
                        
                        if is_clickable:
                            # Attempt to click
                            try:
                                # Try hover first to see if element is interactive
                                element.hover(timeout=1000)
                                
                                # Store current URL to detect navigation
                                current_url = page.url
                                
                                # Perform click
                                element.click(timeout=2000)
                                page.wait_for_timeout(500)  # Brief wait for any effects
                                
                                # Check if click was successful (page changed or element state changed)
                                new_url = page.url
                                if new_url != current_url:
                                    click_attempts.append(f"✅ Successfully clicked {description} (navigated to {new_url[:50]}...)")
                                else:
                                    click_attempts.append(f"✅ Successfully clicked {description} (no navigation)")
                                
                                successful_clicks += 1
                                
                                # Go back if we navigated away
                                if new_url != current_url:
                                    page.go_back(wait_until="domcontentloaded", timeout=3000)
                                    page.wait_for_timeout(1000)
                                
                                # Limit successful clicks to avoid too many interactions
                                if successful_clicks >= 3:
                                    break
                                    
                            except Exception as click_error:
                                click_attempts.append(f"⚠️ Click failed on {description}: {str(click_error)}")
                                
                except Exception as e:
                    # Skip this selector if there's an error
                    continue
            
            if successful_clicks > 0:
                proof_actions.append(f"🖱️ Successfully performed {successful_clicks} click interactions:")
                proof_actions.extend([f"   {attempt}" for attempt in click_attempts])
            else:
                proof_actions.append("🔍 Testing simpler click approach...")
                # Try a more basic approach for post-bypass
                try:
                    simple_element = page.query_selector('a[href], button')
                    if simple_element:
                        try:
                            simple_element.click(timeout=2000, force=True)
                            proof_actions.append("   ✅ Basic element click successful")
                        except Exception as e:
                            if "intercepted" in str(e).lower():
                                proof_actions.append("   🚫 Basic click still intercepted - modals may remain")
                            else:
                                proof_actions.append(f"   ⚠️ Basic click failed: {str(e)}")
                    else:
                        proof_actions.append("   ❌ No basic clickable elements found")
                except Exception:
                    proof_actions.append("   ❌ Could not test basic clicks")
                
                if click_attempts:
                    proof_actions.extend([f"   {attempt}" for attempt in click_attempts[:3]])
            
            # Test 3: Check if main content is visible
            main_content_visible = page.evaluate("""
                () => {
                    const mainSelectors = ['main', '[role="main"]', '#main', '.main', '.content', 'body'];
                    for (const selector of mainSelectors) {
                        const elements = document.querySelectorAll(selector);
                        for (const el of elements) {
                            const style = window.getComputedStyle(el);
                            if (style.display !== 'none' && 
                                style.visibility !== 'hidden' && 
                                el.offsetWidth > 0 && 
                                el.offsetHeight > 0) {
                                return true;
                            }
                        }
                    }
                    return false;
                }
            """)
            
            if main_content_visible:
                proof_actions.append("✅ Main content is visible and accessible")
            else:
                proof_actions.append("❌ Main content may be hidden")
            
            # Test 4: Check page title and text content
            title = page.title()
            text_content_length = page.evaluate("document.body.innerText.length")
            
            if title and text_content_length > 100:
                proof_actions.append(f"✅ Page has title ('{title[:50]}...') and substantial content ({text_content_length} chars)")
            else:
                proof_actions.append("⚠️ Page may be missing content")
                
        except Exception as e:
            proof_actions.append(f"❌ Error testing interactions: {str(e)}")
        
        return proof_actions

    def _test_minimal_interaction(self, page, phase: str) -> List[str]:
        """Quick interaction test to show if elements are clickable"""
        actions = [f"🔍 {phase} INTERACTION TEST:"]
        
        try:
            # Get count of potentially clickable elements first
            element_count = page.evaluate("""
                () => {
                    const selectors = ['a', 'button', '[onclick]', '.btn', 'input[type="submit"]'];
                    let total = 0;
                    selectors.forEach(sel => {
                        const elements = document.querySelectorAll(sel);
                        elements.forEach(el => {
                            const style = window.getComputedStyle(el);
                            const rect = el.getBoundingClientRect();
                            if (style.display !== 'none' && 
                                style.visibility !== 'hidden' && 
                                rect.width > 0 && rect.height > 0 &&
                                rect.top >= 0 && rect.left >= 0) {
                                total++;
                            }
                        });
                    });
                    return total;
                }
            """)
            
            actions.append(f"   📊 Found {element_count} potentially clickable elements")
            
            if element_count == 0:
                actions.append("   ❌ No interactive elements found")
                return actions
            
            # Try different click strategies
            click_targets = [
                ('a[href]:first-of-type', 'first link'),
                ('button:not([disabled]):first-of-type', 'first enabled button'),
                ('.btn:first-of-type', 'first button class'),
                ('nav a:first-of-type', 'navigation link'),
                ('[onclick]:first-of-type', 'onclick element')
            ]
            
            for selector, description in click_targets:
                try:
                    element = page.query_selector(selector)
                    if element:
                        # Check element properties
                        element_info = page.evaluate(f"""
                            () => {{
                                const el = document.querySelector('{selector}');
                                if (!el) return null;
                                const style = window.getComputedStyle(el);
                                const rect = el.getBoundingClientRect();
                                return {{
                                    visible: style.display !== 'none' && style.visibility !== 'hidden',
                                    positioned: rect.width > 0 && rect.height > 0 && rect.top >= 0,
                                    clickable: style.pointerEvents !== 'none',
                                    text: el.innerText?.substring(0, 30) || el.textContent?.substring(0, 30) || 'no text'
                                }};
                            }}
                        """)
                        
                        if element_info and element_info['visible'] and element_info['positioned']:
                            try:
                                # Try a simple click without hover first
                                current_url = page.url
                                element.click(timeout=3000, force=True)
                                page.wait_for_timeout(800)
                                new_url = page.url
                                
                                if new_url != current_url:
                                    actions.append(f"   ✅ Successfully clicked {description} ('{element_info['text']}') - page changed")
                                    page.go_back(wait_until="domcontentloaded", timeout=5000)
                                    page.wait_for_timeout(1000)
                                else:
                                    actions.append(f"   ✅ Successfully clicked {description} ('{element_info['text']}') - element responsive")
                                return actions  # Success, stop testing
                                
                            except Exception as e:
                                error_msg = str(e)
                                if "intercepted" in error_msg.lower():
                                    actions.append(f"   🚫 Click INTERCEPTED on {description} - likely modal blocking")
                                elif "timeout" in error_msg.lower():
                                    actions.append(f"   ⏰ Click TIMEOUT on {description} - element unresponsive")
                                else:
                                    actions.append(f"   ❌ Click FAILED on {description}: {error_msg}")
                                continue
                        else:
                            actions.append(f"   👻 {description} not interactive (visible:{element_info['visible'] if element_info else False})")
                                
                except Exception as e:
                    continue
            
            actions.append("   ❌ No elements were successfully clickable")
            
        except Exception as e:
            actions.append(f"   ❌ Test error: {str(e)}")
            
        return actions

    def _evaluate_interaction_success(self, post_bypass_actions: List[str]) -> bool:
        """
        Evaluate if the website is actually usable after modal bypass.
        
        Returns True ONLY if the website is genuinely functional and interactive.
        We don't care about modal detection success - only website usability.
        """
        actions_text = " ".join(post_bypass_actions).lower()
        
        # STRICT requirement: Must have actual successful clicks/interactions
        has_working_clicks = (
            "successfully clicked" in actions_text and "element responsive" in actions_text
        ) or (
            "successfully performed" in actions_text and "click interactions" in actions_text
        ) or (
            "basic element click successful" in actions_text
        )
        
        # Website-breaking issues that indicate our bypass broke something
        breaking_issues = [
            "click intercepted",  # Still blocked by something
            "still intercepted",  # Our bypass didn't work
            "outside of the viewport",  # Layout broken
            "intercepts pointer events",  # Elements blocking each other
            "no clickable elements could be successfully interacted with",  # Nothing works
            "no elements were successfully clickable",  # Nothing works
            "basic click failed"  # Even simple operations fail
        ]
        
        has_breaking_issues = any(issue in actions_text for issue in breaking_issues)
        
        # Success criteria: Must have working clicks AND no major breaking issues
        if has_working_clicks and not has_breaking_issues:
            return True
        
        # Special case: If we have basic functionality (scroll + content) but some click issues,
        # check if it's minor (like 1-2 viewport issues) vs major (multiple blocking issues)
        if "page scrolling works" in actions_text and "main content is visible" in actions_text:
            # Count actual failures
            failure_phrases = [phrase for phrase in breaking_issues if phrase in actions_text]
            
            # If only viewport issues (not blocking/interception), might be acceptable
            if len(failure_phrases) <= 1 and "outside of the viewport" in actions_text:
                return True
        
        # Default to failure - website not usable
        return False

    def test_brand_modals(self, brand_name: str) -> ModalTestResult:
        """Test modal detection and bypassing for a single brand"""
        
        if self.verbose:
            print(f"\n🔍 Testing brand: {brand_name}")
            print("=" * 60)
        
        brand_data = self.brands_data.get(brand_name)
        if not brand_data:
            result = ModalTestResult(brand_name, "")
            result.error = f"Brand '{brand_name}' not found in brands data"
            return result
        
        # Get test URL
        test_url = self._get_brand_leaf_url(brand_data)
        if not test_url:
            result = ModalTestResult(brand_name, "")
            result.error = "No test URL found for brand"
            return result
        
        result = ModalTestResult(brand_name, test_url)
        
        if self.verbose:
            print(f"🌐 Testing URL: {test_url}")
        
        start_time = time.time()
        
        try:
            with sync_playwright() as p:
                # Launch browser with realistic settings
                browser = p.chromium.launch(
                    headless=not self.verbose,  # Show browser in verbose mode
                    args=['--disable-blink-features=AutomationControlled']
                )
                
                context = browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )
                
                page = context.new_page()
                
                # Skip HTTP request/response logging - too verbose
                
                if self.verbose:
                    print(f"🌐 Loading page: {test_url}")
                
                # Load page
                page.goto(test_url, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(3000)  # Wait for modals to appear
                
                if self.verbose:
                    print(f"📄 Page loaded: {page.title()}")
                
                # Initialize modal engine with brand data
                modal_engine = ModalBypassEngine(brand_data)
                
                if self.verbose:
                    print("🔍 Starting modal detection...")
                
                # Test page interaction BEFORE modal bypass (to show what's blocked)
                if self.verbose:
                    print("🧪 Testing page interaction BEFORE modal bypass...")
                
                pre_bypass_actions = self._test_minimal_interaction(page, "PRE-BYPASS")
                
                # Test modal detection and bypassing
                modal_results = modal_engine.bypass_modals(page, test_url)
                
                # Update result
                result.modals_detected = modal_results["modals_detected"]
                result.modals_bypassed = modal_results["modals_bypassed"]
                result.successful_attacks = modal_results["successful_attacks"]
                result.success = modal_results["success"]
                
                # Capture body fixes if they were applied
                if "body_fixes" in modal_results:
                    result.body_fixes = modal_results["body_fixes"]
                
                if self.verbose:
                    print(f"📊 Modal Results:")
                    print(f"   Detected: {result.modals_detected}")
                    print(f"   Bypassed: {result.modals_bypassed}")
                    print(f"   Success: {result.success}")
                
                # Test page interaction AFTER modal bypass (to prove bypass worked)
                if self.verbose:
                    print("🧪 Testing page interaction AFTER modal bypass...")
                
                post_bypass_actions = self._test_page_interaction(page, test_url)
                
                # Combine pre and post bypass results
                result.proof_actions = pre_bypass_actions + ["--- MODAL BYPASS APPLIED ---"] + post_bypass_actions
                
                # Determine overall success based on both modal bypass AND interaction success
                interaction_success = self._evaluate_interaction_success(post_bypass_actions)
                modal_bypass_success = modal_results["success"]
                
                # Overall success requires both modal bypass AND working interactions
                result.success = modal_bypass_success and interaction_success
                
                if self.verbose:
                    print(f"🎯 Overall Assessment:")
                    print(f"   Modal bypass success: {modal_bypass_success}")
                    print(f"   Interaction success: {interaction_success}")
                    print(f"   Combined success: {result.success}")
                
                if self.verbose:
                    for action in result.proof_actions:
                        print(f"   {action}")
                
                # Update brand data with learned attacks
                if brand_name in self.brands_data:
                    self.brands_data[brand_name] = brand_data
                
                browser.close()
                
        except Exception as e:
            result.error = str(e)
            if self.verbose:
                print(f"❌ Error: {str(e)}")
        
        result.test_time = time.time() - start_time
        
        if self.verbose:
            print(f"⏱️ Test completed in {result.test_time:.2f}s")
        
        return result

    def run_tests(self, brand_names: Optional[List[str]] = None) -> List[ModalTestResult]:
        """Run modal tests for specified brands or all brands"""
        
        if brand_names:
            # Filter to specified brands
            test_brands = {name: data for name, data in self.brands_data.items() if name in brand_names}
            missing_brands = set(brand_names) - set(test_brands.keys())
            if missing_brands:
                print(f"⚠️ Warning: Brands not found: {', '.join(missing_brands)}")
        else:
            test_brands = self.brands_data
        
        total_brands = len(test_brands)
        print(f"🚀 Starting modal detection tests for {total_brands} brands")
        print("=" * 80)
        
        results = []
        start_time = time.time()
        
        for i, brand_name in enumerate(test_brands.keys(), 1):
            if not self.verbose:
                print(f"[{i}/{total_brands}] Testing {brand_name}...", end=" ")
            
            result = self.test_brand_modals(brand_name)
            results.append(result)
            
            if not self.verbose:
                if result.error:
                    print(f"❌ Error: {result.error}")
                else:
                    print(f"✅ {result.modals_detected} detected, {result.modals_bypassed} bypassed ({result.test_time:.1f}s)")
        
        total_time = time.time() - start_time
        
        # Print summary
        print("\n" + "=" * 80)
        print("📊 MODAL DETECTION TEST RESULTS")
        print("=" * 80)
        
        successful_tests = 0
        total_modals_detected = 0
        total_modals_bypassed = 0
        
        for result in results:
            if not result.error:
                successful_tests += 1
                total_modals_detected += result.modals_detected
                total_modals_bypassed += result.modals_bypassed
                
                print(f"\n🏢 {result.brand_name}")
                print(f"   URL: {result.url}")
                print(f"   Modals: {result.modals_detected} detected, {result.modals_bypassed} bypassed")
                
                # Only show what's blocking functionality
                if not result.success:
                    print("   ❌ Website not fully usable after bypass")
                    # Extract and show only blocking issues
                    blocking_issues = []
                    for action in result.proof_actions:
                        action_lower = action.lower()
                        if any(blocker in action_lower for blocker in [
                            "click intercepted", "still intercepted", "outside of the viewport", 
                            "intercepts pointer events", "click failed", "timeout"
                        ]):
                            # Clean up the action text to show just the blocking issue
                            if "click failed" in action_lower or "timeout" in action_lower:
                                blocking_issues.append(action.strip())
                    
                    if blocking_issues:
                        print("   Blocking issues:")
                        for issue in blocking_issues[:3]:  # Show max 3 issues
                            print(f"     • {issue}")
                else:
                    print("   ✅ Website fully usable after bypass")
                
                if self.verbose and result.successful_attacks:
                    print("   Modal attacks used:")
                    for attack in result.successful_attacks:
                        print(f"     - {attack['modal_type']}: {attack['css_rule']}")
                
                if self.verbose and hasattr(result, 'body_fixes') and result.body_fixes:
                    print("   Body fixes applied:")
                    for fix in result.body_fixes:
                        print(f"     + {fix}")
                
                if self.verbose and result.proof_actions:
                    print("   Full test details:")
                    for action in result.proof_actions:
                        print(f"     {action}")
            else:
                print(f"\n❌ {result.brand_name}: {result.error}")
        
        # Performance summary with emphasis on website usability
        usable_websites = len([r for r in results if not r.error and r.success])
        print(f"\n⏱️ PERFORMANCE METRICS")
        print(f"   Total test time: {total_time:.2f}s")
        print(f"   Average time per brand: {total_time/len(results):.2f}s")
        print(f"   📊 USABILITY RESULTS:")
        print(f"     Websites fully usable after bypass: {usable_websites}/{len(results)}")
        print(f"     Success rate (usable websites): {(usable_websites/len(results)*100):.1f}%")
        print(f"   📊 MODAL DETECTION RESULTS:")
        print(f"     Total modals detected: {total_modals_detected}")
        print(f"     Total modals bypassed: {total_modals_bypassed}")
        if total_modals_detected > 0:
            bypass_rate = (total_modals_bypassed / total_modals_detected) * 100
            print(f"     Modal bypass rate: {bypass_rate:.1f}%")
        
        if usable_websites < len(results):
            failed_websites = len(results) - usable_websites
            print(f"\n⚠️  {failed_websites} websites are not fully usable after modal bypass")
        
        return results

    def save_results(self, results: List[ModalTestResult], filename: str = "modal_test_results.json"):
        """Save test results to file"""
        try:
            results_data = [result.to_dict() for result in results]
            with open(filename, 'w') as f:
                json.dump(results_data, f, indent=2)
            if self.verbose:
                print(f"✅ Test results saved to {filename}")
        except Exception as e:
            print(f"❌ Error saving results: {str(e)}")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Test modal detection and bypassing across fashion brands",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        'brands', 
        nargs='*', 
        help='Specific brand names to test (if not specified, tests all brands)'
    )
    
    parser.add_argument(
        '-update', 
        action='store_true', 
        help='Update brands.json with learned modal bypasses'
    )
    
    parser.add_argument(
        '-v', '--verbose', 
        action='store_true', 
        help='Verbose logging (show all LLM calls and detailed output)'
    )
    
    args = parser.parse_args()
    
    # Initialize tester
    tester = ModalTester(verbose=args.verbose)
    
    # Run tests
    results = tester.run_tests(args.brands if args.brands else None)
    
    # Save results
    tester.save_results(results)
    
    # Update brands.json if requested
    if args.update:
        print(f"\n📝 Updating {tester.brands_file} with learned modal bypasses...")
        tester._save_brands_data()
    
    # Exit with appropriate code
    failed_tests = len([r for r in results if r.error])
    if failed_tests > 0:
        print(f"\n⚠️ {failed_tests} tests failed")
        sys.exit(1)
    else:
        print(f"\n✅ All tests completed successfully!")
        sys.exit(0)


if __name__ == "__main__":
    main()