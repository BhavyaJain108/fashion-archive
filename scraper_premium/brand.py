"""
Brand Module
============

Represents a fashion brand.
"""

import sys
import os
import json
from typing import List
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
        
        # Product queue for discovered products
        self.product_queue = Queue()
        self.seen_product_urls = set()  # Track discovered products to avoid duplicates
        self.all_products = set()  # Set of all unique products (by URL)
        
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
            
            # Extract image using the pattern
            image_url = "N/A"
            image_selector = pattern.get('image_selector', 'img')
            if image_selector:
                img_element = target_container.select_one(image_selector)
                if img_element:
                    img_src = img_element.get('src') or img_element.get('data-src') or img_element.get('data-lazy-src')
                    if img_src:
                        if img_src.startswith('http'):
                            image_url = img_src
                        else:
                            image_url = urljoin(base_url, img_src)
            
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
                "image_url": image_url
            }
            
        except Exception as e:
            return {
                "name": "Sample Product",
                "product_url": product_link,
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
        
        # Fallback to text response if structured fails
        llm_response = self.llm_handler.call(prompt, expected_format="text")
        
        if llm_response.get("success", False):
            response_text = llm_response.get("response", "").strip()
            # Extract URLs from response
            found_urls = []
            for link in all_links:
                if link in response_text and link not in found_urls:
                    found_urls.append(link)
                    if len(found_urls) >= 3:  # Limit to 3
                        break
            
            if found_urls:
                print(f"🔗 Fallback found {len(found_urls)} product links")
                return found_urls
        
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
                    "image_selector": "img",
                    "name_selector": ".product-title, .product-name, h3, h4"
                },
                {
                    "container_selector": "[data-product], [data-product-id]",
                    "link_selector": "a",
                    "image_selector": "img",
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
            image_selector = self.product_extraction_pattern.get('image_selector') or ''
            
            # Get ALL containers (no JavaScript marking - rely on URL deduplication)
            # Safely escape selectors for JavaScript
            import json
            container_selector_escaped = json.dumps(container_selector)
            link_selector_escaped = json.dumps(link_selector)
            name_selector_escaped = json.dumps(name_selector)
            image_selector_escaped = json.dumps(image_selector)
            
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
                        
                        let imageSrc = '';
                        if ({image_selector_escaped}) {{
                            const imgEl = container.querySelector({image_selector_escaped});
                            if (imgEl) {{
                                imageSrc = imgEl.getAttribute('src') || imgEl.getAttribute('data-src') || '';
                            }}
                        }}
                        
                        if (href) {{
                            newProducts.push({{
                                href: href,
                                name: name.trim(),
                                image: imageSrc
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
            image_selector = self.product_extraction_pattern.get('image_selector')  # No default
            
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
                    
                    # Extract product image
                    product_image = ""
                    image_element = container.query_selector(image_selector)
                    if image_element:
                        product_image = image_element.get_attribute('src') or ""
                        if product_image and not product_image.startswith('http'):
                            product_image = urljoin(source_url, product_image)
                    
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

    def __repr__(self) -> str:
        return f"Brand(url='{self.url}', pages={len(self.product_pages)}, queue={len(self.starting_pages_queue)})"