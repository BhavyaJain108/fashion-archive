#!/usr/bin/env python3
"""
Brand URL Resolver
==================

Resolves brand names to official website URLs using Google search and AI selection.
Takes a brand name like "Jukuhara" and finds their official website automatically.
"""

import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urlparse, parse_qs, unquote, quote
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import time
import json
import html

from .llm_client import create_my_brands_llm


@dataclass
class SearchResult:
    """Represents a Google search result"""
    title: str
    url: str
    description: str
    domain: str


class BrandURLResolver:
    """Resolves brand names to official website URLs"""
    
    def __init__(self):
        """Initialize with LLM client and search headers"""
        self.llm = create_my_brands_llm()
        self.session = requests.Session()
        
        # Headers to appear as a regular browser
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
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
    
    def resolve_brand_name_to_url(self, brand_name: str) -> Optional[str]:
        """
        Resolve a brand name to its official website URL
        
        Args:
            brand_name: The fashion brand name (e.g., "Jukuhara", "Comme des Garçons")
            
        Returns:
            Official website URL or None if not found
        """
        try:
            # Security: Sanitize input
            sanitized_name = self._sanitize_brand_name(brand_name)
            if not sanitized_name:
                print("❌ Invalid brand name after sanitization")
                return None
            
            print(f"🔍 Searching for '{sanitized_name}' official website...")
            
            # Step 1: Perform Google search
            search_results = self._google_search(sanitized_name)
            
            if not search_results:
                print("❌ No search results found")
                return None
            
            print(f"🔍 Found {len(search_results)} search results")
            
            # Step 2: Use AI to select the most appropriate result
            selected_url = self._ai_select_official_website(sanitized_name, search_results)
            
            if selected_url:
                print(f"✅ Selected official website: {selected_url}")
                return selected_url
            else:
                print("❌ AI could not determine official website")
                return None
                
        except Exception as e:
            print(f"❌ Error resolving brand name: {e}")
            return None
    
    def _sanitize_brand_name(self, brand_name: str) -> str:
        """Basic brand name sanitization"""
        if not brand_name or not isinstance(brand_name, str):
            return ""
        
        # Basic cleanup
        sanitized = brand_name.strip()
        
        # Limit length
        sanitized = sanitized[:100]
        
        # Must have at least 2 characters
        if len(sanitized.strip()) < 2:
            return ""
        
        return sanitized
    
    def _google_search(self, brand_name: str) -> List[SearchResult]:
        """
        Perform simple web search using DuckDuckGo (more reliable than Google)
        
        Args:
            brand_name: Brand name to search for
            
        Returns:
            List of search results
        """
        try:
            # Try multiple search engines/approaches
            search_results = []
            
            # Method 1: DuckDuckGo HTML search
            ddg_results = self._search_duckduckgo(brand_name)
            search_results.extend(ddg_results)
            
            # Method 2: If DDG doesn't work, try Google with different parsing
            if not search_results:
                google_results = self._search_google_simple(brand_name)
                search_results.extend(google_results)
            
            # Method 3: Last resort - manual URL construction
            if not search_results:
                manual_results = self._guess_brand_urls(brand_name)
                search_results.extend(manual_results)
            
            print(f"📋 Total search results: {len(search_results)}")
            return search_results[:6]  # Limit to 6 results
            
        except Exception as e:
            print(f"❌ All search methods failed: {e}")
            return []
    
    def _search_duckduckgo(self, brand_name: str) -> List[SearchResult]:
        """Search using DuckDuckGo"""
        try:
            query = f"{brand_name} fashion brand official website"
            search_url = f"https://html.duckduckgo.com/html/?q={quote(query)}"
            
            print(f"🦆 DuckDuckGo search: {query}")
            
            response = self.session.get(search_url, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            results = []
            # DuckDuckGo result links
            for link in soup.find_all('a', href=True):
                href = link.get('href', '')
                text = link.get_text().strip()
                
                if (href.startswith('http') and 
                    not any(skip in href.lower() for skip in [
                        'duckduckgo.com', 'youtube.com', 'facebook.com', 'instagram.com',
                        'twitter.com', 'wikipedia.org', 'amazon.com', 'etsy.com'
                    ])):
                    
                    try:
                        domain = urlparse(href).netloc.lower()
                        result = SearchResult(
                            title=text[:100] or f"Website from {domain}",
                            url=href,
                            description="",
                            domain=domain
                        )
                        
                        # Check if we already have this URL
                        if not any(existing.url == href for existing in results):
                            results.append(result)
                            print(f"  🔗 {domain}")
                            
                        if len(results) >= 5:
                            break
                    except:
                        continue
            
            print(f"🦆 DuckDuckGo found {len(results)} results")
            return results
            
        except Exception as e:
            print(f"❌ DuckDuckGo search failed: {e}")
            return []
    
    def _search_google_simple(self, brand_name: str) -> List[SearchResult]:
        """Fallback Google search with simpler parsing"""
        try:
            query = f"{brand_name} official website"
            search_url = f"https://www.google.com/search?q={quote(query)}&num=10"
            
            print(f"🌐 Google fallback search: {query}")
            
            response = self.session.get(search_url, timeout=15)
            response.raise_for_status()
            
            # Look for URLs in the HTML content using regex
            import re
            content = response.text
            
            # Find URLs that might be relevant
            url_pattern = r'https?://[^\s<>"\'{}|\\^`\[\]]+' + re.escape(brand_name.lower()) + r'[^\s<>"\'{}|\\^`\[\]]*'
            brand_urls = re.findall(url_pattern, content, re.IGNORECASE)
            
            # Also look for any .com/.jp/.net domains
            general_pattern = r'https?://(?:[a-zA-Z0-9-]+\.)*[a-zA-Z0-9-]+\.[a-zA-Z]{2,}[^\s<>"\'{}|\\^`\[\]]*'
            all_urls = re.findall(general_pattern, content)
            
            results = []
            for url in (brand_urls + all_urls):
                try:
                    # Clean up URL
                    url = url.split('&')[0]  # Remove URL parameters
                    url = url.rstrip('.,;)')  # Remove trailing punctuation
                    
                    if (url.startswith(('http://', 'https://')) and
                        not any(skip in url.lower() for skip in [
                            'google.com', 'youtube.com', 'facebook.com', 'instagram.com',
                            'twitter.com', 'wikipedia.org', 'amazon.com'
                        ])):
                        
                        domain = urlparse(url).netloc.lower()
                        result = SearchResult(
                            title=f"Website from {domain}",
                            url=url,
                            description="",
                            domain=domain
                        )
                        
                        if not any(existing.url == url for existing in results):
                            results.append(result)
                            print(f"  🔗 {domain}")
                            
                        if len(results) >= 5:
                            break
                except:
                    continue
            
            print(f"🌐 Google found {len(results)} results")
            return results
            
        except Exception as e:
            print(f"❌ Google fallback search failed: {e}")
            return []
    
    def _guess_brand_urls(self, brand_name: str) -> List[SearchResult]:
        """Last resort: guess common URL patterns for the brand"""
        try:
            print(f"🔮 Guessing URLs for {brand_name}")
            
            # Clean brand name for URL
            clean_name = re.sub(r'[^a-zA-Z0-9]', '', brand_name.lower())
            
            # Common patterns
            patterns = [
                f"https://{clean_name}.com",
                f"https://{clean_name}.jp",  # Many Japanese brands use .jp
                f"https://www.{clean_name}.com",
                f"https://www.{clean_name}.jp",
                f"https://{clean_name}.net",
                f"https://{clean_name}.org"
            ]
            
            results = []
            for url in patterns:
                try:
                    # Quick check if URL responds
                    response = self.session.head(url, timeout=5, allow_redirects=True)
                    if response.status_code == 200:
                        domain = urlparse(url).netloc.lower()
                        result = SearchResult(
                            title=f"{brand_name} (guessed)",
                            url=url,
                            description="Guessed URL pattern",
                            domain=domain
                        )
                        results.append(result)
                        print(f"  ✅ {url} responds!")
                        break  # Found a working one
                except:
                    print(f"  ❌ {url} doesn't respond")
                    continue
            
            print(f"🔮 Guessing found {len(results)} results")
            return results
            
        except Exception as e:
            print(f"❌ URL guessing failed: {e}")
            return []
    
    
    def _ai_select_official_website(self, brand_name: str, search_results: List[SearchResult]) -> Optional[str]:
        """Use AI to select the most likely official website from search results"""
        
        if not search_results:
            return None
        
        # Prepare search results for AI analysis
        results_text = ""
        for i, result in enumerate(search_results, 1):
            results_text += f"\n{i}. TITLE: {result.title}\n"
            results_text += f"   URL: {result.url}\n"
            results_text += f"   DOMAIN: {result.domain}\n"
            results_text += f"   DESCRIPTION: {result.description}\n"
        
        prompt = f"""
        I searched Google for "{brand_name} official website" and found these results. 
        Please select the most likely OFFICIAL WEBSITE for the fashion brand "{brand_name}".

        SEARCH RESULTS:
        {results_text}

        SELECTION CRITERIA:
        ✅ PREFER:
        - Official brand website (brand's own domain)
        - Clean, professional domain name
        - Domain that matches or contains the brand name
        - Results with "official" or brand name in title
        - Direct brand website (not retailers or marketplaces)

        ❌ AVOID:
        - Retailers selling the brand (Amazon, eBay, etc.)
        - Fashion blogs or news sites
        - Social media pages
        - Multi-brand retailers
        - Generic e-commerce platforms

        RESPOND WITH ONLY VALID JSON:
        {{
            "selected_number": 1-{len(search_results)} (which result number to select),
            "selected_url": "the full URL of the selected result",
            "confidence": 0.0-1.0,
            "reason": "brief explanation why this is the official website"
        }}

        If none of the results appear to be an official website, respond with:
        {{
            "selected_number": null,
            "selected_url": null,
            "confidence": 0.0,
            "reason": "no official website found in results"
        }}
        """
        
        try:
            response_text = self.llm._generate_response(prompt, max_tokens=400)
            
            # Extract JSON from response
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            
            if json_start != -1 and json_end != -1:
                json_text = response_text[json_start:json_end]
                result_data = json.loads(json_text)
                
                selected_url = result_data.get('selected_url')
                confidence = result_data.get('confidence', 0.0)
                reason = result_data.get('reason', '')
                
                print(f"🤖 AI Selection: {reason} (confidence: {confidence:.2f})")
                
                if selected_url and confidence > 0.5:
                    return selected_url
                else:
                    print(f"⚠️  AI confidence too low ({confidence:.2f}) or no selection made")
                    return None
            else:
                print("❌ Could not parse AI response")
                return None
                
        except Exception as e:
            print(f"❌ AI selection failed: {e}")
            # Fallback: return the first result if it looks reasonable
            if search_results:
                first_result = search_results[0]
                print(f"🔄 Fallback: Using first result: {first_result.url}")
                return first_result.url
            return None


# Test function
def test_brand_resolver():
    """Test the brand resolver with some known brands"""
    resolver = BrandURLResolver()
    
    test_brands = [
        "Jukuhara",
        "Comme des Garçons", 
        "Issey Miyake",
        "Yohji Yamamoto"
    ]
    
    for brand in test_brands:
        print(f"\n{'='*50}")
        print(f"Testing: {brand}")
        print('='*50)
        
        url = resolver.resolve_brand_name_to_url(brand)
        
        if url:
            print(f"✅ SUCCESS: {brand} → {url}")
        else:
            print(f"❌ FAILED: Could not find official website for {brand}")


if __name__ == "__main__":
    test_brand_resolver()