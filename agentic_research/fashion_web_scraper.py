#!/usr/bin/env python3

import requests
from bs4 import BeautifulSoup
import time
import random
from typing import List, Dict, Any
from urllib.parse import urljoin, urlparse
import re

class FashionWebScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
        # Fashion websites that are generally scrapeable
        self.fashion_sources = {
            'vogue': 'https://www.vogue.com',
            'wwd': 'https://wwd.com', 
            'harpers_bazaar': 'https://www.harpersbazaar.com',
            'elle': 'https://www.elle.com',
            'fashion_week_online': 'https://fashionweekonline.com'
        }
    
    def search_fashion_content(self, query: str, source_type: str = "general") -> List[Dict[str, Any]]:
        """Search for fashion content across multiple sources"""
        
        results = []
        
        # Try Google search for fashion-specific content
        google_results = self._google_fashion_search(query)
        results.extend(google_results[:3])  # Limit to top 3 results
        
        # Add small delay to be respectful
        time.sleep(1)
        
        return results
    
    def _google_fashion_search(self, query: str) -> List[Dict[str, Any]]:
        """Search Google for fashion content"""
        
        # Add fashion-specific terms to improve results
        fashion_query = f"{query} fashion show review collection"
        
        try:
            # Use DuckDuckGo instead of Google to avoid blocking
            search_url = f"https://html.duckduckgo.com/html/?q={fashion_query.replace(' ', '+')}"
            
            response = self.session.get(search_url, timeout=10)
            if response.status_code == 200:
                return self._parse_search_results(response.text, query)
            else:
                return []
                
        except Exception as e:
            print(f"Search error: {e}")
            return []
    
    def _parse_search_results(self, html: str, original_query: str) -> List[Dict[str, Any]]:
        """Parse search results and extract relevant links"""
        
        soup = BeautifulSoup(html, 'html.parser')
        results = []
        
        # Look for search result links
        for link in soup.find_all('a', class_=lambda x: x and 'result__a' in x):
            try:
                url = link.get('href')
                title = link.get_text().strip()
                
                if url and self._is_fashion_relevant(url, title):
                    # Try to scrape content from this URL
                    content = self._scrape_url_content(url)
                    if content:
                        results.append({
                            'url': url,
                            'title': title,
                            'content': content[:500],  # Limit content length
                            'relevance_score': self._calculate_relevance(content, original_query)
                        })
                
                if len(results) >= 3:  # Limit results
                    break
                    
            except Exception as e:
                continue
        
        return results
    
    def _is_fashion_relevant(self, url: str, title: str) -> bool:
        """Check if URL/title is fashion-related"""
        
        fashion_keywords = [
            'fashion', 'vogue', 'elle', 'bazaar', 'wwd', 'style', 'runway',
            'collection', 'designer', 'couture', 'ready-to-wear', 'show'
        ]
        
        text = f"{url} {title}".lower()
        return any(keyword in text for keyword in fashion_keywords)
    
    def _scrape_url_content(self, url: str) -> str:
        """Scrape content from a fashion URL"""
        
        try:
            response = self.session.get(url, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Remove script and style elements
                for script in soup(["script", "style"]):
                    script.decompose()
                
                # Try to find main content areas
                content_selectors = [
                    'article', '.article-content', '.post-content',
                    '.entry-content', '.content', 'main', '.main'
                ]
                
                content_text = ""
                for selector in content_selectors:
                    elements = soup.select(selector)
                    if elements:
                        content_text = ' '.join([elem.get_text() for elem in elements[:2]])
                        break
                
                if not content_text:
                    # Fallback: get all text
                    content_text = soup.get_text()
                
                # Clean up the text
                content_text = ' '.join(content_text.split())
                return content_text[:1000]  # Limit length
                
        except Exception as e:
            print(f"Scraping error for {url}: {e}")
            return ""
    
    def _calculate_relevance(self, content: str, query: str) -> float:
        """Calculate how relevant the content is to the query"""
        
        if not content:
            return 0.0
        
        query_words = query.lower().split()
        content_lower = content.lower()
        
        matches = sum(1 for word in query_words if word in content_lower)
        return min(matches / len(query_words), 1.0)
    
    def scrape_brand_info(self, brand_name: str) -> Dict[str, Any]:
        """Scrape information specifically about a fashion brand"""
        
        query = f"{brand_name} fashion brand history"
        results = self.search_fashion_content(query, "brand_history")
        
        return {
            'brand': brand_name,
            'sources': results,
            'content_summary': self._summarize_brand_content(results)
        }
    
    def scrape_collection_info(self, collection_query: str) -> Dict[str, Any]:
        """Scrape information about a specific collection"""
        
        results = self.search_fashion_content(collection_query, "collection")
        
        return {
            'collection': collection_query,
            'sources': results,
            'content_summary': self._summarize_collection_content(results)
        }
    
    def _summarize_brand_content(self, results: List[Dict[str, Any]]) -> str:
        """Summarize brand-related content"""
        if not results:
            return "No web content found"
        
        content_pieces = [result['content'] for result in results if result.get('content')]
        return ' '.join(content_pieces)[:800]  # Combine and limit
    
    def _summarize_collection_content(self, results: List[Dict[str, Any]]) -> str:
        """Summarize collection-related content"""
        if not results:
            return "No web content found"
        
        content_pieces = [result['content'] for result in results if result.get('content')]
        return ' '.join(content_pieces)[:800]  # Combine and limit

def test_scraper():
    """Test the fashion web scraper"""
    
    scraper = FashionWebScraper()
    
    print("🔍 Testing Fashion Web Scraper")
    print("=" * 40)
    
    # Test collection search
    collection_query = "Valentino Ready To Wear Fall Winter 2014 Paris"
    print(f"\n🎯 Searching for: {collection_query}")
    
    results = scraper.scrape_collection_info(collection_query)
    
    print(f"Found {len(results['sources'])} sources:")
    for i, source in enumerate(results['sources'], 1):
        print(f"  {i}. {source['title']}")
        print(f"     URL: {source['url']}")
        print(f"     Relevance: {source['relevance_score']:.2f}")
        print(f"     Preview: {source['content'][:100]}...")
        print()
    
    print("📝 Content Summary:")
    print(results['content_summary'])

if __name__ == "__main__":
    test_scraper()