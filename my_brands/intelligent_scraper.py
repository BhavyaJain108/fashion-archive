#!/usr/bin/env python3
"""
Intelligent Web Scraper
=======================

LLM-powered scraping system that makes intelligent decisions at each step.
Follows the methodology: Navigation Page → Category Pages → Product Pages → Products
"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from typing import List, Dict, Any, Optional, Tuple
import time
import json
from dataclasses import dataclass
import sys
import os
# Add parent directory to path for llm_interface import  
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Ensure .env is loaded
from dotenv import load_dotenv
load_dotenv()

from llm_interface import get_llm_client


@dataclass
class ScrapingDecision:
    """LLM decision about what to do next"""
    page_type: str  # 'navigation', 'products', 'single_product', 'unknown'
    action: str  # 'scrape_products', 'follow_categories', 'follow_all_products', 'paginate'
    elements: List[Dict[str, str]]  # Relevant elements (links, products, etc.)
    reasoning: str  # LLM explanation
    confidence: float  # 0.0-1.0


@dataclass 
class Product:
    """Scraped product information"""
    title: str
    image_url: str
    product_url: str
    price: Optional[str] = None
    confidence: float = 0.0
    detection_method: str = "intelligent_scraper"
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


class IntelligentScraper:
    """LLM-powered intelligent web scraper"""
    
    def __init__(self):
        self.llm = get_llm_client()
        self.session = requests.Session()
        # Enhanced headers to appear more like a real browser
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'max-age=0'
        })
        self.visited_urls = set()
        self.max_pages = 10  # Prevent infinite loops
        
    def scrape(self, url: str, config: Dict[str, Any] = None) -> ScrapingResult:
        """Main scraping entry point"""
        print(f"🤖 Starting intelligent scrape of: {url}")
        
        try:
            # Reset state
            self.visited_urls.clear()
            all_products = []
            errors = []
            
            # Start with the main page
            products, page_errors = self._scrape_page_intelligently(url)
            all_products.extend(products)
            errors.extend(page_errors)
            
            return ScrapingResult(
                success=len(all_products) > 0,
                products=all_products,
                total_found=len(all_products),
                strategy_used="intelligent_llm_guided",
                confidence=0.9 if all_products else 0.1,
                errors=errors
            )
            
        except Exception as e:
            print(f"❌ Intelligent scraping failed: {e}")
            return ScrapingResult(
                success=False,
                products=[],
                total_found=0,
                strategy_used="intelligent_llm_guided", 
                confidence=0.0,
                errors=[str(e)]
            )
    
    def _scrape_page_intelligently(self, url: str) -> Tuple[List[Product], List[str]]:
        """Scrape a single page using LLM guidance"""
        if url in self.visited_urls or len(self.visited_urls) >= self.max_pages:
            return [], []
            
        self.visited_urls.add(url)
        print(f"🧠 Analyzing page: {url}")
        
        try:
            # Add random delay to seem more human-like
            time.sleep(1)
            
            # Fetch page content
            response = self.session.get(url, timeout=15)
            print(f"📄 Response status: {response.status_code}")
            
            if response.status_code == 403:
                print("⚠️  Access forbidden - site may be blocking scrapers")
                return [], [f"Access forbidden to {url}"]
            elif response.status_code == 429:
                print("⚠️  Rate limited - too many requests")
                return [], [f"Rate limited for {url}"]
                
            response.raise_for_status()
            
            # Debug: Save HTML to see what we're getting
            print(f"📄 Response length: {len(response.content)} bytes")
            print(f"📄 Content type: {response.headers.get('content-type', 'unknown')}")
            
            if len(response.content) == 0:
                print("⚠️  Empty response - trying browser automation fallback")
                return self._scrape_with_browser(url)
            
            print(f"📄 Response preview: {response.text[:500]}...")
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Check if page appears to be minimally rendered (JS-heavy site)
            if self._is_js_rendered_page(soup):
                print("⚠️  Page appears to be JavaScript-rendered - trying browser automation")
                return self._scrape_with_browser(url)
            
            # Get LLM decision about this page
            decision = self._get_llm_decision(url, soup)
            print(f"🎯 LLM Decision: {decision.page_type} → {decision.action}")
            print(f"💭 LLM Reasoning: {decision.reasoning}")
            print(f"📋 LLM Found {len(decision.elements)} elements: {[elem.get('text', 'N/A')[:30] for elem in decision.elements[:3]]}")
            
            all_products = []
            errors = []
            
            # Execute the LLM's decision
            if decision.action == 'scrape_products':
                products = self._extract_products_from_page(soup, url, decision)
                all_products.extend(products)
                
                # If no products found with requests, try browser automation
                if len(products) == 0:
                    print("⚠️  No products found with requests - trying browser automation fallback")
                    browser_products, browser_errors = self._scrape_with_browser(url)
                    all_products.extend(browser_products)
                    errors.extend(browser_errors)
                
                # Check for pagination
                if decision.page_type == 'products':
                    paginated_products, page_errors = self._handle_pagination(soup, url, decision)
                    all_products.extend(paginated_products)
                    errors.extend(page_errors)
                    
            elif decision.action == 'follow_categories':
                # Follow category links
                print(f"🗂️  LLM found {len(decision.elements)} category elements:")
                for i, elem in enumerate(decision.elements[:5]):
                    print(f"   {i+1}. {elem.get('text', 'No text')} → {elem.get('href', 'No URL')}")
                
                # If LLM didn't find good elements, use manual detection
                elements_to_use = decision.elements
                if len(decision.elements) == 0 or not any(elem.get('href') for elem in decision.elements):
                    print("🔧 LLM elements empty/invalid - using manual collection detection")
                    elements_to_use = self._manual_collection_detection(soup, url)
                    print(f"🔧 Manual detection found {len(elements_to_use)} collections")
                
                category_products, cat_errors = self._follow_category_links(elements_to_use, url)
                all_products.extend(category_products)
                errors.extend(cat_errors)
                
            elif decision.action == 'follow_all_products':
                # Follow "all products" or "shop all" link
                if decision.elements:
                    all_products_url = urljoin(url, decision.elements[0].get('href', ''))
                    print(f"🛒 Following 'all products' link: {all_products_url}")
                    products, page_errors = self._scrape_page_intelligently(all_products_url)
                    all_products.extend(products)
                    errors.extend(page_errors)
                else:
                    print("⚠️  No 'all products' link found in decision elements")
            
            return all_products, errors
            
        except Exception as e:
            print(f"❌ Error analyzing page {url}: {e}")
            return [], [str(e)]
    
    def _get_llm_decision(self, url: str, soup: BeautifulSoup) -> ScrapingDecision:
        """Ask LLM to analyze page and decide what to do"""
        
        # Extract key HTML elements for analysis
        html_sample = self._extract_html_sample(soup)
        
        prompt = f"""
        Analyze this webpage and decide how to scrape products from it.
        
        URL: {url}
        HTML Sample:
        {html_sample}
        
        Classify this page and decide the action:
        
        PAGE TYPES:
        - 'navigation': Homepage/landing with category links (Men, Women, Accessories, etc.)
        - 'products': Product listing page with multiple products
        - 'single_product': Individual product page
        - 'unknown': Can't determine
        
        ACTIONS:
        - 'scrape_products': Extract products directly from this page
        - 'follow_categories': Navigate to multiple category/collection pages (e.g. Collection 1, Collection 2, Drop 10, Archives, etc.)
        - 'follow_all_products': Navigate to single "Shop All" or "All Products" page
        - 'paginate': Handle pagination/load more
        
        PRIORITY: If you see multiple collections or categories (like "Drop 10", "Collection", "Archive"), use 'follow_categories' to capture all of them.
        
        IMPORTANT: Respond with ONLY the JSON object, no additional text or explanation.
        
        {{
            "page_type": "navigation|products|single_product|unknown",
            "action": "scrape_products|follow_categories|follow_all_products|paginate",
            "elements": [
                {{"text": "element text", "href": "relative_url", "selector": "css_selector"}}
            ],
            "reasoning": "explanation of decision",
            "confidence": 0.95
        }}
        
        Focus on finding:
        1. Product grids/listings
        2. Collection navigation (Drop 10, Collection, Archive, Season names, etc.)
        3. Category navigation (Men, Women, All Products, etc.)
        4. Pagination controls
        5. Product links and images
        
        For fashion brands, look especially for:
        - Collection names (Drop, Season, Archive, etc.)
        - Links to different product categories
        - Navigation menus with multiple destination
        """
        
        try:
            response = self.llm.generate(prompt, max_tokens=1000, temperature=0.1)
            
            # Try to extract JSON from the response (Claude sometimes adds extra text)
            try:
                decision_data = json.loads(response)
            except json.JSONDecodeError:
                # Try to find JSON within the response
                import re
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    decision_data = json.loads(json_match.group())
                else:
                    raise ValueError("No valid JSON found in LLM response")
            
            return ScrapingDecision(
                page_type=decision_data.get('page_type', 'unknown'),
                action=decision_data.get('action', 'scrape_products'),
                elements=decision_data.get('elements', []),
                reasoning=decision_data.get('reasoning', ''),
                confidence=decision_data.get('confidence', 0.5)
            )
            
        except Exception as e:
            print(f"⚠️  LLM decision failed: {e}")
            # Fallback to simple heuristics
            return self._fallback_decision(soup, url)
    
    def _extract_html_sample(self, soup: BeautifulSoup) -> str:
        """Extract relevant HTML for LLM analysis"""
        
        # Remove scripts, styles, etc.
        for element in soup(['script', 'style', 'noscript', 'iframe']):
            element.decompose()
        
        # Focus on key areas
        key_sections = []
        
        # Navigation/header
        nav = soup.find(['nav', 'header']) or soup.find(class_=lambda x: x and any(word in x.lower() for word in ['nav', 'header', 'menu']))
        if nav:
            key_sections.append(str(nav)[:1000])
        
        # Main content area
        main = soup.find(['main', 'section']) or soup.find(class_=lambda x: x and any(word in x.lower() for word in ['main', 'content', 'products', 'grid']))
        if main:
            key_sections.append(str(main)[:2000])
        
        # Product-like elements
        product_elements = soup.find_all(class_=lambda x: x and any(word in x.lower() for word in ['product', 'item', 'card', 'grid']))
        for elem in product_elements[:3]:  # First 3
            key_sections.append(str(elem)[:500])
        
        # Links that might be categories
        category_links = soup.find_all('a', href=True)
        category_text = []
        for link in category_links[:10]:  # First 10 links
            text = link.get_text(strip=True).lower()
            if any(word in text for word in ['men', 'women', 'all', 'shop', 'category', 'collection']):
                category_text.append(f'<a href="{link.get("href")}">{link.get_text(strip=True)}</a>')
        
        if category_text:
            key_sections.append("Category Links: " + ", ".join(category_text))
        
        return "\n\n".join(key_sections)[:4000]  # Limit total size
    
    def _fallback_decision(self, soup: BeautifulSoup, url: str) -> ScrapingDecision:
        """Fallback decision making when LLM fails"""
        
        # Simple heuristics
        product_indicators = soup.find_all(class_=lambda x: x and any(word in x.lower() for word in ['product', 'item']))
        
        if len(product_indicators) >= 3:
            return ScrapingDecision(
                page_type='products',
                action='scrape_products', 
                elements=[],
                reasoning='Fallback: Found multiple product indicators',
                confidence=0.6
            )
        else:
            return ScrapingDecision(
                page_type='navigation',
                action='follow_categories',
                elements=[],
                reasoning='Fallback: Assuming navigation page',
                confidence=0.3
            )
    
    def _extract_products_from_page(self, soup: BeautifulSoup, base_url: str, decision: ScrapingDecision) -> List[Product]:
        """Extract products from a product listing page using LLM guidance"""
        
        print(f"📦 Extracting products from page...")
        
        # Get more detailed product structure from LLM
        product_structure_decision = self._get_product_extraction_guidance(soup, base_url, decision)
        print(f"🎯 Product Structure: {product_structure_decision.get('primary_selector', 'Not found')}")
        
        products = []
        
        # Use LLM-identified selectors to find product elements
        product_elements = self._find_products_using_llm_guidance(soup, product_structure_decision)
        
        print(f"🔍 Found {len(product_elements)} potential product elements")
        
        for i, element in enumerate(product_elements):  # Process all found elements
            try:
                # Extract product info
                title = self._extract_product_title(element)
                image_url = self._extract_product_image(element, base_url)
                product_url = self._extract_product_url(element, base_url)
                price = self._extract_product_price(element)
                
                # Debug first few elements and show progress
                if i < 3:
                    classes = element.get('class', [])
                    print(f"   Debug element {i}: classes={classes[:2]}, title='{title}', image='{str(image_url)[:50] if image_url else None}', price='{price}'")
                elif i % 50 == 0:  # Progress updates every 50 elements
                    print(f"   Processing element {i}/{len(product_elements)}...")
                
                # For image-heavy sites, accept products with just images if no titles found
                if image_url and ('.webp' in image_url or '.jpg' in image_url or '.png' in image_url):
                    # Generate a title from the image URL if no title found
                    if not title:
                        # Extract filename and clean it up
                        from urllib.parse import urlparse
                        path = urlparse(image_url).path
                        filename = path.split('/')[-1].split('.')[0]
                        # Clean up filename to make a readable title
                        title = filename.replace('-', ' ').replace('_', ' ').title()
                        if len(title) < 3:
                            title = f"Entire Studios Product {i+1}"
                    
                    # Check for duplicates (same image URL)
                    if not any(p.image_url == image_url for p in products):
                        products.append(Product(
                            title=title,
                            image_url=image_url,
                            product_url=product_url or base_url,
                            price=price or "Price not available",
                            confidence=0.7,  # Lower confidence without price
                            detection_method="llm_guided_extraction"
                        ))
                    
            except Exception as e:
                print(f"⚠️  Error extracting product {i}: {e}")
                continue
        
        print(f"✅ Extracted {len(products)} products")
        return products
    
    def _get_product_extraction_guidance(self, soup: BeautifulSoup, base_url: str, decision: ScrapingDecision) -> Dict[str, Any]:
        """Ask LLM to identify specific product selectors"""
        
        # Get a focused HTML sample of the products area
        products_html = self._extract_products_html_sample(soup)
        
        prompt = f"""
        Analyze this product listing page HTML and identify the exact CSS selectors to extract products.
        
        URL: {base_url}
        Products Area HTML:
        {products_html}
        
        I need you to identify the EXACT CSS selectors that will find:
        1. The container element for each individual product
        2. The title/name element within each product
        3. The image element within each product  
        4. The price element within each product
        5. The product link element
        
        IMPORTANT: Respond with ONLY the JSON object, no additional text.
        
        {{
            "primary_selector": "css_selector_for_product_containers",
            "title_selector": "css_selector_for_titles_within_product",
            "image_selector": "css_selector_for_images_within_product", 
            "price_selector": "css_selector_for_prices_within_product",
            "link_selector": "css_selector_for_links_within_product",
            "confidence": 0.9,
            "reasoning": "explanation of selectors chosen"
        }}
        """
        
        try:
            response = self.llm.generate(prompt, max_tokens=600, temperature=0.1)
            
            # Extract JSON from response
            try:
                guidance = json.loads(response)
            except json.JSONDecodeError:
                # Try to find JSON within the response
                import re
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    guidance = json.loads(json_match.group())
                else:
                    raise ValueError("No valid JSON found in LLM response")
            
            return guidance
            
        except Exception as e:
            print(f"⚠️  Product extraction guidance failed: {e}")
            # Fallback to basic selectors
            return {
                "primary_selector": ".product, .item, [class*='product'], [class*='item']",
                "title_selector": "h2, h3, .title, .name, .product-title",
                "image_selector": "img",
                "price_selector": ".price, .cost, [class*='price']",
                "link_selector": "a",
                "confidence": 0.3,
                "reasoning": "Fallback selectors due to LLM failure"
            }
    
    def _extract_products_html_sample(self, soup: BeautifulSoup) -> str:
        """Extract HTML sample focused on product listings"""
        
        # Look for main content areas that likely contain products
        product_areas = []
        
        # Try to find main content areas
        main_selectors = [
            'main', '[role="main"]', '.main', '#main',
            '.products', '.product-grid', '.collection', 
            '.items', '.grid', '[class*="product"]'
        ]
        
        for selector in main_selectors:
            elements = soup.select(selector)
            for elem in elements:
                if elem and len(str(elem)) > 500:  # Substantial content
                    product_areas.append(str(elem)[:2000])  # First 2000 chars
        
        # If no specific areas found, use body content
        if not product_areas:
            body = soup.find('body')
            if body:
                product_areas.append(str(body)[:3000])
        
        return '\n\n'.join(product_areas[:2])  # Max 2 areas
    
    def _find_products_using_llm_guidance(self, soup: BeautifulSoup, guidance: Dict[str, Any]) -> List:
        """Find product elements using LLM-provided selectors"""
        
        primary_selector = guidance.get('primary_selector', '.product')
        print(f"🎯 Trying primary selector: '{primary_selector}'")
        
        try:
            # Try the LLM-provided selector first
            product_elements = soup.select(primary_selector)
            print(f"🎯 Primary selector found: {len(product_elements)} elements")
            
            if product_elements:
                return product_elements
                
        except Exception as e:
            print(f"⚠️  LLM selector failed: {e}")
        
        # Debug: Let's see what elements are actually available
        print("🔍 Debugging available elements:")
        li_elements = soup.find_all('li')
        print(f"   Total <li> elements: {len(li_elements)}")
        
        grid_elements = soup.find_all(attrs={'class': lambda x: x and 'grid' in ' '.join(x).lower()})
        print(f"   Elements with 'grid' class: {len(grid_elements)}")
        
        item_elements = soup.find_all(attrs={'class': lambda x: x and 'item' in ' '.join(x).lower()})
        print(f"   Elements with 'item' class: {len(item_elements)}")
        
        # Show first few li elements for debugging
        for i, li in enumerate(li_elements[:5]):
            classes = li.get('class', [])
            text_preview = li.get_text(strip=True)[:50] if li.get_text(strip=True) else "no text"
            has_img = "✓" if li.find('img') else "✗"
            print(f"   li[{i}] classes: {classes}, text: {text_preview}, img: {has_img}")
        
        # Debug webp files specifically
        webp_images = soup.find_all('img', src=lambda x: x and '.webp' in x)
        print(f"   Found {len(webp_images)} WebP images")
        for i, img in enumerate(webp_images[:3]):
            src = img.get('src', 'no-src')
            parent_classes = img.parent.get('class', []) if img.parent else []
            print(f"   webp[{i}]: {src[:60]}... (parent: {parent_classes})")
        
        # Debug: find elements that actually contain WebP images
        webp_containers = []
        for img in webp_images:
            container = img.parent
            level = 0
            while container and level < 4:  # Go up 4 levels max
                classes = container.get('class', [])
                if classes:
                    webp_containers.append((container.name, list(classes)))  # Convert to list
                    break
                container = container.parent
                level += 1
        
        # Get unique container patterns
        unique_containers = []
        seen = set()
        for name, classes in webp_containers:
            key = (name, tuple(sorted(classes)))
            if key not in seen:
                seen.add(key)
                unique_containers.append((name, classes))
                if len(unique_containers) >= 5:
                    break
                    
        print(f"   WebP parent containers: {unique_containers}")
        
        # Fallback to common product selectors, including site-specific ones
        fallback_selectors = [
            '.es-character-image',  # Found from WebP analysis  
            '[class*="character"]', '[class*="es-"]',  # Site-specific patterns
            'li[class*="grid"]', 'li[class*="item"]', 'li[class*="product"]',
            '.product', '.item', '.card',
            '[class*="product"]', '[class*="item"]', '[class*="card"]',
            'article', '.grid-item'
        ]
        
        for selector in fallback_selectors:
            try:
                elements = soup.select(selector)
                print(f"🔍 Fallback '{selector}': {len(elements)} elements")
                if elements and len(elements) >= 1:  # Even 1 product is worth trying
                    return elements
            except Exception as e:
                print(f"⚠️  Fallback selector '{selector}' failed: {e}")
                continue
                
        return []
    
    def _identify_product_structure(self, soup: BeautifulSoup) -> Dict[str, str]:
        """Legacy method - kept for compatibility"""
        return {
            'title_selector': 'h2, h3, .title, .name, .product-title',
            'image_selector': 'img',
            'price_selector': '.price, .cost, [class*="price"]',
            'link_selector': 'a'
        }
    
    def _extract_product_title(self, element) -> Optional[str]:
        """Extract product title from element"""
        # For image-based elements, look for title in parent containers
        if 'es-character-image' in element.get('class', []):
            # Go up to find the product container
            parent = element.parent
            for level in range(4):
                if not parent:
                    break
                # Look for title in this container
                title_elem = parent.find(attrs={'class': lambda x: x and any(word in ' '.join(x).lower() for word in ['title', 'name', 'product'])})
                if title_elem:
                    text = title_elem.get_text(strip=True)
                    if text and len(text) > 3:
                        return text[:100]
                parent = parent.parent
        
        # Try multiple standard approaches
        title_selectors = ['h2', 'h3', '.title', '.name', '.product-title', 'a']
        
        for selector in title_selectors:
            title_elem = element.select_one(selector)
            if title_elem:
                text = title_elem.get_text(strip=True)
                if text and len(text) > 3:
                    return text[:100]  # Limit length
        
        # Fallback: use alt text from first image
        img = element.find('img')
        if img and img.get('alt'):
            alt_text = img.get('alt').strip()
            if len(alt_text) > 3:
                return alt_text[:100]
        
        return None
    
    def _extract_product_image(self, element, base_url: str) -> Optional[str]:
        """Extract product image URL"""
        # For es-character-image elements, the element itself contains the image
        if 'es-character-image' in element.get('class', []):
            img = element.find('img')
            if img:
                # Try multiple src attributes
                src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
                if src:
                    # Handle relative URLs
                    if src.startswith('//'):
                        src = 'https:' + src
                    elif src.startswith('/'):
                        src = urljoin(base_url, src)
                    return src
        
        # Standard image extraction
        img = element.find('img')
        if img:
            src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
            if src:
                return urljoin(base_url, src)
        
        return None
    
    def _extract_product_url(self, element, base_url: str) -> Optional[str]:
        """Extract product page URL"""
        link = element.find('a', href=True)
        if link:
            return urljoin(base_url, link['href'])
        
        return None
    
    def _extract_product_price(self, element) -> Optional[str]:
        """Extract product price"""
        price_selectors = ['.price', '.cost', '[class*="price"]', '[class*="cost"]']
        
        for selector in price_selectors:
            price_elem = element.select_one(selector)
            if price_elem:
                price_text = price_elem.get_text(strip=True)
                if any(char in price_text for char in '$€£¥₹'):
                    return price_text[:20]  # Limit length
        
        return None
    
    def _follow_category_links(self, category_elements: List[Dict], base_url: str) -> Tuple[List[Product], List[str]]:
        """Follow category links with dynamic parallel batching based on performance"""
        
        print(f"🗂️  Following {len(category_elements)} category links...")
        print("📋 Found collections:")
        for i, category in enumerate(category_elements[:10]):  # Show first 10
            name = category.get('text', 'Unknown')
            href = category.get('href', 'No URL')
            print(f"   {i+1}. {name} → {href}")
        
        all_products = []
        errors = []
        
        # DYNAMIC PARALLEL BATCHING
        print("🚀 DYNAMIC PARALLEL MODE: Adaptive batching based on performance")
        
        import time
        import concurrent.futures
        from threading import Lock
        
        # Dynamic batching parameters
        initial_batch_size = 15  # Start smaller for faster first results
        min_batch_size = 10
        max_batch_size = 50
        target_time_per_batch = 30.0  # Target 30 seconds per batch
        max_parallel_collections = 3  # Process 3 collections simultaneously
        
        products_lock = Lock()
        performance_stats = {'total_time': 0, 'total_products': 0, 'collections_processed': 0}
        
        def scrape_collection_batch(collection_info, current_batch_size):
            """Scrape a single collection with performance tracking"""
            category_url, collection_name, collection_index = collection_info
            start_time = time.time()
            
            try:
                print(f"📂 [{collection_index}] Starting {collection_name} (batch_size: {current_batch_size})")
                
                collection_products, collection_errors = self._scrape_collection_progressively(
                    category_url, collection_name, current_batch_size
                )
                
                # Tag products with collection information
                for product in collection_products:
                    product.collection_name = collection_name
                    product.collection_url = category_url
                
                elapsed = time.time() - start_time
                products_per_second = len(collection_products) / max(elapsed, 0.1)
                
                print(f"   ✅ [{collection_index}] {collection_name}: {len(collection_products)} products in {elapsed:.1f}s ({products_per_second:.1f} p/s)")
                
                return {
                    'products': collection_products,
                    'errors': collection_errors,
                    'elapsed': elapsed,
                    'collection_name': collection_name,
                    'products_count': len(collection_products)
                }
                
            except Exception as e:
                elapsed = time.time() - start_time
                error_msg = f"Error loading {collection_name}: {e}"
                print(f"   ❌ [{collection_index}] {error_msg} ({elapsed:.1f}s)")
                return {
                    'products': [],
                    'errors': [error_msg],
                    'elapsed': elapsed,
                    'collection_name': collection_name,
                    'products_count': 0
                }
        
        # Prepare collection info
        collection_tasks = []
        for i, category in enumerate(category_elements[:10]):
            category_url = urljoin(base_url, category.get('href', ''))
            if category_url and category_url not in self.visited_urls:
                collection_name = category.get('text', 'Unknown')
                collection_tasks.append((category_url, collection_name, i+1))
        
        current_batch_size = initial_batch_size
        processed_collections = 0
        batch_start_time = time.time()
        
        # Process collections in parallel batches
        while processed_collections < len(collection_tasks) and len(all_products) < 100:  # Stop at 100 products
            batch_collections = collection_tasks[processed_collections:processed_collections + max_parallel_collections]
            batch_size = min(len(batch_collections), max_parallel_collections)
            
            print(f"\n🔄 Processing batch of {batch_size} collections (batch_size: {current_batch_size})")
            
            batch_start = time.time()
            
            # Execute collections in parallel
            with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as executor:
                future_to_collection = {
                    executor.submit(scrape_collection_batch, collection_info, current_batch_size): collection_info
                    for collection_info in batch_collections
                }
                
                batch_products = []
                batch_errors = []
                batch_performance = []
                
                for future in concurrent.futures.as_completed(future_to_collection):
                    result = future.result()
                    batch_products.extend(result['products'])
                    batch_errors.extend(result['errors'])
                    batch_performance.append({
                        'elapsed': result['elapsed'],
                        'products_count': result['products_count'],
                        'collection_name': result['collection_name']
                    })
            
            batch_elapsed = time.time() - batch_start
            total_batch_products = len(batch_products)
            
            # Add products to main collection
            all_products.extend(batch_products)
            errors.extend(batch_errors)
            
            # Update performance stats
            performance_stats['total_time'] += batch_elapsed
            performance_stats['total_products'] += total_batch_products
            performance_stats['collections_processed'] += len(batch_collections)
            
            print(f"📊 Batch complete: {total_batch_products} products in {batch_elapsed:.1f}s")
            
            # DYNAMIC BATCH SIZE ADJUSTMENT
            if batch_performance:
                avg_time = sum(p['elapsed'] for p in batch_performance) / len(batch_performance)
                avg_products = sum(p['products_count'] for p in batch_performance) / len(batch_performance)
                
                if avg_time < target_time_per_batch * 0.5:  # Too fast, increase batch size
                    new_batch_size = min(current_batch_size + 10, max_batch_size)
                    if new_batch_size != current_batch_size:
                        print(f"⚡ Performance good, increasing batch size: {current_batch_size} → {new_batch_size}")
                        current_batch_size = new_batch_size
                        
                elif avg_time > target_time_per_batch:  # Too slow, decrease batch size
                    new_batch_size = max(current_batch_size - 5, min_batch_size)
                    if new_batch_size != current_batch_size:
                        print(f"🐌 Performance slow, decreasing batch size: {current_batch_size} → {new_batch_size}")
                        current_batch_size = new_batch_size
                
                print(f"📈 Avg performance: {avg_time:.1f}s per collection, {avg_products:.1f} products per collection")
            
            processed_collections += len(batch_collections)
            
            # Early exit if we have enough products for initial display
            if len(all_products) >= 30:
                print(f"🎯 Reached target of 30+ products ({len(all_products)}), stopping for initial display")
                break
        
        # Performance summary
        total_elapsed = time.time() - batch_start_time
        if performance_stats['total_products'] > 0:
            overall_rate = performance_stats['total_products'] / max(total_elapsed, 0.1)
            print(f"\n🏁 FINAL STATS:")
            print(f"   • Total products: {len(all_products)}")
            print(f"   • Collections processed: {performance_stats['collections_processed']}")
            print(f"   • Total time: {total_elapsed:.1f}s")
            print(f"   • Overall rate: {overall_rate:.1f} products/second")
            print(f"   • Final batch size: {current_batch_size}")
        
        return all_products, errors
    
    def _scrape_collection_progressively(self, collection_url: str, collection_name: str, max_products: int) -> Tuple[List[Product], List[str]]:
        """Scrape a single collection with scroll/pagination support and product limits"""
        
        print(f"📄 Loading up to {max_products} products from {collection_name}")
        
        try:
            # First try with standard requests
            products, errors = self._scrape_page_intelligently(collection_url)
            
            # Filter out navigation results - we only want actual products
            actual_products = [p for p in products if p.detection_method != "navigation_discovery"]
            
            print(f"🔍 Found {len(products)} total results, {len(actual_products)} actual products from standard request")
            
            # If we didn't get enough actual products, try browser automation
            if len(actual_products) < max_products:
                print(f"⏬ Need more products, trying browser automation for {collection_name}")
                
                # Try browser automation for pages that require scrolling
                browser_products, browser_errors = self._scrape_with_browser(collection_url)
                
                print(f"🎭 Browser found {len(browser_products)} results")
                browser_actual = [p for p in browser_products if p.detection_method != "navigation_discovery"]
                print(f"🎭 Browser actual products: {len(browser_actual)}")
                
                # Merge browser results, avoiding duplicates and filtering navigation
                seen_urls = {p.product_url for p in actual_products if p.product_url}
                for bp in browser_products:
                    if (bp.detection_method != "navigation_discovery" and 
                        bp.product_url and bp.product_url not in seen_urls):
                        actual_products.append(bp)
                        if len(actual_products) >= max_products:
                            break
                
                errors.extend(browser_errors)
            
            # If we still don't have actual products, this might be a navigation page
            if len(actual_products) == 0 and len(products) > 0:
                print(f"⚠️  Collection {collection_name} appears to be a navigation page, not a product page")
                # Return the navigation results so they can be processed further up the chain
                return products[:max_products], errors
            
            # Limit to requested number of actual products
            final_products = actual_products[:max_products]
            
            print(f"📦 Collection {collection_name}: Final count = {len(final_products)} products")
            return final_products, errors
            
        except Exception as e:
            print(f"❌ Error scraping collection {collection_name}: {e}")
            return [], [str(e)]
    
    def _handle_pagination(self, soup: BeautifulSoup, current_url: str, decision: ScrapingDecision) -> Tuple[List[Product], List[str]]:
        """Handle pagination/next page links"""
        
        print(f"📄 Checking for pagination...")
        
        # Look for next page links
        next_links = soup.find_all('a', href=True)
        next_page_url = None
        
        for link in next_links:
            link_text = link.get_text(strip=True).lower()
            if any(word in link_text for word in ['next', 'more', '>', '→', 'page 2']):
                next_page_url = urljoin(current_url, link['href'])
                break
        
        if next_page_url and next_page_url not in self.visited_urls:
            print(f"➡️  Following pagination to: {next_page_url}")
            return self._scrape_page_intelligently(next_page_url)
        
        return [], []
    
    def _is_js_rendered_page(self, soup: BeautifulSoup) -> bool:
        """Detect if a page is likely JavaScript-rendered"""
        
        # Check for common indicators of JS-heavy sites
        body = soup.find('body')
        if not body:
            return True
            
        # Very small body content suggests JS rendering
        body_text = body.get_text(strip=True)
        if len(body_text) < 200:
            return True
            
        # Check for common JS framework indicators
        js_indicators = [
            'data-react', 'data-vue', 'ng-app', 'data-angular',
            '__NEXT_DATA__', '__nuxt', 'vue-app', 'react-app'
        ]
        
        page_html = str(soup).lower()
        if any(indicator.lower() in page_html for indicator in js_indicators):
            return True
            
        # Check for minimal content with loading indicators
        loading_indicators = [
            'loading', 'spinner', 'please wait', 'loading products'
        ]
        
        if any(indicator in body_text.lower() for indicator in loading_indicators):
            return True
            
        return False
    
    def _scrape_with_browser(self, url: str) -> Tuple[List[Product], List[str]]:
        """Scrape using Playwright browser automation"""
        
        try:
            from playwright.sync_api import sync_playwright
            
            print(f"🎭 Launching browser for: {url}")
            
            with sync_playwright() as p:
                # Launch browser with more realistic settings
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        '--no-sandbox',
                        '--disable-blink-features=AutomationControlled',
                        '--disable-web-security',
                        '--disable-dev-shm-usage'
                    ]
                )
                context = browser.new_context(
                    user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    viewport={'width': 1920, 'height': 1080},
                    locale='en-US',
                    timezone_id='America/New_York'
                )
                page = context.new_page()
                
                # Remove automation indicators
                page.evaluate("""
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined,
                    });
                """)
                
                try:
                    # Navigate to page and wait for content
                    print(f"🌐 Navigating to {url}")
                    page.goto(url, wait_until='networkidle', timeout=30000)
                    
                    # Wait for potential product content to load
                    print("⏳ Waiting for content to load...")
                    page.wait_for_timeout(3000)  # 3 second initial wait
                    
                    # Try progressive scrolling to load more products (for infinite scroll)
                    try:
                        print("⏬ Progressive scrolling to load products...")
                        scroll_attempts = 5  # Limit scrolling attempts
                        for scroll in range(scroll_attempts):
                            # Scroll to bottom gradually
                            page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {(scroll + 1) / scroll_attempts})")
                            page.wait_for_timeout(2000)  # Wait for content to load
                            
                            # Check if new products loaded by counting product elements
                            product_count = page.evaluate("""
                                document.querySelectorAll('img, .product, .item, [class*="product"], [class*="item"]').length
                            """)
                            print(f"   Scroll {scroll + 1}/{scroll_attempts}: {product_count} product elements found")
                            
                            # If we found a good number of products, we can stop early
                            if product_count >= 30:
                                print(f"   ✅ Found sufficient products ({product_count}), stopping scroll")
                                break
                        
                        # Scroll back to top for easier parsing
                        page.evaluate("window.scrollTo(0, 0)")
                        page.wait_for_timeout(1000)
                        
                        # Try to hover over potential navigation areas
                        page.evaluate("""
                            // Look for navigation elements and trigger hover
                            const navElements = document.querySelectorAll('nav, .nav, [class*="nav"], [class*="menu"]');
                            navElements.forEach(el => {
                                el.dispatchEvent(new Event('mouseenter'));
                            });
                        """)
                        page.wait_for_timeout(2000)
                    except Exception as e:
                        print(f"⚠️  Navigation trigger failed: {e}")
                        pass
                    
                    # Try to wait for product-related elements
                    try:
                        page.wait_for_selector('img, .product, .item, [class*="product"], [class*="item"]', timeout=10000)
                        print("✅ Found product elements!")
                    except:
                        print("⚠️  No product selectors found, continuing anyway")
                    
                    # Get the rendered HTML
                    html = page.content()
                    print(f"🎭 Browser rendered {len(html)} bytes of HTML")
                    
                    # Debug: Show a sample of what we got
                    if len(html) < 1000:
                        print(f"🎭 Full HTML content:\n{html}")
                    else:
                        print(f"🎭 HTML preview:\n{html[:1000]}...")
                    
                    # Parse with BeautifulSoup
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Debug: Look for navigation links manually
                    all_links = soup.find_all('a', href=True)
                    collection_links = []
                    for link in all_links:
                        href = link.get('href', '')
                        text = link.get_text(strip=True)
                        if any(word in href.lower() for word in ['collection', 'drop', 'archive']) or \
                           any(word in text.lower() for word in ['collection', 'drop', 'archive']):
                            collection_links.append({'text': text, 'href': href})
                    
                    if collection_links:
                        print(f"🔍 Manual collection link detection found {len(collection_links)} links:")
                        for i, link in enumerate(collection_links[:5]):
                            print(f"   {i+1}. {link['text']} → {link['href']}")
                    else:
                        print("🔍 No collection links found manually - checking all navigation links:")
                        nav_links = [{'text': link.get_text(strip=True)[:30], 'href': link.get('href')[:50]} 
                                   for link in all_links[:10] if link.get_text(strip=True)]
                        for i, link in enumerate(nav_links):
                            print(f"   {i+1}. {link['text']} → {link['href']}")
                    
                    # Check if we actually found product elements
                    has_product_elements = len(soup.find_all(['img', '*'], class_=lambda x: x and ('product' in x.lower() or 'item' in x.lower()))) > 0
                    image_count = len(soup.find_all('img'))
                    
                    print(f"🔍 Product analysis: {image_count} images, product elements: {has_product_elements}")
                    
                    # Use our existing LLM-guided extraction, but override for product pages
                    decision = self._get_llm_decision(url, soup)
                    print(f"🎯 Browser LLM Decision: {decision.page_type} → {decision.action}")
                    
                    products = []
                    
                    # OVERRIDE: If we have many images (indicating products), force product extraction
                    if image_count > 20 and '/collection/' in url:
                        print(f"🎯 OVERRIDE: Found {image_count} images on collection page - forcing product extraction")
                        decision.action = 'scrape_products'
                        decision.page_type = 'products'
                    
                    if decision.action == 'scrape_products':
                        products = self._extract_products_from_page(soup, url, decision)
                        print(f"🎭 Browser extracted {len(products)} products")
                    elif decision.action == 'follow_categories':
                        print(f"🎭 Browser found navigation page - TRIGGERING DYNAMIC PARALLEL BATCHING")
                        collections = self._manual_collection_detection(soup, url)
                        print(f"🎭 Browser found {len(collections)} collections, starting parallel scraping...")
                        
                        # TRIGGER DYNAMIC PARALLEL BATCHING from browser context
                        parallel_products, parallel_errors = self._follow_category_links(collections, url)
                        products.extend(parallel_products)
                        
                        print(f"🎭 Parallel batching completed: {len(parallel_products)} products from browser automation")
                    
                    return products, []
                    
                except Exception as e:
                    print(f"❌ Browser navigation failed: {e}")
                    return [], [f"Browser navigation failed: {str(e)}"]
                    
                finally:
                    browser.close()
                    
        except ImportError:
            return [], ["Playwright not installed - cannot use browser automation"]
        except Exception as e:
            print(f"❌ Browser automation failed: {e}")
            return [], [f"Browser automation failed: {str(e)}"]
    
    def _manual_collection_detection(self, soup: BeautifulSoup, base_url: str) -> List[Dict]:
        """Manually detect collection links when LLM fails"""
        
        all_links = soup.find_all('a', href=True)
        collection_links = []
        
        for link in all_links:
            href = link.get('href', '')
            text = link.get_text(strip=True)
            
            # Look for collection patterns in URL or text
            collection_patterns = ['collection', 'drop', 'archive', 'season', 'fw', 'ss', 'aw', 'spring', 'summer', 'fall', 'winter']
            
            is_collection = False
            if any(pattern in href.lower() for pattern in collection_patterns):
                is_collection = True
            elif any(pattern in text.lower() for pattern in ['drop', 'collection', 'archive', 'season']):
                is_collection = True
            elif text.lower() in ['aw25', 'ss25', 'fw25', 'eyewear']:  # Specific brand patterns
                is_collection = True
            
            if is_collection and href and href != '#' and len(text) > 0:
                # Avoid duplicates
                if not any(existing['href'] == href for existing in collection_links):
                    collection_links.append({
                        'text': text,
                        'href': href,
                        'selector': f'a[href="{href}"]'
                    })
        
        return collection_links


# Factory function for compatibility
def get_intelligent_scraper():
    """Get the intelligent scraper instance"""
    return IntelligentScraper()