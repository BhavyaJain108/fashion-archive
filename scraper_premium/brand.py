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



class LogBuffer:
    """Context manager to buffer print statements during parallel execution"""
    def __init__(self):
        self.logs = []
        self.original_print = None

    def __enter__(self):
        import builtins
        self.original_print = builtins.print
        builtins.print = self._buffered_print
        return self

    def _buffered_print(self, *args, **kwargs):
        # Capture the print output
        import io
        buffer = io.StringIO()
        # Remove 'file' from kwargs if present to avoid conflict
        kwargs_copy = kwargs.copy()
        kwargs_copy['file'] = buffer
        self.original_print(*args, **kwargs_copy)
        self.logs.append(buffer.getvalue().rstrip('\n'))

    def __exit__(self, exc_type, exc_val, exc_tb):
        import builtins
        builtins.print = self.original_print
        return False

    def dump(self):
        """Print all buffered logs at once"""
        for log in self.logs:
            self.original_print(log)


class Brand:
    """
    Represents a fashion brand for scraping.
    """

    def __init__(self, url: str, llm_handler: LLMHandler = None, test_mode: bool = False):
        """
        Initialize a Brand

        Args:
            url: The main URL of the brand website
            llm_handler: LLM handler instance (optional)
            test_mode: If True, save images to tests/results directory
        """
        self.url = url
        self.product_pages: List[str] = []
        self.starting_pages_queue: List[str] = []
        self.product_extraction_pattern: dict = {}
        self.llm_handler = llm_handler or LLMHandler()
        self.test_mode = test_mode

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

        # Lineage memory for multi-page extraction optimization (global sets)
        self.approved_lineages = set()  # Global approved lineages across all categories
        self.rejected_lineages = set()  # Global rejected lineages across all categories

        # HTML processing pipeline
        self.html_queue = Queue()  # Queue of (html, source_url) tuples
        self.pattern_ready = threading.Event()  # Signal when pattern is detected
        self.workers_active = False
        self.worker_pool = None

        # Image downloading pipeline
        self.image_downloader = ImageDownloader()
        self.image_download_queue = Queue()  # Queue of image download tasks
        self.image_workers_active = False
        self.image_worker_pool = None

        # Thread-safe stats tracking for async image downloads
        self.image_stats_lock = threading.Lock()
        self.image_stats = {
            "total_queued": 0,
            "total_downloaded": 0,
            "total_failed": 0,
            "by_category": {}  # category_url -> {"queued": int, "downloaded": int, "failed": int, "failed_urls": []}
        }

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
            links_with_context = self.extract_page_links_with_context(first_page_url)
            # Links extracted

            product_links = self._find_product_links(links_with_context, first_page_url)

            if not product_links:
                print(f"❌ LLM failed to identify product links from {len(links_with_context)} links")
                raise Exception(f"No valid product links found")

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
            import traceback
            print(f"❌ Product pattern analysis failed: {e}")
            print(f"📋 Full traceback:")
            traceback.print_exc()
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
            links_with_context = self.extract_page_links_with_context(first_page_url)
            all_links = [link_info['url'] for link_info in links_with_context]
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

    def _get_page_html_with_dropdowns(self, url: str) -> str:
        """
        Get the full rendered HTML of a page, triggering any dropdown menus first.
        Uses ARIA attributes (web standards) to detect and expand navigation menus.

        Strategy:
        1. ARIA-based detection: Look for aria-expanded="false" and aria-haspopup
        2. Try hover first (for CSS-only menus), then click if needed
        3. Fallback to common text patterns if ARIA doesn't reveal new links

        Args:
            url: The URL to fetch

        Returns:
            The complete rendered HTML content with dropdowns expanded
        """
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    ignore_https_errors=True,
                    user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )
                page = context.new_page()

                # Load page
                page.goto(url, wait_until="domcontentloaded", timeout=10000)
                page.wait_for_timeout(2000)

                # Count initial links for validation
                initial_link_count = page.locator('a[href]').count()

                # Strategy 1: ARIA-based detection (most reliable)
                # Find collapsed menu triggers
                aria_selectors = [
                    '[aria-expanded="false"][aria-haspopup]',  # Collapsed menu with popup
                    '[aria-expanded="false"]',  # Any collapsed element
                    '[aria-haspopup="menu"]',  # Menu trigger
                    '[aria-haspopup="true"]',  # Generic popup trigger
                ]

                menus_expanded = 0
                for selector in aria_selectors:
                    try:
                        triggers = page.locator(selector).all()
                        for trigger in triggers:
                            try:
                                # Try hover first (works for CSS-only dropdowns)
                                trigger.hover(timeout=500)
                                page.wait_for_timeout(300)

                                # Check if menu expanded (aria-expanded changed to true)
                                aria_expanded = trigger.get_attribute('aria-expanded')
                                if aria_expanded == 'false':
                                    # Still collapsed, try clicking
                                    trigger.click(timeout=500)
                                    page.wait_for_timeout(300)
                                    menus_expanded += 1
                                else:
                                    menus_expanded += 1

                            except Exception:
                                continue
                    except Exception:
                        continue

                # Final link count
                final_link_count = page.locator('a[href]').count()
                total_revealed = final_link_count - initial_link_count

                if total_revealed > 0:
                    print(f"   🎯 Revealed {total_revealed} additional links by expanding {menus_expanded} menus")

                # Get final HTML with all dropdowns expanded
                html_content = page.content()
                browser.close()
                return html_content

        except Exception as e:
            print(f"⚠️  Error fetching HTML with dropdowns: {e}")
            return ""

    def extract_page_links_with_context(self, url: str, expand_navigation_menus: bool = False) -> List[dict]:
        """
        Extract all links from a page with their HTML context.

        Args:
            url: The URL to extract links from
            expand_navigation_menus: If True, detect and expand dropdown navigation menus
                                    before extracting links (useful for homepage navigation)

        Returns:
            List of dicts with keys: url, position_index, full_element, parent_container
        """
        from bs4 import BeautifulSoup

        # Use dropdown expansion if requested (typically for homepage navigation analysis)
        if expand_navigation_menus:
            html_content = self._get_page_html_with_dropdowns(url)
        else:
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

            # Extract parent container path for semantic analysis
            parent_path = self._get_parent_container_path(a_tag)

            # Extract essential information
            link_info = {
                'url': href,
                'position_index': position_index,
                'full_element': str(a_tag)[:200] + '...' if len(str(a_tag)) > 200 else str(a_tag),
                'parent_container': parent_path
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

    def _get_parent_container_path(self, element, max_depth=3):
        """
        Get CSS selector path for parent containers to identify link location.

        Args:
            element: BeautifulSoup element
            max_depth: How many levels up to traverse

        Returns:
            CSS selector path like "div.product-grid > div.product-card > a"
        """
        path_parts = []
        current = element

        for _ in range(max_depth):
            if current.parent and current.parent.name != '[document]':
                parent = current.parent

                # Build selector for this parent
                selector = parent.name
                if parent.get('class'):
                    classes = '.'.join(parent.get('class'))
                    selector = f"{selector}.{classes}"
                elif parent.get('id'):
                    selector = f"{selector}#{parent.get('id')}"

                path_parts.insert(0, selector)
                current = parent
            else:
                break

        return ' > '.join(path_parts) if path_parts else 'body'

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
    
    def _find_product_links(self, links_with_context: List[dict], page_url: str) -> List[dict]:
        """
        Step 1: Use LLM to identify up to 3 valid product links from all page links

        Args:
            links_with_context: List of dicts with 'url', 'parent_container', 'position_index'
            page_url: Current page URL

        Returns:
            List of dicts with 'url' and 'parent_container' keys
        """
        from prompts.product_link_finder import get_prompt, get_response_model

        # Pass full context (URLs + parent containers) to prompt
        prompt = get_prompt(page_url, links_with_context)

        # Try structured output first
        llm_response = self.llm_handler.call(prompt, expected_format="json", response_model=get_response_model())

        # Debug: print LLM response
        if not llm_response.get("success", False):
            print(f"🐛 LLM call failed: {llm_response.get('error', 'Unknown error')}")

        if llm_response.get("success", False):
            data = llm_response.get("data", {})
            selected_links = data.get("selected_links", [])

            # Validate URLs exist in the original links and extract URL + parent
            all_urls = {link['url']: link['parent_container'] for link in links_with_context}
            valid_links = []

            for link_obj in selected_links:
                # Handle both dict and Pydantic object
                url = link_obj.get('url') if isinstance(link_obj, dict) else link_obj.url
                parent = link_obj.get('parent_container') if isinstance(link_obj, dict) else link_obj.parent_container

                if url in all_urls:
                    valid_links.append({
                        'url': url,
                        'parent_container': parent
                    })

            if valid_links:
                print(f"\n✅ LLM selected {len(valid_links)} product links:")
                for link in valid_links:
                    print(f"   • {link['url']}")
                    print(f"     Parent: {link['parent_container']}")

                return valid_links

        # Simple heuristic fallback when LLM fails
        print("🔧 Using heuristic fallback to find product links")
        heuristic_links = []
        for link_info in links_with_context:
            link = link_info['url']
            parent = link_info['parent_container']

            # Look for common product URL patterns
            if any(pattern in link.lower() for pattern in ['/product/', '/products/', '/item/', '/items/']):
                # Exclude homepage and category pages
                if not link.endswith('/') and '?' not in link and '#' not in link:
                    heuristic_links.append({
                        'url': link,
                        'parent_container': parent
                    })
                    if len(heuristic_links) >= 3:  # Limit to 3
                        break

        if heuristic_links:
            print(f"🔗 Heuristic found {len(heuristic_links)} product links")
            return heuristic_links

        print(f"❌ No product links found")
        return []

    def _extract_container_selector(self, parent_path: str) -> str:
        """
        Extract the most specific parent container selector from a path

        Args:
            parent_path: CSS path like "ul.product-grid.product-grid--template > li.product-item > a"

        Returns:
            Most specific selector, e.g., "ul.product-grid"
        """
        if not parent_path:
            return ""

        # Split by ' > ' to get individual selectors
        parts = parent_path.split(' > ')

        # Look for the first part that has meaningful class names (product-grid, product-list, catalog, etc.)
        for part in parts:
            part = part.strip()
            # Skip generic tags without classes
            if '.' not in part and '#' not in part:
                continue

            # Return first meaningful container
            # This should be something like "ul.product-grid" or "div.product-list"
            return part

        # Fallback: return first part if no classes found
        return parts[0].strip() if parts else ""

    def _analyze_link_pattern(self, html_content: str, product_links: List[dict], base_url: str) -> dict:
        """
        Step 2: Analyze HTML around multiple product links to find container pattern
        Uses parent container info to find the correct occurrence when URLs appear multiple times

        Args:
            html_content: Full page HTML
            product_links: List of dicts with 'url' and 'parent_container' keys
            base_url: Base URL for the page
        """
        import re
        from urllib.parse import urlparse
        from bs4 import BeautifulSoup

        product_contexts = []

        for product_link_info in product_links:
            product_url = product_link_info['url']
            parent_container = product_link_info['parent_container']

            # Extract path with query params from the URL
            parsed = urlparse(product_url)
            search_href = parsed.path
            if parsed.query:
                search_href = f"{parsed.path}?{parsed.query}"

            # Strategy: Use BeautifulSoup to find the link within the specific parent container
            soup = BeautifulSoup(html_content, 'html.parser')

            # Extract the most specific parent container selector from path
            # E.g., "ul.product-grid.product-grid--template > li > a" -> "ul.product-grid"
            container_selector = self._extract_container_selector(parent_container)

            context_html = None

            if container_selector:
                # Try to find the parent container first
                try:
                    parent_elements = soup.select(container_selector)

                    # Search within each matching parent for our specific link
                    for parent_el in parent_elements:
                        # Find link within this container
                        links = parent_el.find_all('a', href=True)
                        for link in links:
                            href = link.get('href', '')
                            # Match either full URL or path (with/without query params)
                            if search_href in href or href in product_url:
                                # Found the right occurrence! Extract context around it
                                link_str = str(link)
                                link_pos = html_content.find(link_str)
                                if link_pos != -1:
                                    context_start = max(0, link_pos - 3750)
                                    context_end = min(len(html_content), link_pos + len(link_str) + 3000)
                                    context_html = html_content[context_start:context_end]
                                    break

                        if context_html:
                            break

                except Exception as e:
                    print(f"⚠️  Container-based search failed for {container_selector}: {e}")

            # Fallback: Use original regex approach if container-based search failed
            if not context_html:
                pattern = rf'<a[^>]*href="[^"]*{re.escape(search_href)}"[^>]*>.*?</a>'
                match = re.search(pattern, html_content, re.DOTALL | re.IGNORECASE)

                if match:
                    context_start = max(0, match.start() - 3750)
                    context_end = min(len(html_content), match.end() + 3000)
                    context_html = html_content[context_start:context_end]

            if context_html:
                product_contexts.append((product_url, context_html))
            else:
                print(f"⚠️  Could not find link in HTML: {search_href}")

        if not product_contexts:
            print(f"❌ No product contexts extracted - cannot analyze pattern")
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
                first_product_link = product_links[0]['url']
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
        """
        Image downloading worker thread
        Processes image download tasks from the queue with retry logic
        Exits when queue is empty and no more tasks will be added
        """
        import os
        import requests
        from urllib.parse import urlparse

        while True:
            try:
                # Get task from queue (non-blocking with timeout)
                task = self.image_download_queue.get(timeout=1)

                if task is None:  # Poison pill for graceful shutdown
                    break

                # Extract task data
                product_name = task["product_name"]
                image_url = task["image_url"]
                category_path = task["category_path"]
                brand_name = task["brand_name"]
                test_mode = task["test_mode"]
                image_index = task["image_index"]
                total_images = task["total_images"]
                category_url = task["category_url"]

                # Build directory path
                if test_mode:
                    base_dir = os.path.join(
                        os.path.dirname(os.path.abspath(__file__)),
                        'tests', 'results', brand_name
                    )
                else:
                    base_dir = brand_name

                path_components = [comp.replace(' ', '_').replace('/', '_') for comp in category_path]
                images_dir = os.path.join(base_dir, *path_components)
                os.makedirs(images_dir, exist_ok=True)

                # Generate filename
                extension = os.path.splitext(urlparse(image_url).path)[1] or '.jpg'
                if total_images > 1:
                    filename = f"{product_name}_{image_index}{extension}"
                else:
                    filename = f"{product_name}{extension}"

                filepath = os.path.join(images_dir, filename)

                # Skip if already downloaded
                if os.path.exists(filepath):
                    with self.image_stats_lock:
                        self.image_stats["total_downloaded"] += 1
                        self.image_stats["by_category"][category_url]["downloaded"] += 1
                    continue

                # Download with retry (1 retry on failure)
                success = False
                for attempt in range(2):  # 2 attempts total (original + 1 retry)
                    try:
                        response = requests.get(image_url, timeout=10)
                        if response.status_code == 200:
                            with open(filepath, 'wb') as f:
                                f.write(response.content)
                            success = True
                            break
                    except Exception as e:
                        if attempt == 0:  # First attempt failed, will retry
                            continue
                        else:  # Second attempt failed, log error
                            print(f"   ⚠️  Worker {worker_id}: Failed to download {filename}: {str(e)[:50]}")

                # Update stats
                with self.image_stats_lock:
                    if success:
                        self.image_stats["total_downloaded"] += 1
                        self.image_stats["by_category"][category_url]["downloaded"] += 1
                    else:
                        self.image_stats["total_failed"] += 1
                        self.image_stats["by_category"][category_url]["failed"] += 1
                        self.image_stats["by_category"][category_url]["failed_urls"].append(image_url)

                # Mark task as done
                self.image_download_queue.task_done()

            except Exception:
                # Queue timeout - check if we should exit
                if not self.image_workers_active and self.image_download_queue.empty():
                    # Pipeline done and queue empty - exit worker
                    break
                # Otherwise continue waiting for more tasks
                continue
    
    def start_image_workers(self, num_workers: int = 8):
        """
        Start background threads for async image downloading

        Workers run as NON-daemon threads to prevent forced termination mid-download.
        Process stays alive until all queued images are downloaded.

        Args:
            num_workers: Number of concurrent download workers (default: 8)
        """
        if self.image_workers_active:
            return  # Already running

        self.image_workers_active = True
        self.image_worker_pool = []

        for worker_id in range(num_workers):
            thread = threading.Thread(
                target=self._image_worker,
                args=(worker_id,),
                daemon=False,  # Non-daemon - keeps process alive until downloads finish
                name=f"ImageWorker-{worker_id}"
            )
            thread.start()
            self.image_worker_pool.append(thread)

        print(f"🚀 Started {num_workers} image download workers (process stays alive until queue empty)")

    def stop_image_workers(self):
        """
        Signal image workers to stop gracefully
        Workers will finish processing remaining queue items before exiting
        """
        if not self.image_workers_active:
            return

        self.image_workers_active = False
        print(f"🛑 Signaled image workers to stop (will finish remaining downloads)")

    def queue_product_for_image_download(self, product):
        """Add product to image download queue (legacy method, kept for compatibility)"""
        if product.image:
            self.image_download_queue.put(product)

    def store_lineage_memory(self, category_url: str, rejected_lineages: set, approved_lineages: set = None):
        """Store lineage memory globally (across all categories and pages)"""
        self.rejected_lineages.update(rejected_lineages)
        if approved_lineages:
            self.approved_lineages.update(approved_lineages)

    def get_lineage_memory(self, category_url: str) -> dict:
        """Get global lineage memory"""
        return {
            "rejected_lineages": self.rejected_lineages,
            "approved_lineages": self.approved_lineages
        }

    def has_lineage_memory(self, category_url: str) -> bool:
        """Check if we have any lineage memory"""
        return len(self.approved_lineages) > 0 or len(self.rejected_lineages) > 0

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

        # Start background image download workers (daemon threads)
        self.start_image_workers(num_workers=8)

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
            # Pass navigation tree and test_mode for proper hierarchy and image storage
            processed_categories = self._process_categories_with_parallel_optimization(
                leaf_urls,
                navigation_tree=navigation_tree,
                test_mode=self.test_mode
            )

            for category_url, category_result in processed_categories.items():
                # Add failed_images from stats to category result
                with self.image_stats_lock:
                    category_stats = self.image_stats["by_category"].get(category_url, {})
                    if category_stats.get("failed_urls"):
                        category_result["failed_images"] = category_stats["failed_urls"]

                categories_results[category_url] = category_result
                total_products += len(category_result.get("products", []))
                total_images += category_result.get("extraction_stats", {}).get("images_queued", 0)

            # Phase 4: Save Results
            print(f"\n💾 Phase 4: Saving results to JSON...")
            total_time = time.time() - start_time

            # Get current download stats (in progress)
            with self.image_stats_lock:
                images_queued = self.image_stats["total_queued"]
                images_downloaded = self.image_stats["total_downloaded"]
                images_failed = self.image_stats["total_failed"]

            pipeline_results = {
                "success": True,
                "navigation_tree": navigation_tree,
                "categories": categories_results,
                "summary": {
                    "total_categories": len(categories_results),
                    "categories_processed": len([c for c in categories_results.values() if c.get("products")]),
                    "total_products": total_products,
                    "total_images_queued": images_queued,
                    "images_downloaded_at_completion": images_downloaded,
                    "images_failed_at_completion": images_failed,
                    "extraction_time": total_time,
                    "note": "Image downloads continue in background (process stays alive until all downloads complete)"
                }
            }

            # Save to JSON file
            self._save_pipeline_results_to_json(pipeline_results)

            print(f"✅ PIPELINE COMPLETE - {total_products} products from {len(categories_results)} categories in {total_time:.1f}s")
            print(f"📊 Images: {images_queued} queued, {images_downloaded} downloaded so far, {images_failed} failed")

            remaining = images_queued - images_downloaded - images_failed
            if remaining > 0:
                print(f"⏳ {remaining} images still downloading in background (process will stay alive until complete)")
            else:
                print(f"✅ All images processed!")

            # Signal workers to stop after queue is empty
            self.stop_image_workers()

            return pipeline_results
            
        except Exception as e:
            total_time = time.time() - start_time
            print(f"❌ Pipeline failed after {total_time:.1f}s: {e}")
            # Stop workers even on failure
            self.stop_image_workers()
            return {"success": False, "error": str(e), "extraction_time": total_time}
    
    def _extract_navigation_tree(self) -> dict:
        """Extract and analyze navigation tree from homepage"""
        from prompts import PromptManager

        # Extract homepage links with context and menu expansion
        homepage_links = self.extract_page_links_with_context(self.url, expand_navigation_menus=True)
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

    def _find_category_path_in_tree(self, category_url: str, tree_node: dict, current_path: List[str] = None) -> List[str]:
        """
        Find the hierarchical path for a category URL in the navigation tree

        Args:
            category_url: The URL to find
            tree_node: Current node in the navigation tree
            current_path: Current path being built

        Returns:
            List of category names from root to leaf, or None if not found
        """
        if current_path is None:
            current_path = []

        # Check if this node has the URL we're looking for
        node_url = tree_node.get('url')
        node_name = tree_node.get('name', 'Unknown')

        if node_url == category_url:
            # Found it! Return the path including this node
            return current_path + [node_name]

        # If this node has children, search them
        children = tree_node.get('children')
        if children:
            new_path = current_path + [node_name] if node_url is None else current_path
            for child in children:
                result = self._find_category_path_in_tree(category_url, child, new_path)
                if result:
                    return result

        return None

    def _get_category_hierarchy_path(self, category_url: str, navigation_tree: dict) -> List[str]:
        """
        Get the full hierarchical path for a category URL from the navigation tree

        Args:
            category_url: The URL to find the path for
            navigation_tree: The full navigation tree dict

        Returns:
            List of category names forming the path, or [category_name] as fallback
        """
        if not navigation_tree or 'category_tree' not in navigation_tree:
            return []

        # Search through all top-level categories
        for root_category in navigation_tree['category_tree']:
            path = self._find_category_path_in_tree(category_url, root_category, [])
            if path:
                return path

        # Fallback: extract category name from URL
        from page_extractor import extract_category_name
        return [extract_category_name(category_url)]
    
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
    
    def _process_categories_with_parallel_optimization(self, leaf_urls: List[str], navigation_tree: dict = None, test_mode: bool = False) -> dict:
        """
        Process categories with optimization: sequential until first pattern found, then parallel

        Args:
            leaf_urls: List of category URLs to process
            navigation_tree: Navigation tree for determining hierarchy
            test_mode: If True, save images to tests/results directory
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
            category_result = self._extract_category_products(
                category_url, pattern, i, len(leaf_urls),
                navigation_tree=navigation_tree,
                test_mode=test_mode
            )
            categories_results[category_url] = category_result
            sequential_count += 1

            # If we have discovered patterns, switch to parallel mode
            if len(self.discovered_patterns) > 0 and not first_pattern_found:
                first_pattern_found = True
                remaining_urls = leaf_urls[i:]  # Remaining categories to process

                if remaining_urls:
                    print(f"\n   ⚡ Phase 3b: Parallel processing for remaining {len(remaining_urls)} categories...")
                    parallel_results = self._process_categories_parallel(
                        remaining_urls, i + 1, len(leaf_urls),
                        navigation_tree=navigation_tree,
                        test_mode=test_mode
                    )
                    categories_results.update(parallel_results)
                break

        if not first_pattern_found:
            print(f"   📊 Completed {sequential_count} categories sequentially (no pattern found)")
        else:
            print(f"   📊 Processed {sequential_count} sequential + {len(categories_results) - sequential_count} parallel")

        return categories_results
    
    def _process_categories_parallel(self, category_urls: List[str], start_index: int, total_categories: int, navigation_tree: dict = None, test_mode: bool = False) -> dict:
        """
        Process multiple categories in parallel (8x concurrency)

        Args:
            category_urls: List of category URLs to process
            start_index: Starting index for display
            total_categories: Total number of categories
            navigation_tree: Navigation tree for determining hierarchy
            test_mode: If True, save images to tests/results directory
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from page_extractor import extract_category_name

        parallel_results = {}
        max_workers = min(8, len(category_urls))  # 8x concurrency

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all category processing tasks
            future_to_info = {}
            for i, category_url in enumerate(category_urls):
                future = executor.submit(
                    self._process_single_category_parallel,
                    category_url, start_index + i, total_categories,
                    navigation_tree, test_mode
                )
                future_to_info[future] = {"url": category_url, "index": start_index + i}

            # Collect results as they complete
            for future in as_completed(future_to_info):
                info = future_to_info[future]
                category_url = info["url"]

                try:
                    category_result = future.result()

                    # Dump buffered logs for this category
                    buffered_logs = category_result.pop("_logs", [])
                    for log in buffered_logs:
                        print(log)

                    # Print completion summary
                    products_found = len(category_result.get("products", []))
                    print(f"      ✅ Parallel {info['index']}: {products_found} products")

                    parallel_results[category_url] = category_result

                except Exception as e:
                    print(f"      ❌ Parallel {info['index']}: Failed - {e}")
                    parallel_results[category_url] = {
                        "name": extract_category_name(category_url),
                        "products": [],
                        "error": str(e)
                    }

        return parallel_results

    def _process_single_category_parallel(self, category_url: str, category_index: int, total_categories: int, navigation_tree: dict = None, test_mode: bool = False) -> dict:
        """
        Process a single category in parallel mode (thread-safe)

        Args:
            category_url: URL of the category to process
            category_index: Current category index
            total_categories: Total number of categories
            navigation_tree: Navigation tree for determining hierarchy
            test_mode: If True, save images to tests/results directory

        Returns:
            Dict with category results and buffered logs
        """
        from page_extractor import extract_category_name

        # Buffer all logs during parallel execution
        log_buffer = LogBuffer()
        with log_buffer:
            # Try extraction with each pattern until one works
            result = self._extract_category_products_with_fallback(
                category_url, category_index, total_categories,
                navigation_tree=navigation_tree,
                test_mode=test_mode
            )

        # Attach buffered logs to result
        result["_logs"] = log_buffer.logs
        return result
    
    def _extract_category_products_with_fallback(self, category_url: str, category_num: int, total_categories: int, navigation_tree: dict = None, test_mode: bool = False) -> dict:
        """
        Try each pattern by actually extracting. Keep results from first that works.

        Args:
            category_url: URL of the category to extract
            category_num: Current category number
            total_categories: Total number of categories
            navigation_tree: Navigation tree to determine hierarchy path
            test_mode: If True, save images to tests/results directory

        Returns:
            Extraction results from first working pattern, or error if none work
        """
        from page_extractor import extract_category_name

        category_name = extract_category_name(category_url)

        # Try all existing patterns first
        for i, pattern in enumerate(self.discovered_patterns):
            print(f"      🔍 Trying pattern {i+1}/{len(self.discovered_patterns)}...")

            result = self._extract_category_products(
                category_url, pattern, category_num, total_categories,
                navigation_tree=navigation_tree,
                test_mode=test_mode
            )

            # If we got products, this pattern works - use it!
            if result.get("products"):
                print(f"      ✅ Pattern {i+1} worked - got {len(result['products'])} products")
                return result
            else:
                print(f"      ❌ Pattern {i+1} failed - no products")

        # All patterns failed - try discovering new pattern
        print(f"      🆕 All patterns failed - discovering new pattern...")

        try:
            # Use existing pattern discovery logic
            self.starting_pages_queue = [category_url]
            self.product_pages = [category_url]

            pattern_result = self.analyze_product_pattern()
            if pattern_result and pattern_result.get("extraction_pattern"):
                new_pattern = pattern_result["extraction_pattern"]

                # Store in global patterns list
                self.discovered_patterns.append(new_pattern)
                print(f"      ✅ New pattern discovered!")
                print(f"      📊 Total discovered patterns: {len(self.discovered_patterns)}")

                # Extract with new pattern
                result = self._extract_category_products(
                    category_url, new_pattern, category_num, total_categories,
                    navigation_tree=navigation_tree,
                    test_mode=test_mode
                )
                return result

        except Exception as e:
            print(f"      ❌ Pattern discovery failed: {e}")

        # Everything failed
        return {
            "name": category_name,
            "url": category_url,
            "products": [],
            "error": "No working pattern found"
        }

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
            import traceback
            print(f"         ❌ Pattern discovery failed: {e}")
            print(f"         📋 Traceback:")
            traceback.print_exc()

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
    
    def _extract_category_products(self, category_url: str, pattern: dict, category_num: int, total_categories: int, navigation_tree: dict = None, test_mode: bool = False) -> dict:
        """
        Extract all products from a single category with multi-page support and image downloads

        Args:
            category_url: URL of the category to extract
            pattern: Extraction pattern to use
            category_num: Current category number
            total_categories: Total number of categories
            navigation_tree: Navigation tree to determine hierarchy path
            test_mode: If True, save images to tests/results directory
        """
        from page_extractor import extract_products_from_page, extract_category_name
        import time

        category_name = extract_category_name(category_url)

        # Get the hierarchical path for this category
        if navigation_tree:
            category_path = self._get_category_hierarchy_path(category_url, navigation_tree)
        else:
            category_path = [category_name]

        print(f"      📂 Extracting from: {' > '.join(category_path)}")

        start_time = time.time()

        try:
            # Extract products from page 1
            extraction_result = extract_products_from_page(
                category_url, [pattern], category_name,
                allow_pattern_discovery=False,  # Don't discover new patterns on secondary pages
                brand_instance=self  # Pass brand instance for global learning
            )

            products = extraction_result.get("products", [])
            pagination_detected = extraction_result.get("pagination_detected", {})
            pages_extracted = 1

            print(f"         📦 Found {len(products)} products on page 1")

            # Multi-page extraction if pagination was detected
            if pagination_detected.get("pagination_found", False):
                from page_extractor import extract_multi_page_products
                from urllib.parse import urlparse

                print(f"         🔗 Multi-page pagination detected...")

                brand_name = urlparse(self.url).netloc.replace('www.', '').split('.')[0]
                multi_page_result = extract_multi_page_products(
                    category_url, pattern, brand_name, category_name,
                    brand_instance=self,
                    pagination_result=pagination_detected
                )

                additional_products = multi_page_result.get("products", [])
                pages_extracted += multi_page_result.get("pages_extracted", 0)

                if additional_products:
                    print(f"         ✅ Multi-page: {len(additional_products)} products from {pages_extracted - 1} additional pages")
                    products.extend(additional_products)
                else:
                    print(f"         📄 Multi-page: No additional products found")

            # Deduplicate products by URL across all pages
            seen_urls = set()
            unique_products = []
            for product in products:
                product_url_field = product.get("product_url", "")
                if product_url_field and product_url_field not in seen_urls:
                    seen_urls.add(product_url_field)
                    unique_products.append(product)

            duplicates_removed = len(products) - len(unique_products)
            if duplicates_removed > 0:
                print(f"         🔄 Removed {duplicates_removed} duplicate products")

            extraction_time = time.time() - start_time
            print(f"         📦 Total: {len(unique_products)} unique products from {pages_extracted} pages")

            # Queue images for async download (non-blocking) - after deduplication
            images_queued = 0
            if unique_products:
                images_queued = self._queue_category_images_for_download(unique_products, category_path, category_url)

            return {
                "name": category_name,
                "url": category_url,
                "products": unique_products,
                "pattern_used": pattern,
                "extraction_stats": {
                    "pages_processed": pages_extracted,
                    "products_found": len(unique_products),
                    "images_queued": images_queued,
                    "extraction_time": extraction_time,
                    "duplicates_removed": duplicates_removed
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
    
    def _download_category_images(self, products: List[dict], category_path: List[str], test_mode: bool = False) -> int:
        """
        Download images for all products in a category

        Args:
            products: List of product dicts with image information
            category_path: Hierarchical path as list (e.g., ['Clothing', 'Tops', 'T-Shirts'])
            test_mode: If True, save to tests/results directory

        Returns:
            Number of images successfully downloaded
        """
        import os
        import requests
        from urllib.parse import urlparse

        if not products:
            return 0

        # Build directory path based on hierarchy
        brand_name = urlparse(self.url).netloc.replace('www.', '').split('.')[0]

        # Create hierarchical directory structure
        if test_mode:
            # Save to tests/results/{brand_name}/{hierarchy}/
            base_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                'tests', 'results', brand_name
            )
        else:
            # Save to {brand_name}/{hierarchy}/ (for production)
            base_dir = brand_name

        # Build the full path using the hierarchy
        path_components = [comp.replace(' ', '_').replace('/', '_') for comp in category_path]
        images_dir = os.path.join(base_dir, *path_components)
        os.makedirs(images_dir, exist_ok=True)

        downloaded_count = 0

        for product in products:
            try:
                images = product.get("images", [])
                if not images:
                    continue

                # Download ALL images for this product
                product_name = product.get("product_name", "unknown").replace(" ", "_").replace("/", "_")[:50]

                for img_index, image in enumerate(images, 1):
                    image_url = image.get("src")
                    if not image_url:
                        continue

                    # Generate filename with index for multiple images
                    extension = os.path.splitext(urlparse(image_url).path)[1] or '.jpg'
                    if len(images) > 1:
                        # Multiple images: Product_Name_1.jpg, Product_Name_2.jpg, etc.
                        filename = f"{product_name}_{img_index}{extension}"
                    else:
                        # Single image: Product_Name.jpg
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

    def _queue_category_images_for_download(self, products: List[dict], category_path: List[str], category_url: str) -> int:
        """
        Queue all images from products for asynchronous download by background workers

        Args:
            products: List of product dicts with image information
            category_path: Hierarchical path as list (e.g., ['Clothing', 'Tops', 'T-Shirts'])
            category_url: Category URL for stats attribution

        Returns:
            Number of images queued
        """
        import os
        from urllib.parse import urlparse

        if not products:
            return 0

        # Get brand name for task
        brand_name = urlparse(self.url).netloc.replace('www.', '').split('.')[0]

        images_queued = 0

        for product in products:
            try:
                images = product.get("images", [])
                if not images:
                    continue

                product_name = product.get("product_name", "unknown").replace(" ", "_").replace("/", "_")[:50]

                # Queue each image as a separate task
                for img_index, image in enumerate(images, 1):
                    image_url = image.get("src")
                    if not image_url:
                        continue

                    # Create download task
                    task = {
                        "product_name": product_name,
                        "image_url": image_url,
                        "category_path": category_path,
                        "brand_name": brand_name,
                        "test_mode": self.test_mode,
                        "image_index": img_index,
                        "total_images": len(images),
                        "category_url": category_url
                    }

                    # Add to queue
                    self.image_download_queue.put(task)
                    images_queued += 1

            except Exception:
                continue  # Skip problematic products

        # Update stats
        if images_queued > 0:
            with self.image_stats_lock:
                self.image_stats["total_queued"] += images_queued

                # Initialize category stats if needed
                if category_url not in self.image_stats["by_category"]:
                    self.image_stats["by_category"][category_url] = {
                        "queued": 0,
                        "downloaded": 0,
                        "failed": 0,
                        "failed_urls": []
                    }

                self.image_stats["by_category"][category_url]["queued"] += images_queued

            print(f"         📤 {images_queued} images added to download queue")

        return images_queued

    def _save_pipeline_results_to_json(self, results: dict):
        """Save pipeline results to JSON file"""
        import json
        import os
        from urllib.parse import urlparse

        # Generate filename from brand URL
        brand_name = urlparse(self.url).netloc.replace('www.', '').split('.')[0]
        filename = f"{brand_name}_extraction_results.json"

        # Determine results directory based on test_mode
        if self.test_mode:
            # Save to tests/results directory
            results_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                'tests', 'results'
            )
        else:
            # Save to results directory in current working directory
            results_dir = "results"

        # Create results directory if needed
        os.makedirs(results_dir, exist_ok=True)
        filepath = os.path.join(results_dir, filename)

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