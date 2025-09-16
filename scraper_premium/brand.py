"""
Brand Module
============

Represents a fashion brand.
"""

import sys
import os
import json
from typing import List
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright
import re

# Add parent directories to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from llm_handler import LLMHandler



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
    
    def analyze_navigation(self) -> List[str]:
        """
        Analyze brand navigation and discover product page URLs.
        
        This function uses LLM analysis to find all product page URLs
        and populates the starting pages queue.
        
        Returns:
            List of product category URLs
        """
        try:
            links = self.extract_page_links(self.url)
            
            if not links:
                raise Exception("Failed to extract any links from the page")
            
            prompt = self._build_navigation_prompt(links)
            llm_response = self.llm_handler.call(prompt, expected_format="json")
            
            if not llm_response.get("success", False):
                raise Exception(f"LLM analysis failed: {llm_response.get('error', 'Unknown error')}")
            
            analysis = llm_response.get("data", {})
            
            # Get URLs and normalize them
            included_urls = analysis.get("included_urls", [])
            normalized_urls = []
            for url_obj in included_urls:
                url = url_obj.get("url", "") if isinstance(url_obj, dict) else url_obj
                if url.startswith('/'):
                    # Convert relative URL to absolute
                    normalized_urls.append(urljoin(self.url, url))
                else:
                    normalized_urls.append(url)
            
            # Store results and populate starting pages queue
            self.product_pages = normalized_urls
            self.starting_pages_queue = normalized_urls.copy()
            
            # If we found product pages, analyze the first one for extraction pattern
            if self.starting_pages_queue:
                print(f"🔍 Analyzing product pattern from first page...")
                self.product_extraction_pattern = self.analyze_product_pattern()
            
            return normalized_urls
            
        except Exception:
            self.product_pages = []
            self.starting_pages_queue = []
            return []
    
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
            # Get HTML content and extract all links
            html_content = self.get_page_html(first_page_url)
            if not html_content:
                raise Exception("Failed to fetch HTML content")
            
            # Step 1: Find one valid product link
            all_links = self.extract_page_links(first_page_url)
            print(f"📋 Extracted {len(all_links)} links from page")
            print(f"   First 10 links: {all_links[:10]}")
            
            product_link = self._find_product_link(all_links, first_page_url)
            
            if not product_link:
                print(f"❌ LLM failed to identify product link from {len(all_links)} links")
                raise Exception("No valid product link found")
            
            print(f"🔗 Found product link: {product_link}")
            
            # Step 2: Analyze pattern around that specific link
            pattern_analysis = self._analyze_link_pattern(html_content, product_link, first_page_url)
            
            if not pattern_analysis:
                raise Exception("Failed to analyze link pattern")
            
            return pattern_analysis
            
        except Exception as e:
            print(f"❌ Product pattern analysis failed: {e}")
            return {}
    
    def get_page_html(self, url: str) -> str:
        """
        Get the full rendered HTML of a page using Playwright.
        Uses fast 'load' strategy with minimal wait for product links.
        
        Args:
            url: The URL to fetch
            
        Returns:
            The complete rendered HTML content
        """
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                
                # Use fast 'load' strategy
                page.goto(url, wait_until="load", timeout=15000)
                
                # Short wait for product links to appear
                try:
                    page.wait_for_selector('a[href*="/products/"], a[href*="/product/"]', timeout=3000)
                except:
                    # If no product links found quickly, just continue
                    pass
                
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
    
    def _find_product_link(self, all_links: List[str], base_url: str) -> str:
        """
        Step 1: Use LLM to identify one valid product link from all page links
        """
        # Format links for prompt - give it ALL links
        links_text = "\n".join(f"- {link}" for link in all_links)
        
        print(f"🔍 ALL LINKS SENT TO LLM ({len(all_links)} total):")
        for i, link in enumerate(all_links, 1):
            print(f"   {i:2d}. {link}")
        
        prompt = f"""
Find ONE valid product link from this fashion website.

Website: {base_url}
All links found:
{links_text}

Return the ONE best product link that leads to an individual clothing/fashion item.
Look for links that contain product names, clothing items, or fashion accessories.
Exclude: collections, categories, about pages, contact, search, account, blog.

Return only the URL, nothing else.
""".strip()
        
        # Use Sonnet 3.5 for quality
        llm_response = self.llm_handler.call(prompt, expected_format="text")
        
        print(f"🔍 Step 1 LLM Response:")
        print(f"   Success: {llm_response.get('success', False)}")
        print(f"   Response: {llm_response.get('response', 'N/A')[:200]}...")
        print(f"   Error: {llm_response.get('error', 'None')}")
        
        if llm_response.get("success", False):
            response_text = llm_response.get("response", "").strip()
            # Extract URL from response - find exact match or best match
            
            # First try exact match
            for link in all_links:
                if link == response_text:
                    print(f"✅ Exact match: {link}")
                    return link
            
            # Then try if response contains the link
            for link in all_links:
                if response_text in link:
                    print(f"✅ Response contained in link: {link}")
                    return link
                    
            # Finally try if link is in response (but prioritize longer/more specific links)
            best_match = ""
            for link in all_links:
                if link in response_text and len(link) > len(best_match):
                    best_match = link
            
            if best_match:
                print(f"✅ Best match found: {best_match}")
                return best_match
            
            print(f"❌ No link matched in response: {response_text}")
        
        return ""
    
    def _analyze_link_pattern(self, html_content: str, product_link: str, base_url: str) -> dict:
        """
        Step 2: Analyze HTML around the specific product link to find container pattern
        """
        # Extract the product path from the full URL
        from urllib.parse import urlparse
        parsed_link = urlparse(product_link)
        link_path = parsed_link.path
        
        # Find surrounding HTML context (search for the href in HTML)
        import re
        # Look for the actual <a> tag with this href
        href_pattern = rf'<a[^>]*href="{re.escape(link_path)}"[^>]*>.*?</a>'
        match = re.search(href_pattern, html_content, re.DOTALL | re.IGNORECASE)
        
        if not match:
            # Try with relative href
            href_pattern = rf'<a[^>]*href="{re.escape(product_link)}"[^>]*>.*?</a>'
            match = re.search(href_pattern, html_content, re.DOTALL | re.IGNORECASE)
        
        if not match:
            return {}
        
        # Get 2000 characters before and after the match for context
        match_start = match.start()
        context_start = max(0, match_start - 2000)
        context_end = min(len(html_content), match.end() + 2000)
        context_html = html_content[context_start:context_end]
        
        prompt = f"""
Analyze this HTML containing a product link and identify the container pattern.

Product Link: {product_link}
HTML Context:
{context_html}

Find the HTML structure around the product link and return:
1. What element contains/wraps the product link? 
2. CSS selectors to find all similar product containers
3. CSS selectors for images, names, links within each container

Return JSON:
{{
    "container_selector": "CSS selector for product containers",
    "image_selector": "CSS selector for images within container", 
    "name_selector": "CSS selector for names within container",
    "link_selector": "CSS selector for product links within container"
}}
""".strip()
        
        # Use Haiku for speed
        llm_response = self.llm_handler.call(prompt, expected_format="json")
        
        if llm_response.get("success", False):
            data = llm_response.get("data", {})
            if data and "container_selector" in data:
                print(f"✅ Pattern extracted:")
                print(f"   Container: {data.get('container_selector', 'N/A')}")
                print(f"   Image: {data.get('image_selector', 'N/A')}")
                print(f"   Name: {data.get('name_selector', 'N/A')}")
                print(f"   Link: {data.get('link_selector', 'N/A')}")
                
                return {
                    "extraction_pattern": data,
                    "example_products": [{
                        "name": "Sample Product",
                        "product_url": product_link,
                        "image_url": "N/A"
                    }]
                }
        
        return {}
    
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
Here sometimes you may see a everything for a particular subcategory. for example womens/all or shoes/all. These are going to be gametime decisions where you have to judge what collectoin of links would form the a distinct yet complete set of products offered.
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
    
    def set_analysis_result(self, webfetch_response: str) -> List[str]:
        """
        Set the WebFetch analysis result and parse it.
        
        Args:
            webfetch_response: Raw response from WebFetch tool
            
        Returns:
            List of product URLs
        """
        try:
            # Parse JSON from WebFetch response
            if isinstance(webfetch_response, str):
                start_idx = webfetch_response.find('{')
                end_idx = webfetch_response.rfind('}') + 1
                if start_idx != -1 and end_idx != -1:
                    json_str = webfetch_response[start_idx:end_idx]
                    analysis = json.loads(json_str)
                else:
                    raise ValueError("No JSON found in WebFetch response")
            else:
                analysis = webfetch_response
            
            # Get URLs
            product_urls = analysis.get("product_urls", [])
            
            # Store results and populate starting pages queue
            self.product_pages = product_urls
            self.starting_pages_queue = product_urls.copy()
            
            # Log results
            print(f"✅ Found {len(product_urls)} product page(s):")
            for i, url in enumerate(product_urls, 1):
                print(f"   {i}. {url}")
            
            confidence = analysis.get("confidence", 0.0)
            reasoning = analysis.get("reasoning", "No reasoning provided")
            print(f"🎯 Confidence: {confidence:.1f}")
            print(f"💭 Reasoning: {reasoning}")
            
            return product_urls
            
        except Exception as e:
            print(f"❌ Failed to parse WebFetch response: {e}")
            self.product_pages = []
            self.starting_pages_queue = []
            return []
    
    def _build_product_detection_prompt(self, html_content: str, url: str) -> str:
        """Build the product detection prompt based on the old system"""
        
        # Truncate HTML for LLM processing
        HTML_TRUNCATE_LIMIT = 10000
        
        # Try to find the main content area that contains the product grid
        body_match = re.search(r'<body[^>]*>(.*)</body>', html_content, re.DOTALL | re.IGNORECASE)
        if body_match:
            body_content = body_match.group(1)
            
            # Look for product grid sections specifically
            grid_patterns = [
                r'<div[^>]*class="[^"]*(?:product-grid|products-grid|collection|grid)[^"]*"[^>]*>.*?</div>',
                r'<section[^>]*class="[^"]*(?:product|collection)[^"]*"[^>]*>.*?</section>',
                r'<main[^>]*>.*?</main>',
                r'<div[^>]*id="[^"]*(?:product|collection|main)[^"]*"[^>]*>.*?</div>'
            ]
            
            best_section = None
            max_product_indicators = 0
            
            for pattern in grid_patterns:
                matches = re.findall(pattern, body_content, re.DOTALL)
                for match in matches:
                    # Count product indicators in this section
                    product_count = (
                        len(re.findall(r'<[^>]*class="[^"]*(?:product|item|card)[^"]*"', match)) +
                        len(re.findall(r'<x-cell', match)) +
                        len(re.findall(r'data-product', match)) +
                        len(re.findall(r'product-', match))
                    )
                    
                    if product_count > max_product_indicators:
                        max_product_indicators = product_count
                        best_section = match
            
            if best_section and max_product_indicators > 10:
                # Found a section with many product indicators - use it
                html_preview = best_section[:HTML_TRUNCATE_LIMIT]
                print(f"🔍 Using product grid section with {max_product_indicators} product indicators")
            else:
                # Look for the middle section of body content (skip header/footer)
                body_lines = body_content.split('\n')
                start_idx = len(body_lines) // 4  # Skip first 25%
                end_idx = 3 * len(body_lines) // 4  # Use up to 75%
                middle_content = '\n'.join(body_lines[start_idx:end_idx])
                html_preview = middle_content[:HTML_TRUNCATE_LIMIT]
                print(f"🔍 Using middle section of body content")
        else:
            # Fallback to original approach but skip scripts and styles
            content_no_scripts = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
            content_no_styles = re.sub(r'<style[^>]*>.*?</style>', '', content_no_scripts, flags=re.DOTALL | re.IGNORECASE)
            html_preview = content_no_styles[:HTML_TRUNCATE_LIMIT]
            print(f"🔍 Using cleaned HTML content (no scripts/styles)")
        
        return f"""
Look at this fashion brand page and help me identify the pattern for finding products.

URL: {url}
HTML Content:
{html_preview}

I need you to find 2-3 example products and tell me how to identify ALL products programmatically.

Your task:
1. Find 2-3 clear product examples from this page
2. For each example, show me:
   - The product name/title
   - The image URL
   - The product URL (link to individual product page)
   - The HTML structure around that product

3. Tell me the pattern:
   - What CSS selector would find all product containers?
   - What CSS selector would find product images within each container?
   - What CSS selector would find product names within each container?
   - What CSS selector would find product links within each container?

Return a JSON object:
{{
    "example_products": [
        {{
            "name": "product name",
            "image_url": "image URL",
            "product_url": "full URL to individual product page",
            "html_snippet": "HTML around this product (200 chars)"
        }}
    ],
    "extraction_pattern": {{
        "container_selector": "CSS selector for product containers",
        "image_selector": "CSS selector for images within container",
        "name_selector": "CSS selector for names within container",
        "link_selector": "CSS selector for product links within container",
        "how_to_use": "brief explanation of how to use these selectors"
    }}
}}

Focus on giving me selectors I can use with document.querySelectorAll() to find ALL products.

Respond with only valid JSON.
""".strip()
    
    def __repr__(self) -> str:
        return f"Brand(url='{self.url}', pages={len(self.product_pages)}, queue={len(self.starting_pages_queue)})"