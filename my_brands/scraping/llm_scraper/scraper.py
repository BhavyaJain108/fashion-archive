#!/usr/bin/env python3
"""
LLM-Driven Fashion Brand Scraper
===============================

Uses LLM + Playwright to intelligently navigate and scrape fashion brands.
"""

import asyncio
import json
import sys
import os
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from playwright.async_api import async_playwright, Browser, Page
import concurrent.futures

# Add parent directories to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from .prompts import (
    get_navigation_prompt, 
    get_menu_navigation_prompt,
    get_category_links_prompt,
    get_all_products_link_prompt,
    get_product_detection_prompt,
    get_pagination_prompt
)

# Import LLM client and decision maker
from llm_interface import ClaudeInterface
from .llm_decisions import LLMDecisionMaker

@dataclass
class Product:
    """Scraped product information"""
    title: str
    image_url: str
    product_url: Optional[str] = None
    confidence: float = 0.8
    detection_method: str = "llm_scraper"
    collection_name: Optional[str] = None
    collection_url: Optional[str] = None

@dataclass
class ScrapingResult:
    """Result of scraping operation"""
    success: bool
    products: List[Product]
    total_found: int
    strategy_used: str
    confidence: float
    errors: List[str] = None

class LLMScraper:
    """LLM-driven web scraper using Playwright"""
    
    def __init__(self):
        # Use cheaper model for scraping
        self.llm = ClaudeInterface(model="claude-3-haiku-20240307")
        self.browser: Optional[Browser] = None
        self.max_parallel_categories = 3  # Limit parallel category processing
        # Initialize decision maker with the cheaper model
        self.decision_maker = LLMDecisionMaker(self.llm)
    
    def _extract_json_from_response(self, response: str):
        """Extract JSON from LLM response that might have extra text"""
        response = response.strip()
        
        # Try parsing as-is first
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass
        
        # Try to find JSON object
        json_start = response.find('{')
        json_end = response.rfind('}') + 1
        if json_start != -1 and json_end > json_start:
            json_text = response[json_start:json_end]
            return json.loads(json_text)
        
        # Try to find JSON array
        array_start = response.find('[')
        array_end = response.rfind(']') + 1
        if array_start != -1 and array_end > array_start:
            json_text = response[array_start:array_end]
            return json.loads(json_text)
        
        # If it's just a quoted string, handle it
        if response.startswith('"') and response.endswith('"'):
            return json.loads(response)
        
        raise json.JSONDecodeError("No valid JSON found", response, 0)
    
    async def scrape(self, url: str) -> ScrapingResult:
        """Main scraping entry point"""
        print(f"🤖 Starting LLM scraping of: {url}")
        
        async with async_playwright() as p:
            # Launch browser (headless=True for production)
            self.browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-dev-shm-usage']
            )
            
            try:
                all_products = []
                errors = []
                
                # Navigate through the site
                products, scrape_errors = await self._navigate_and_scrape(url)
                all_products.extend(products)
                errors.extend(scrape_errors)
                
                return ScrapingResult(
                    success=len(all_products) > 0,
                    products=all_products,
                    total_found=len(all_products),
                    strategy_used="llm_driven_playwright",
                    confidence=0.9 if all_products else 0.1,
                    errors=errors
                )
                
            except Exception as e:
                print(f"❌ LLM scraping failed: {e}")
                return ScrapingResult(
                    success=False,
                    products=[],
                    total_found=0,
                    strategy_used="llm_driven_playwright",
                    confidence=0.0,
                    errors=[str(e)]
                )
            finally:
                await self.browser.close()
    
    async def _navigate_and_scrape(self, url: str) -> Tuple[List[Product], List[str]]:
        """Navigate through site structure and scrape products"""
        errors = []
        all_products = []
        
        # Step 1: Load homepage and analyze
        print("🔍 Step 1: Loading homepage...")
        page = await self.browser.new_page()
        print(f"🌐 Navigating to: {url}")
        await page.goto(url, timeout=60000)
        print("⏳ Waiting for page to load...")
        try:
            await page.wait_for_load_state('networkidle', timeout=10000)
            print("✅ Page loaded (networkidle)")
        except:
            print("⚠️ Networkidle timeout, trying domcontentloaded...")
            await page.wait_for_load_state('domcontentloaded')
            print("✅ Page loaded (domcontentloaded)")
        
        html_content = await page.content()
        
        # Step 2: Get navigation strategy from LLM
        print("🔍 Step 2: Getting navigation strategy from LLM...")
        nav_strategy = await self._get_navigation_strategy(html_content, url)
        print(f"🎯 Navigation strategy: {nav_strategy}")
        
        # Step 3: Execute navigation strategy
        initial_product_pages = []
        
        if nav_strategy == "menu":
            initial_product_pages = await self._handle_menu_navigation(page)
        elif nav_strategy == "all_products_link":
            initial_product_pages = await self._find_all_products_link(page)
        elif nav_strategy == "category_links":
            initial_product_pages = await self._find_category_links(page)
        elif nav_strategy == "products_already_here":
            initial_product_pages = [{"url": url, "page": page, "name": "Homepage"}]
        
        if not initial_product_pages:
            errors.append("No product pages found after navigation")
            await page.close()
            return [], errors
        
        print(f"📂 Found {len(initial_product_pages)} initial product pages")
        
        # Step 4: Process pages with immediate async extraction
        # Create a queue for discovered pages
        page_queue = asyncio.Queue()
        
        
        # Add initial pages to queue
        for page_info in initial_product_pages:
            await page_queue.put(page_info)
        
        # Track active tasks
        active_tasks = set()
        max_concurrent_tasks = 5  # Limit concurrent operations
        
        async def process_page_and_discover_more(page_info):
            """Process a single page: extract products AND discover more pages"""
            try:
                print(f"🚀 Starting async processing for: {page_info.get('name', 'Unknown')}")
                
                # Extract products from this page
                products, page_errors = await self._scrape_product_page_with_discovery(page_info, page_queue, processed_urls)
                
                print(f"✅ Completed {page_info.get('name', 'Unknown')}: {len(products)} products")
                return products, page_errors
                
            except Exception as e:
                print(f"❌ Error processing {page_info.get('name', 'Unknown')}: {e}")
                return [], [str(e)]
        
        # Process pages as they're discovered
        processed_urls = set()
        completed_tasks = []  # Store completed results in order
        
        while not page_queue.empty() or active_tasks:
            # Start new tasks if under limit
            while not page_queue.empty() and len(active_tasks) < max_concurrent_tasks:
                page_info = await page_queue.get()
                
                # Skip if already processed
                if page_info['url'] in processed_urls:
                    continue
                    
                processed_urls.add(page_info['url'])
                
                # Create task for this page
                task = asyncio.create_task(process_page_and_discover_more(page_info))
                active_tasks.add(task)
            
            # Wait for at least one task to complete
            if active_tasks:
                done, pending = await asyncio.wait(active_tasks, return_when=asyncio.FIRST_COMPLETED)
                
                for task in done:
                    active_tasks.remove(task)
                    try:
                        products, page_errors = await task
                        # Store results in order instead of extending immediately
                        completed_tasks.append((products, page_errors))
                        print(f"✅ Completed task: {len(products)} products")
                    except Exception as e:
                        print(f"❌ Task failed: {e}")
                        errors.append(str(e))
            
            # Small delay to prevent busy waiting
            if page_queue.empty() and active_tasks:
                await asyncio.sleep(0.1)
        
        # Combine all results in order after all tasks complete
        print(f"📋 Combining results from {len(completed_tasks)} completed tasks...")
        for task_products, task_errors in completed_tasks:
            all_products.extend(task_products)
            errors.extend(task_errors)
        
        # Deduplicate products by name + image_url to prevent recursive adding
        print(f"🔄 Deduplicating {len(all_products)} products...")
        seen_products = set()
        unique_products = []
        
        for product in all_products:
            # Create unique key based on name and image URL
            product_key = (product.title.strip().lower(), product.image_url)
            
            if product_key not in seen_products:
                seen_products.add(product_key)
                unique_products.append(product)
            else:
                print(f"   🗑️  Removing duplicate: {product.title}")
        
        print(f"✅ Removed {len(all_products) - len(unique_products)} duplicates")
        all_products = unique_products
        
        # Clean up
        try:
            await page.close()
        except:
            pass  # Page might already be closed
            
        print(f"🎉 Total unique products collected: {len(all_products)}")
        return all_products, errors
    
    async def _get_navigation_strategy(self, html_content: str, url: str) -> str:
        """Ask LLM for navigation strategy"""
        try:
            import asyncio
            print("🤖 Creating navigation prompt...")
            prompt = get_navigation_prompt(html_content, url)
            print("🤖 Sending prompt to LLM...")
            
            # Run synchronous LLM call in thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                self.llm.generate,
                prompt,
                50,  # max_tokens
                0.1  # temperature
            )
            print(f"🤖 LLM response: {response}")
            
            # Clean response and validate using LLM
            strategy = response.strip().lower()
            
            # Use LLM to validate the strategy
            validation_prompt = self.decision_maker.get_navigation_strategy_validation_prompt(strategy)
            validation_result = await self.decision_maker.decide(validation_prompt)
            
            if validation_result.get("is_valid", False):
                return validation_result.get("corrected_strategy", strategy)
            else:
                print(f"⚠️ Invalid strategy '{strategy}', LLM corrected to: {validation_result.get('corrected_strategy', 'products_already_here')}")
                return validation_result.get("corrected_strategy", "products_already_here")
                
        except Exception as e:
            print(f"❌ Navigation strategy LLM call failed: {e}")
            return "products_already_here"
    
    async def _handle_menu_navigation(self, page: Page) -> List[Dict[str, Any]]:
        """Handle menu -> products navigation"""
        # TODO: Implement menu clicking logic
        # For now, assume we found menu and analyze it
        html_content = await page.content()
        url = page.url
        
        try:
            prompt = get_menu_navigation_prompt(html_content, url)
            response = self.llm.generate(prompt, max_tokens=50, temperature=0.1)
            
            menu_strategy = response.strip().lower()
            
            # Validate menu strategy using LLM
            validation_prompt = self.decision_maker.get_menu_strategy_validation_prompt(menu_strategy)
            validation_result = await self.decision_maker.decide(validation_prompt)
            
            if validation_result.get("is_valid", False):
                corrected_strategy = validation_result.get("corrected_strategy", menu_strategy)
                
                if corrected_strategy == "all_products_link":
                    return await self._find_all_products_link(page)
                elif corrected_strategy == "category_links":
                    return await self._find_category_links(page)
            
            print(f"⚠️ Invalid menu strategy: {menu_strategy}")
            return []
                
        except Exception as e:
            print(f"❌ Menu navigation failed: {e}")
            return []
    
    async def _find_all_products_link(self, page: Page) -> List[Dict[str, Any]]:
        """Find and navigate to 'All Products' page"""
        try:
            import asyncio
            html_content = await page.content()
            prompt = get_all_products_link_prompt(html_content, page.url)
            
            # Run synchronous LLM call in thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                self.llm.generate,
                prompt,
                200,  # max_tokens
                0.1   # temperature
            )
            print(f"🤖 LLM response for all products link: {response}")
            
            try:
                link_data = self._extract_json_from_response(response)
            except json.JSONDecodeError as e:
                print(f"❌ Invalid JSON response: {response}")
                return []
            
            if link_data.get("url"):
                # Navigate to all products page
                products_url = link_data["url"]
                if not products_url.startswith("http"):
                    products_url = page.url.rstrip("/") + "/" + products_url.lstrip("/")
                
                products_page = await self.browser.new_page()
                print(f"🌐 Navigating to products page: {products_url}")
                await products_page.goto(products_url, timeout=60000)
                print("⏳ Waiting for products page to load...")
                try:
                    await products_page.wait_for_load_state('networkidle', timeout=10000)
                    print("✅ Products page loaded (networkidle)")
                except:
                    print("⚠️ Networkidle timeout, trying domcontentloaded...")
                    await products_page.wait_for_load_state('domcontentloaded')
                    print("✅ Products page loaded (domcontentloaded)")
                    print("⏳ Waiting 3 seconds for JavaScript to load products...")
                    await products_page.wait_for_timeout(3000)
                
                return [{"url": products_url, "page": products_page, "name": "All Products"}]
            else:
                return []
                
        except Exception as e:
            print(f"❌ All products link finding failed: {e}")
            return []
    
    async def _find_category_links(self, page: Page) -> List[Dict[str, Any]]:
        """Find all category links"""
        try:
            import asyncio
            html_content = await page.content()
            prompt = get_category_links_prompt(html_content, page.url)
            
            # Run synchronous LLM call in thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                self.llm.generate,
                prompt,
                1000,  # max_tokens
                0.1    # temperature
            )
            print(f"🤖 LLM response for categories: {response}")
            
            try:
                categories = self._extract_json_from_response(response)
            except json.JSONDecodeError as e:
                print(f"❌ Invalid JSON response: {response}")
                return []
            
            category_pages = []
            for category in categories:
                if category.get("url"):
                    cat_url = category["url"]
                    if not cat_url.startswith("http"):
                        cat_url = page.url.rstrip("/") + "/" + cat_url.lstrip("/")
                    
                    category_pages.append({
                        "url": cat_url,
                        "page": None,  # Will create page when scraping
                        "name": category.get("text", "Category")
                    })
            
            return category_pages
            
        except Exception as e:
            print(f"❌ Category links finding failed: {e}")
            return []
    
    async def _scrape_product_page_with_discovery(self, page_info: Dict[str, Any], page_queue: asyncio.Queue, processed_urls: set = None) -> Tuple[List[Product], List[str]]:
        """Scrape products from a page AND discover more pages to add to queue"""
        errors = []
        all_products = []
        
        try:
            # Create new page if needed
            if page_info.get("page"):
                page = page_info["page"]
                should_close = False  # Don't close provided pages
            else:
                page = await self.browser.new_page()
                await page.goto(page_info["url"], timeout=60000)
                await page.wait_for_load_state('domcontentloaded')
                await page.wait_for_timeout(2000)  # Let JS load
                should_close = True  # Close pages we create
            
            print(f"📦 Extracting products from: {page_info['name']}")
            
            # Get HTML for analysis
            html_content = await page.content()
            
            # Get product detection pattern from LLM (first page only needs this)
            if not page_info.get('extraction_pattern'):
                print("🔍 Getting product detection info from LLM...")
                
                # Find sample images for context
                import re
                product_images = []
                shopify_imgs = re.findall(r'<img[^>]*src="[^"]*cdn/shop[^"]*"[^>]*>', html_content)
                product_images.extend(shopify_imgs[:10])
                
                product_analysis = await self._get_product_detection(html_content, page_info["url"], product_images)
                
                if not product_analysis:
                    errors.append(f"Could not analyze products on {page_info['name']}")
                    if should_close:
                        await page.close()
                    return [], errors
                
                extraction_pattern = product_analysis.get("extraction_pattern", {})
                print(f"   📋 Extraction pattern: {extraction_pattern}")
            else:
                # Use provided pattern from previous analysis
                extraction_pattern = page_info['extraction_pattern']
                print(f"   📋 Using existing pattern: {extraction_pattern}")
            
            # Extract products using the pattern
            container_selector = extraction_pattern.get("container_selector")
            image_selector = extraction_pattern.get("image_selector")
            name_selector = extraction_pattern.get("name_selector")
            
            print(f"   🎯 Selectors - Container: {container_selector}, Image: {image_selector}, Name: {name_selector}")
            
            if container_selector:
                try:
                    containers = await page.query_selector_all(container_selector)
                    print(f"   Found {len(containers)} products on this page")
                    
                    for i, container in enumerate(containers, 1):
                        try:
                            # Extract image
                            product_image = ""
                            if image_selector:
                                img_elem = await container.query_selector(image_selector)
                                if img_elem:
                                    product_image = await img_elem.get_attribute("src") or await img_elem.get_attribute("data-src")
                            
                            # Extract name
                            product_name = f"Product {i}"
                            if name_selector:
                                name_elem = await container.query_selector(name_selector)
                                if name_elem:
                                    product_name = (await name_elem.inner_text()).strip()
                            
                            # Clean up image URL
                            if product_image and not product_image.startswith("http"):
                                if product_image.startswith("//"):
                                    product_image = "https:" + product_image
                                else:
                                    from urllib.parse import urljoin
                                    product_image = urljoin(page_info["url"], product_image)
                            
                            all_products.append(Product(
                                title=product_name,
                                image_url=product_image,
                                product_url=page_info["url"],
                                collection_name=page_info["name"],
                                collection_url=page_info["url"],
                                confidence=0.9,
                                detection_method="llm_pattern_extraction"
                            ))
                            
                        except Exception as e:
                            continue
                    
                except Exception as e:
                    errors.append(f"Failed to extract products: {e}")
            else:
                print(f"   ⚠️ No container selector found in extraction pattern")
                errors.append("No container selector found")
            
            # ASYNC PAGINATION DISCOVERY - Add new pages to queue
            print(f"🔍 Discovering more pages from: {page_info['name']}")
            pagination_urls = await self._find_pagination_urls(page)
            
            for url in pagination_urls:
                # Only add if not already processed (prevents infinite loops)
                if processed_urls is None or url not in processed_urls:
                    new_page_info = {
                        "url": url,
                        "page": None,  # Will create new page when processing
                        "name": f"Page from {page_info['name']}",
                        "extraction_pattern": extraction_pattern  # Reuse the pattern!
                    }
                    # Add to queue for processing
                    await page_queue.put(new_page_info)
                    print(f"   📄 Added to queue: {url}")
                else:
                    print(f"   ⚠️ Skipping already processed: {url}")
            
            # Clean up
            if should_close:
                await page.close()
            
            return all_products, errors
            
        except Exception as e:
            print(f"❌ Error in page processing: {e}")
            errors.append(str(e))
            return [], errors
    
    async def _scrape_product_page(self, page_info: Dict[str, Any]) -> Tuple[List[Product], List[str]]:
        """Scrape products from a single product page"""
        errors = []
        
        try:
            # Create new page if needed
            if page_info.get("page"):
                page = page_info["page"]
            else:
                page = await self.browser.new_page()
                await page.goto(page_info["url"], timeout=60000)
                await page.wait_for_load_state('networkidle')
            
            print(f"📦 Scraping products from: {page_info['name']}")
            print("🔍 Getting product detection info from LLM...")
            
            # Get product detection instructions from LLM
            html_content = await page.content()
            print(f"🔍 HTML content length: {len(html_content)} chars")
            
            # Find product images to help with detection
            import re
            
            # Try multiple patterns to find product images
            product_images = []
            
            # Pattern 1: Shopify CDN (for Shopify sites)
            shopify_imgs = re.findall(r'<img[^>]*src="[^"]*cdn/shop[^"]*"[^>]*>', html_content)
            product_images.extend(shopify_imgs)
            print(f"🔍 Found {len(shopify_imgs)} Shopify CDN images")
            
            # Pattern 2: Images with product-related classes
            class_imgs = re.findall(r'<img[^>]*class="[^"]*(?:product|item|card)[^"]*"[^>]*>', html_content)
            product_images.extend(class_imgs)
            print(f"🔍 Found {len(class_imgs)} images with product classes")
            
            # Pattern 3: Images with alt text (likely product images)
            alt_imgs = re.findall(r'<img[^>]*alt="[^"]+"[^>]*src="[^"]*"[^>]*>', html_content)
            product_images.extend(alt_imgs)
            print(f"🔍 Found {len(alt_imgs)} images with alt text")
            
            # Pattern 4: Any img tags (last resort)
            if not product_images:
                all_imgs = re.findall(r'<img[^>]*src="[^"]*"[^>]*>', html_content)
                product_images.extend(all_imgs[:10])  # Take first 10
                print(f"🔍 Found {len(all_imgs)} total images, using first 10")
            
            # Remove duplicates while preserving order
            seen = set()
            unique_images = []
            for img in product_images:
                if img not in seen:
                    seen.add(img)
                    unique_images.append(img)
            product_images = unique_images
            
            print(f"🔍 Total unique product images for context: {len(product_images)}")
            if product_images:
                print(f"   Sample: {product_images[0][:200]}...")
            
            product_analysis = await self._get_product_detection(html_content, page_info["url"], product_images)
            
            if not product_analysis:
                print(f"❌ Could not analyze products on {page_info['name']}")
                errors.append(f"Could not analyze products on {page_info['name']}")
                if not page_info.get("page"):
                    await page.close()
                return [], errors
            
            print(f"🔍 Product analysis result:")
            print(f"   Products found by LLM: {len(product_analysis.get('products_found', []))}")
            print(f"   Pattern insights: {product_analysis.get('patterns_identified', {})}")
            
            # Get the extraction pattern from LLM analysis
            extraction_pattern = product_analysis.get("extraction_pattern", {})
            if not extraction_pattern:
                print(f"❌ LLM could not identify extraction pattern on {page_info['name']}")
                errors.append(f"LLM could not identify extraction pattern on {page_info['name']}")
                if not page_info.get("page"):
                    await page.close()
                return [], errors
            
            # Use the pattern to extract ALL products with the browser
            container_selector = extraction_pattern.get("container_selector")
            image_selector = extraction_pattern.get("image_selector") 
            name_selector = extraction_pattern.get("name_selector")
            
            if not container_selector:
                print(f"❌ No container selector provided by LLM")
                errors.append(f"No container selector provided by LLM")
                if not page_info.get("page"):
                    await page.close()
                return [], errors
            
            print(f"🔍 Using LLM-identified pattern:")
            print(f"   Container: {container_selector}")
            print(f"   Image: {image_selector}")
            print(f"   Name: {name_selector}")
            
            # Extract ALL products using the pattern
            all_products = []
            
            try:
                # Find all product containers
                containers = await page.query_selector_all(container_selector)
                print(f"📦 Found {len(containers)} product containers")
                
                for i, container in enumerate(containers, 1):
                    try:
                        # Extract image
                        product_image = ""
                        if image_selector:
                            img_elem = await container.query_selector(image_selector)
                            if img_elem:
                                product_image = await img_elem.get_attribute("src")
                                if not product_image:
                                    product_image = await img_elem.get_attribute("data-src")
                        
                        # Extract name
                        product_name = f"Product {i}"
                        if name_selector:
                            name_elem = await container.query_selector(name_selector)
                            if name_elem:
                                product_name = await name_elem.inner_text()
                                product_name = product_name.strip()
                        
                        # Clean up image URL
                        if product_image and not product_image.startswith("http"):
                            if product_image.startswith("//"):
                                product_image = "https:" + product_image
                            elif product_image.startswith("/"):
                                from urllib.parse import urljoin
                                product_image = urljoin(page_info["url"], product_image)
                        
                        # Create product object
                        product = Product(
                            title=product_name,
                            image_url=product_image,
                            product_url=page_info["url"],
                            collection_name=page_info["name"],
                            collection_url=page_info["url"],
                            confidence=0.9,
                            detection_method="llm_pattern_extraction"
                        )
                        
                        all_products.append(product)
                        
                        if i <= 5:  # Show first 5 for debugging
                            print(f"   ✅ {i}. '{product_name}' - {product_image}")
                        
                    except Exception as e:
                        print(f"   ❌ Failed to extract product {i}: {e}")
                
                print(f"📦 Successfully extracted {len(all_products)} products using pattern")
                
                # NOTE: Pagination is now handled by the new async discovery system
                # The old pagination method has been disabled to prevent duplicates
                additional_products = []
                all_products.extend(additional_products)
                
            except Exception as e:
                print(f"❌ Failed to use container selector '{container_selector}': {e}")
                errors.append(f"Failed to use container selector: {e}")
                if not page_info.get("page"):
                    await page.close()
                return [], errors
            
            # Close page if we created it
            if not page_info.get("page"):
                await page.close()
            
            return all_products, errors
            
        except Exception as e:
            print(f"❌ Error scraping {page_info['name']}: {e}")
            errors.append(str(e))
            return [], errors
    
    async def _get_product_detection(self, html_content: str, url: str, sample_images: list = None) -> Optional[Dict[str, Any]]:
        """Get product detection instructions from LLM"""
        try:
            # Use more powerful Sonnet model for complex HTML analysis
            from llm_interface import ClaudeInterface
            import asyncio
            
            sonnet_llm = ClaudeInterface(model="claude-3-5-sonnet-20241022")
            
            prompt = get_product_detection_prompt(html_content, url, sample_images)
            print(f"🔍 Product detection prompt length: {len(prompt)} chars")
            print("🤖 Using Claude 3.5 Sonnet for product detection...")
            if sample_images:
                print(f"🔍 Using {len(sample_images)} sample images for context")
            
            # Run synchronous LLM call in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,  # Use default thread pool
                sonnet_llm.generate,
                prompt,
                800,  # max_tokens
                0.1   # temperature
            )
            
            print(f"🤖 LLM response received ({len(response)} chars)")
            
            return self._extract_json_from_response(response)
            
        except Exception as e:
            print(f"❌ Product detection LLM call failed: {e}")
            return None
    
    async def _get_pagination_strategy(self, html_content: str, url: str) -> Dict[str, Any]:
        """Get pagination strategy from LLM"""
        try:
            prompt = get_pagination_prompt(html_content, url)
            response = self.llm.generate(prompt, max_tokens=300, temperature=0.1)
            print(f"🤖 LLM response for pagination: {response}")
            
            result = self._extract_json_from_response(response)
            
            # Handle case where LLM returns just a strategy string instead of JSON object
            if isinstance(result, str):
                return {"strategy": result, "selector": None, "notes": f"Strategy: {result}"}
            
            return result
            
        except Exception as e:
            print(f"❌ Pagination strategy LLM call failed: {e}")
            return {"strategy": "done", "selector": None, "notes": "LLM call failed"}
    
    async def _extract_products_from_page(self, page: Page, product_info: Dict[str, Any], collection_name: str) -> List[Product]:
        """Extract products from current page using LLM instructions"""
        try:
            # Get product containers
            container_selector = product_info["product_container_selector"]
            containers = await page.query_selector_all(container_selector)
            
            print(f"🔍 Found {len(containers)} product containers with selector: {container_selector}")
            
            products = []
            
            for i, container in enumerate(containers):
                try:
                    # Extract image
                    image_url = await self._extract_image_from_container(container, product_info["image_extraction"])
                    
                    # Extract name
                    name = await self._extract_name_from_container(container, product_info["name_extraction"])
                    
                    # Extract product URL (optional)
                    product_url = await self._extract_product_url_from_container(container, page.url)
                    
                    if image_url and name:
                        products.append(Product(
                            title=name,
                            image_url=image_url,
                            product_url=product_url,
                            collection_name=collection_name,
                            collection_url=page.url
                        ))
                    
                except Exception as e:
                    print(f"⚠️ Error extracting product {i}: {e}")
                    continue
            
            return products
            
        except Exception as e:
            print(f"❌ Product extraction failed: {e}")
            return []
    
    async def _extract_image_from_container(self, container, image_config: Dict[str, Any]) -> Optional[str]:
        """Extract image URL from product container"""
        try:
            method = image_config["method"]
            selector = image_config["selector"]
            attribute = image_config["attribute"]
            
            # Validate extraction method using LLM
            method_validation = await self.decision_maker.decide(
                self.decision_maker.get_extraction_method_classification_prompt(method)
            )
            validated_method = method_validation.get("corrected_method", method) if method_validation.get("is_valid", True) else method
            
            if validated_method in ["img_src", "img_data_src"]:
                img_element = await container.query_selector(selector)
                if img_element:
                    return await img_element.get_attribute(attribute)
            
            elif validated_method == "background_image":
                element = await container.query_selector(selector)
                if element:
                    style = await element.get_attribute("style")
                    if style and "background-image" in style:
                        # Extract URL from background-image: url(...)
                        import re
                        match = re.search(r'url\([\'"]?([^\'"]+)[\'"]?\)', style)
                        if match:
                            return match.group(1)
            
            return None
            
        except Exception as e:
            print(f"⚠️ Image extraction error: {e}")
            return None
    
    async def _extract_name_from_container(self, container, name_config: Dict[str, Any]) -> Optional[str]:
        """Extract product name from container"""
        try:
            selector = name_config["selector"]
            attribute = name_config["attribute"]
            
            element = await container.query_selector(selector)
            if element:
                if attribute == "text":
                    return await element.text_content()
                else:
                    return await element.get_attribute(attribute)
            
            return None
            
        except Exception as e:
            print(f"⚠️ Name extraction error: {e}")
            return None
    
    async def _extract_product_url_from_container(self, container, base_url: str) -> Optional[str]:
        """Extract product page URL from container"""
        try:
            # Look for first link in container
            link = await container.query_selector("a[href]")
            if link:
                href = await link.get_attribute("href")
                if href:
                    if href.startswith("http"):
                        return href
                    else:
                        return base_url.rstrip("/") + "/" + href.lstrip("/")
            
            return None
            
        except Exception as e:
            return None
    
    async def _handle_pagination(self, page: Page, pagination_info: Dict[str, Any]) -> bool:
        """Handle pagination by clicking next button"""
        try:
            selector = pagination_info.get("selector")
            if selector:
                next_button = await page.query_selector(selector)
                if next_button:
                    await next_button.click()
                    await page.wait_for_load_state('networkidle')
                    return True
            
            return False
            
        except Exception as e:
            print(f"⚠️ Pagination failed: {e}")
            return False
    
    async def _handle_scrolling(self, page: Page) -> bool:
        """Handle infinite scroll"""
        try:
            # Get current height
            prev_height = await page.evaluate("document.body.scrollHeight")
            
            # Scroll to bottom
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            
            # Wait a bit for new content to load
            await page.wait_for_timeout(2000)
            
            # Check if height changed (new content loaded)
            new_height = await page.evaluate("document.body.scrollHeight")
            
            return new_height > prev_height
            
        except Exception as e:
            print(f"⚠️ Scrolling failed: {e}")
            return False
    
    async def _handle_load_more(self, page: Page, pagination_info: Dict[str, Any]) -> bool:
        """Handle 'Load More' button"""
        try:
            selector = pagination_info.get("selector")
            if selector:
                load_button = await page.query_selector(selector)
                if load_button:
                    await load_button.click()
                    await page.wait_for_timeout(2000)
                    return True
            
            return False
            
        except Exception as e:
            print(f"⚠️ Load more failed: {e}")
            return False
    
    async def _handle_pagination_and_scrape(self, page: Page, extraction_pattern: Dict[str, Any], collection_name: str) -> List[Product]:
        """Find additional pages recursively and scrape them with the same pattern"""
        try:
            print("🔄 Looking for pagination recursively...")
            
            # Discover all pagination URLs recursively
            all_urls = await self._discover_all_pagination_urls(page)
            
            if not all_urls:
                print("📄 No additional pages found")
                return []
            
            print(f"📄 Found {len(all_urls)} total additional pages")
            
            # Scrape all pages in parallel (but limit concurrency)
            additional_products = []
            batch_size = 3  # Process 3 pages at a time
            
            for i in range(0, len(all_urls), batch_size):
                batch_urls = all_urls[i:i + batch_size]
                print(f"🔄 Processing pagination batch {i//batch_size + 1}: {len(batch_urls)} pages")
                
                # Create tasks for parallel processing
                tasks = []
                for url in batch_urls:
                    task = self._scrape_single_page_with_pattern(url, extraction_pattern, collection_name)
                    tasks.append(task)
                
                # Run batch in parallel
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Process results
                for j, result in enumerate(batch_results):
                    if isinstance(result, Exception):
                        print(f"❌ Error scraping page {batch_urls[j]}: {result}")
                    else:
                        products = result
                        additional_products.extend(products)
                        print(f"✅ Page {batch_urls[j]}: {len(products)} products")
            
            print(f"🔄 Pagination complete: {len(additional_products)} additional products")
            return additional_products
            
        except Exception as e:
            print(f"❌ Pagination handling failed: {e}")
            return []
    
    async def _discover_all_pagination_urls(self, initial_page: Page) -> List[str]:
        """Recursively discover all pagination URLs by following pagination chains"""
        try:
            discovered_urls = set()
            pages_to_check = [initial_page.url]
            visited_pages = set([initial_page.url])
            
            print("🔄 Starting recursive pagination discovery...")
            
            while pages_to_check:
                current_url = pages_to_check.pop(0)
                print(f"   Checking page: {current_url}")
                
                # Create page if not the initial page
                if current_url == initial_page.url:
                    current_page = initial_page
                else:
                    current_page = await self.browser.new_page()
                    await current_page.goto(current_url, timeout=60000)
                    await current_page.wait_for_load_state('domcontentloaded')
                
                # Find pagination links on this page
                page_urls = await self._find_pagination_urls(current_page)
                
                for url in page_urls:
                    if url not in visited_pages:
                        discovered_urls.add(url)
                        pages_to_check.append(url)
                        visited_pages.add(url)
                        print(f"      ✅ New page discovered: {url}")
                
                # Close page if we created it
                if current_url != initial_page.url:
                    await current_page.close()
                
                # Safety limit to prevent infinite loops
                if len(visited_pages) > 20:
                    print("   ⚠️ Reached safety limit of 20 pages")
                    break
            
            # Remove the initial page URL from discovered URLs
            discovered_urls.discard(initial_page.url)
            
            final_urls = list(discovered_urls)
            print(f"🔄 Recursive discovery complete: {len(final_urls)} total pages")
            for i, url in enumerate(final_urls, 1):
                print(f"   {i}. {url}")
            
            return final_urls
            
        except Exception as e:
            print(f"❌ Failed recursive pagination discovery: {e}")
            return []
    
    async def _find_pagination_urls(self, page: Page) -> List[str]:
        """Find all pagination URLs on the current page"""
        try:
            pagination_urls = []
            base_url = page.url.split('?')[0]  # Remove query params
            
            print("🔍 Scanning for pagination links...")
            
            # Enhanced pagination selectors
            pagination_selectors = [
                'a[rel="next"]',  # Next button
                '.pagination a',  # Any pagination links
                '[class*="pagination"] a',  # Pagination with partial class match
                '[class*="pager"] a',  # Alternative pagination class
                'a[href*="page="]',  # Page parameter links
                'a[href*="/page/"]',  # Page path links
                'a[href*="phcursor"]',  # Shopify pagination cursor
                'nav a[href*="page"]',  # Navigation links with page
            ]
            
            for selector in pagination_selectors:
                try:
                    links = await page.query_selector_all(selector)
                    print(f"   Selector '{selector}': found {len(links)} links")
                    
                    for link in links:
                        href = await link.get_attribute('href')
                        link_text = await link.inner_text()
                        
                        if href:
                            # Convert relative URLs to absolute
                            if href.startswith('/'):
                                from urllib.parse import urljoin
                                href = urljoin(page.url, href)
                            
                            # Debug output for each link found
                            print(f"      Link: '{link_text.strip()}' -> {href}")
                            
                            # Add if it's a different page
                            if href != page.url and href not in pagination_urls:
                                # Use LLM to classify if this link leads to more products
                                classification_prompt = self.decision_maker.get_pagination_url_classification_prompt(
                                    href, link_text.strip(), page.url
                                )
                                classification = await self.decision_maker.decide(classification_prompt)
                                
                                if classification.get("is_product_page", False):
                                    pagination_urls.append(href)
                                    link_type = classification.get("type", "unknown")
                                    confidence = classification.get("confidence", 0.0)
                                    print(f"      ✅ Added {link_type} URL (confidence: {confidence:.2f}): {link_text.strip()}")
                                    if classification.get("reasoning"):
                                        print(f"         Reason: {classification['reasoning']}")
                                
                except Exception as e:
                    print(f"      ❌ Error with selector '{selector}': {e}")
                    continue
            
            # Additional strategy: batch classify remaining links for efficiency
            try:
                print("   🔍 Analyzing remaining links for product pages...")
                all_links = await page.query_selector_all('a')
                unprocessed_links = []
                
                for link in all_links[:50]:  # Limit to first 50 links to avoid too many LLM calls
                    href = await link.get_attribute('href')
                    text = await link.inner_text()
                    
                    if href and href not in pagination_urls:
                        if href.startswith('/'):
                            from urllib.parse import urljoin
                            href = urljoin(page.url, href)
                        
                        if href != page.url:
                            unprocessed_links.append({
                                "url": href,
                                "text": text.strip()
                            })
                
                # Batch classify links for efficiency
                if unprocessed_links:
                    batch_prompt = self.decision_maker.get_bulk_link_classification_prompt(
                        unprocessed_links[:20],  # Process up to 20 at once
                        page.url
                    )
                    classifications = await self.decision_maker.decide(batch_prompt)
                    
                    if isinstance(classifications, list):
                        for item in classifications:
                            if item.get("is_product_page", False) and item.get("url") not in pagination_urls:
                                pagination_urls.append(item["url"])
                                print(f"   ✅ Batch classified: {item.get('type', 'unknown')} - {item['url'][:50]}...")
                            
            except Exception as e:
                print(f"   ❌ Error in batch link analysis: {e}")
            
            # Remove duplicates while preserving order
            seen = set()
            unique_urls = []
            for url in pagination_urls:
                if url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
            
            print(f"🔍 Total unique pagination URLs found: {len(unique_urls)}")
            for i, url in enumerate(unique_urls, 1):
                print(f"   {i}. {url}")
            
            return unique_urls[:10]  # Limit to 10 additional pages
            
        except Exception as e:
            print(f"❌ Failed to find pagination URLs: {e}")
            return []
    
    async def _scrape_single_page_with_pattern(self, url: str, extraction_pattern: Dict[str, Any], collection_name: str) -> List[Product]:
        """Scrape a single page using the known pattern"""
        try:
            # Create new page for this URL
            new_page = await self.browser.new_page()
            await new_page.goto(url, timeout=60000)
            await new_page.wait_for_load_state('domcontentloaded')
            
            # Extract products using the same pattern
            products = []
            container_selector = extraction_pattern.get("container_selector")
            image_selector = extraction_pattern.get("image_selector")
            name_selector = extraction_pattern.get("name_selector")
            
            if container_selector:
                containers = await new_page.query_selector_all(container_selector)
                
                for i, container in enumerate(containers, 1):
                    try:
                        # Extract image
                        product_image = ""
                        if image_selector:
                            img_elem = await container.query_selector(image_selector)
                            if img_elem:
                                product_image = await img_elem.get_attribute("src")
                                if not product_image:
                                    product_image = await img_elem.get_attribute("data-src")
                        
                        # Extract name
                        product_name = f"Product {i}"
                        if name_selector:
                            name_elem = await container.query_selector(name_selector)
                            if name_elem:
                                product_name = await name_elem.inner_text()
                                product_name = product_name.strip()
                        
                        # Clean up image URL
                        if product_image and not product_image.startswith("http"):
                            if product_image.startswith("//"):
                                product_image = "https:" + product_image
                            elif product_image.startswith("/"):
                                from urllib.parse import urljoin
                                product_image = urljoin(url, product_image)
                        
                        # Create product object
                        product = Product(
                            title=product_name,
                            image_url=product_image,
                            product_url=url,
                            collection_name=collection_name,
                            collection_url=url,
                            confidence=0.9,
                            detection_method="llm_pattern_extraction"
                        )
                        
                        products.append(product)
                        
                    except Exception as e:
                        continue  # Skip failed products
            
            await new_page.close()
            return products
            
        except Exception as e:
            print(f"❌ Failed to scrape page {url}: {e}")
            return []


# Factory function for compatibility
def get_llm_scraper():
    """Get the LLM scraper instance"""
    return LLMScraper()