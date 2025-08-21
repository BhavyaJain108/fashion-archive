#!/usr/bin/env python3
"""
Scraping Strategies for Fashion Brand Websites
==============================================

Implements the 6 different website patterns with smart product detection:
1. Pattern matching in image names
2. Most common visual elements analysis  
3. Product-focused logical reasoning
"""

import re
from collections import Counter, defaultdict
from urllib.parse import urljoin, urlparse
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from bs4 import BeautifulSoup
import requests
from pathlib import Path


@dataclass
class ProductCandidate:
    """Represents a potential product found on the page"""
    title: str
    image_url: str
    price: str
    product_url: str
    confidence: float
    detection_method: str


@dataclass  
class ScrapingResult:
    """Result of scraping attempt"""
    success: bool
    products: List[ProductCandidate]
    strategy_used: str
    total_found: int
    confidence: float
    next_pages: List[str]
    errors: List[str]


class ProductDetector:
    """Smart product detection using pattern analysis"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def detect_products_by_image_patterns(self, soup: BeautifulSoup, base_url: str) -> List[ProductCandidate]:
        """
        Strategy 1: Analyze image name patterns to find products
        Look for repeated naming conventions that suggest product images
        """
        products = []
        
        # Get all images with meaningful src attributes
        images = soup.find_all('img', src=True)
        image_data = []
        
        for img in images:
            src = img.get('src', '')
            alt = img.get('alt', '')
            
            # Skip tiny images, icons, logos
            if any(skip in src.lower() for skip in ['icon', 'logo', 'arrow', 'social', 'thumb']):
                continue
                
            # Extract filename patterns
            filename = Path(urlparse(src).path).name
            if filename:
                image_data.append({
                    'element': img,
                    'src': src,
                    'filename': filename,
                    'alt': alt
                })
        
        # Analyze filename patterns
        filename_patterns = self._analyze_filename_patterns([img['filename'] for img in image_data])
        
        # Find images that match product patterns
        for img_data in image_data:
            filename = img_data['filename']
            confidence = 0.0
            
            # Check against detected patterns
            for pattern, count in filename_patterns.items():
                if count >= 3 and pattern in filename.lower():  # Pattern appears 3+ times
                    confidence += 0.3
            
            # Look for product-like naming
            product_indicators = [
                r'\d+',  # Contains numbers (product IDs)
                r'product',
                r'item',
                r'model',
                r'-\d+x\d+',  # Dimensions like -800x600
                r'_\d+',  # Underscore numbers
            ]
            
            for indicator in product_indicators:
                if re.search(indicator, filename, re.IGNORECASE):
                    confidence += 0.2
            
            if confidence > 0.4:  # Threshold for product likelihood
                # Try to find associated product info
                product_info = self._extract_product_context(img_data['element'], soup, base_url)
                if product_info:
                    products.append(ProductCandidate(
                        title=product_info['title'],
                        image_url=urljoin(base_url, img_data['src']),
                        price=product_info['price'],
                        product_url=product_info['url'],
                        confidence=confidence,
                        detection_method="image_pattern_analysis"
                    ))
        
        return products
    
    def detect_products_by_common_elements(self, soup: BeautifulSoup, base_url: str) -> List[ProductCandidate]:
        """
        Strategy 2: Find the most common visual patterns on the page
        What element structure appears repeatedly? That's likely products.
        """
        products = []
        
        # Analyze structural patterns
        element_patterns = self._find_repeated_structures(soup)
        
        # Find the most common meaningful pattern
        best_pattern = None
        max_count = 0
        
        for pattern, elements in element_patterns.items():
            # Skip overly common patterns (like divs with no class)
            if len(elements) >= 3 and len(elements) <= 50:  # Sweet spot for product grids
                # Check if pattern contains product-like elements
                sample_element = elements[0]
                has_image = bool(sample_element.find('img'))
                has_link = bool(sample_element.find('a'))
                has_text = bool(sample_element.get_text(strip=True))
                
                # Score this pattern
                pattern_score = sum([has_image, has_link, has_text])
                if pattern_score >= 2 and len(elements) > max_count:
                    max_count = len(elements)
                    best_pattern = (pattern, elements)
        
        if best_pattern:
            pattern_name, elements = best_pattern
            
            for element in elements:
                product_info = self._extract_product_from_element(element, base_url)
                if product_info:
                    products.append(ProductCandidate(
                        title=product_info['title'],
                        image_url=product_info['image'],
                        price=product_info['price'],
                        product_url=product_info['url'],
                        confidence=0.7,  # High confidence from pattern matching
                        detection_method=f"common_pattern: {pattern_name}"
                    ))
        
        return products
    
    def detect_products_by_logical_reasoning(self, soup: BeautifulSoup, base_url: str) -> List[ProductCandidate]:
        """
        Strategy 3: Think logically about what represents products
        Look for elements that have the key components: image + title + price + link
        """
        products = []
        
        # Find all images that could be products
        images = soup.find_all('img', src=True)
        
        for img in images:
            # Skip obviously non-product images
            src = img.get('src', '')
            alt = img.get('alt', '')
            
            if any(skip in src.lower() for skip in ['icon', 'logo', 'banner', 'social']):
                continue
            
            # Look for product context around this image
            confidence = 0.0
            context = self._get_image_context(img)
            
            # Check if this image has product-like context
            has_title = self._find_nearby_title(img)
            has_price = self._find_nearby_price(img)
            has_link = self._find_nearby_link(img)
            
            if has_title:
                confidence += 0.3
            if has_price:
                confidence += 0.4  # Price is strong indicator
            if has_link:
                confidence += 0.2
            
            # Check image characteristics
            if any(indicator in alt.lower() for indicator in ['product', 'item', 'model', 'look']):
                confidence += 0.3
            
            # Check if image is reasonably sized (not tiny icon)
            width = img.get('width')
            height = img.get('height')
            if width and height:
                try:
                    w, h = int(width), int(height)
                    if w >= 200 and h >= 200:  # Reasonable product image size
                        confidence += 0.2
                except:
                    pass
            
            if confidence > 0.6:  # Threshold for logical product detection
                product_info = self._build_product_from_context(img, base_url, has_title, has_price, has_link)
                if product_info:
                    products.append(ProductCandidate(
                        title=product_info['title'],
                        image_url=urljoin(base_url, img.get('src')),
                        price=product_info['price'],
                        product_url=product_info['url'],
                        confidence=confidence,
                        detection_method="logical_reasoning"
                    ))
        
        return products
    
    def _analyze_filename_patterns(self, filenames: List[str]) -> Dict[str, int]:
        """Analyze filenames to find common patterns"""
        patterns = defaultdict(int)
        
        for filename in filenames:
            # Extract various pattern types
            filename_lower = filename.lower()
            
            # Word patterns (remove numbers and extensions)
            base_name = re.sub(r'\d+', '', filename_lower)
            base_name = re.sub(r'\.[^.]+$', '', base_name)  # Remove extension
            
            if len(base_name) > 2:
                patterns[base_name] += 1
            
            # Prefix patterns (everything before first number)
            prefix_match = re.match(r'^([a-zA-Z_-]+)', filename)
            if prefix_match:
                prefix = prefix_match.group(1).lower()
                if len(prefix) > 2:
                    patterns[f"prefix:{prefix}"] += 1
        
        return dict(patterns)
    
    def _find_repeated_structures(self, soup: BeautifulSoup) -> Dict[str, List]:
        """Find HTML structures that repeat multiple times"""
        structure_patterns = defaultdict(list)
        
        # Look for elements with similar structure
        for tag_name in ['div', 'article', 'section', 'li']:
            elements = soup.find_all(tag_name)
            
            for element in elements:
                # Create a signature for this element structure
                signature = self._create_element_signature(element)
                if signature:
                    structure_patterns[signature].append(element)
        
        # Filter to only meaningful patterns
        meaningful_patterns = {
            sig: elements for sig, elements in structure_patterns.items() 
            if len(elements) >= 3
        }
        
        return meaningful_patterns
    
    def _create_element_signature(self, element) -> str:
        """Create a signature representing element structure"""
        try:
            # Create signature based on classes and child elements
            classes = element.get('class', [])
            class_signature = '+'.join(sorted(classes)) if classes else 'no-class'
            
            # Count child element types
            child_counts = Counter(child.name for child in element.find_all(recursive=False) if child.name)
            child_signature = '+'.join(f"{tag}:{count}" for tag, count in sorted(child_counts.items()))
            
            signature = f"{element.name}[{class_signature}]({child_signature})"
            
            # Only return if signature has some meaningful structure
            if len(child_signature) > 0 or len(classes) > 0:
                return signature
            
        except:
            pass
        
        return None
    
    def _extract_product_context(self, img_element, soup: BeautifulSoup, base_url: str) -> Optional[Dict[str, str]]:
        """Extract product information from around an image"""
        context = {
            'title': '',
            'price': '', 
            'url': base_url
        }
        
        # Look for title in nearby elements
        title = self._find_nearby_title(img_element)
        if title:
            context['title'] = title
        
        # Look for price
        price = self._find_nearby_price(img_element)
        if price:
            context['price'] = price
        
        # Look for product URL
        product_url = self._find_nearby_link(img_element)
        if product_url:
            context['url'] = urljoin(base_url, product_url)
        
        return context if context['title'] or context['price'] else None
    
    def _find_nearby_title(self, img_element) -> str:
        """Find title text near an image"""
        # Check parent containers for titles
        parent = img_element.parent
        for _ in range(3):  # Check up to 3 levels up
            if not parent:
                break
                
            # Look for heading tags
            for heading_tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                heading = parent.find(heading_tag)
                if heading:
                    title = heading.get_text(strip=True)
                    if len(title) > 3:
                        return title
            
            # Look for elements with title-like classes
            for class_pattern in ['title', 'name', 'product', 'item']:
                title_elem = parent.find(attrs={'class': lambda x: x and class_pattern in ' '.join(x).lower()})
                if title_elem:
                    title = title_elem.get_text(strip=True)
                    if len(title) > 3:
                        return title
            
            parent = parent.parent
        
        # Check image alt text as fallback
        alt = img_element.get('alt', '').strip()
        if len(alt) > 3 and not any(skip in alt.lower() for skip in ['image', 'photo', 'picture']):
            return alt
        
        return ''
    
    def _find_nearby_price(self, img_element) -> str:
        """Find price text near an image"""
        parent = img_element.parent
        for _ in range(3):  # Check up to 3 levels up
            if not parent:
                break
            
            # Look for price patterns in text
            text = parent.get_text()
            price_patterns = [
                r'\$\d+(?:\.\d{2})?',
                r'€\d+(?:\.\d{2})?', 
                r'£\d+(?:\.\d{2})?',
                r'\d+(?:\.\d{2})?\s*(?:USD|EUR|GBP)',
            ]
            
            for pattern in price_patterns:
                match = re.search(pattern, text)
                if match:
                    return match.group(0)
            
            # Look for elements with price-like classes
            for class_pattern in ['price', 'cost', 'amount']:
                price_elem = parent.find(attrs={'class': lambda x: x and class_pattern in ' '.join(x).lower()})
                if price_elem:
                    price_text = price_elem.get_text(strip=True)
                    if price_text:
                        return price_text
            
            parent = parent.parent
        
        return ''
    
    def _find_nearby_link(self, img_element) -> str:
        """Find product URL near an image"""
        # Check if image itself is wrapped in a link
        parent = img_element.parent
        for _ in range(3):  # Check up to 3 levels up
            if not parent:
                break
            
            if parent.name == 'a' and parent.get('href'):
                href = parent.get('href')
                # Filter out obvious non-product links
                if not any(skip in href.lower() for skip in ['#', 'javascript:', 'mailto:', 'tel:']):
                    return href
            
            parent = parent.parent
        
        return ''
    
    def _get_image_context(self, img_element) -> Dict[str, Any]:
        """Get contextual information about an image"""
        context = {
            'parent_classes': [],
            'nearby_text': '',
            'nearby_links': []
        }
        
        # Get parent element classes
        parent = img_element.parent
        if parent and parent.get('class'):
            context['parent_classes'] = parent.get('class')
        
        # Get nearby text
        if parent:
            context['nearby_text'] = parent.get_text(strip=True)[:200]  # First 200 chars
        
        return context
    
    def _extract_product_from_element(self, element, base_url: str) -> Optional[Dict[str, str]]:
        """Extract product information from a structural element"""
        # Find image
        img = element.find('img', src=True)
        if not img:
            return None
        
        # Find title
        title = ''
        for heading_tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            heading = element.find(heading_tag)
            if heading:
                title = heading.get_text(strip=True)
                break
        
        if not title:
            # Look for title-like classes
            title_elem = element.find(attrs={'class': lambda x: x and 'title' in ' '.join(x).lower()})
            if title_elem:
                title = title_elem.get_text(strip=True)
        
        # Find price
        price = ''
        text = element.get_text()
        price_patterns = [r'\$\d+(?:\.\d{2})?', r'€\d+(?:\.\d{2})?', r'£\d+(?:\.\d{2})?']
        for pattern in price_patterns:
            match = re.search(pattern, text)
            if match:
                price = match.group(0)
                break
        
        # Find URL
        url = base_url
        link = element.find('a', href=True)
        if link:
            url = urljoin(base_url, link.get('href'))
        
        return {
            'title': title,
            'image': urljoin(base_url, img.get('src')),
            'price': price,
            'url': url
        } if title else None
    
    def _build_product_from_context(self, img_element, base_url: str, 
                                   has_title: str, has_price: str, has_link: str) -> Optional[Dict[str, str]]:
        """Build product info from contextual elements"""
        return {
            'title': has_title or img_element.get('alt', ''),
            'price': has_price,
            'url': urljoin(base_url, has_link) if has_link else base_url
        }


class ScrapingStrategy:
    """Base class for different website scraping strategies"""
    
    def __init__(self):
        self.detector = ProductDetector()
        # Import here to avoid circular imports
        import sys
        import os
        current_dir = os.path.dirname(os.path.abspath(__file__))
        sys.path.append(current_dir)
        from intelligent_scraper import IntelligentScraper
        self.intelligent_scraper = IntelligentScraper()
    
    def scrape(self, url: str, config: Dict[str, Any] = None) -> ScrapingResult:
        """Scrape products using intelligent LLM-guided approach"""
        print(f"🤖 Using intelligent scraping for: {url}")
        return self.intelligent_scraper.scrape(url, config)


class HomepageAllProductsStrategy(ScrapingStrategy):
    """Strategy 1: All products displayed on homepage/main page"""
    
    def scrape(self, url: str, config: Dict[str, Any] = None) -> ScrapingResult:
        """Use intelligent LLM-guided scraping"""
        return super().scrape(url, config)
    
    def _deduplicate_products(self, products: List[ProductCandidate]) -> List[ProductCandidate]:
        """Remove duplicate products based on image URL or title"""
        seen_images = set()
        seen_titles = set()
        unique_products = []
        
        for product in products:
            # Skip if we've seen this image or title
            if product.image_url in seen_images or product.title in seen_titles:
                continue
            
            seen_images.add(product.image_url)
            seen_titles.add(product.title)
            unique_products.append(product)
        
        return unique_products


# Additional strategy classes would be implemented similarly...
class CategoryBasedStrategy(ScrapingStrategy):
    """Strategy 2: Navigate categories then scrape products - Uses intelligent scraper"""
    
    def scrape(self, url: str, config: Dict[str, Any] = None) -> ScrapingResult:
        """Use intelligent LLM-guided scraping"""
        return super().scrape(url, config)

class ProductGridStrategy(ScrapingStrategy):
    """Strategy 3: Handle product grid layouts - Uses intelligent scraper"""
    
    def scrape(self, url: str, config: Dict[str, Any] = None) -> ScrapingResult:
        """Use intelligent LLM-guided scraping"""
        return super().scrape(url, config)

class PaginatedStrategy(ScrapingStrategy):
    """Strategy 4: Handle multiple pages/pagination - Uses intelligent scraper"""
    
    def scrape(self, url: str, config: Dict[str, Any] = None) -> ScrapingResult:
        """Use intelligent LLM-guided scraping"""
        return super().scrape(url, config)

class ImageClickStrategy(ScrapingStrategy):
    """Strategy 5: Click images for full resolution - Uses intelligent scraper"""
    
    def scrape(self, url: str, config: Dict[str, Any] = None) -> ScrapingResult:
        """Use intelligent LLM-guided scraping"""
        return super().scrape(url, config)

class SinglePageScrollStrategy(ScrapingStrategy):
    """Strategy 6: Handle infinite scroll or long pages - Uses intelligent scraper"""
    
    def scrape(self, url: str, config: Dict[str, Any] = None) -> ScrapingResult:
        """Use intelligent LLM-guided scraping"""
        return super().scrape(url, config)


# Factory function to get appropriate strategy
def get_scraping_strategy(strategy_name: str) -> ScrapingStrategy:
    """Get scraping strategy instance by name"""
    strategies = {
        'homepage-all-products': HomepageAllProductsStrategy,
        'category-based': CategoryBasedStrategy,
        'product-grid': ProductGridStrategy,
        'paginated': PaginatedStrategy,
        'image-click': ImageClickStrategy,
        'single-page-scroll': SinglePageScrollStrategy,
    }
    
    strategy_class = strategies.get(strategy_name, HomepageAllProductsStrategy)
    return strategy_class()