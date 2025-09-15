#!/usr/bin/env python3
"""
Streaming Parallel Fashion Brand Scraper
========================================

Triple-parallel architecture:
1. Discovery Stream: Continuous product discovery (scrolling/pagination)
2. LLM Analysis Stream: Background pattern analysis
3. Download Stream: Immediate image downloads

Race-condition safe with proper coordination.
"""

import asyncio
import json
import os
import sys
from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass, field
from playwright.async_api import async_playwright, Browser, Page
import concurrent.futures
from urllib.parse import urljoin, urlparse
import time
import threading
import io

# Add parent directories to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from llm_interface import ClaudeInterface

@dataclass
class StreamingProduct:
    """Product with streaming metadata"""
    title: str
    image_url: str
    product_url: Optional[str] = None
    confidence: float = 0.8
    detection_method: str = "streaming_scraper"
    collection_name: Optional[str] = None
    collection_url: Optional[str] = None
    discovery_time: float = field(default_factory=time.time)
    download_started: bool = False
    download_completed: bool = False
    download_path: Optional[str] = None

@dataclass
class StreamingResult:
    """Result with streaming statistics"""
    success: bool
    products: List[StreamingProduct]
    total_discovered: int
    total_downloaded: int
    discovery_time: float
    download_time: float
    llm_analysis_time: float
    errors: List[str] = field(default_factory=list)

class ThreadSafeProductCollector:
    """Thread-safe product collection with deduplication"""
    
    def __init__(self):
        self._products: Dict[str, StreamingProduct] = {}
        self._seen_urls: Set[str] = set()
        self._lock = asyncio.Lock()
        self._download_queue = asyncio.Queue()
        self._discovery_complete = False
        self._downloads_complete = False
    
    async def add_product(self, product: StreamingProduct) -> bool:
        """Add product if not seen before. Returns True if added."""
        async with self._lock:
            # Use image URL as unique identifier
            unique_key = product.image_url
            
            if unique_key not in self._seen_urls:
                self._seen_urls.add(unique_key)
                self._products[unique_key] = product
                await self._download_queue.put(product)
                return True
            return False
    
    async def get_products(self) -> List[StreamingProduct]:
        """Get all discovered products"""
        async with self._lock:
            return list(self._products.values())
    
    async def mark_discovery_complete(self):
        """Mark discovery phase as complete"""
        async with self._lock:
            self._discovery_complete = True
    
    async def mark_downloads_complete(self):
        """Mark download phase as complete"""
        async with self._lock:
            self._downloads_complete = True
    
    async def is_complete(self) -> bool:
        """Check if both discovery and downloads are complete"""
        async with self._lock:
            return self._discovery_complete and self._downloads_complete
    
    def get_download_queue(self) -> asyncio.Queue:
        """Get the download queue for workers"""
        return self._download_queue

class StreamingLLMScraper:
    """Streaming parallel fashion brand scraper"""
    
    def __init__(self):
        # LLM clients
        self.fast_llm = ClaudeInterface(model="claude-3-haiku-20240307")  # Fast decisions
        self.smart_llm = ClaudeInterface(model="claude-3-5-sonnet-20241022")  # Deep analysis
        
        # Browser management
        self.browser: Optional[Browser] = None
        self.playwright = None
        
        # Streaming coordination
        self.collector = ThreadSafeProductCollector()
        self.download_workers: List[asyncio.Task] = []
        self.llm_workers: List[asyncio.Task] = []
        
        # Statistics
        self.start_time = 0
        self.discovery_start_time = 0
        self.download_start_time = 0
        self.llm_start_time = 0
    
    async def __aenter__(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
    
    # ==========================================
    # MAIN STREAMING SCRAPER INTERFACE
    # ==========================================
    
    async def scrape(self, url: str) -> StreamingResult:
        """Main streaming scrape method"""
        self.start_time = time.time()
        print(f"🚀 Starting STREAMING scraping of: {url}")
        
        try:
            # Phase 1: Start download workers immediately
            self.download_start_time = time.time()
            await self._start_download_workers()
            
            # Phase 2: Start discovery stream
            self.discovery_start_time = time.time()
            discovery_task = asyncio.create_task(self._discovery_stream(url))
            
            # Phase 3: Start LLM analysis stream (runs in background)
            self.llm_start_time = time.time()
            # LLM analysis will be triggered as needed during discovery
            
            # Wait for discovery to complete
            await discovery_task
            await self.collector.mark_discovery_complete()
            print("✅ Discovery stream complete")
            
            # Wait for downloads to complete
            await self._wait_for_downloads()
            await self.collector.mark_downloads_complete()
            print("✅ Download stream complete")
            
            # Collect results
            products = await self.collector.get_products()
            total_time = time.time() - self.start_time
            
            return StreamingResult(
                success=True,
                products=products,
                total_discovered=len(products),
                total_downloaded=sum(1 for p in products if p.download_completed),
                discovery_time=time.time() - self.discovery_start_time,
                download_time=time.time() - self.download_start_time,
                llm_analysis_time=time.time() - self.llm_start_time
            )
        
        except Exception as e:
            print(f"❌ Streaming scrape error: {e}")
            products = await self.collector.get_products()
            return StreamingResult(
                success=False,
                products=products,
                total_discovered=len(products),
                total_downloaded=sum(1 for p in products if p.download_completed),
                discovery_time=time.time() - self.discovery_start_time,
                download_time=time.time() - self.download_start_time, 
                llm_analysis_time=time.time() - self.llm_start_time,
                errors=[str(e)]
            )
    
    # ==========================================
    # DISCOVERY STREAM (Main Thread)
    # ==========================================
    
    async def _discovery_stream(self, url: str):
        """Main discovery stream - finds products and streams them to queue"""
        page = await self.browser.new_page()
        
        try:
            # Load initial page
            print(f"🌐 Loading: {url}")
            await page.goto(url, timeout=60000)
            await page.wait_for_load_state('domcontentloaded')
            print("✅ Page loaded")
            
            # Check if this is a products page or homepage
            is_products_page = await self._is_products_page(page)
            
            if is_products_page:
                print("✅ This IS a products page - extracting products...")
                # Phase 1: Basic product discovery (immediate)
                print("📦 Phase 1: Basic discovery with fallback selectors")
                await self._basic_discovery(page)
                
                # Phase 2: Enhanced discovery with scrolling and pagination
                print("📦 Phase 2: Enhanced discovery with scrolling")
                await self._enhanced_discovery(page)
            else:
                print("❌ This is NOT a products page - finding product pages...")
                # Find collections/product pages and scrape them
                await self._find_and_scrape_product_pages(page)
            
        finally:
            await page.close()
    
    async def _basic_discovery(self, page: Page):
        """Immediate basic discovery using common selectors"""
        # Known patterns for fast discovery
        basic_patterns = [
            {
                "container_selector": "x-cell[class][prod-instock]",  # iconaclub.com pattern (working selector)
                "image_selector": ".card-image img",
                "name_selector": ".card-title h2 a"
            },
            {
                "container_selector": ".collection-item",
                "image_selector": "img[data-widths], img",
                "name_selector": ".custom-card-title, h3, .product-title, .title"
            },
            {
                "container_selector": ".product-card",
                "image_selector": "img",
                "name_selector": ".product-title, .card-title, h2, h3"
            },
            {
                "container_selector": ".product-item",
                "image_selector": "img",
                "name_selector": ".title, .name, h2, h3"
            },
            {
                "container_selector": "[data-product], .grid-item",
                "image_selector": "img",
                "name_selector": "h2, h3, .title, .name"
            }
        ]
        
        for pattern in basic_patterns:
            containers = await page.query_selector_all(pattern["container_selector"])
            if len(containers) > 0:
                print(f"🎯 Basic discovery: Found {len(containers)} products with {pattern['container_selector']}")
                products = await self._extract_products_from_containers(page, containers, pattern)
                await self._stream_products(products, "basic_discovery")
                return  # Use first working pattern
        
        print("⚠️ Basic discovery found no products - continuing with enhanced discovery")
    
    async def _enhanced_discovery(self, page: Page):
        """Enhanced discovery with scrolling and pattern analysis"""
        # Start LLM analysis in background
        html_content = await page.content()
        llm_task = asyncio.create_task(self._analyze_patterns_async(html_content, page.url))
        
        # Continue with scrolling while LLM analyzes
        await self._scroll_and_discover(page, llm_task)
    
    async def _scroll_and_discover(self, page: Page, llm_task: asyncio.Task):
        """Scroll and discover products while LLM analysis runs in background"""
        max_scrolls = 20
        no_new_products = 0
        last_product_count = len(await self.collector.get_products())
        
        for scroll_attempt in range(max_scrolls):
            print(f"🔄 Scroll {scroll_attempt + 1}/{max_scrolls}")
            
            # Scroll down
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(3000)  # Wait for content to load
            
            # Try to get better selectors from LLM if ready
            pattern = None
            if llm_task.done():
                try:
                    pattern = llm_task.result()
                    print("🧠 Using LLM-enhanced pattern")
                except Exception as e:
                    print(f"⚠️ LLM analysis failed: {e}")
            
            # Extract new products
            if pattern:
                await self._extract_with_pattern(page, pattern)
            else:
                await self._extract_with_basic_selectors(page)
            
            # Check if we found new products
            current_product_count = len(await self.collector.get_products())
            if current_product_count > last_product_count:
                print(f"✅ Found {current_product_count - last_product_count} new products (total: {current_product_count})")
                last_product_count = current_product_count
                no_new_products = 0
            else:
                no_new_products += 1
                print(f"⏸️ No new products (attempt {no_new_products}/3)")
                
                if no_new_products >= 3:
                    print("🛑 No new products after 3 attempts - stopping scroll")
                    break
    
    # ==========================================
    # PRODUCT EXTRACTION
    # ==========================================
    
    async def _extract_products_from_containers(self, page: Page, containers: List, pattern: Dict[str, str]) -> List[StreamingProduct]:
        """Extract products from container elements"""
        products = []
        
        for i, container in enumerate(containers[:50]):  # Limit batch size
            try:
                # Extract name
                name = f"Product {i+1}"  # Default fallback
                name_selector = pattern.get("name_selector", "h2, h3, .title")
                name_elem = await container.query_selector(name_selector)
                if name_elem:
                    name_text = await name_elem.inner_text()
                    if name_text and name_text.strip():
                        name = name_text.strip()
                
                # Extract image
                image_url = ""
                image_selector = pattern.get("image_selector", "img")
                img_elem = await container.query_selector(image_selector)
                if img_elem:
                    src = await img_elem.get_attribute('src')
                    data_src = await img_elem.get_attribute('data-src')
                    image_url = src or data_src or ""
                
                # Fix image URL
                if image_url and not image_url.startswith('http'):
                    if image_url.startswith('//'):
                        image_url = 'https:' + image_url
                    elif image_url.startswith('/'):
                        image_url = urljoin(page.url, image_url)
                
                # Extract product link
                product_url = page.url
                link_elem = await container.query_selector('a[href]')
                if link_elem:
                    href = await link_elem.get_attribute('href')
                    if href:
                        if href.startswith('/'):
                            product_url = urljoin(page.url, href)
                        else:
                            product_url = href
                
                if name and image_url:
                    products.append(StreamingProduct(
                        title=name,
                        image_url=image_url,
                        product_url=product_url,
                        collection_name=f"Page: {page.url}",
                        collection_url=page.url,
                        confidence=0.8,
                        detection_method="streaming_basic"
                    ))
            
            except Exception as e:
                print(f"⚠️ Error extracting product {i}: {e}")
                continue
        
        return products
    
    async def _extract_with_pattern(self, page: Page, pattern: Dict[str, str]):
        """Extract products using LLM-provided pattern"""
        container_selector = pattern.get("container_selector", ".product-card")
        containers = await page.query_selector_all(container_selector)
        
        if containers:
            products = await self._extract_products_from_containers(page, containers, pattern)
            await self._stream_products(products, "llm_enhanced")
    
    async def _extract_with_basic_selectors(self, page: Page):
        """Extract with basic fallback selectors"""
        basic_selectors = ["x-cell[prod-instock], x-cell[prod-outstock]", ".collection-item", ".product-card", ".product-item", ".grid-item"]
        
        for selector in basic_selectors:
            containers = await page.query_selector_all(selector)
            if containers:
                pattern = {
                    "container_selector": selector,
                    "image_selector": "img",
                    "name_selector": "h2, h3, .title, .name"
                }
                products = await self._extract_products_from_containers(page, containers, pattern)
                if products:
                    await self._stream_products(products, "fallback")
                    break
    
    async def _stream_products(self, products: List[StreamingProduct], method: str):
        """Stream products to download queue"""
        added_count = 0
        for product in products:
            product.detection_method = method
            was_added = await self.collector.add_product(product)
            if was_added:
                added_count += 1
        
        if added_count > 0:
            print(f"📤 Streamed {added_count} new products ({method})")
    
    # ==========================================
    # PAGE TYPE DETECTION
    # ==========================================
    
    async def _is_products_page(self, page: Page) -> bool:
        """Check if this page has products on it"""
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
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                self.fast_llm.generate,
                prompt,
                200,
                0.1
            )
            
            # Parse response
            response = response.strip()
            if response.startswith('{'):
                result = json.loads(response)
                has_products = result.get('has_products', False)
                confidence = result.get('confidence', 0.0)
                reasoning = result.get('reasoning', 'No reasoning provided')
                
                print(f"🤖 LLM says: {'YES' if has_products else 'NO'} (confidence: {confidence:.2f})")
                print(f"   Reasoning: {reasoning}")
                
                return has_products and confidence > 0.5
        except Exception as e:
            print(f"⚠️ Error in products page detection: {e}")
        
        return False  # Default to assuming it's not a products page
    
    async def _find_and_scrape_product_pages(self, page: Page):
        """Find product/collections pages and scrape them"""
        print("🔍 Finding product pages...")
        
        # Look for collections/products links
        collections_urls = await self._find_collections_urls(page)
        
        print(f"📋 Found {len(collections_urls)} product page URLs:")
        for i, url in enumerate(collections_urls):
            print(f"   {i+1}. {url}")
        
        # Scrape each collections page
        for url in collections_urls:
            await self._scrape_collections_page(url)
    
    async def _find_collections_urls(self, page: Page) -> List[str]:
        """Find collections/products page URLs"""
        # Look for common patterns
        collections_urls = await page.evaluate("""
            () => {
                const links = document.querySelectorAll('a[href]');
                const collections = [];
                
                for (const link of links) {
                    const href = link.href;
                    const text = link.textContent.toLowerCase();
                    
                    // Look for collections, shop, products pages
                    if (href.includes('/collections/') || 
                        href.includes('/products') ||
                        href.includes('/shop') ||
                        text.includes('shop') ||
                        text.includes('products') ||
                        text.includes('collection')) {
                        
                        // Avoid duplicates
                        if (!collections.includes(href)) {
                            collections.push(href);
                        }
                    }
                }
                
                return collections;
            }
        """)
        
        # Filter to most likely collections page
        filtered_urls = []
        for url in collections_urls:
            if '/collections/all' in url or '/collections' in url:
                filtered_urls.append(url)
        
        # If no collections found, try shop pages
        if not filtered_urls:
            for url in collections_urls:
                if '/shop' in url or '/products' in url:
                    filtered_urls.append(url)
        
        return filtered_urls[:3]  # Limit to 3 pages max
    
    async def _scrape_collections_page(self, url: str):
        """Scrape a specific collections page"""
        collections_page = await self.browser.new_page()
        try:
            print(f"🌐 Loading collections page: {url}")
            await collections_page.goto(url, timeout=60000)
            await collections_page.wait_for_load_state('domcontentloaded')
            print("✅ Collections page loaded")
            
            # Basic discovery on this page
            await self._basic_discovery(collections_page)
            
            # Enhanced discovery with scrolling
            await self._enhanced_discovery(collections_page)
            
            # Look for pagination on this page
            await self._discover_and_scrape_pagination(collections_page)
            
        finally:
            await collections_page.close()
    
    async def _discover_and_scrape_pagination(self, page: Page):
        """Discover and scrape pagination pages"""
        # Look for pagination links
        pagination_urls = await page.evaluate("""
            () => {
                const links = document.querySelectorAll('a[href]');
                const pages = [];
                
                for (const link of links) {
                    const href = link.href;
                    const text = link.textContent.trim();
                    
                    // Look for page numbers or next buttons
                    if (href.includes('page=') || 
                        text.match(/^\\d+$/) || 
                        text.includes('Next') ||
                        text.includes('next')) {
                        
                        if (!pages.includes(href)) {
                            pages.push(href);
                        }
                    }
                }
                
                return pages;
            }
        """)
        
        if pagination_urls:
            print(f"📄 Found {len(pagination_urls)} pagination URLs")
            
            # Scrape pagination pages in parallel (limit to 5)
            for url in pagination_urls[:5]:
                await self._scrape_collections_page(url)

    # ==========================================
    # LLM ANALYSIS STREAM (Background)
    # ==========================================
    
    async def _analyze_patterns_async(self, html_content: str, url: str) -> Optional[Dict[str, str]]:
        """Background LLM pattern analysis"""
        try:
            print("🧠 Starting background LLM pattern analysis...")
            
            # Extract relevant HTML sections
            relevant_html = self._extract_clean_html(html_content)[:15000]  # Limit size
            
            prompt = f"""
Analyze this e-commerce page and identify the MAIN PRODUCT containers.

URL: {url}
HTML: {relevant_html}

Find the CSS selector for actual product containers (not navigation menus).

Look for patterns like:
- .product-card, .product-item, .collection-item
- div[data-product], .grid-item
- NOT .submenu-item, .nav-item, .menu-item

Return ONLY this JSON object with no other text:
{{
    "container_selector": "CSS selector for product containers",
    "image_selector": "img selector within container", 
    "name_selector": "selector for product name",
    "confidence": 0.0-1.0
}}

CRITICAL: Respond with ONLY the JSON object, no explanation or other text.
"""
            
            # Use executor to run in thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                self.smart_llm.generate,
                prompt,
                500,  # max_tokens
                0.1   # temperature
            )
            
            # Parse response with robust JSON extraction
            response = response.strip()
            
            # Try direct parsing first
            try:
                if response.startswith('{'):
                    pattern = json.loads(response)
                    # Default confidence to 0.7 if not provided but we got selectors
                    if 'container_selector' in pattern and 'confidence' not in pattern:
                        pattern['confidence'] = 0.7
                    confidence = pattern.get('confidence', 0.0)
                    if confidence > 0.5 or 'container_selector' in pattern:
                        print(f"🧠 LLM pattern analysis complete (confidence: {confidence:.2f})")
                        return pattern
            except json.JSONDecodeError:
                pass  # Try extraction methods below
            
            # Extract JSON from response if not clean
            import re
            
            # Method 1: Find JSON object with regex
            json_patterns = [
                r'\{[^{}]*"container_selector"[^{}]*\}',  # Find object with container_selector
                r'\{.*?\}(?=\s*$)',  # JSON object at end
                r'\{.*?\}',  # Any JSON object
            ]
            
            for pattern_regex in json_patterns:
                json_match = re.search(pattern_regex, response, re.DOTALL)
                if json_match:
                    try:
                        pattern = json.loads(json_match.group(0))
                        # Default confidence to 0.7 if not provided but we got selectors
                        if 'container_selector' in pattern and 'confidence' not in pattern:
                            pattern['confidence'] = 0.7
                        confidence = pattern.get('confidence', 0.0)
                        if confidence > 0.5 or 'container_selector' in pattern:
                            print(f"🧠 LLM pattern analysis complete (confidence: {confidence:.2f})")
                            return pattern
                    except json.JSONDecodeError:
                        continue
            
            # Method 2: Clean up common issues
            if '{' in response:
                # Extract from first { to last }
                start = response.find('{')
                end = response.rfind('}')
                if start != -1 and end != -1 and end > start:
                    try:
                        json_str = response[start:end+1]
                        pattern = json.loads(json_str)
                        # Default confidence to 0.7 if not provided but we got selectors
                        if 'container_selector' in pattern and 'confidence' not in pattern:
                            pattern['confidence'] = 0.7
                        confidence = pattern.get('confidence', 0.0)
                        if confidence > 0.5 or 'container_selector' in pattern:
                            print(f"🧠 LLM pattern analysis complete (confidence: {confidence:.2f})")
                            return pattern
                    except json.JSONDecodeError:
                        pass
            
            print("⚠️ LLM pattern analysis returned unparseable or low confidence result")
            return None
            
        except Exception as e:
            print(f"⚠️ LLM pattern analysis failed: {e}")
            return None
    
    def _extract_clean_html(self, html_content: str) -> str:
        """Extract clean HTML for analysis"""
        import re
        
        # Remove scripts and styles
        html_content = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        html_content = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        
        # Extract main content area
        body_match = re.search(r'<body[^>]*>(.*)</body>', html_content, re.DOTALL | re.IGNORECASE)
        if body_match:
            return body_match.group(1)
        
        return html_content
    
    # ==========================================
    # DOWNLOAD STREAM (Background Workers)
    # ==========================================
    
    async def _start_download_workers(self):
        """Start download worker pool"""
        num_workers = 8  # Parallel download workers
        print(f"🏭 Starting {num_workers} download workers")
        
        for i in range(num_workers):
            worker = asyncio.create_task(self._download_worker(f"worker-{i}"))
            self.download_workers.append(worker)
    
    async def _download_worker(self, worker_name: str):
        """Download worker that continuously processes queue"""
        download_queue = self.collector.get_download_queue()
        
        while True:
            try:
                # Wait for product with timeout
                product = await asyncio.wait_for(download_queue.get(), timeout=5.0)
                
                # Mark as started
                product.download_started = True
                print(f"⬇️ {worker_name}: Downloading {product.title[:30]}...")
                
                # Download the image (placeholder - integrate with existing download system)
                download_path = await self._download_image(product)
                
                if download_path:
                    product.download_completed = True
                    product.download_path = download_path
                    print(f"✅ {worker_name}: Downloaded {product.title[:30]}")
                else:
                    print(f"❌ {worker_name}: Failed {product.title[:30]}")
                
                download_queue.task_done()
                
            except asyncio.TimeoutError:
                # No products in queue - check if discovery is complete
                if await self.collector.is_complete():
                    break
                continue
            except Exception as e:
                print(f"❌ {worker_name}: Download error: {e}")
                continue
        
        print(f"🏁 {worker_name}: Download worker complete")
    
    async def _download_image(self, product: StreamingProduct) -> Optional[str]:
        """Download product image using existing infrastructure"""
        try:
            import aiohttp
            import aiofiles
            from pathlib import Path
            from PIL import Image
            import hashlib
            import config
            
            # Create downloads directory
            downloads_path = Path(config.DOWNLOADS_DIR if hasattr(config, 'DOWNLOADS_DIR') else 'my_brands_cache')
            downloads_path.mkdir(exist_ok=True)
            
            # Generate safe filename
            safe_title = "".join(c for c in product.title if c.isalnum() or c in (' ', '-', '_')).strip()[:50]
            image_hash = hashlib.md5(product.image_url.encode()).hexdigest()[:8]
            filename = f"{safe_title}_{image_hash}.jpg"
            file_path = downloads_path / filename
            
            # Download image
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(product.image_url) as response:
                    response.raise_for_status()
                    image_data = await response.read()
                
                # Validate and save image
                try:
                    # Validate it's a real image
                    image = Image.open(io.BytesIO(image_data))
                    
                    # Convert to RGB if needed and save as JPEG
                    if image.mode in ('RGBA', 'P'):
                        image = image.convert('RGB')
                    
                    image.save(file_path, 'JPEG', quality=90, optimize=True)
                    return str(file_path)
                    
                except Exception as img_e:
                    print(f"⚠️ Image processing error for {product.title}: {img_e}")
                    # Save raw data as fallback
                    async with aiofiles.open(file_path, 'wb') as f:
                        await f.write(image_data)
                    return str(file_path)
                
        except Exception as e:
            print(f"❌ Download failed for {product.title}: {e}")
            return None
    
    async def _wait_for_downloads(self):
        """Wait for all downloads to complete"""
        print("⏳ Waiting for downloads to complete...")
        
        download_queue = self.collector.get_download_queue()
        await download_queue.join()  # Wait for all tasks to complete
        
        # Cancel workers
        for worker in self.download_workers:
            worker.cancel()
        
        await asyncio.gather(*self.download_workers, return_exceptions=True)
        print("✅ All downloads complete")

# Usage example
async def main():
    async with StreamingLLMScraper() as scraper:
        result = await scraper.scrape("https://prixworkshop.com/collections/all")
        
        print(f"\n🎉 STREAMING RESULTS:")
        print(f"✅ Total discovered: {result.total_discovered}")
        print(f"✅ Total downloaded: {result.total_downloaded}")
        print(f"⏱️ Discovery time: {result.discovery_time:.2f}s")
        print(f"⏱️ Download time: {result.download_time:.2f}s")
        print(f"⏱️ LLM analysis time: {result.llm_analysis_time:.2f}s")

if __name__ == "__main__":
    asyncio.run(main())