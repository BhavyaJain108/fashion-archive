#!/usr/bin/env python3
"""
Google Video Search for Fashion Shows
Uses Google search with video filter to find fashion runway shows more reliably.
"""

import os
import re
import requests
from urllib.parse import quote_plus
from dataclasses import dataclass
from typing import List, Optional
from bs4 import BeautifulSoup
from anthropic import Anthropic
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


@dataclass
class GoogleVideoResult:
    """Represents a found fashion show video from Google search"""
    title: str
    url: str
    thumbnail_url: str = ""
    source: str = "google"


class GoogleVideoSearch:
    """Searches for fashion show videos using Google with video filter"""
    
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
    
    def search_fashion_show(self, query: str) -> Optional[GoogleVideoResult]:
        """
        Search Google for fashion show videos and use LLM to pick the best result
        
        Args:
            query: Fashion show query (e.g. "Givenchy Ready To Wear Fall Winter 2014 Paris")
            
        Returns:
            Best video result or None if nothing found
        """
        print(f"🔍 Google video search for: {query}")
        
        try:
            # Clean query: convert dashes to spaces
            clean_query = query.replace("-", " ")
            print(f"🧹 Cleaned query: {clean_query}")
            
            # Get full Google search results page with video filter
            html_content = self._get_google_video_search_page(clean_query)
            
            if not html_content:
                print("❌ Failed to get Google search results")
                return None
            
            # Use LLM to analyze the full page and pick best video
            best_video = self._analyze_with_llm(clean_query, html_content)
            
            return best_video
            
        except Exception as e:
            print(f"❌ Error in Google video search: {e}")
            return None
    
    def _get_google_video_search_page(self, query: str) -> Optional[str]:
        """Get Google search results page with video filter"""
        try:
            # Google search URL with video filter (tbm=vid)
            search_url = f"https://www.google.com/search?q={quote_plus(query)}&tbm=vid"
            print(f"🌐 Fetching: {search_url}")
            
            response = requests.get(search_url, headers=self.headers, timeout=10)
            response.raise_for_status()
            
            print(f"✅ Got Google results ({len(response.text)} characters)")
            return response.text
            
        except Exception as e:
            print(f"❌ Error fetching Google results: {e}")
            return None
    
    def _analyze_with_llm(self, query: str, html_content: str) -> Optional[GoogleVideoResult]:
        """Use Claude to analyze Google results and pick the best video"""
        try:
            print(f"🤖 Using Claude to analyze Google results...")
            
            api_key = os.getenv('CLAUDE_API_KEY') or os.getenv('ANTHROPIC_API_KEY')
            if not api_key:
                print("❌ No Claude API key found")
                return None
                
            client = Anthropic(api_key=api_key)
            
            # Extract video URLs from the HTML first
            soup = BeautifulSoup(html_content, 'html.parser')
            available_urls = []
            for element in soup.find_all('a', href=True):
                href = element.get('href', '')
                if 'youtube.com' in href or 'youtu.be' in href or 'vimeo.com' in href:
                    if href.startswith('/url?q='):
                        href = href[7:].split('&')[0]
                        from urllib.parse import unquote
                        href = unquote(href)
                    if href not in available_urls:
                        available_urls.append(href)
            
            if not available_urls:
                print("❌ No video URLs found in search results")
                return None
            
            # Create prompt with the actual URLs found
            urls_list = "\n".join([f"{i+1}. {url}" for i, url in enumerate(available_urls)])
            
            prompt = f"""For the query "{query}", analyze these video URLs from Google search results and select the BEST one that contains the full runway show for the exact season, brand, and collection specified.

IMPORTANT: You must select from one of these EXACT URLs found on the page:

{urls_list}

STRICT MATCHING RULES - BE VERY STRICT:

1. YEAR MATCHING:
- If searching for 2014: REJECT videos with "13/14", "2013-2014", "2013/2014" (contains previous year 2013)
- If searching for 2014: ACCEPT videos with "2014", "14/15", "2014-2015", "2014/2015" (starts with 2014)
- RULE: If video title contains the PREVIOUS year before the target year → REJECT
- EXAMPLE: Search=2014, Video="FW 13/14" → REJECT (contains 2013)
- EXAMPLE: Search=2014, Video="FW 14/15" → ACCEPT (starts with 2014)

2. COLLECTION TYPE MATCHING:
- Ready To Wear (RTW) ≠ Couture ≠ Haute Couture ≠ Menswear (MW)
- These are DIFFERENT collection types and NOT interchangeable
- If query says "Ready To Wear" → REJECT videos with "Couture", "Haute Couture", or "Menswear"
- If query says "Couture" → REJECT videos with "Haute Couture", "Ready To Wear", or "Menswear"  
- If query says "Haute Couture" → REJECT videos with "Couture", "Ready To Wear", or "Menswear"
- If query says "Menswear" → REJECT videos with any women's collections

3. SEASON MATCHING:
- Spring Summer (SS) ≠ Fall Winter (FW) - These are DIFFERENT seasons
- If query says "Spring Summer" → REJECT videos with "Fall Winter", "Autumn Winter", "FW", "AW"
- If query says "Fall Winter" → REJECT videos with "Spring Summer", "SS"
- EXAMPLE: Search="Spring Summer 2014" Video="Fall Winter 2014" → REJECT (wrong season)

Also look for:
- Official brand channels or reputable fashion sources  
- Full runway shows (not highlights, backstage, or reviews)
- Exact match for brand, season (Spring Summer vs Fall Winter), collection type, and year

You MUST select one of the URLs listed above. Do not create or modify URLs.
If NO videos meet ALL criteria above, return "found_match": false.

Return ONLY valid JSON. Use these exact field names and structure:

{{
    "found_match": true,
    "selected_url": "https://www.youtube.com/watch?v=example",
    "reasoning": "explanation here",
    "evidence": "exact webpage text here"
}}

OR if no match:

{{
    "found_match": false,
    "selected_url": "",
    "reasoning": "why no match was found",
    "evidence": ""
}}

CRITICAL: Your response must be valid JSON that can be parsed by json.loads(). Do not add any text before or after the JSON."""

            response = client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=1000,
                temperature=0.0,
                messages=[{"role": "user", "content": prompt}]
            )
            
            # Parse Claude's response
            response_text = response.content[0].text.strip()
            print(f"🎯 Claude response: {response_text}")
            
            import json
            # Extract JSON from response with better parsing
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            
            if json_start != -1 and json_end != -1:
                json_text = response_text[json_start:json_end]
                
                
                print(f"🔍 Extracted JSON: {json_text}")
                try:
                    result_data = json.loads(json_text)
                except json.JSONDecodeError as e:
                    print(f"❌ JSON parsing error: {e}")
                    print(f"📄 Problematic JSON: {json_text}")
                    return None
                
                if result_data.get('found_match', False):
                    selected_url = result_data.get('selected_url', '')
                    
                    # Verify the selected URL is actually from our list
                    if selected_url not in available_urls:
                        print(f"⚠️ Claude selected URL not in available list: {selected_url}")
                        return None
                    
                    print(f"🎯 Claude selected: {selected_url}")
                    print(f"💭 Reasoning: {result_data.get('reasoning', '')}")
                    print(f"🔍 Evidence from webpage: {result_data.get('evidence', '')}")
                    
                    # VERIFICATION LOOP: Get actual video title and check for year issues
                    actual_title = self._get_video_title(selected_url)
                    if actual_title:
                        print(f"📹 Actual video title: {actual_title}")
                        
                        # Check for year and collection type mismatches
                        verification_failed = False
                        failure_reason = ""
                        
                        # Extract target year from query
                        target_year = self._extract_target_year(query)
                        if target_year and self._contains_previous_year(actual_title, target_year):
                            verification_failed = True
                            failure_reason = f"Video contains previous year {target_year-1}"
                        
                        
                        if verification_failed:
                            print(f"🚫 VERIFICATION FAILED: {failure_reason}")
                            print(f"🔄 Asking Claude to try again with stricter filtering...")
                            
                            # Remove the bad URL and try again
                            filtered_urls = [url for url in available_urls if url != selected_url]
                            if filtered_urls:
                                return self._retry_with_stricter_rules(query, filtered_urls, actual_title, target_year, failure_reason)
                            else:
                                print("❌ No other URLs to try")
                                return None
                        else:
                            print("✅ Verification passed - year and collection type look correct")
                    
                    video_result = GoogleVideoResult(
                        title=actual_title or f"Video from {selected_url}",
                        url=selected_url,
                        source="google"
                    )
                    
                    print(f"✅ Final selection: {video_result.title}")
                    return video_result
                else:
                    print(f"❌ No match found. Reasoning: {result_data.get('reasoning', '')}")
                    return None
            else:
                print("❌ Could not parse JSON from Claude response")
                return None
                
        except Exception as e:
            print(f"❌ Error in LLM analysis: {e}")
            return None
    
    def _get_video_title(self, youtube_url: str) -> Optional[str]:
        """Get actual video title from YouTube URL"""
        try:
            print(f"🔍 Fetching video title for: {youtube_url}")
            response = requests.get(youtube_url, headers=self.headers, timeout=10)
            response.raise_for_status()
            
            # Extract title from YouTube page
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Try multiple selectors for YouTube title
            title_selectors = [
                'meta[name="title"]',
                'meta[property="og:title"]',
                'title'
            ]
            
            for selector in title_selectors:
                title_element = soup.select_one(selector)
                if title_element:
                    title = title_element.get('content') or title_element.get_text()
                    if title and '- YouTube' in title:
                        title = title.replace(' - YouTube', '').strip()
                    if title and len(title) > 5:
                        print(f"✅ Found title: {title}")
                        return title
            
            print("⚠️ Could not extract video title")
            return None
            
        except Exception as e:
            print(f"❌ Error fetching video title: {e}")
            return None
    
    def _extract_target_year(self, query: str) -> Optional[int]:
        """Extract target year from search query"""
        import re
        year_match = re.search(r'20(\d{2})', query)
        if year_match:
            return int(f"20{year_match.group(1)}")
        return None
    
    def _contains_previous_year(self, title: str, target_year: int) -> bool:
        """Check if title contains previous year (e.g., 2013 when searching for 2014)"""
        import re
        
        previous_year = target_year - 1
        previous_year_short = str(previous_year)[-2:]  # Get last 2 digits (e.g., "13" from 2013)
        
        # Look for previous year patterns
        patterns = [
            rf'\b{previous_year}\b',  # Full year: 2013
            rf'\b{previous_year_short}/\d{{2}}\b',  # Short format: 13/14
            rf'\b{previous_year_short}-\d{{2}}\b',  # Short format: 13-14
        ]
        
        for pattern in patterns:
            if re.search(pattern, title, re.IGNORECASE):
                print(f"🚫 Found previous year pattern '{pattern}' in title")
                return True
        
        return False
    
    
    def _retry_with_stricter_rules(self, query: str, remaining_urls: List[str], failed_title: str, target_year: int, failure_reason: str = "") -> Optional[GoogleVideoResult]:
        """Retry Claude selection with stricter rules and example of what went wrong"""
        try:
            api_key = os.getenv('CLAUDE_API_KEY') or os.getenv('ANTHROPIC_API_KEY')
            if not api_key:
                return None
                
            client = Anthropic(api_key=api_key)
            
            urls_list = "\n".join([f"{i+1}. {url}" for i, url in enumerate(remaining_urls)])
            
            failure_explanation = failure_reason or f"contains the WRONG YEAR {target_year-1} instead of {target_year}"
            
            prompt = f"""PREVIOUS ATTEMPT FAILED! The last video selected was "{failed_title}" which {failure_explanation}.

For the query "{query}", analyze these remaining video URLs and select the BEST one that contains the full runway show for the EXACT season, brand, and collection specified.

REMAINING URLs:
{urls_list}

STRICT VERIFICATION RULES - NO EXCEPTIONS:

1. YEAR MATCHING:
- Target year: {target_year}
- REJECT any video containing {target_year-1} (previous year)
- REJECT patterns like "{str(target_year-1)[-2:]}/{str(target_year)[-2:]}" or "{target_year-1}-{target_year}"
- ONLY ACCEPT videos with exactly {target_year} or starting with {target_year}

2. COLLECTION TYPE MATCHING:
- Ready To Wear (RTW) ≠ Couture ≠ Haute Couture ≠ Menswear (MW)
- These are DIFFERENT collection types and NOT interchangeable
- If query says "Ready To Wear" → REJECT videos with "Couture", "Haute Couture", or "Menswear"
- If query says "Couture" → REJECT videos with "Haute Couture", "Ready To Wear", or "Menswear"
- If query says "Haute Couture" → REJECT videos with "Couture", "Ready To Wear", or "Menswear"
- If query says "Menswear" → REJECT videos with any women's collections

3. SEASON MATCHING:
- Spring Summer (SS) ≠ Fall Winter (FW) - These are DIFFERENT seasons
- If query says "Spring Summer" → REJECT videos with "Fall Winter", "Autumn Winter", "FW", "AW"
- If query says "Fall Winter" → REJECT videos with "Spring Summer", "SS"
- EXAMPLE: Search="Spring Summer 2014" Video="Fall Winter 2014" → REJECT (wrong season)

EXAMPLE OF WHAT WENT WRONG: 
- Bad selection: "{failed_title}" ({failure_explanation})
- We need: Exact match for year AND collection type AND season

Also avoid: Style.com, Elle, Vogue highlights, backstage content

Return ONLY valid JSON. Use these exact field names and structure:

{{
    "found_match": true,
    "selected_url": "https://www.youtube.com/watch?v=example",
    "reasoning": "explanation focusing on why this {target_year} video is correct",
    "evidence": "exact text showing this video is from {target_year}"
}}

OR if no match:

{{
    "found_match": false,
    "selected_url": "",
    "reasoning": "why no match was found after previous failure",
    "evidence": ""
}}

CRITICAL: Your response must be valid JSON that can be parsed by json.loads(). Do not add any text before or after the JSON."""

            response = client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=1000,
                temperature=0.0,
                messages=[{"role": "user", "content": prompt}]
            )
            
            response_text = response.content[0].text.strip()
            print(f"🔄 Retry Claude response: {response_text}")
            
            # Parse the retry response
            import json
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            
            if json_start != -1 and json_end != -1:
                json_text = response_text[json_start:json_end]
                
                
                try:
                    result_data = json.loads(json_text)
                    
                    if result_data.get('found_match', False):
                        selected_url = result_data.get('selected_url', '')
                        if selected_url in remaining_urls:
                            print(f"🎯 Retry selection: {selected_url}")
                            print(f"💭 Retry reasoning: {result_data.get('reasoning', '')}")
                            print(f"🔍 Retry evidence: {result_data.get('evidence', '')}")
                            
                            return GoogleVideoResult(
                                title=f"Retry selection from {selected_url}",
                                url=selected_url,
                                source="google"
                            )
                    
                    print(f"❌ Retry failed. Reasoning: {result_data.get('reasoning', '')}")
                    return None
                    
                except json.JSONDecodeError as e:
                    print(f"❌ Retry JSON parsing error: {e}")
                    return None
            
            return None
            
        except Exception as e:
            print(f"❌ Error in retry attempt: {e}")
            return None


def main():
    import sys
    
    if len(sys.argv) != 2:
        print("Usage: python google_video_search.py 'Your Search Query'")
        print("Example: python google_video_search.py 'Givenchy Ready To Wear Fall Winter 2014 Paris'")
        return
    
    query = sys.argv[1]
    google_search = GoogleVideoSearch()
    
    print(f"🔍 Search Query: {query}")
    
    # Clean query: convert dashes to spaces
    clean_query = query.replace("-", " ")
    print(f"🧹 Cleaned Query: {clean_query}")
    
    # Get Google search URL
    from urllib.parse import quote_plus
    search_url = f"https://www.google.com/search?q={quote_plus(clean_query)}&tbm=vid"
    print(f"🌐 Google Search URL: {search_url}")
    
    # Get the HTML content
    html_content = google_search._get_google_video_search_page(clean_query)
    
    if not html_content:
        print("❌ Failed to get Google search results")
        return
    
    # Extract and print all video URLs (debug step)
    soup = BeautifulSoup(html_content, 'html.parser')
    
    all_urls = []
    for element in soup.find_all('a', href=True):
        href = element.get('href', '')
        if 'youtube.com' in href or 'youtu.be' in href or 'vimeo.com' in href:
            # Clean up Google's URL format
            if href.startswith('/url?q='):
                href = href[7:].split('&')[0]
                from urllib.parse import unquote
                href = unquote(href)
            all_urls.append(href)
    
    # Remove duplicates while preserving order
    seen = set()
    unique_urls = []
    for url in all_urls:
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)
    
    print(f"\n📺 URLs found on page ({len(unique_urls)} total):")
    for i, url in enumerate(unique_urls):
        print(f"{i + 1}. {url}")
    
    # Use LLM to select the best video
    print(f"\n🤖 LLM Analysis:")
    result = google_search.search_fashion_show(query)
    
    if result:
        print(f"\n✅ SELECTED URL: {result.url}")
        print(f"📝 Title: {result.title}")
    else:
        print(f"\n❌ No suitable video selected")


if __name__ == "__main__":
    main()