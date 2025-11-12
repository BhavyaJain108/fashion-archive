"""
Brand Module
============

Represents a fashion brand.
"""

import sys
import os
import json
from typing import List, Optional
from queue import Queue
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse
from playwright.sync_api import sync_playwright
import re

# Add current directory to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

from llm_handler import LLMHandler
from prompts import PromptManager
from product import Product
from image_downloader import ImageDownloader



class Brand:
    """
    Represents a fashion brand for scraping.
    """
    
    def __init__(self, url: str, llm_handler: LLMHandler = None):
        """
        Initialize a Brand
        
        Args:
            url: The main URL of the brand website
            llm_handler: LLM handler instance (optional)
        """
        self.url = url
        self.product_pages: List[str] = []
        self.starting_pages_queue: List[str] = []
        self.product_extraction_pattern: dict = {}
        self.llm_handler = llm_handler or LLMHandler()
        
        # Load more functionality
        self.load_more_detected: Optional[bool] = None  # None=not checked, True=found, False=none found
        self.load_more_button_selector: Optional[str] = None
        self.load_more_modal_bypasses: dict = {}
        self.load_more_modals_applied: bool = False  # Track if modals were already applied this session
        self.load_more_loading_mechanism: bool = False  # Track if we know this site uses load more (across all pages)
        
        # Product queue for discovered products
        self.product_queue = Queue()
        self.seen_product_urls = set()  # Track discovered products to avoid duplicates
        
        # Global pattern storage for cross-category reuse
        self.discovered_patterns: List[dict] = []  # Patterns that work across categories
        self.all_products = set()  # Set of all unique products (by URL)
        
        # Lineage memory for multi-page extraction optimization
        self.lineage_memory = {}  # Dict[category_url: {"rejected_lineages": set(), "approved_lineages": set()}]
        
        # HTML processing pipeline
        self.html_queue = Queue()  # Queue of (html, source_url) tuples
        self.pattern_ready = threading.Event()  # Signal when pattern is detected
        self.workers_active = False
        self.worker_pool = None
        
        # Image downloading pipeline
        self.image_downloader = ImageDownloader()
        self.image_download_queue = Queue()  # Queue of products needing image downloads
        self.image_workers_active = False
        self.image_worker_pool = None
        
        # Streaming control
        self.scrolling_active = False
        self.scroll_thread = None
    
    def analyze_product_pattern(self) -> dict:
        """
        Two-step analysis to determine product extraction patterns:
        1. Find one valid product link from all page links
        2. Analyze surrounding HTML to extract container pattern
        
        Returns:
            Dict containing extraction pattern with CSS selectors
        """
        if not self.starting_pages_queue:
            return {}
        
        first_page_url = self.starting_pages_queue[0]
        
        try:
            
            # Step 1: Find one valid product link
            all_links = self.extract_page_links(first_page_url)
            # Links extracted
            
            product_links = self._find_product_links(all_links, first_page_url)
            
            if not product_links:
                print(f"❌ LLM failed to identify product links from {len(all_links)} links")
                raise Exception(f"No valid product links found {all_links}")
            
            # Product link found
            
            # Get HTML content and extract all links
            html_content = self.get_page_html(first_page_url)
            if not html_content:
                raise Exception("Failed to fetch HTML content")
            
            # Step 2: Analyze pattern around multiple product links
            pattern_analysis = self._analyze_link_pattern(html_content, product_links, first_page_url)
            
            if not pattern_analysis:
                raise Exception("Failed to analyze link pattern")
            
            # Store the extraction pattern
            self.product_extraction_pattern = pattern_analysis.get('extraction_pattern', {})
            
            # Pattern stored
            
            return pattern_analysis
            
        except Exception as e:
            print(f"❌ Product pattern analysis failed: {e}")
            return {}
    
    def analyze_pagination_pattern(self) -> dict:
        """
        Analyze pagination pattern from the first category page.
        Runs in parallel to product pattern discovery.
        
        Returns:
            Dict containing pagination pattern information or empty dict if none found
        """
        if not self.starting_pages_queue:
            return {}
        
        first_page_url = self.starting_pages_queue[0]
        
        try:
            print(f"🔍 Discovering pagination pattern from: {first_page_url}")
            
            # Extract all links from first page
            all_links = self.extract_page_links(first_page_url)
            if not all_links:
                print(f"❌ No links found on page for pagination analysis")
                return {}
            
            print(f"📊 Analyzing {len(all_links)} links for pagination pattern")
            
            # Build pagination analysis prompt
            pagination_result = self._analyze_pagination_links(all_links, first_page_url)
            
            if pagination_result.get("success", False):
                pattern = pagination_result.get("pagination_pattern", {})
                pattern_type = pattern.get("type", "none")
                
                if pattern_type != "none":
                    print(f"✅ Pagination pattern discovered: {pattern.get('template', 'N/A')} (type: {pattern_type})")
                    return pattern
                else:
                    print(f"📝 No pagination pattern found - single page categories")
                    return {}
            else:
                print(f"❌ Pagination analysis failed: {pagination_result.get('error', 'Unknown error')}")
                return {}
                
        except Exception as e:
            print(f"❌ Pagination pattern analysis failed: {e}")
            return {}
    
    def _analyze_pagination_links(self, all_links: List[str], current_page_url: str) -> dict:
        """
        Use LLM to analyze links and identify pagination pattern
        """
        links_text = "\n".join(f"- {link}" for link in all_links)
        
        prompt = f"""
Analyze these links from a product category page to identify pagination pattern:

Current Page: {current_page_url}
All links from page: {links_text}

Identify the pagination strategy used:

1. NUMBERED PAGINATION: Links like ?page=2, ?page=3, /page/2/, etc.
2. NEXT BUTTON ONLY: Only "Next" or "→" links, no numbered pages
3. MIXED: Both numbered pages AND next/previous buttons
4. NONE: No pagination found

Return JSON:
{{
    "pagination_detected": true,
    "type": "numbered|next_button|mixed|none",
    "template": "?page=X" | "/page/X/" | "next_button",
    "next_selector": "a[href*='page=2']" (if next_button or mixed type),
    "reasoning": "Found numbered pagination with ?page= parameter"
}}

Examples:
- If you see: ?page=2, ?page=3 → type: "numbered", template: "?page=X"
- If you see: /page/2/, /page/3/ → type: "numbered", template: "/page/X/"  
- If you see: only "Next" link → type: "next_button", template: "next_button"
- If you see: pages 1,2,3 AND Next → type: "mixed", template: "?page=X"

If no pagination:
{{
    "pagination_detected": false,
    "type": "none",
    "reasoning": "No pagination links found"
}}
""".strip()
        
        try:
            llm_response = self.llm_handler.call(prompt, expected_format="json", response_model=PaginationAnalysis)
            
            if llm_response.get("success", False):
                data = llm_response.get("data", {})
                
                if data.get("pagination_detected", False):
                    pagination_pattern = {
                        "type": data.get("type", "none"),
                        "template": data.get("template", ""),
                        "next_selector": data.get("next_selector", ""),
                        "reasoning": data.get("reasoning", "")
                    }
                    
                    return {
                        "success": True,
                        "pagination_pattern": pagination_pattern
                    }
                else:
                    return {
                        "success": True,
                        "pagination_pattern": {"type": "none"}
                    }
            else:
                return {
                    "success": False,
                    "error": llm_response.get('error', 'LLM analysis failed')
                }
                
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def save_load_more_info(self, selector: str, modal_bypasses: dict):
        """
        Save load more button information to the brand instance.
        
        Args:
            selector: CSS selector for the load more button
            modal_bypasses: Dictionary containing modal bypass information
        """
        self.load_more_detected = True
        self.load_more_button_selector = selector
        self.load_more_modal_bypasses = modal_bypasses
        self.load_more_loading_mechanism = True  # Mark that we know this brand uses load more
        print(f"📝 Stored load more info - Selector: {selector}, Modals: {modal_bypasses.get('modals_detected', 0)}")
        print(f"⚡ Optimized loading mechanism detected - future pages will skip lazy loading waits")
    
    def mark_no_load_more(self):
        """Mark that no load more button was found (to avoid re-checking)."""
        self.load_more_detected = False
        print("📝 No load more button found - marked as checked")
    
    def _extract_sample_product(self, html_content: str, pattern: dict, product_link: str, base_url: str) -> dict:
        """
        Extract a sample product using the detected CSS selectors to verify the pattern works
        """
        try:
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin
            
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Find containers using the detected selector
            containers = soup.select(pattern.get('container_selector', ''))
            
            if not containers:
                return {
                    "name": "Sample Product",
                    "product_url": product_link,
                    "image_url": "N/A - No containers found"
                }
            
            # Find the container that contains our known product link
            target_container = None
            for container in containers:
                # Check if this container has our product link
                links = container.select('a')
                for link in links:
                    href = link.get('href', '')
                    if href and (href in product_link or product_link.endswith(href)):
                        target_container = container
                        break
                if target_container:
                    break
            
            if not target_container:
                # Just use the first container as fallback
                target_container = containers[0]
            
            # Extract images using new approach - get all img tags in container
            images = []
            img_elements = target_container.select('img')
            for img_element in img_elements:
                img_src = img_element.get('src') or img_element.get('data-src') or img_element.get('data-lazy-src')
                if img_src:
                    if img_src.startswith('http'):
                        image_url = img_src
                    else:
                        image_url = urljoin(base_url, img_src)
                    
                    images.append({
                        "src": image_url,
                        "alt": img_element.get('alt', ''),
                        "width": int(img_element.get('width', 0)) if img_element.get('width') else 0,
                        "height": int(img_element.get('height', 0)) if img_element.get('height') else 0
                    })
            
            # Use first image for backward compatibility
            primary_image = images[0]['src'] if images else "N/A"
            
            # Extract name using the pattern
            product_name = "Sample Product"
            name_selector = pattern.get('name_selector', '')
            if name_selector:
                name_element = target_container.select_one(name_selector)
                if name_element:
                    product_name = name_element.get_text(strip=True) or "Sample Product"
            
            return {
                "name": product_name,
                "product_url": product_link,
                "images": images,
                "image_url": primary_image  # Keep for backward compatibility
            }
            
        except Exception as e:
            return {
                "name": "Sample Product",
                "product_url": product_link,
                "images": [],
                "image_url": f"N/A - Error: {e}"
            }
    
    def get_page_html(self, url: str) -> str:
        """
        Get the full rendered HTML of a page using Playwright.
        Uses fast 'domcontentloaded' strategy for quicker loading.
        
        Args:
            url: The URL to fetch
            
        Returns:
            The complete rendered HTML content
        """
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    ignore_https_errors=True,  # Ignore SSL/certificate errors
                    user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )
                page = context.new_page()
                
                # Use domcontentloaded for faster loading
                page.goto(url, wait_until="domcontentloaded", timeout=10000)
                
                # Brief wait for JavaScript to render
                page.wait_for_timeout(2000)
                
                html_content = page.content()
                browser.close()
                return html_content
                
        except Exception as e:
            print(f"⚠️  Error fetching HTML: {e}")
            return ""
    
    def extract_page_links(self, url: str) -> List[str]:
        """
        Extract all links from a page.
        
        Args:
            url: The URL to extract links from
            
        Returns:
            List of unique links found on the page
        """
        html_content = self.get_page_html(url)
        if not html_content:
            return []
        
        # Extract all href attributes
        href_pattern = r'href="([^"]+)"'
        all_links = re.findall(href_pattern, html_content, re.IGNORECASE)
        
        # Filter and normalize links
        filtered_links = []
        for link in all_links:
            # Skip empty, javascript, mailto, tel, and anchor links
            if not link or link.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
                continue
            
            # Convert relative URLs to absolute
            if link.startswith('/'):
                link = urljoin(url, link)
            elif not link.startswith('http'):
                continue  # Skip relative paths without leading slash
            
            # Only include links from the same domain
            from urllib.parse import urlparse
            base_domain = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
            if link.startswith(base_domain) or link.startswith('/'):
                filtered_links.append(link)
        
        # Remove duplicates and sort
        unique_links = sorted(list(set(filtered_links)))
        return unique_links
    
    def extract_page_links_with_context(self, url: str) -> List[dict]:
        """
        Extract all links from a page with their HTML context.
        
        Args:
            url: The URL to extract links from
            
        Returns:
            List of dicts with keys: url, text, context, parent_tag, classes
        """
        from bs4 import BeautifulSoup
        
        html_content = self.get_page_html(url)
        if not html_content:
            return []
        
        soup = BeautifulSoup(html_content, 'html.parser')
        links_with_context = []
        
        # Find all anchor tags and track position
        for position_index, a_tag in enumerate(soup.find_all('a', href=True)):
            href = a_tag.get('href', '')
            
            # Skip empty, javascript, mailto, tel, and anchor links
            if not href or href.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
                continue
            
            # Convert relative URLs to absolute
            if href.startswith('/'):
                href = urljoin(url, href)
            elif not href.startswith('http'):
                continue  # Skip relative paths without leading slash
            
            # Only include links from the same domain
            base_domain = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
            if not (href.startswith(base_domain) or href.startswith('/')):
                continue
            
            # Update the href in the tag to be absolute for the full_element
            original_href = a_tag.get('href')
            a_tag['href'] = href  # Set to absolute URL
            
            # Extract essential information
            link_info = {
                'url': href,
                'position_index': position_index,
                'full_element': str(a_tag)[:200] + '...' if len(str(a_tag)) > 200 else str(a_tag)
            }
            
            # Restore original href to not modify the soup
            a_tag['href'] = original_href
            
            links_with_context.append(link_info)
        
        # Remove duplicates by URL while keeping the first occurrence
        seen_urls = set()
        unique_links = []
        for link_info in links_with_context:
            if link_info['url'] not in seen_urls:
                seen_urls.add(link_info['url'])
                unique_links.append(link_info)
        
        return unique_links
    
    def _get_context_snippet(self, element, max_length=100):
        """Get a snippet of text context around an element"""
        # Get text from parent or surrounding elements
        parent = element.parent
        if parent:
            parent_text = parent.get_text(strip=True)
            # Find the position of our element's text in parent
            element_text = element.get_text(strip=True)
            if element_text and element_text in parent_text:
                start = parent_text.find(element_text)
                # Get some context before and after
                context_start = max(0, start - 30)
                context_end = min(len(parent_text), start + len(element_text) + 30)
                context = parent_text[context_start:context_end]
                if len(context) > max_length:
                    context = context[:max_length] + '...'
                return context
        
        return element.get_text(strip=True)[:max_length]
    
    def _find_product_links(self, all_links: List[str], page_url: str) -> List[str]:
        """
        Step 1: Use LLM to identify up to 3 valid product links from all page links
        """
        from prompts.product_link_finder import get_prompt, get_response_model
        
        # Use structured prompt from prompts module
        prompt = get_prompt(page_url, all_links)
        
        # Try structured output first
        llm_response = self.llm_handler.call(prompt, expected_format="json", response_model=get_response_model())
        
        # Debug: print LLM response
        if not llm_response.get("success", False):
            print(f"🐛 LLM call failed: {llm_response.get('error', 'Unknown error')}")
        
        if llm_response.get("success", False):
            data = llm_response.get("data", {})
            product_urls = data.get("product_urls", [])
            
            # Validate URLs exist in the original links
            valid_urls = []
            for url in product_urls:
                if url in all_links:
                    valid_urls.append(url)
            
            if valid_urls:
                print(f"🔗 Found {len(valid_urls)} product links for pattern analysis")
                return valid_urls
        
        # Simple heuristic fallback when LLM fails
        print("🔧 Using heuristic fallback to find product links")
        heuristic_urls = []
        for link in all_links:
            # Look for common product URL patterns
            if any(pattern in link.lower() for pattern in ['/product/', '/products/', '/item/', '/items/']):
                # Exclude homepage and category pages
                if not link.endswith('/') and '?' not in link and '#' not in link:
                    heuristic_urls.append(link)
                    if len(heuristic_urls) >= 3:  # Limit to 3
                        break
        
        if heuristic_urls:
            print(f"🔗 Heuristic found {len(heuristic_urls)} product links")
            return heuristic_urls
        
        print(f"❌ No product links found")
        return []
    
    def _analyze_link_pattern(self, html_content: str, product_links: List[str], base_url: str) -> dict:
        """
        Step 2: Analyze HTML around multiple product links to find container pattern
        """
        # Extract HTML contexts for all product links
        import re
        from urllib.parse import urlparse
        
        product_contexts = []
        
        for product_link in product_links:
            # Extract the product path from the full URL
            parsed_link = urlparse(product_link)
            link_path = parsed_link.path
            
            # Find surrounding HTML context (search for the href in HTML)
            # Look for the actual <a> tag with this href
            href_pattern = rf'<a[^>]*href="{re.escape(link_path)}"[^>]*>.*?</a>'
            match = re.search(href_pattern, html_content, re.DOTALL | re.IGNORECASE)
            
            if not match:
                # Try with relative href
                href_pattern = rf'<a[^>]*href="{re.escape(product_link)}"[^>]*>.*?</a>'
                match = re.search(href_pattern, html_content, re.DOTALL | re.IGNORECASE)
            
            if match:
                # Extract context around the match (3000 chars before and after)
                match_start = match.start()
                context_start = max(0, match_start - 3750)
                context_end = min(len(html_content), match.end() + 3000)
                context_html = html_content[context_start:context_end]
                product_contexts.append((product_link, context_html))
        
        if not product_contexts:
            return {}
        
        # Use updated prompt that handles multiple product contexts
        from prompts.product_pattern_analysis import get_prompt, get_response_model
        
        
        # Debug: Log the product contexts being analyzed
        print(f"📄 Analyzing {len(product_contexts)} product contexts")
        for i, (link, context) in enumerate(product_contexts, 1):
            print(f"🔗 Product {i}: {link}")
            print(f"📏 Context length: {len(context)} characters")
        
        # Use Haiku for speed with structured output
        prompt = get_prompt(product_contexts)
        llm_response = self.llm_handler.call(prompt, expected_format="json", response_model=get_response_model())
        
        if llm_response.get("success", False):
            data = llm_response.get("data", {})
            if data and "container_selector" in data:
                # Log LLM's reasoning for debugging
                print(f"🧠 LLM Analysis: {data.get('analysis', 'No reasoning provided')}")
                print(f"🎯 Chosen Selector: {data.get('container_selector')}")
                if data.get('alternative_selectors'):
                    print(f"🔍 Alternatives Considered: {', '.join(data.get('alternative_selectors', []))}")
                
                # Pattern extracted successfully - now extract actual sample data using first product
                first_product_link = product_links[0]
                sample_product = self._extract_sample_product(html_content, data, first_product_link, base_url)
                
                return {
                    "extraction_pattern": data,
                    "example_products": [sample_product]
                }
            else:
                # LLM succeeded but didn't provide valid pattern
                print(f"⚠️  LLM response missing required selectors:")
                print(f"📋 Raw LLM response: {llm_response}")
                print(f"📋 Parsed data: {data}")
                # Raw response data available
                return {"error": "Missing required CSS selectors", "partial_data": data}
        else:
            # LLM call failed
            error_msg = llm_response.get("error", "Unknown LLM error")
            print(f"❌ LLM pattern analysis failed: {error_msg}")
            
            # Try common fallback patterns
            print(f"🔄 Attempting fallback pattern detection...")
            fallback_patterns = [
                {
                    "container_selector": ".product, .product-item, .collection-item",
                    "link_selector": "a[href*='/product']",
                    "name_selector": ".product-title, .product-name, h3, h4"
                },
                {
                    "container_selector": "[data-product], [data-product-id]",
                    "link_selector": "a",
                    "name_selector": "[data-product-title], .title"
                }
            ]
            
            # Test if any fallback works
            for i, pattern in enumerate(fallback_patterns, 1):
                try:
                    # Quick test with BeautifulSoup
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(html_content, 'html.parser')
                    containers = soup.select(pattern["container_selector"])
                    if containers:
                        print(f"   ✅ Fallback pattern #{i} found {len(containers)} containers")
                        return {
                            "extraction_pattern": pattern,
                            "fallback": True,
                            "error": error_msg
                        }
                except:
                    continue
            
            print(f"   ❌ No fallback patterns matched")
            return {"error": error_msg}
    
    def _build_navigation_prompt(self, links: List[str]) -> str:
        """Build the navigation analysis prompt for this brand"""
        
        # Format links for display
        links_text = "\n".join(f"- {link}" for link in links)
        
        return f"""
Analyze this fashion brand website's navigation links and find product category URLs:

Website: {self.url}

All links found on the page:
{links_text}

You are a clothing expert and understand all types of clothing styles and categories.
This is a clothing/fashion website. Categorize these links to find product categories/collections where customers can directly browse and buy products
Essentially you are navigating a tree of urls and we wnat to find the branches/subbracnhes that this website uses to organize its products.

Find PRODUCT PAGE URLS: List ALL URLs that lead to actual product category listings
   - Include only direct product pages: /collections/tees, /collections/pants, /shop/mens, /category/tops, etc.
   - Exclude: About pages, contact pages, info pages, search pages, account pages, navigation pages, blog pages, etc.

IMPORTANT: We want every single individual product categories so that we can see all the products offered. links that end with a category/clothing/accessory type are usually your go to. 
IMPORTANT: DO NOT RETURN "Shop All" or "All Products" or "main-products-page" or similar consolidation pages, we are interested in the getting all the DISTINCT categories not everything at once. 
Here sometimes you may see a everything for a particular subcategory. for example womens/all or shoes/all. these are probably ok, but just all_products or shop_all are not. 
These are going to be gametime decisions where you have to judge what collection of links would form the a distinct yet complete set of products offered.
Be careful not to fall for when links diffferntiated by a subcategory first. If theres mens/shoes and womens/shoes we wan both because they even though the final categories is the same, the parent categories are different. 
IMPORTANT CONSIDERATION: If unsure about a URL, ALWAYS INCLUDE it.
DO NOT INCLUDE ALTERNATIVES/ multiple options for exactly the same category.

Return JSON:
{{
    "included_urls": [
        {{
            "url": "https://example.com/collections/womens/tops",
            "reasoning": "Direct product category for women's tops"
        }},
        {{
            "url": "https://example.com/collections/bottoms", 
            "reasoning": "Direct product category for bottoms/pants"
        }},
        {{
            "url": "https://example.com/collections/accessories",
            "reasoning": "Direct product category for accessories"
        }}
    ],
    "confidence": 0.8,
    "reasoning": "Found multiple individual product categories for different clothing types"
}}
""".strip()
    
    def process_starting_page(self, page_url: str) -> int:
        """
        Process a starting page: scroll through it and queue all discovered products.
        Uses the product_extraction_pattern to find products.
        
        Args:
            page_url: URL of the starting page to process
            
        Returns:
            Number of products discovered and queued
        """
        if not self.product_extraction_pattern:
            print(f"❌ No product extraction pattern defined. Run analyze_product_pattern() first.")
            return 0
        
        products_found = 0
        
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                
                # Go to the starting page
                print(f"📄 Processing: {page_url}")
                page.goto(page_url, wait_until="load", timeout=15000)
                
                # Wait for initial products to load
                container_selector = self.product_extraction_pattern.get('container_selector')
                try:
                    page.wait_for_selector(container_selector, timeout=5000)
                except:
                    print(f"⚠️  No products found with selector: {container_selector}")
                    browser.close()
                    return 0
                
                # Track scroll position
                last_height = 0
                scroll_attempts = 0
                max_scrolls = 10  # Safety limit
                
                while scroll_attempts < max_scrolls:
                    # Extract only NEW products (not already processed)
                    products_batch = self._extract_new_products_from_page(page, page_url)
                    products_found += products_batch
                    
                    # Get current scroll height
                    current_height = page.evaluate("document.body.scrollHeight")
                    
                    # Check if we've reached the bottom
                    if current_height == last_height:
                        print(f"✅ Reached end of page after {scroll_attempts} scrolls")
                        break
                    
                    # Scroll to bottom
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    
                    # Wait for new products to load
                    page.wait_for_timeout(2000)  # 2 second wait
                    
                    last_height = current_height
                    scroll_attempts += 1
                
                # No need for final extraction - last scroll already extracted everything
                browser.close()
                
                print(f"✅ Completed: Found {products_found} products from {page_url}")
                print(f"📦 Queue size: {self.product_queue.qsize()} total products")
                
                return products_found
                
        except Exception as e:
            print(f"❌ Error processing {page_url}: {e}")
            return products_found
    
    def _extract_new_products_from_page(self, page, source_url: str) -> int:
        """
        Extract only NEW products from current page state (marks them as processed).
        Uses JavaScript to mark containers as processed to avoid reprocessing.
        
        Args:
            page: Playwright page object
            source_url: The starting page URL (for tracking source)
            
        Returns:
            Number of new products queued
        """
        new_products = 0
        
        try:
            # Get selectors - fail if no container selector
            container_selector = self.product_extraction_pattern.get('container_selector')
            if not container_selector:
                print("❌ No container selector in pattern - cannot extract products")
                return 0
            
            # Get other selectors - use only what pattern provides (no defaults)
            link_selector = self.product_extraction_pattern.get('link_selector') or ''
            name_selector = self.product_extraction_pattern.get('name_selector') or ''
            
            # Get ALL containers (no JavaScript marking - rely on URL deduplication)
            # Safely escape selectors for JavaScript
            import json
            container_selector_escaped = json.dumps(container_selector)
            link_selector_escaped = json.dumps(link_selector)
            name_selector_escaped = json.dumps(name_selector)
            
            extraction_result = page.evaluate(f"""
                () => {{
                    const containers = document.querySelectorAll({container_selector_escaped});
                    const newProducts = [];
                    let noLinkCount = 0;
                    
                    containers.forEach(container => {{
                        
                        // Extract product data - only use selectors that were provided
                        let href = null;
                        if ({link_selector_escaped}) {{
                            const linkEl = container.querySelector({link_selector_escaped});
                            href = linkEl ? linkEl.getAttribute('href') : null;
                        }} else {{
                            // No link selector - try to find any product link
                            const linkEl = container.querySelector('a[href*="/product"]');
                            href = linkEl ? linkEl.getAttribute('href') : null;
                        }}
                        
                        let name = 'Unknown';
                        if ({name_selector_escaped}) {{
                            const nameEl = container.querySelector({name_selector_escaped});
                            if (nameEl) {{
                                name = nameEl.innerText || nameEl.getAttribute('alt') || nameEl.getAttribute('title') || 'Unknown';
                            }}
                        }}
                        
                        // Extract all images from container
                        const images = [];
                        const imgElements = container.querySelectorAll('img');
                        imgElements.forEach(img => {{
                            const src = img.getAttribute('src') || 
                                       img.getAttribute('data-src') || 
                                       img.getAttribute('data-lazy-src') || 
                                       img.getAttribute('data-original') || '';
                            if (src) {{
                                images.push({{
                                    src: src,
                                    alt: img.getAttribute('alt') || '',
                                    width: parseInt(img.width) || 0,
                                    height: parseInt(img.height) || 0
                                }});
                            }}
                        }});
                        
                        // Use first image for backward compatibility
                        let imageSrc = images.length > 0 ? images[0].src : '';
                        
                        if (href) {{
                            newProducts.push({{
                                href: href,
                                name: name.trim(),
                                images: images,
                                image: imageSrc  // Keep for backward compatibility
                            }});
                        }} else {{
                            noLinkCount++;
                        }}
                    }});
                    
                    return {{
                        products: newProducts,
                        totalContainers: containers.length,
                        noLinkCount: noLinkCount
                    }};
                }}
            """)
            
            new_containers_data = extraction_result.get('products', [])
            
            # Process the extracted products
            duplicates_skipped = 0
            for product_data in new_containers_data:
                try:
                    # Build full URL
                    href = product_data.get('href', '')
                    if not href:
                        continue
                        
                    if href.startswith('/'):
                        product_url = urljoin(source_url, href)
                    elif href.startswith('http'):
                        product_url = href
                    else:
                        product_url = urljoin(source_url, href)
                    
                    # Skip if we've seen this URL before
                    if product_url in self.seen_product_urls:
                        duplicates_skipped += 1
                        continue
                    
                    # Get product details
                    product_name = product_data.get('name', 'Unknown')
                    product_image = product_data.get('image', '')
                    if product_image and not product_image.startswith('http'):
                        product_image = urljoin(source_url, product_image)
                    
                    # Create Product object
                    product = Product(
                        name=product_name,
                        url=product_url,
                        image=product_image
                    )
                    
                    # Add metadata
                    product.metadata['source_page'] = source_url
                    product.metadata['discovered_at'] = time.time()
                    
                    # Queue the product
                    self.product_queue.put(product)
                    self.seen_product_urls.add(product_url)
                    new_products += 1
                    
                    # Queue for image download if workers are active
                    if self.image_workers_active:
                        self.queue_product_for_image_download(product)
                    
                except Exception as e:
                    # Skip problematic products but continue
                    continue
            
            # Only print if we found products to avoid spam
            if new_products > 0:
                print(f"   📦 Found {len(new_containers_data)} containers")
            
        except Exception as e:
            print(f"⚠️  Error extracting products: {e}")
        
        return new_products
    
    def _extract_products_from_page(self, page, source_url: str) -> int:
        """
        Extract products from current page state and add to queue.
        
        Args:
            page: Playwright page object
            source_url: The starting page URL (for tracking source)
            
        Returns:
            Number of new products queued
        """
        new_products = 0
        
        try:
            # Get container selector - fail if not found
            container_selector = self.product_extraction_pattern.get('container_selector')
            if not container_selector:
                print("❌ No container selector in pattern - cannot extract products")
                return 0
            
            # Get other selectors - use only what pattern provides
            link_selector = self.product_extraction_pattern.get('link_selector')  # No default
            name_selector = self.product_extraction_pattern.get('name_selector')  # No default
            
            # Find all product containers
            containers = page.query_selector_all(container_selector)
            
            for container in containers:
                try:
                    # Extract product URL
                    link_element = container.query_selector(link_selector) if link_selector else container
                    product_url = None
                    
                    if link_element:
                        href = link_element.get_attribute('href')
                        if href:
                            # Convert relative URL to absolute
                            if href.startswith('/'):
                                product_url = urljoin(source_url, href)
                            elif href.startswith('http'):
                                product_url = href
                            else:
                                product_url = urljoin(source_url, href)
                    
                    # Skip if we've seen this product
                    if not product_url or product_url in self.seen_product_urls:
                        continue
                    
                    # Extract product name
                    product_name = "Unknown"
                    if name_selector:
                        name_element = container.query_selector(name_selector)
                        if name_element:
                            product_name = name_element.inner_text().strip()
                    
                    # Extract all product images from container
                    product_images = []
                    image_elements = container.query_selector_all('img')
                    for img_el in image_elements:
                        img_src = img_el.get_attribute('src') or img_el.get_attribute('data-src') or ""
                        if img_src:
                            if img_src.startswith('//'):
                                img_src = 'https:' + img_src
                            elif img_src.startswith('/'):
                                img_src = urljoin(source_url, img_src)
                            elif not img_src.startswith('http'):
                                img_src = urljoin(source_url, img_src)
                            
                            product_images.append({
                                "src": img_src,
                                "alt": img_el.get_attribute('alt') or '',
                                "width": int(img_el.get_attribute('width') or 0),
                                "height": int(img_el.get_attribute('height') or 0)
                            })
                    
                    # Use first image for backward compatibility
                    product_image = product_images[0]['src'] if product_images else ""
                    
                    # Create Product object and queue it
                    product = Product(
                        name=product_name,
                        url=product_url,
                        image=product_image
                    )
                    
                    # Add metadata
                    product.metadata['source_page'] = source_url
                    product.metadata['discovered_at'] = time.time()
                    
                    # Queue the product
                    self.product_queue.put(product)
                    self.seen_product_urls.add(product_url)
                    new_products += 1
                    
                    # Queue for image download if workers are active
                    if self.image_workers_active:
                        self.queue_product_for_image_download(product)
                    
                except Exception as e:
                    # Skip problematic products but continue
                    continue
                    
        except Exception as e:
            print(f"⚠️  Error extracting products: {e}")
        
        return new_products
    
    def process_all_starting_pages(self) -> int:
        """
        Process all starting pages in the queue.
        
        Returns:
            Total number of products discovered
        """
        if not self.starting_pages_queue:
            print("❌ No starting pages to process")
            return 0
        
        if not self.product_extraction_pattern:
            print("❌ Product extraction pattern not defined")
            return 0
        
        total_products = 0
        
        print(f"\n🚀 Processing {len(self.starting_pages_queue)} starting pages...")
        
        for i, page_url in enumerate(self.starting_pages_queue, 1):
            print(f"\n[{i}/{len(self.starting_pages_queue)}] Processing page...")
            products_found = self.process_starting_page(page_url)
            total_products += products_found
        
        print(f"\n✅ Completed all pages!")
        print(f"📊 Total products discovered: {total_products}")
        print(f"📦 Product queue size: {self.product_queue.qsize()}")
        
        return total_products
    
    def _extract_product_image(self, html_content: str, href: str, source_url: str) -> str:
        """Extract product image URL from HTML"""
        
        # Strategy 1: Image within the same link
        link_img_pattern = rf'<a[^>]*href="{re.escape(href)}"[^>]*>.*?<img[^>]*src="([^"]+)".*?</a>'
        match = re.search(link_img_pattern, html_content, re.DOTALL | re.IGNORECASE)
        if match:
            img_url = match.group(1)
            return self._normalize_image_url(img_url, source_url)
        
        # Strategy 2: Image before the link (common pattern)
        before_pattern = rf'<img[^>]*src="([^"]+)"[^>]*>.*?<a[^>]*href="{re.escape(href)}"'
        match = re.search(before_pattern, html_content, re.DOTALL | re.IGNORECASE)
        if match:
            img_url = match.group(1)
            return self._normalize_image_url(img_url, source_url)
        
        # Strategy 3: Look for data-src (lazy loading)
        lazy_pattern = rf'<a[^>]*href="{re.escape(href)}"[^>]*>.*?data-src="([^"]+)".*?</a>'
        match = re.search(lazy_pattern, html_content, re.DOTALL | re.IGNORECASE)
        if match:
            img_url = match.group(1)
            return self._normalize_image_url(img_url, source_url)
        
        return ""
    
    def _normalize_image_url(self, img_url: str, source_url: str) -> str:
        """Convert relative image URLs to absolute and decode HTML entities"""
        if not img_url:
            return ""
        
        # Decode HTML entities (e.g., &amp; -> &)
        import html
        img_url = html.unescape(img_url)
        
        if img_url.startswith('//'):
            return 'https:' + img_url
        elif img_url.startswith('/'):
            return urljoin(source_url, img_url)
        elif img_url.startswith('http'):
            return img_url
        else:
            return urljoin(source_url, img_url)    

    def _image_worker(self, worker_id: int):
        """Image downloading worker thread"""
        print(f"🖼️  Image worker {worker_id} started")
        
        while self.image_workers_active:
            try:
                # Get product from queue
                product = self.image_download_queue.get(timeout=1)
                
                if product is None:  # Poison pill
                    break
                
                # Download image
                if product.image:
                    success, local_path, error = self.image_downloader.download_image(
                        product.image, 
                        product.name or f"product_{worker_id}_{int(time.time())}", 
                        self.brand_name
                    )
                    
                    if success:
                        product.metadata['local_image_path'] = local_path
                        print(f"   🖼️  Worker {worker_id}: Downloaded {product.name[:30]}...")
                    else:
                        print(f"   ❌ Worker {worker_id}: Failed to download {product.name[:30]}...: {error}")
                
            except:
                # Queue timeout or other exception - just continue waiting
                # Don't break the loop unless workers should stop
                continue
        
        print(f"🛑 Image worker {worker_id} stopped")
    
    def queue_product_for_image_download(self, product):
        """Add product to image download queue"""
        if product.image:
            self.image_download_queue.put(product)

    def store_lineage_memory(self, category_url: str, rejected_lineages: set, approved_lineages: set = None):
        """Store lineage memory for a category to optimize subsequent pages"""
        if category_url not in self.lineage_memory:
            self.lineage_memory[category_url] = {
                "rejected_lineages": set(),
                "approved_lineages": set()
            }
        
        self.lineage_memory[category_url]["rejected_lineages"].update(rejected_lineages)
        if approved_lineages:
            self.lineage_memory[category_url]["approved_lineages"].update(approved_lineages)
    
    def get_lineage_memory(self, category_url: str) -> dict:
        """Get lineage memory for a category"""
        return self.lineage_memory.get(category_url, {
            "rejected_lineages": set(),
            "approved_lineages": set()
        })
    
    def has_lineage_memory(self, category_url: str) -> bool:
        """Check if we have lineage memory for a category"""
        return category_url in self.lineage_memory and len(self.lineage_memory[category_url]["rejected_lineages"]) > 0

    def run_full_extraction_pipeline(self) -> dict:
        """
        Complete extraction pipeline: Homepage → Navigation Tree → All Categories → All Products
        
        This is the main pipeline function that:
        1. Extracts navigation tree from homepage
        2. Gets all leaf category URLs
        3. Discovers/reuses patterns for each category
        4. Extracts all products with multi-page support
        5. Downloads images for all products
        6. Saves results to JSON
        
        Returns:
            {
                "success": bool,
                "navigation_tree": {...},
                "categories": {
                    "category_url": {
                        "name": str,
                        "products": [...],
                        "pattern_used": {...},
                        "extraction_stats": {...}
                    }
                },
                "summary": {
                    "total_categories": int,
                    "total_products": int, 
                    "total_images": int,
                    "extraction_time": float
                }
            }
        """
        import time
        import json
        import os
        from page_extractor import extract_products_from_page, extract_all_urls_from_navigation_tree, extract_category_name
        from prompts import PromptManager
        
        print(f"\n🚀 STARTING FULL EXTRACTION PIPELINE")
        start_time = time.time()
        
        try:
            # Phase 1: Extract Navigation Tree
            print(f"📋 Phase 1: Extracting navigation tree from homepage...")
            navigation_tree = self._extract_navigation_tree()
            if not navigation_tree:
                return {"success": False, "error": "Failed to extract navigation tree"}
            
            # Phase 2: Get All Leaf URLs  
            print(f"🍃 Phase 2: Extracting leaf category URLs...")
            leaf_urls = self._extract_all_leaf_urls(navigation_tree)
            if not leaf_urls:
                return {"success": False, "error": "No category URLs found"}
            
            print(f"   ✅ Found {len(leaf_urls)} category URLs")
            
            # Phase 3: Extract Products from Each Category
            print(f"📦 Phase 3: Extracting products from all categories...")
            categories_results = {}
            total_products = 0
            total_images = 0
            
            # Process categories: Sequential until first pattern found, then parallel
            processed_categories = self._process_categories_with_parallel_optimization(leaf_urls)
            
            for category_url, category_result in processed_categories.items():
                categories_results[category_url] = category_result
                total_products += len(category_result.get("products", []))
                total_images += category_result.get("extraction_stats", {}).get("images_downloaded", 0)
            
            # Phase 4: Save Results
            print(f"\n💾 Phase 4: Saving results to JSON...")
            total_time = time.time() - start_time
            
            pipeline_results = {
                "success": True,
                "navigation_tree": navigation_tree,
                "categories": categories_results,
                "summary": {
                    "total_categories": len(categories_results),
                    "categories_processed": len([c for c in categories_results.values() if c.get("products")]),
                    "total_products": total_products,
                    "total_images": total_images,
                    "extraction_time": total_time
                }
            }
            
            # Save to JSON file
            self._save_pipeline_results_to_json(pipeline_results)
            
            print(f"✅ PIPELINE COMPLETE - {total_products} products from {len(categories_results)} categories in {total_time:.1f}s")
            return pipeline_results
            
        except Exception as e:
            total_time = time.time() - start_time
            print(f"❌ Pipeline failed after {total_time:.1f}s: {e}")
            return {"success": False, "error": str(e), "extraction_time": total_time}
    
    def _extract_navigation_tree(self) -> dict:
        """Extract and analyze navigation tree from homepage"""
        from prompts import PromptManager
        
        # Extract homepage links
        homepage_links = self.extract_page_links(self.url)
        if not homepage_links:
            print(f"      ❌ No links found on homepage")
            return None
        
        print(f"      🔗 Found {len(homepage_links)} homepage links")
        
        # Analyze navigation with LLM
        try:
            prompt_data = PromptManager.get_navigation_analysis_prompt(self.url, homepage_links)
            navigation_result = self.llm_handler.call(
                prompt_data['prompt'], 
                expected_format="json", 
                response_model=prompt_data['model']
            )
            
            if navigation_result.get("success"):
                navigation_tree = navigation_result.get("data", {})
                print(f"      ✅ Navigation analysis successful")
                
                # Print the navigation tree structure
                self._print_navigation_tree(navigation_tree)
                
                return navigation_tree
            else:
                print(f"      ❌ Navigation analysis failed: {navigation_result.get('error', 'Unknown')}")
                return None
                
        except Exception as e:
            print(f"      ❌ Navigation analysis exception: {e}")
            return None
    
    def _extract_all_leaf_urls(self, navigation_tree: dict) -> List[str]:
        """Extract all leaf URLs from navigation tree"""
        from page_extractor import extract_all_urls_from_navigation_tree
        
        try:
            # Extract URLs using existing function
            if 'category_tree' in navigation_tree:
                # New hierarchical format
                leaf_urls = navigation_tree.get_flat_urls() if hasattr(navigation_tree, 'get_flat_urls') else []
                if not leaf_urls and navigation_tree.get('category_tree'):
                    # Manual extraction for dict format
                    leaf_urls = []
                    for category in navigation_tree['category_tree']:
                        if isinstance(category, dict):
                            leaf_urls.extend(self._extract_urls_from_category(category))
            else:
                # Fallback to old format
                leaf_urls = extract_all_urls_from_navigation_tree([navigation_tree])
            
            return leaf_urls
            
        except Exception as e:
            print(f"      ❌ URL extraction failed: {e}")
            return []
    
    def _extract_urls_from_category(self, category: dict) -> List[str]:
        """Recursively extract URLs from category tree node"""
        urls = []
        
        if category.get('children'):
            # Has children - recurse
            for child in category['children']:
                urls.extend(self._extract_urls_from_category(child))
        else:
            # Leaf node - include URL if exists
            if category.get('url'):
                urls.append(category['url'])
                
        return urls
    
    def _print_navigation_tree(self, navigation_tree: dict):
        """Print the navigation tree structure using Rich"""
        try:
            from rich.tree import Tree
            from rich.console import Console
            
            if not navigation_tree or 'category_tree' not in navigation_tree:
                return
            
            # Build Rich tree from category data
            tree = self._build_rich_tree(navigation_tree['category_tree'])
            
            # Print the tree
            console = Console()
            print(f"\n📋 NAVIGATION TREE:")
            console.print(tree)
            print()  # Add spacing
            
        except Exception as e:
            print(f"      ⚠️  Could not display navigation tree: {e}")
    
    def _build_rich_tree(self, category_nodes, parent_tree=None):
        """Build a rich Tree from CategoryNode list (adapted from test_01)"""
        from rich.tree import Tree
        
        if parent_tree is None:
            tree = Tree("🏪 Navigation Structure")
            root = tree
        else:
            root = parent_tree
        
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
            
            # Create node label with URL info
            if url:
                label = f"[bold blue]{name}[/bold blue] ([green]{url}[/green])"
            else:
                label = f"[bold]{name}[/bold] [dim](organization)[/dim]"
            
            branch = root.add(label)
            
            # Add children if they exist
            if children:
                self._build_rich_tree(children, branch)
        
        return tree if parent_tree is None else root
    
    def _process_categories_with_parallel_optimization(self, leaf_urls: List[str]) -> dict:
        """
        Process categories with optimization: sequential until first pattern found, then parallel
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from page_extractor import extract_category_name
        import time
        
        categories_results = {}
        
        # Phase 3a: Sequential processing until first pattern is discovered
        print(f"   🔍 Phase 3a: Sequential pattern discovery...")
        first_pattern_found = False
        sequential_count = 0
        
        for i, category_url in enumerate(leaf_urls, 1):
            print(f"\n   📁 Sequential {i}/{len(leaf_urls)}: {category_url}")
            
            # Get working pattern for this category
            pattern = self._get_working_pattern_for_category(category_url)
            if not pattern:
                print(f"      ❌ No working pattern found - skipping category")
                categories_results[category_url] = {
                    "name": extract_category_name(category_url),
                    "products": [],
                    "error": "No working pattern"
                }
                continue
            
            print(f"      🎯 Using pattern: {pattern.get('container_selector', 'Unknown')}")
            
            # Extract products from this category
            category_result = self._extract_category_products(category_url, pattern, i, len(leaf_urls))
            categories_results[category_url] = category_result
            sequential_count += 1
            
            # If we have discovered patterns, switch to parallel mode
            if len(self.discovered_patterns) > 0 and not first_pattern_found:
                first_pattern_found = True
                remaining_urls = leaf_urls[i:]  # Remaining categories to process
                
                if remaining_urls:
                    print(f"\n   ⚡ Phase 3b: Parallel processing for remaining {len(remaining_urls)} categories...")
                    parallel_results = self._process_categories_parallel(remaining_urls, i + 1, len(leaf_urls))
                    categories_results.update(parallel_results)
                break
        
        if not first_pattern_found:
            print(f"   📊 Completed {sequential_count} categories sequentially (no pattern found)")
        else:
            print(f"   📊 Processed {sequential_count} sequential + {len(categories_results) - sequential_count} parallel")
        
        return categories_results
    
    def _process_categories_parallel(self, category_urls: List[str], start_index: int, total_categories: int) -> dict:
        """Process multiple categories in parallel (4x concurrency)"""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from page_extractor import extract_category_name
        
        parallel_results = {}
        max_workers = min(4, len(category_urls))  # 4x concurrency
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all category processing tasks
            future_to_info = {}
            for i, category_url in enumerate(category_urls):
                future = executor.submit(
                    self._process_single_category_parallel,
                    category_url, start_index + i, total_categories
                )
                future_to_info[future] = {"url": category_url, "index": start_index + i}
            
            # Collect results as they complete
            for future in as_completed(future_to_info):
                info = future_to_info[future]
                category_url = info["url"]
                
                try:
                    category_result = future.result()
                    parallel_results[category_url] = category_result
                    
                    products_found = len(category_result.get("products", []))
                    print(f"      ✅ Parallel {info['index']}: {products_found} products")
                    
                except Exception as e:
                    print(f"      ❌ Parallel {info['index']}: Failed - {e}")
                    parallel_results[category_url] = {
                        "name": extract_category_name(category_url),
                        "products": [],
                        "error": str(e)
                    }
        
        return parallel_results
    
    def _process_single_category_parallel(self, category_url: str, category_index: int, total_categories: int) -> dict:
        """Process a single category in parallel mode (thread-safe)"""
        from page_extractor import extract_category_name
        
        # Get working pattern (should be fast since patterns are discovered)
        pattern = self._get_working_pattern_for_category(category_url)
        if not pattern:
            return {
                "name": extract_category_name(category_url),
                "products": [],
                "error": "No working pattern"
            }
        
        # Extract products from this category
        return self._extract_category_products(category_url, pattern, category_index, total_categories)
    
    def _get_working_pattern_for_category(self, category_url: str) -> dict:
        """
        Get a working pattern for the category - try existing patterns first,
        only discover new pattern if all existing patterns fail
        """
        print(f"      🔍 Finding working pattern for category...")
        
        # Try all existing patterns first
        for i, pattern in enumerate(self.discovered_patterns):
            print(f"         Trying existing pattern {i+1}/{len(self.discovered_patterns)}")
            if self._test_pattern_on_page(category_url, pattern):
                print(f"         ✅ Existing pattern works!")
                return pattern
        
        # Only if ALL existing patterns fail → discover new pattern
        print(f"         🆕 No existing patterns work - discovering new pattern...")
        try:
            # Use existing pattern discovery logic
            self.starting_pages_queue = [category_url]
            self.product_pages = [category_url]
            
            pattern_result = self.analyze_product_pattern()
            if pattern_result and pattern_result.get("extraction_pattern"):
                new_pattern = pattern_result["extraction_pattern"]
                
                # Store in global patterns list
                self.discovered_patterns.append(new_pattern)
                print(f"         ✅ New pattern discovered and stored globally!")
                print(f"         📊 Total discovered patterns: {len(self.discovered_patterns)}")
                
                return new_pattern
            
        except Exception as e:
            print(f"         ❌ Pattern discovery failed: {e}")
        
        return None
    
    def _test_pattern_on_page(self, page_url: str, pattern: dict) -> bool:
        """Test if a pattern works on a given page by trying to extract products"""
        try:
            from page_extractor import extract_products_from_page
            
            # Try to extract products with this pattern
            test_result = extract_products_from_page(
                page_url, [pattern], "test", allow_pattern_discovery=False, brand_instance=self
            )
            
            products = test_result.get("products", [])
            return len(products) > 0
            
        except Exception:
            return False
    
    def _extract_category_products(self, category_url: str, pattern: dict, category_num: int, total_categories: int) -> dict:
        """Extract all products from a single category with multi-page support and image downloads"""
        from page_extractor import extract_products_from_page, extract_category_name
        import time
        
        category_name = extract_category_name(category_url)
        print(f"      📂 Extracting from: {category_name}")
        
        start_time = time.time()
        
        try:
            # Extract products using our advanced multi-page system
            extraction_result = extract_products_from_page(
                category_url, [pattern], category_name, 
                allow_pattern_discovery=False,  # Don't discover new patterns on secondary pages
                brand_instance=self  # Pass brand instance for global learning
            )
            
            products = extraction_result.get("products", [])
            extraction_time = time.time() - start_time
            
            print(f"         📦 Found {len(products)} products")
            
            # Download images for all products
            images_downloaded = 0
            if products:
                print(f"         🖼️  Downloading images...")
                images_downloaded = self._download_category_images(products, category_name)
                print(f"         ✅ Downloaded {images_downloaded}/{len(products)} images")
            
            return {
                "name": category_name,
                "url": category_url,
                "products": products,
                "pattern_used": pattern,
                "extraction_stats": {
                    "pages_processed": extraction_result.get("pages_extracted", 1),
                    "products_found": len(products),
                    "images_downloaded": images_downloaded,
                    "extraction_time": extraction_time
                }
            }
            
        except Exception as e:
            print(f"         ❌ Extraction failed: {e}")
            return {
                "name": category_name,
                "url": category_url,
                "products": [],
                "error": str(e),
                "extraction_stats": {
                    "extraction_time": time.time() - start_time
                }
            }
    
    def _download_category_images(self, products: List[dict], category_name: str) -> int:
        """Download images for all products in a category"""
        import os
        import requests
        from urllib.parse import urlparse
        
        if not products:
            return 0
        
        # Create category images directory
        brand_name = urlparse(self.url).netloc.replace('www.', '').split('.')[0]
        images_dir = f"{brand_name}_images/{category_name.replace(' ', '_').replace('/', '_')}"
        os.makedirs(images_dir, exist_ok=True)
        
        downloaded_count = 0
        
        for product in products:
            try:
                images = product.get("images", [])
                if not images:
                    continue
                    
                # Download first image
                first_image = images[0]
                image_url = first_image.get("src") 
                if not image_url:
                    continue
                
                # Generate filename
                product_name = product.get("product_name", "unknown").replace(" ", "_").replace("/", "_")[:50]
                extension = os.path.splitext(urlparse(image_url).path)[1] or '.jpg'
                filename = f"{product_name}{extension}"
                filepath = os.path.join(images_dir, filename)
                
                # Skip if already downloaded
                if os.path.exists(filepath):
                    downloaded_count += 1
                    continue
                
                # Download image
                response = requests.get(image_url, timeout=10)
                if response.status_code == 200:
                    with open(filepath, 'wb') as f:
                        f.write(response.content)
                    downloaded_count += 1
                    
            except Exception:
                continue  # Skip failed downloads
        
        return downloaded_count
    
    def _save_pipeline_results_to_json(self, results: dict):
        """Save pipeline results to JSON file"""
        import json
        import os
        from urllib.parse import urlparse
        
        # Generate filename from brand URL
        brand_name = urlparse(self.url).netloc.replace('www.', '').split('.')[0]
        filename = f"{brand_name}_extraction_results.json"
        
        # Create results directory if needed
        os.makedirs("results", exist_ok=True)
        filepath = os.path.join("results", filename)
        
        # Convert sets to lists for JSON serialization
        json_results = self._make_json_serializable(results)
        
        with open(filepath, 'w') as f:
            json.dump(json_results, f, indent=2)
        
        print(f"      💾 Results saved to: {filepath}")
    
    def _make_json_serializable(self, obj):
        """Convert sets and other non-serializable objects to JSON-compatible format"""
        if isinstance(obj, set):
            return list(obj)
        elif isinstance(obj, dict):
            return {k: self._make_json_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._make_json_serializable(item) for item in obj]
        else:
            return obj

    def __repr__(self) -> str:
        return f"Brand(url='{self.url}', pages={len(self.product_pages)}, queue={len(self.starting_pages_queue)})"