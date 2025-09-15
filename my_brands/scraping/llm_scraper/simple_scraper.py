#!/usr/bin/env python3
"""
Simple LLM-Driven Fashion Brand Scraper
======================================

Clean, simple scraper with clear decision tree. No infinite loops.
"""

import asyncio
import json
import sys
import os
import aiohttp
import aiofiles
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from playwright.async_api import async_playwright, Browser, Page
import concurrent.futures
from urllib.parse import urlparse
import hashlib

# Add parent directories to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Import LLM client
from llm_interface import ClaudeInterface

@dataclass
class Product:
    """Scraped product information"""
    title: str
    image_url: str
    product_url: Optional[str] = None
    confidence: float = 0.8
    detection_method: str = "simple_scraper"
    collection_name: Optional[str] = None
    collection_url: Optional[str] = None
    download_path: Optional[str] = None

@dataclass
class ScrapingResult:
    """Result of scraping operation"""
    success: bool
    products: List[Product]
    total_found: int
    strategy_used: str
    confidence: float
    errors: List[str] = None

class SimpleLLMScraper:
    """Simple LLM-driven web scraper - no infinite loops!"""
    
    def __init__(self):
        # Use fast model for decisions
        self.llm = ClaudeInterface(model="claude-3-haiku-20240307")
        
        # Streaming download system
        self.download_queue = asyncio.Queue()
        self.download_workers = []
        self.num_workers = 8
        self.downloads_dir = "my_brands_cache"
        
        # Ensure downloads directory exists
        os.makedirs(self.downloads_dir, exist_ok=True)
        # Use smart model for pattern detection
        self.smart_llm = ClaudeInterface(model="claude-3-5-sonnet-20241022")
        self.browser: Optional[Browser] = None
    
    def _generate_filename(self, image_url: str, title: str) -> str:
        """Generate a unique filename for the image"""
        # Create a hash from URL and title for uniqueness
        content = f"{image_url}_{title}"
        hash_obj = hashlib.md5(content.encode())
        filename_hash = hash_obj.hexdigest()[:8]
        
        # Get file extension from URL
        parsed_url = urlparse(image_url)
        path = parsed_url.path
        extension = os.path.splitext(path)[1] if '.' in path else '.jpg'
        
        # Clean title for filename
        clean_title = "".join(c for c in title[:20] if c.isalnum() or c in (' ', '-', '_')).strip()
        clean_title = clean_title.replace(' ', '_')
        
        return f"{clean_title}_{filename_hash}{extension}"
    
    async def _download_worker(self, worker_id: int):
        """Download worker that processes the download queue"""
        print(f"🔄 Download worker {worker_id} started")
        
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    # Get next download task
                    product = await self.download_queue.get()
                    
                    if product is None:  # Shutdown signal
                        break
                    
                    # Generate filename
                    filename = self._generate_filename(product.image_url, product.title)
                    download_path = os.path.join(self.downloads_dir, filename)
                    
                    # Skip if already downloaded
                    if os.path.exists(download_path):
                        print(f"⏭️ Worker {worker_id}: Already exists - {filename}")
                        product.download_path = download_path
                        self.download_queue.task_done()
                        continue
                    
                    # Download the image
                    print(f"⬇️ Worker {worker_id}: Downloading {filename}")
                    async with session.get(product.image_url) as response:
                        if response.status == 200:
                            async with aiofiles.open(download_path, 'wb') as f:
                                async for chunk in response.content.iter_chunked(8192):
                                    await f.write(chunk)
                            
                            product.download_path = download_path
                            print(f"✅ Worker {worker_id}: Downloaded {filename}")
                        else:
                            print(f"❌ Worker {worker_id}: Failed to download {filename} - Status {response.status}")
                    
                    self.download_queue.task_done()
                    
                except Exception as e:
                    print(f"❌ Worker {worker_id}: Error downloading - {e}")
                    self.download_queue.task_done()
    
    async def _start_download_workers(self):
        """Start the download workers"""
        print(f"🚀 Starting {self.num_workers} download workers...")
        self.download_workers = []
        for i in range(self.num_workers):
            worker = asyncio.create_task(self._download_worker(i + 1))
            self.download_workers.append(worker)
    
    async def _stop_download_workers(self):
        """Stop the download workers"""
        print("🛑 Stopping download workers...")
        
        # Send shutdown signals
        for _ in range(self.num_workers):
            await self.download_queue.put(None)
        
        # Wait for workers to finish
        await asyncio.gather(*self.download_workers, return_exceptions=True)
        
        print("✅ All download workers stopped")
    
    def _queue_product_download(self, product: Product):
        """Queue a product for download"""
        if product.image_url:
            try:
                self.download_queue.put_nowait(product)
                print(f"📥 Queued for download: {product.title[:30]}...")
            except asyncio.QueueFull:
                print(f"⚠️ Download queue full, skipping: {product.title[:30]}...")
    
    # ===========================================
    # MAIN SCRAPING FLOW
    # ===========================================
    
    async def scrape(self, url: str) -> ScrapingResult:
        """Main scraping entry point - SIMPLE FLOW"""
        print(f"🤖 Starting SIMPLE scraping of: {url}")
        
        # Start download workers
        await self._start_download_workers()
        
        async with async_playwright() as p:
            # Launch browser
            self.browser = await p.chromium.launch(headless=True)
            
            try:
                # STEP 1: Load homepage
                page = await self._load_page(url)
                
                # STEP 2: Simple decision - is this a products page?
                is_products_page = await self._is_products_page(page)
                
                if is_products_page:
                    print("✅ This IS a products page - extracting products...")
                    products = await self._extract_all_products_from_page(page)
                    
                    # Wait for all downloads to complete
                    await self.download_queue.join()
                    
                    return ScrapingResult(
                        success=True,
                        products=products,
                        total_found=len(products),
                        strategy_used="direct_products_page",
                        confidence=0.9,
                        errors=[]
                    )
                else:
                    print("❌ This is NOT a products page - finding product pages...")
                    # STEP 3: Find product pages
                    product_pages = await self._find_product_pages(page)
                    
                    if not product_pages:
                        await self._stop_download_workers()
                        return ScrapingResult(
                            success=False,
                            products=[],
                            total_found=0,
                            strategy_used="no_products_found",
                            confidence=0.0,
                            errors=["Could not find any product pages"]
                        )
                    
                    print(f"📂 Found {len(product_pages)} product pages to scrape")
                    
                    # STEP 4: Extract from all product pages (in parallel if multiple)
                    all_products = await self._extract_from_multiple_pages(product_pages)
                    
                    # Wait for all downloads to complete
                    await self.download_queue.join()
                    
                    return ScrapingResult(
                        success=True,
                        products=all_products,
                        total_found=len(all_products),
                        strategy_used=f"multiple_pages_{len(product_pages)}",
                        confidence=0.8,
                        errors=[]
                    )
                    
            except Exception as e:
                print(f"❌ Scraping failed: {e}")
                return ScrapingResult(
                    success=False,
                    products=[],
                    total_found=0,
                    strategy_used="error",
                    confidence=0.0,
                    errors=[str(e)]
                )
            finally:
                if self.browser:
                    await self.browser.close()
                # Stop download workers
                await self._stop_download_workers()
    
    # ===========================================
    # STEP IMPLEMENTATIONS
    # ===========================================
    
    async def _load_page(self, url: str) -> Page:
        """Load a page and wait for it to be ready"""
        print(f"🌐 Loading: {url}")
        page = await self.browser.new_page()
        await page.goto(url, timeout=60000)
        
        try:
            await page.wait_for_load_state('networkidle', timeout=10000)
        except:
            await page.wait_for_load_state('domcontentloaded')
        
        print("✅ Page loaded")
        return page
    
    async def _is_products_page(self, page: Page) -> bool:
        """Ask LLM: Is this a page with products on it?"""
        print("🤔 Asking LLM: Is this a products page?")
        
        html_content = await page.content()
        
        prompt = f"""
Look at this webpage and answer: Does this page show PRODUCTS that can be purchased?

URL: {page.url}
HTML (first 3000 chars): {html_content[:3000]}

Look for:
- Product images with names/titles
- Prices 
- "Add to cart" buttons
- Product grids/lists
- Shopping functionality

Answer with JSON:
{{
    "has_products": true/false,
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation"
}}

Only respond with valid JSON.
""".strip()
        
        try:
            response = await self._ask_llm(prompt)
            print(f"🤖 Raw LLM response: {response}")
            
            # Clean and parse JSON
            result = self._parse_json_response(response)
            has_products = result.get("has_products", False)
            confidence = result.get("confidence", 0.0)
            reasoning = result.get("reasoning", "No reasoning provided")
            
            print(f"🤖 LLM says: {'YES' if has_products else 'NO'} (confidence: {confidence:.2f})")
            print(f"   Reasoning: {reasoning}")
            
            return has_products
            
        except Exception as e:
            print(f"❌ LLM decision failed: {e}")
            print(f"   Response was: {response if 'response' in locals() else 'No response'}")
            return False
    
    async def _find_product_pages(self, page: Page) -> List[str]:
        """Find URLs that lead to product pages"""
        print("🔍 Finding product pages...")
        
        html_content = await page.content()
        
        prompt = f"""
Analyze this homepage and find ALL the URLs that lead to pages with products.

URL: {page.url}
HTML (first 5000 chars): {html_content[:5000]}

Look for:
1. "Shop All" or "All Products" links (BEST - shows everything)
2. Category links (Men, Women, Tops, etc.)
3. Collection links (Summer 2024, New Arrivals, etc.)
4. Any link that would show multiple purchasable products

CRITICAL DECISION RULE:
- If you find an "All Products", "Shop All", "All", or similar comprehensive page that shows ALL products, return ONLY that URL
- Only return multiple category URLs if there's NO comprehensive "all products" page

Return JSON array of URLs:
[
    "https://example.com/collections/all"
]

OR if no "all" page exists:

[
    "https://example.com/collections/men",
    "https://example.com/collections/women",
    "https://example.com/collections/shoes"
]

Prioritize comprehensive pages over individual categories.

Only respond with valid JSON array.
""".strip()
        
        try:
            response = await self._ask_smart_llm(prompt)  # Use smart LLM for this
            urls = self._parse_json_response(response)
            
            if isinstance(urls, list):
                # Convert relative URLs to absolute
                absolute_urls = []
                for url in urls:
                    if url.startswith('/'):
                        from urllib.parse import urljoin
                        url = urljoin(page.url, url)
                    absolute_urls.append(url)
                
                
                print(f"📋 Found {len(absolute_urls)} product page URLs:")
                for i, url in enumerate(absolute_urls, 1):
                    print(f"   {i}. {url}")
                
                return absolute_urls
            else:
                print(f"❌ Expected array, got: {type(urls)}")
                return []
                
        except Exception as e:
            print(f"❌ Failed to find product pages: {e}")
            return []
    
    async def _extract_all_products_from_page(self, page: Page) -> List[Product]:
        """Extract all products from a single page"""
        print(f"📦 Extracting products from: {page.url}")
        
        # First, detect the pattern
        pattern = await self._detect_product_pattern(page)
        if not pattern:
            print("❌ Could not detect product pattern")
            return []
        
        # Check for infinite scroll using the actual product pattern
        page_has_scroll, scroll_products = await self._check_infinite_scroll_with_pattern(page, pattern)
        if page_has_scroll:
            print("🔄 Current page has infinite scroll - using products from scroll detection...")
            products = scroll_products  # Use products found during scroll detection
        else:
            # Extract normally  
            products = await self._extract_products_using_pattern(page, pattern)
        
        print(f"✅ Extracted {len(products)} products from this page")
        
        # Check for pagination and get ALL pages
        all_page_urls = await self._find_all_page_urls(page)
        
        if all_page_urls:
            if all_page_urls == ["INFINITE_SCROLL"]:
                print("🔄 Found infinite scroll - extracting all products by scrolling...")
                # Use the current page for infinite scroll
                scroll_products = await self._extract_with_infinite_scroll(page, pattern)
                products.extend(scroll_products)
            else:
                print(f"📄 Found {len(all_page_urls)} total pages to scrape")
                # Pass along whether page 1 had infinite scroll
                all_products = await self._extract_from_pagination_pages(all_page_urls, pattern, None, page_has_scroll)
                products.extend(all_products)
        
        # Simple deduplication using set
        unique_products = []
        seen = set()
        for product in products:
            key = (product.title, product.image_url)
            if key not in seen:
                seen.add(key)
                unique_products.append(product)
        
        if len(products) != len(unique_products):
            print(f"🧹 Removed {len(products) - len(unique_products)} duplicates")
        
        
        print(f"✅ Total unique products: {len(unique_products)}")
        return unique_products
    
    async def _extract_from_multiple_pages(self, page_urls: List[str]) -> List[Product]:
        """Extract products from multiple pages in parallel"""
        print(f"🚀 Processing {len(page_urls)} pages in parallel...")
        
        async def process_single_page(url: str) -> List[Product]:
            try:
                page = await self._load_page(url)
                products = await self._extract_all_products_from_page(page)
                await page.close()
                return products
            except Exception as e:
                print(f"❌ Failed to process {url}: {e}")
                return []
        
        # Process all pages in parallel
        tasks = [process_single_page(url) for url in page_urls]
        results = await asyncio.gather(*tasks)
        
        # Combine all products
        all_products = []
        for products in results:
            all_products.extend(products)
        
        print(f"🎉 Total products from all pages: {len(all_products)}")
        return all_products
    
    # ===========================================
    # PRODUCT PATTERN DETECTION & EXTRACTION
    # ===========================================
    
    async def _detect_product_pattern(self, page: Page) -> Optional[Dict[str, str]]:
        """Detect the pattern for finding products on this page"""
        print("🔍 Detecting product pattern...")
        
        # FAST DETECTION: Try known selectors first for common sites
        known_patterns = [
            {
                "container_selector": ".collection-item",
                "image_selector": "img[data-widths]",
                "name_selector": ".custom-card-title, h3, .product-title",
                "link_selector": "a"
            },
            {
                "container_selector": ".product-card",
                "image_selector": "img",
                "name_selector": ".product-title, .card-title, h2, h3",
                "link_selector": "a"
            },
            {
                "container_selector": ".product-item",
                "image_selector": "img", 
                "name_selector": ".title, .name, h2, h3",
                "link_selector": "a"
            }
        ]
        
        # Test each known pattern
        for pattern in known_patterns:
            container_count = len(await page.query_selector_all(pattern["container_selector"]))
            if container_count > 0:
                print(f"🎯 Found {container_count} products with selector: {pattern['container_selector']}")
                return pattern
        
        # Fallback to LLM analysis if needed
        html_content = await page.content()
        relevant_html = self._extract_clean_body_html(html_content)
        print(f"🧹 Fallback LLM analysis: {len(relevant_html)} chars of HTML")
        
        prompt = f"""
Analyze this fashion brand e-commerce page and find ACTUAL PRODUCTS for sale (not navigation menus).

URL: {page.url}
RELEVANT HTML (product sections): {relevant_html}

CRITICAL: Look for MAIN PRODUCT LISTINGS, NOT navigation/menu items.

Look for patterns like:
- .product-card, .product-item, .grid-item (actual product containers)
- NOT .submenu-product-item, .nav-item, .menu-item (navigation elements)

Find 2-3 ACTUAL PRODUCTS from the main shopping grid:
- Products with prices, "Add to Cart" buttons, product images
- NOT navigation links or menu items
- Look for div/article elements with product-related classes

Return JSON:
{{
    "example_products": [
        {{
            "name": "actual product name from main product grid",
            "image_url": "actual product image URL",
            "container_html": "HTML container around this ACTUAL product (first 200 chars)"
        }}
    ],
    "extraction_pattern": {{
        "container_selector": "CSS selector for ACTUAL product containers (not nav items)",
        "image_selector": "img selector within product container",
        "name_selector": "selector for product name/title",
        "link_selector": "selector for product page link",
        "notes": "focus on main product grid, avoid navigation"
    }}
}}

IMPORTANT:
- Show REAL examples from the HTML to prove these are products
- name_selector must target a TEXT element (h3, span, a with text)
- If name is in img alt attribute, note that in "notes" field
- Focus on selectors that will find ALL products on the page

Only respond with valid JSON.
""".strip()
        
        try:
            response = await self._ask_smart_llm(prompt)
            print(f"🔍 Pattern detection FULL response:")
            print(response)
            print("=" * 50)
            
            pattern = self._parse_json_response(response)
            print(f"🔧 Parsed pattern object: {pattern}")
            
            # Try to extract extraction_pattern if it exists
            if 'extraction_pattern' in pattern:
                extraction_pattern = pattern['extraction_pattern']
                print(f"🎯 Found extraction_pattern:")
                print(f"   Container: {extraction_pattern.get('container_selector')}")
                print(f"   Image: {extraction_pattern.get('image_selector')}")
                print(f"   Name: {extraction_pattern.get('name_selector')}")
                print(f"   Link: {extraction_pattern.get('link_selector')}")
                
                # Use the extraction_pattern, not the top level
                if extraction_pattern.get('container_selector'):
                    return extraction_pattern
            else:
                print(f"❌ No 'extraction_pattern' key found in response")
                print(f"   Available keys: {list(pattern.keys()) if isinstance(pattern, dict) else 'Not a dict'}")
            
            print("❌ No valid container selector found")
            return None
            
        except Exception as e:
            print(f"❌ Pattern detection failed: {e}")
            return None
    
    async def _extract_products_using_pattern(self, page: Page, pattern: Dict[str, str]) -> List[Product]:
        """Extract products using the detected pattern"""
        products = []
        
        try:
            container_selector = pattern.get('container_selector')
            if not container_selector:
                return []
            
            containers = await page.query_selector_all(container_selector)
            print(f"📋 Found {len(containers)} product containers")
            
            for i, container in enumerate(containers):
                try:
                    # Extract name
                    name = f"Product {i+1}"
                    name_selector = pattern.get('name_selector')
                    notes = pattern.get('notes', '')
                    
                    if name_selector:
                        # Check if we need to get alt attribute from image
                        if 'alt' in notes.lower() or 'img[alt]' in name_selector:
                            # Name is in img alt attribute
                            img_elem = await container.query_selector('img')
                            if img_elem:
                                name = await img_elem.get_attribute('alt') or f"Product {i+1}"
                        else:
                            # Normal text extraction with fallbacks
                            name_elem = await container.query_selector(name_selector)
                            if name_elem:
                                try:
                                    name = (await name_elem.inner_text()).strip()
                                    if not name:
                                        name = (await name_elem.text_content()).strip()
                                except:
                                    try:
                                        name = (await name_elem.text_content()).strip()
                                    except:
                                        name = f"Product {i+1}"
                            else:
                                # Fallback: try common name selectors
                                fallback_selectors = ['.card-title', 'h2', 'h3', '.product-title', 'a[title]']
                                for fallback_selector in fallback_selectors:
                                    try:
                                        fallback_elem = await container.query_selector(fallback_selector)
                                        if fallback_elem:
                                            fallback_name = (await fallback_elem.inner_text()).strip()
                                            if fallback_name:
                                                name = fallback_name
                                                print(f"   🔄 Used fallback selector '{fallback_selector}' for product {i+1}")
                                                break
                                    except:
                                        continue
                    
                    # Extract image
                    image_url = ""
                    image_selector = pattern.get('image_selector')
                    if image_selector:
                        img_elem = await container.query_selector(image_selector)
                        if img_elem:
                            image_url = await img_elem.get_attribute('src') or await img_elem.get_attribute('data-src') or ""
                    
                    # Extract product link
                    product_url = page.url
                    link_selector = pattern.get('link_selector')
                    if link_selector:
                        link_elem = await container.query_selector(link_selector)
                        if link_elem:
                            href = await link_elem.get_attribute('href')
                            if href:
                                if href.startswith('/'):
                                    from urllib.parse import urljoin
                                    product_url = urljoin(page.url, href)
                                else:
                                    product_url = href
                    
                    # Fix image URL
                    if image_url and not image_url.startswith('http'):
                        if image_url.startswith('//'):
                            image_url = 'https:' + image_url
                        elif image_url.startswith('/'):
                            from urllib.parse import urljoin
                            image_url = urljoin(page.url, image_url)
                    
                    if name and image_url:
                        product = Product(
                            title=name,
                            image_url=image_url,
                            product_url=product_url,
                            collection_name=f"Page: {page.url}",
                            collection_url=page.url,
                            confidence=0.8,
                            detection_method="simple_pattern_extraction"
                        )
                        products.append(product)
                        
                        # Queue product for immediate download
                        self._queue_product_download(product)
                
                except Exception as e:
                    print(f"⚠️ Failed to extract product {i+1}: {e}")
                    continue
            
            return products
            
        except Exception as e:
            print(f"❌ Product extraction failed: {e}")
            return []
    
    async def _find_all_page_urls(self, page: Page) -> List[str]:
        """LLM-powered pagination detection and URL extraction"""
        print("🔄 Finding all pagination URLs using LLM analysis...")
        
        try:
            # Collect comprehensive pagination data for LLM
            pagination_data = await page.evaluate("""
                () => {
                    // Get all potential pagination links
                    const links = Array.from(document.querySelectorAll('a[href]'))
                        .filter(link => {
                            const text = link.textContent.trim().toLowerCase();
                            const href = link.href;
                            // Filter for likely pagination links
                            return (
                                /page=\\d+|\\/page\\/\\d+/.test(href) ||
                                /next|prev|more|load/.test(text) ||
                                /^\\d+$/.test(text) ||
                                text.includes('»') || text.includes('«') ||
                                text.includes('>')  || text.includes('<')
                            );
                        })
                        .map(link => ({
                            text: link.textContent.trim(),
                            href: link.href,
                            classes: link.className,
                            parent_text: link.parentElement?.textContent?.trim()
                        }));
                    
                    // Get pagination container HTML
                    const paginationContainers = document.querySelectorAll(
                        '.pagination, .pager, .page-nav, [class*="page"], [class*="pagination"]'
                    );
                    const paginationHTML = Array.from(paginationContainers)
                        .map(el => el.outerHTML)
                        .join('\\n');
                    
                    // Get current page indicators
                    const currentPageIndicators = document.querySelectorAll(
                        '.current, .active, [aria-current="page"], .selected'
                    );
                    
                    return {
                        links: links,
                        pagination_html: paginationHTML.slice(0, 3000), // Limit size
                        current_indicators: Array.from(currentPageIndicators).map(el => el.textContent.trim()),
                        total_links_found: links.length,
                        page_url: window.location.href
                    };
                }
            """)
            
            # Ask LLM to analyze pagination type and strategy
            import json
            
            prompt = f"""
Analyze this webpage's pagination system and determine how to get ALL products.

Current URL: {page.url}
Found {pagination_data['total_links_found']} potential pagination links:
{json.dumps(pagination_data['links'][:10], indent=2)}

Pagination HTML context:
{pagination_data['pagination_html']}

Current page indicators: {pagination_data['current_indicators']}

CRITICAL PAGE CHECK: 
- If the current URL contains "page=" parameter and it's NOT page=1 (like page=2, page=3, etc.), return NO_PAGINATION immediately
- Only look for more pages if we are on the first page (page=1 or no page parameter)

Determine the navigation strategy:

1. **PAGE_NUMBERS**: Site shows numbered pages (2, 3, 4...) - return URLs for pages 2 onwards
2. **NEXT_ONLY**: Site only has Next/Load More - return the next page URL  
3. **NO_PAGINATION**: This is the only page OR we are already on page 2+ 
4. **INFINITE_SCROLL**: Content loads by scrolling only

Return JSON:
{{
    "strategy": "PAGE_NUMBERS" | "NEXT_ONLY" | "NO_PAGINATION" | "INFINITE_SCROLL",
    "urls": ["url1", "url2", "url3"], // URLs to visit (exclude page 1)
    "reasoning": "brief explanation"
}}

For PAGE_NUMBERS: Include ALL page URLs found (2, 3, 4, 5...) BUT ONLY if we're on page 1
For NEXT_ONLY: Include only the immediate next page URL BUT ONLY if we're on page 1
For NO_PAGINATION/INFINITE_SCROLL: Return empty urls array

Only respond with valid JSON.
""".strip()
            
            response = await self._ask_smart_llm(prompt)
            result = self._parse_json_response(response)
            
            strategy = result.get('strategy', 'NO_PAGINATION')
            urls = result.get('urls', [])
            reasoning = result.get('reasoning', 'No reasoning provided')
            
            print(f"🤖 LLM pagination strategy: {strategy}")
            print(f"   💭 Reasoning: {reasoning}")
            
            if strategy == "INFINITE_SCROLL":
                return ["INFINITE_SCROLL"]
            elif urls:
                print(f"📄 Found {len(urls)} pagination URLs:")
                for i, url in enumerate(urls[:5], 1):  # Show first 5
                    print(f"   {i}. {url}")
                if len(urls) > 5:
                    print(f"   ... and {len(urls) - 5} more")
                return urls
            else:
                print("✅ No pagination URLs found")
                return []
                
        except Exception as e:
            print(f"❌ LLM pagination analysis failed: {e}")
            return []
    
    async def _check_infinite_scroll(self, page: Page) -> bool:
        """Check if the page has infinite scroll by scrolling and seeing if more content loads"""
        try:
            print("   🔍 Testing for infinite scroll...")
            
            # Get initial product count
            initial_count = await page.evaluate("""
                () => {
                    const containers = document.querySelectorAll('x-cell[prod-instock], .product-item, .product-card, [data-product], .grid-item');
                    return containers.length;
                }
            """)
            
            if initial_count == 0:
                return False
            
            # Scroll to bottom
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            
            # Wait a bit for content to load
            await page.wait_for_timeout(2000)
            
            # Check if more products loaded
            final_count = await page.evaluate("""
                () => {
                    const containers = document.querySelectorAll('x-cell[prod-instock], .product-item, .product-card, [data-product], .grid-item');
                    return containers.length;
                }
            """)
            
            if final_count > initial_count:
                print(f"   ✅ Infinite scroll detected: {initial_count} -> {final_count} products")
                # Scroll back to top for consistent extraction
                await page.evaluate("window.scrollTo(0, 0)")
                await page.wait_for_timeout(1000)
                return True
            else:
                print(f"   ❌ No infinite scroll: {initial_count} products remained the same")
                return False
                
        except Exception as e:
            print(f"   ❌ Infinite scroll check failed: {e}")
            return False
    
    async def _check_infinite_scroll_with_pattern(self, page: Page, pattern: Dict[str, str]) -> Tuple[bool, List[Product]]:
        """Aggressive infinite scroll detection that extracts products during scroll"""
        try:
            print("   🔍 Testing for infinite scroll with product pattern...")
            
            container_selector = pattern.get('container_selector')
            if not container_selector:
                return False, []
            
            # Extract initial products using actual product extraction
            initial_products = await self._extract_products_using_pattern(page, pattern)
            initial_count = len(initial_products)
            
            if initial_count == 0:
                return False, []
            
            print(f"   📊 Initial product count: {initial_count}")
            
            # SIMPLE AGGRESSIVE SCROLLING - extract products as we find them
            max_attempts = 20  # Allow more attempts
            all_products = initial_products[:]  # Copy initial products
            current_count = initial_count
            no_new_products_count = 0
            
            for attempt in range(max_attempts):
                print(f"   🔄 Scroll attempt {attempt + 1}/{max_attempts}")
                
                # Just scroll to the bottom
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                
                # Wait for content to load
                await page.wait_for_timeout(3000)  # Wait longer for load
                
                # Extract all current products
                current_products = await self._extract_products_using_pattern(page, pattern)
                new_count = len(current_products)
                
                if new_count > current_count:
                    # Add only the new products (avoid duplicates)
                    new_products = current_products[current_count:]
                    all_products.extend(new_products)
                    print(f"   ✅ Found {new_count - current_count} new products (total: {new_count})")
                    current_count = new_count
                    no_new_products_count = 0  # Reset counter
                else:
                    no_new_products_count += 1
                    print(f"   ⏸️ No new products found (attempt {no_new_products_count}/3)")
                    
                    if no_new_products_count >= 3:
                        print("   🛑 No new products after 3 attempts - stopping")
                        break
                
                # Try clicking any "Load More" buttons as fallback
                load_more_clicked = await page.evaluate("""
                    () => {
                        const loadMoreTexts = ['loading more', 'load more', 'show more', 'view more'];
                        const allButtons = [...document.querySelectorAll('a[href], button')];
                        
                        for (const btn of allButtons) {
                            const text = btn.textContent.trim().toLowerCase();
                            if (loadMoreTexts.some(t => text.includes(t))) {
                                btn.click();
                                return true;
                            }
                        }
                        return false;
                    }
                """)
                
                if load_more_clicked:
                    print(f"   📜 Used scroll strategy in attempt {attempt + 1}")
                
                # Wait for lazy loading
                await page.wait_for_timeout(4000)
            
            # Success if we found more products
            if len(all_products) > initial_count:
                print(f"   ✅ AGGRESSIVE SCROLL SUCCESS: {initial_count} -> {len(all_products)} products (+{len(all_products) - initial_count})")
                print(f"   📦 Used scroll strategy in attempt {attempt + 1}")
                # Scroll back to top for consistent extraction
                await page.evaluate("window.scrollTo(0, 0)")
                await page.wait_for_timeout(1000)
                return True, all_products
            else:
                print(f"   ❌ No infinite scroll detected after {max_attempts} attempts")
                return False, initial_products
                
        except Exception as e:
            print(f"   ❌ Infinite scroll pattern check failed: {e}")
            return False, []
    
    async def _extract_from_pagination_pages(self, page_urls: List[str], pattern: Dict[str, str], visited_urls: set = None, page1_has_scroll: bool = False) -> List[Product]:
        """Extract products from pagination pages or handle infinite scroll"""
        
        # Initialize visited set if not provided
        if visited_urls is None:
            visited_urls = set()
        
        # Check for infinite scroll marker
        if page_urls == ["INFINITE_SCROLL"]:
            print("🔄 Handling infinite scroll pagination...")
            # We need to use the same page that detected infinite scroll
            # This should be passed from the calling function
            return []  # Will be handled in the main extraction function
        
        # Normalize URLs for comparison (extract base URL and page number)
        def normalize_url(url):
            """Extract base URL and page number for comparison"""
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(url)
            base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            
            # Try to extract page number from query params
            params = parse_qs(parsed.query)
            page_num = params.get('page', ['1'])[0]  # Default to page 1
            
            return f"{base}?page={page_num}"
        
        # Filter out already visited URLs using normalized comparison
        new_urls = []
        for url in page_urls:
            normalized = normalize_url(url)
            if normalized not in visited_urls:
                new_urls.append(url)
                visited_urls.add(normalized)  # Add normalized version to visited
            else:
                print(f"   ⏭️ Skipping already visited: page={normalized.split('page=')[-1]}")
        
        if not new_urls:
            print("✅ All pagination URLs already visited")
            return []
        
        # Traditional pagination
        print(f"🚀 Processing {len(new_urls)} new pagination pages...")
        
        async def process_pagination_page(url: str) -> List[Product]:
            try:
                page = await self._load_page(url)
                
                # Use page 1's scroll behavior for all pages (per requirement #2)  
                if page1_has_scroll:
                    print(f"   🔄 Page has infinite scroll (like page 1) - loading all products...")
                    products = await self._extract_with_infinite_scroll(page, pattern)
                else:
                    # Extract normally
                    products = await self._extract_products_using_pattern(page, pattern)
                
                await page.close()
                
                print(f"✅ {url}: Found {len(products)} products")
                
                # For PAGE_NUMBERS strategy, we already have all URLs from page 1
                # Only check for more pagination if this is a NEXT_ONLY strategy
                
                return products
            except Exception as e:
                print(f"❌ Failed to process {url}: {e}")
                return []
        
        # Process all pages in parallel
        tasks = [process_pagination_page(url) for url in new_urls]
        results = await asyncio.gather(*tasks)
        
        # Combine all products
        all_products = []
        for products in results:
            all_products.extend(products)
        
        print(f"🎉 Pagination complete: {len(all_products)} products from {len(page_urls)} pages")
        return all_products
    
    async def _extract_with_infinite_scroll(self, page: Page, pattern: Dict[str, str]) -> List[Product]:
        """Extract all products by scrolling through infinite scroll"""
        all_products = []
        previous_count = 0
        max_scrolls = 20  # Prevent infinite loops
        scroll_attempts = 0
        
        print("🔄 Starting infinite scroll extraction...")
        
        while scroll_attempts < max_scrolls:
            # Extract products from current state
            current_products = await self._extract_products_using_pattern(page, pattern)
            current_count = len(current_products)
            
            print(f"   📦 Scroll {scroll_attempts + 1}: Found {current_count} products")
            
            # If no new products loaded, we're done
            if current_count <= previous_count:
                print(f"   ✅ No new products loaded, stopping")
                break
            
            # Update our collection (only add new ones)
            if current_count > previous_count:
                # Add only the new products (avoid duplicates)
                new_products = current_products[previous_count:]
                all_products.extend(new_products)
                print(f"   ➕ Added {len(new_products)} new products")
                
                # Queue new products for download immediately
                for product in new_products:
                    self._queue_product_download(product)
            
            previous_count = current_count
            
            # Scroll down to load more
            print(f"   ⬇️ Scrolling to load more products...")
            await page.evaluate("""
                () => {
                    window.scrollTo(0, document.body.scrollHeight);
                    // Also try scrolling the main container
                    const containers = document.querySelectorAll('.products, .collection, .grid, main');
                    containers.forEach(container => {
                        container.scrollTop = container.scrollHeight;
                    });
                }
            """)
            
            # Wait for new content to load
            await page.wait_for_timeout(3000)
            
            scroll_attempts += 1
        
        if scroll_attempts >= max_scrolls:
            print(f"   ⚠️ Reached maximum scroll limit ({max_scrolls})")
        
        print(f"🎉 Infinite scroll complete: {len(all_products)} total products")
        return all_products
    
    # ===========================================
    # HTML PROCESSING HELPERS
    # ===========================================
    
    def _extract_clean_body_html(self, html_content: str) -> str:
        """
        Extract clean body HTML for LLM analysis - SIMPLE VERSION
        
        This replaced the complex grid extraction that was finding 20+ separate sections
        and confusing the LLM. Now just removes scripts/styles and uses middle content.
        """
        import re
        
        print("🧹 Extracting clean body HTML (simple approach)...")
        
        # Remove scripts and styles
        content = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        content = re.sub(r'<style[^>]*>.*?</style>', '', content, flags=re.DOTALL | re.IGNORECASE)
        
        # Extract body content
        body_match = re.search(r'<body[^>]*>(.*?)</body>', content, re.DOTALL | re.IGNORECASE)
        if body_match:
            body_content = body_match.group(1)
            
            # Skip header and footer sections, focus on main content
            lines = body_content.split('\n')
            # Use middle 60% of content (skip first 20% and last 20%)
            start_idx = len(lines) // 5  
            end_idx = 4 * len(lines) // 5
            middle_content = '\n'.join(lines[start_idx:end_idx])
            
            # Limit to reasonable size for LLM
            if len(middle_content) > 25000:
                middle_content = middle_content[:25000]
            
            print(f"✅ Simple extraction complete: {len(middle_content)} chars (no grid complexity)")
            return middle_content
        
        # Fallback to full content (cleaned)
        content = content[:25000] if len(content) > 25000 else content
        print(f"⚠️ Using full cleaned content: {len(content)} chars")
        return content
    
    
    # ===========================================
    # LLM HELPERS
    # ===========================================
    
    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """Parse JSON from LLM response with robust error handling"""
        response = response.strip()
        
        # Try direct parsing first
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass
        
        # Try to find JSON in the response
        import re
        
        # Look for JSON object with proper nesting
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass
        
        # Look for JSON array
        array_match = re.search(r'\[.*\]', response, re.DOTALL)
        if array_match:
            try:
                return json.loads(array_match.group(0))
            except json.JSONDecodeError:
                pass
        
        return {}
    
    async def _ask_llm(self, prompt: str) -> str:
        """Ask the fast LLM a question"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.llm.generate,
            prompt,
            500,  # max_tokens
            0.1   # temperature
        )
    
    async def _ask_smart_llm(self, prompt: str) -> str:
        """Ask the smart LLM a question"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.smart_llm.generate,
            prompt,
            1000,  # max_tokens
            0.1    # temperature
        )


# ===========================================
# ASYNC GENERATOR FOR STREAMING
# ===========================================

class SimpleLLMScraperStreaming(SimpleLLMScraper):
    """Streaming version for real-time updates"""
    
    async def scrape_brand_products(self, brand_id: int, collection_url: str = None):
        """Stream scraping progress for the API"""
        try:
            url = collection_url or "https://example.com"  # This should come from brand data
            
            yield {"status": "starting", "message": f"Starting simple scraping of {url}"}
            
            result = await self.scrape(url)
            
            if result.success:
                yield {
                    "status": "completed",
                    "message": f"Scraping completed successfully",
                    "products_found": result.total_found,
                    "strategy": result.strategy_used,
                    "confidence": result.confidence
                }
            else:
                yield {
                    "status": "failed", 
                    "message": f"Scraping failed: {'; '.join(result.errors)}",
                    "products_found": 0
                }
                
        except Exception as e:
            yield {"status": "error", "message": f"Scraper error: {str(e)}"}


if __name__ == "__main__":
    # Test the scraper
    async def test():
        scraper = SimpleLLMScraper()
        result = await scraper.scrape("https://iconaclub.com/")
        print(f"Final result: {result.total_found} products")
    
    asyncio.run(test())