#!/usr/bin/env python3
"""
Brand Validator
===============

AI-powered validation system to ensure only small, independent fashion brands
are added to the catalog. Filters out large conglomerates and non-fashion sites.
"""

import os
import requests
from bs4 import BeautifulSoup
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()

@dataclass
class ValidationResult:
    """Result of brand validation"""
    is_valid: bool
    confidence: float
    reason: str
    brand_name: str = ""
    brand_type: str = ""
    issues: List[str] = None

class BrandValidator:
    """Validates fashion brand websites using AI"""
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize with Claude API key"""
        self.api_key = api_key or os.getenv('CLAUDE_API_KEY') or os.getenv('ANTHROPIC_API_KEY')
        if not self.api_key:
            raise ValueError("CLAUDE_API_KEY or ANTHROPIC_API_KEY environment variable is required")
        
        self.client = Anthropic(api_key=self.api_key)
        
        # Known conglomerate patterns to reject
        self.blocked_domains = {
            'amazon.com', 'amazon.co.uk', 'amazon.de', 'amazon.fr',
            'ebay.com', 'aliexpress.com', 'wish.com', 'temu.com',
            'walmart.com', 'target.com', 'kohls.com', 'macys.com',
            'nordstrom.com', 'saksfifthavenue.com', 'bergdorfgoodman.com',
            'farfetch.com', 'net-a-porter.com', 'theoutnet.com',
            'ssense.com', 'matchesfashion.com', 'mytheresa.com',
            'zalando.com', 'asos.com', 'boohoo.com', 'shein.com',
            'h&m.com', 'zara.com', 'uniqlo.com', 'gap.com'
        }
    
    def validate_brand_website(self, url: str) -> ValidationResult:
        """
        Validate if a website represents a small, independent fashion brand
        
        Args:
            url: Website URL to validate
            
        Returns:
            ValidationResult with validation details
        """
        try:
            # Quick domain check
            domain_check = self._check_blocked_domains(url)
            if not domain_check[0]:
                return ValidationResult(
                    is_valid=False,
                    confidence=1.0,
                    reason=domain_check[1]
                )
            
            # Fetch website content
            website_content = self._fetch_website_content(url)
            if not website_content:
                return ValidationResult(
                    is_valid=False,
                    confidence=0.9,
                    reason="Unable to access website content"
                )
            
            # AI validation
            validation = self._ai_validate_content(url, website_content)
            return validation
            
        except Exception as e:
            return ValidationResult(
                is_valid=False,
                confidence=0.5,
                reason=f"Validation error: {str(e)}"
            )
    
    def _check_blocked_domains(self, url: str) -> Tuple[bool, str]:
        """Check if URL contains blocked domain patterns"""
        url_lower = url.lower()
        
        for blocked_domain in self.blocked_domains:
            if blocked_domain in url_lower:
                return False, f"Blocked domain detected: {blocked_domain} (large retailer/marketplace)"
        
        return True, ""
    
    def _fetch_website_content(self, url: str) -> Optional[str]:
        """Fetch and clean website content for analysis"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.decompose()
            
            # Get text content
            text = soup.get_text()
            
            # Clean up text
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = ' '.join(chunk for chunk in chunks if chunk)
            
            # Limit content length for AI processing
            return text[:8000] if len(text) > 8000 else text
            
        except Exception as e:
            print(f"Error fetching website content: {e}")
            return None
    
    def _ai_validate_content(self, url: str, content: str) -> ValidationResult:
        """Use AI to validate if this is a small independent fashion brand"""
        
        prompt = f"""
        Analyze this website to determine if it represents a small, independent fashion brand suitable for promotion.

        Website URL: {url}
        Website Content: {content[:4000]}...

        VALIDATION CRITERIA:

        ✅ APPROVE if the website is:
        - A small, independent fashion brand (not a conglomerate)
        - Selling original fashion/clothing designs
        - Single brand focus (not a multi-brand retailer)
        - Appears to be run by designers/small team
        - Has original products with unique designs

        ❌ REJECT if the website is:
        - Large fashion conglomerate or corporation
        - Multi-brand retailer or marketplace
        - Dropshipping/reseller site
        - Not primarily focused on fashion
        - Adult content or inappropriate material
        - Fake/scam website
        - Major department store or chain

        ANALYSIS REQUIREMENTS:
        1. Determine the brand name
        2. Assess if it's truly independent and small-scale
        3. Verify it's focused on original fashion design
        4. Check for signs of being a large retailer

        Respond with ONLY valid JSON:
        {{
            "is_valid": true/false,
            "confidence": 0.0-1.0,
            "brand_name": "extracted brand name",
            "brand_type": "independent_designer|small_brand|large_retailer|marketplace|non_fashion",
            "reason": "single line explanation of decision",
            "issues": ["list", "of", "any", "concerns", "found"]
        }}
        """
        
        try:
            response = self.client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=500,
                temperature=0.0,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )
            
            response_text = response.content[0].text.strip()
            
            # Extract JSON from response
            import json
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            
            if json_start != -1 and json_end != -1:
                json_text = response_text[json_start:json_end]
                result_data = json.loads(json_text)
                
                return ValidationResult(
                    is_valid=result_data.get('is_valid', False),
                    confidence=result_data.get('confidence', 0.0),
                    reason=result_data.get('reason', 'AI validation completed'),
                    brand_name=result_data.get('brand_name', ''),
                    brand_type=result_data.get('brand_type', ''),
                    issues=result_data.get('issues', [])
                )
            else:
                return ValidationResult(
                    is_valid=False,
                    confidence=0.3,
                    reason="Could not parse AI validation response"
                )
                
        except Exception as e:
            return ValidationResult(
                is_valid=False,
                confidence=0.3,
                reason=f"AI validation failed: {str(e)}"
            )

    def batch_validate_urls(self, urls: List[str]) -> List[Tuple[str, ValidationResult]]:
        """Validate multiple URLs"""
        results = []
        for url in urls:
            result = self.validate_brand_website(url)
            results.append((url, result))
        return results