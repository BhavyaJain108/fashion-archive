#!/usr/bin/env python3
"""
My Brands LLM Client
===================

Dedicated LLM interface for My Brands feature validation and analysis.
Supports multiple providers with specialized prompts for fashion brand evaluation.
"""

import os
import json
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class BrandAnalysis:
    """Result of AI brand analysis"""
    is_valid_brand: bool
    confidence: float
    brand_name: str
    brand_type: str
    reason: str
    issues: List[str]
    is_scrapable: bool
    scraping_strategy: str
    scraping_confidence: float


class MyBrandsLLM:
    """LLM client specifically designed for My Brands feature"""
    
    def __init__(self, provider: str = None, api_key: str = None):
        """Initialize LLM client with specified provider"""
        self.provider = provider or os.getenv('LLM_PROVIDER', 'claude').lower()
        self.api_key = api_key or self._get_api_key()
        self.client = self._initialize_client()
    
    def _get_api_key(self) -> str:
        """Get API key based on provider"""
        if self.provider == 'claude':
            key = os.getenv('CLAUDE_API_KEY') or os.getenv('ANTHROPIC_API_KEY')
            if not key:
                raise ValueError("CLAUDE_API_KEY or ANTHROPIC_API_KEY required for Claude provider")
            return key
        elif self.provider == 'openai':
            key = os.getenv('OPENAI_API_KEY')
            if not key:
                raise ValueError("OPENAI_API_KEY required for OpenAI provider")
            return key
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")
    
    def _initialize_client(self):
        """Initialize the appropriate LLM client"""
        if self.provider == 'claude':
            try:
                from anthropic import Anthropic
                return Anthropic(api_key=self.api_key)
            except ImportError:
                raise ImportError("anthropic package required. Run: pip install anthropic")
        
        elif self.provider == 'openai':
            try:
                import openai
                return openai.OpenAI(api_key=self.api_key)
            except ImportError:
                raise ImportError("openai package required. Run: pip install openai")
    
    def _generate_response(self, prompt: str, max_tokens: int = 1000) -> str:
        """Generate response using the configured LLM"""
        if self.provider == 'claude':
            response = self.client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=max_tokens,
                temperature=0.0,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text.strip()
        
        elif self.provider == 'openai':
            response = self.client.chat.completions.create(
                model="gpt-4",
                max_tokens=max_tokens,
                temperature=0.0,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.choices[0].message.content.strip()
    
    def analyze_brand_website(self, url: str, website_content: str) -> BrandAnalysis:
        """
        Comprehensive brand analysis including validation and scraping strategy
        
        Args:
            url: Brand website URL
            website_content: Extracted website text content
            
        Returns:
            BrandAnalysis object with complete assessment
        """
        
        prompt = f"""
        You are a fashion industry expert analyzing websites to determine if they represent small, independent fashion brands suitable for promotion and product catalog scraping.

        Website URL: {url}
        Website Content: {website_content[:4000]}...

        TASK 1 - BRAND VALIDATION:
        
        ✅ APPROVE if the website is:
        - Small, independent fashion brand (not corporate conglomerate)
        - Selling original fashion/clothing designs  
        - Single brand focus (not multi-brand retailer)
        - Run by designers/small team (under 50 employees typically)
        - Has unique, creative designs
        - Direct-to-consumer or small boutique presence
        
        ❌ REJECT if the website is:
        - Large fashion conglomerate (Zara, H&M, etc.)
        - Multi-brand retailer or marketplace (Amazon, SSENSE, etc.)
        - Dropshipping or reseller site
        - Not primarily focused on fashion
        - Adult/inappropriate content
        - Scam/fake website
        - Major department store
        
        TASK 2 - SCRAPING STRATEGY ANALYSIS:
        
        Analyze the website structure and determine the best scraping approach:
        
        1. **homepage-all-products**: All products displayed on homepage/main page
        2. **category-based**: Home page leads to category pages with products
        3. **product-grid**: Category pages show grid of products 
        4. **paginated**: Multiple pages requiring pagination navigation
        5. **image-click**: Need to click product images for full resolution
        6. **single-page-scroll**: Long scrolling page or infinite scroll
        
        Consider scrapability factors:
        - Are product listings clearly structured?
        - Are images accessible and high quality? 
        - Are prices and product info extractable?
        - Does the site use anti-scraping measures?
        - Is the HTML structure clean and parseable?

        RESPOND WITH ONLY VALID JSON:
        {{
            "is_valid_brand": true/false,
            "confidence": 0.0-1.0,
            "brand_name": "extracted brand name",
            "brand_type": "independent_designer|small_brand|large_retailer|marketplace|non_fashion",
            "reason": "clear explanation of validation decision",
            "issues": ["list", "of", "any", "concerns"],
            "is_scrapable": true/false,
            "scraping_strategy": "homepage-all-products|category-based|product-grid|paginated|image-click|single-page-scroll|not-scrapable",
            "scraping_confidence": 0.0-1.0
        }}
        """
        
        try:
            response_text = self._generate_response(prompt, max_tokens=800)
            
            # Extract JSON from response
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            
            if json_start != -1 and json_end != -1:
                json_text = response_text[json_start:json_end]
                result_data = json.loads(json_text)
                
                return BrandAnalysis(
                    is_valid_brand=result_data.get('is_valid_brand', False),
                    confidence=result_data.get('confidence', 0.0),
                    brand_name=result_data.get('brand_name', ''),
                    brand_type=result_data.get('brand_type', ''),
                    reason=result_data.get('reason', ''),
                    issues=result_data.get('issues', []),
                    is_scrapable=result_data.get('is_scrapable', False),
                    scraping_strategy=result_data.get('scraping_strategy', 'not-scrapable'),
                    scraping_confidence=result_data.get('scraping_confidence', 0.0)
                )
            else:
                return BrandAnalysis(
                    is_valid_brand=False,
                    confidence=0.3,
                    brand_name='',
                    brand_type='',
                    reason='Could not parse AI response',
                    issues=['JSON parsing failed'],
                    is_scrapable=False,
                    scraping_strategy='not-scrapable',
                    scraping_confidence=0.0
                )
                
        except Exception as e:
            return BrandAnalysis(
                is_valid_brand=False,
                confidence=0.2,
                brand_name='',
                brand_type='',
                reason=f'Analysis failed: {str(e)}',
                issues=[f'Error: {str(e)}'],
                is_scrapable=False,
                scraping_strategy='not-scrapable',
                scraping_confidence=0.0
            )
    
    def analyze_website_structure(self, url: str, html_content: str) -> Dict[str, Any]:
        """
        Detailed analysis of website structure for scraping strategy refinement
        
        Args:
            url: Website URL
            html_content: Raw HTML content for structure analysis
            
        Returns:
            Dict with detailed structure analysis
        """
        
        prompt = f"""
        Analyze this website's HTML structure to determine the optimal product scraping strategy.
        
        Website: {url}
        HTML Structure: {html_content[:6000]}...
        
        ANALYSIS REQUIREMENTS:
        1. Product listing structure
        2. Navigation patterns
        3. Image organization
        4. Price display methods
        5. Pagination or scrolling patterns
        6. Anti-scraping measures detected
        
        Provide detailed technical analysis for each scraping strategy:
        
        RESPOND WITH VALID JSON:
        {{
            "primary_strategy": "strategy_name",
            "strategy_details": {{
                "product_selectors": ["css", "selectors", "for", "products"],
                "image_selectors": ["css", "selectors", "for", "images"], 
                "price_selectors": ["css", "selectors", "for", "prices"],
                "title_selectors": ["css", "selectors", "for", "titles"],
                "pagination_pattern": "description of pagination",
                "ajax_loading": true/false,
                "challenges": ["scraping", "challenges", "identified"]
            }},
            "alternative_strategies": ["backup", "strategies"],
            "scraping_difficulty": "easy|medium|hard",
            "estimated_success_rate": 0.0-1.0,
            "recommendations": ["specific", "implementation", "tips"]
        }}
        """
        
        try:
            response_text = self._generate_response(prompt, max_tokens=1200)
            
            # Extract JSON from response
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            
            if json_start != -1 and json_end != -1:
                json_text = response_text[json_start:json_end]
                return json.loads(json_text)
            else:
                return {"error": "Could not parse structure analysis"}
                
        except Exception as e:
            return {"error": f"Structure analysis failed: {str(e)}"}


# Convenience function for easy usage
def create_my_brands_llm(provider: str = None) -> MyBrandsLLM:
    """Create My Brands LLM client with current configuration"""
    return MyBrandsLLM(provider=provider)