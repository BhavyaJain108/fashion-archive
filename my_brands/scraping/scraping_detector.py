#!/usr/bin/env python3
"""
Web Scraping Capability Detection
=================================

AI-powered system to analyze fashion brand websites and determine:
1. Whether the site can be scraped effectively
2. Which scraping strategy pattern fits best
3. Technical implementation details for scraping
"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import re
import time
from ..llm_client import create_my_brands_llm


@dataclass
class ScrapingCapability:
    """Assessment of website's scraping potential"""
    is_scrapable: bool
    confidence: float
    primary_strategy: str
    difficulty: str  # easy, medium, hard
    estimated_products: int
    challenges: List[str]
    technical_details: Dict[str, any]


@dataclass
class WebsiteStructure:
    """Analysis of website's structural elements"""
    has_product_grid: bool
    has_categories: bool
    has_pagination: bool
    uses_ajax: bool
    image_quality: str  # high, medium, low
    price_display: str  # visible, hidden, variable
    navigation_type: str  # menu, links, buttons
    product_count_estimate: int


class ScrapingDetector:
    """Analyzes websites to determine scraping feasibility and strategy"""
    
    def __init__(self):
        """Initialize with LLM client for AI analysis"""
        self.llm = create_my_brands_llm()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })
    
    def analyze_website(self, url: str) -> ScrapingCapability:
        """
        Comprehensive analysis of website for scraping capability
        
        Args:
            url: Website URL to analyze
            
        Returns:
            ScrapingCapability assessment
        """
        try:
            # Step 1: Fetch website content
            html_content, text_content = self._fetch_website_content(url)
            if not html_content:
                return ScrapingCapability(
                    is_scrapable=False,
                    confidence=0.0,
                    primary_strategy="not-accessible",
                    difficulty="impossible",
                    estimated_products=0,
                    challenges=["Website not accessible"],
                    technical_details={}
                )
            
            # Step 2: Analyze HTML structure
            structure = self._analyze_html_structure(html_content)
            
            # Step 3: AI-powered strategy analysis  
            ai_analysis = self.llm.analyze_website_structure(url, html_content[:8000])
            
            # Step 4: Test scraping feasibility
            feasibility = self._test_scraping_feasibility(url, html_content)
            
            # Step 5: Combine analyses
            return self._combine_assessments(structure, ai_analysis, feasibility)
            
        except Exception as e:
            return ScrapingCapability(
                is_scrapable=False,
                confidence=0.0,
                primary_strategy="error",
                difficulty="impossible", 
                estimated_products=0,
                challenges=[f"Analysis error: {str(e)}"],
                technical_details={"error": str(e)}
            )
    
    def _fetch_website_content(self, url: str) -> Tuple[Optional[str], Optional[str]]:
        """Fetch and parse website content"""
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Remove script and style elements for clean text
            for element in soup(["script", "style", "nav", "footer", "header"]):
                element.decompose()
            
            # Get clean text content
            text = soup.get_text()
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            clean_text = ' '.join(chunk for chunk in chunks if chunk)
            
            return response.text, clean_text[:10000]
            
        except Exception as e:
            print(f"Error fetching website content: {e}")
            return None, None
    
    def _analyze_html_structure(self, html_content: str) -> WebsiteStructure:
        """Analyze HTML structure for scraping indicators"""
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Look for product indicators
        product_selectors = [
            '[class*="product"]',
            '[class*="item"]', 
            '[class*="card"]',
            '[data-product]',
            '.product-grid',
            '.shop-item',
            '.collection-item'
        ]
        
        product_elements = []
        for selector in product_selectors:
            elements = soup.select(selector)
            product_elements.extend(elements)
        
        # Analyze structure patterns
        has_product_grid = len(product_elements) > 3
        
        # Check for categories/navigation
        category_selectors = [
            'nav a[href*="categor"]',
            'nav a[href*="shop"]',
            'nav a[href*="collection"]',
            '[class*="menu"] a',
            '[class*="nav"] a'
        ]
        
        category_links = []
        for selector in category_selectors:
            links = soup.select(selector)
            category_links.extend(links)
        
        has_categories = len(category_links) > 2
        
        # Check for pagination
        pagination_selectors = [
            '[class*="paginat"]',
            'a[href*="page"]',
            '.next',
            '.prev',
            '[class*="load-more"]'
        ]
        
        pagination_elements = []
        for selector in pagination_selectors:
            elements = soup.select(selector)
            pagination_elements.extend(elements)
        
        has_pagination = len(pagination_elements) > 0
        
        # Check for AJAX indicators
        ajax_indicators = [
            'data-ajax',
            'onclick',
            'data-load',
            'infinite-scroll'
        ]
        
        uses_ajax = any(
            soup.find(attrs={indicator: True}) for indicator in ajax_indicators
        ) or any(
            indicator in html_content.lower() for indicator in ajax_indicators
        )
        
        # Estimate image quality
        images = soup.find_all('img')
        high_res_images = [
            img for img in images 
            if any(keyword in (img.get('src', '') + img.get('data-src', '')).lower() 
                  for keyword in ['1920', '1080', '2000', 'large', 'full'])
        ]
        
        if len(high_res_images) > len(images) * 0.7:
            image_quality = "high"
        elif len(high_res_images) > len(images) * 0.3:
            image_quality = "medium" 
        else:
            image_quality = "low"
        
        # Check price visibility
        price_selectors = [
            '[class*="price"]',
            '[data-price]',
            '.cost',
            '.amount',
            '$',
            '€',
            '£'
        ]
        
        price_elements = []
        for selector in price_selectors[:-3]:  # CSS selectors only
            elements = soup.select(selector)
            price_elements.extend(elements)
        
        # Check for currency symbols in text
        price_text_matches = sum(1 for symbol in price_selectors[-3:] if symbol in html_content)
        
        if len(price_elements) > 5 or price_text_matches > 3:
            price_display = "visible"
        elif len(price_elements) > 0 or price_text_matches > 0:
            price_display = "variable"
        else:
            price_display = "hidden"
        
        # Determine navigation type
        if soup.find('nav') or soup.select('[class*="nav"]'):
            navigation_type = "menu"
        elif len(category_links) > 5:
            navigation_type = "links"
        else:
            navigation_type = "buttons"
        
        return WebsiteStructure(
            has_product_grid=has_product_grid,
            has_categories=has_categories,
            has_pagination=has_pagination,
            uses_ajax=uses_ajax,
            image_quality=image_quality,
            price_display=price_display,
            navigation_type=navigation_type,
            product_count_estimate=min(len(product_elements), 200)
        )
    
    def _test_scraping_feasibility(self, url: str, html_content: str) -> Dict[str, any]:
        """Test actual scraping feasibility with small sample"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Test basic selectors
            test_results = {
                "can_extract_images": False,
                "can_extract_titles": False,
                "can_extract_prices": False,
                "can_extract_links": False,
                "response_time": 0,
                "status_code": 200
            }
            
            # Test image extraction
            images = soup.find_all('img', src=True)
            if len(images) > 0:
                test_results["can_extract_images"] = True
            
            # Test title extraction
            titles = soup.find_all(['h1', 'h2', 'h3', 'h4'])
            title_texts = [t.get_text().strip() for t in titles if t.get_text().strip()]
            if len(title_texts) > 0:
                test_results["can_extract_titles"] = True
            
            # Test price extraction (basic)
            price_patterns = [r'\$\d+', r'€\d+', r'£\d+', r'\d+\.\d{2}']
            page_text = soup.get_text()
            price_matches = sum(1 for pattern in price_patterns if re.search(pattern, page_text))
            if price_matches > 0:
                test_results["can_extract_prices"] = True
            
            # Test link extraction
            links = soup.find_all('a', href=True)
            product_links = [
                link for link in links 
                if any(keyword in link.get('href', '').lower() 
                      for keyword in ['product', 'item', 'shop', 'buy'])
            ]
            if len(product_links) > 0:
                test_results["can_extract_links"] = True
            
            return test_results
            
        except Exception as e:
            return {"error": str(e), "feasible": False}
    
    def _combine_assessments(self, structure: WebsiteStructure, 
                           ai_analysis: Dict, feasibility: Dict) -> ScrapingCapability:
        """Combine all assessments into final capability assessment"""
        
        # Determine if scrapable based on multiple factors
        scraping_indicators = [
            structure.has_product_grid,
            structure.product_count_estimate > 0,
            feasibility.get("can_extract_images", False),
            feasibility.get("can_extract_titles", False),
            not feasibility.get("error", False)
        ]
        
        scrapability_score = sum(scraping_indicators) / len(scraping_indicators)
        is_scrapable = scrapability_score > 0.5
        
        # Determine primary strategy
        if not is_scrapable:
            primary_strategy = "not-scrapable"
        elif structure.product_count_estimate > 50 and structure.has_pagination:
            primary_strategy = "paginated"
        elif structure.has_categories and structure.has_product_grid:
            primary_strategy = "category-based"
        elif structure.product_count_estimate > 20:
            primary_strategy = "product-grid"
        elif structure.uses_ajax:
            primary_strategy = "single-page-scroll"
        else:
            primary_strategy = "homepage-all-products"
        
        # Determine difficulty
        difficulty_factors = [
            structure.uses_ajax,
            structure.image_quality == "low",
            structure.price_display == "hidden",
            feasibility.get("error", False)
        ]
        
        difficulty_score = sum(difficulty_factors)
        if difficulty_score >= 3:
            difficulty = "hard"
        elif difficulty_score >= 1:
            difficulty = "medium"
        else:
            difficulty = "easy"
        
        # Compile challenges
        challenges = []
        if structure.uses_ajax:
            challenges.append("AJAX/JavaScript heavy site")
        if structure.image_quality == "low":
            challenges.append("Low quality images")
        if structure.price_display == "hidden":
            challenges.append("Prices not visible or variable")
        if not structure.has_product_grid:
            challenges.append("No clear product structure")
        if feasibility.get("error"):
            challenges.append(f"Technical error: {feasibility.get('error')}")
        
        # Create technical details
        technical_details = {
            "structure_analysis": {
                "product_grid": structure.has_product_grid,
                "categories": structure.has_categories,
                "pagination": structure.has_pagination,
                "ajax": structure.uses_ajax,
                "image_quality": structure.image_quality,
                "price_display": structure.price_display,
                "navigation": structure.navigation_type,
                "estimated_products": structure.product_count_estimate
            },
            "feasibility_test": feasibility,
            "ai_suggestions": ai_analysis if not ai_analysis.get("error") else {}
        }
        
        return ScrapingCapability(
            is_scrapable=is_scrapable,
            confidence=scrapability_score,
            primary_strategy=primary_strategy,
            difficulty=difficulty,
            estimated_products=structure.product_count_estimate,
            challenges=challenges,
            technical_details=technical_details
        )


# Convenience function
def analyze_brand_website_scraping(url: str) -> ScrapingCapability:
    """Analyze a brand website for scraping capability"""
    detector = ScrapingDetector()
    return detector.analyze_website(url)