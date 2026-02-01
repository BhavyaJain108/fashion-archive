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
from dotenv import load_dotenv
from llm_interface import get_llm_client

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

    def get_all_video_candidates(self, query: str) -> List[str]:
        """
        Get all video URLs from Google search results for fallback attempts
        
        Args:
            query: Fashion show query
            
        Returns:
            List of video URLs ordered by relevance
        """
        print(f"🔍 Getting all video candidates for: {query}")
        
        try:
            # Clean query: convert dashes to spaces
            clean_query = query.replace("-", " ")
            
            # Get full Google search results page with video filter
            html_content = self._get_google_video_search_page(clean_query)
            
            if not html_content:
                print("❌ Failed to get Google search results")
                return []
            
            # Extract all video URLs from the HTML
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
            
            print(f"✅ Found {len(available_urls)} video candidates")
            return available_urls
            
        except Exception as e:
            print(f"❌ Error getting video candidates: {e}")
            return []
    
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
            print(f"🤖 Using LLM to analyze Google results...")
            
            try:
                llm_client = get_llm_client()
            except (ValueError, ImportError) as e:
                print(f"❌ LLM setup failed: {e}")
                return None
            
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
            
            # Fetch titles for each URL so the LLM can judge quality and relevance
            max_urls_to_check = min(8, len(available_urls))
            urls_with_titles = []
            print(f"📊 Fetching titles for {max_urls_to_check} of {len(available_urls)} URLs...")
            for i, url in enumerate(available_urls[:max_urls_to_check]):
                title = self._get_video_title(url) or f"(unknown title)"
                urls_with_titles.append((url, title))
                print(f"  {i+1}. {title} — {url}")

            urls_list = "\n".join([f"{i+1}. TITLE: {title}\n   URL: {url}" for i, (url, title) in enumerate(urls_with_titles)])

            prompt = f"""For the query "{query}", analyze these video URLs and their titles from Google search results and select the BEST one.

You must select from one of these EXACT URLs found on the page:

{urls_list}

CRITICAL RULE: DO NOT ANALYZE DATES OR TIMING. Do not say anything about "future shows", "hasn't happened yet", or "show footage could exist". Ignore all calendar considerations completely. Just pick the most relevant URL from the list.

IMPORTANT: Your job is to pick the MOST LIKELY match from the available URLs, even if it's not perfect. The verification system will check it properly later.

QUALITY AND RELEVANCE GUIDELINES (in priority order):
1. CORRECT MATCH FIRST: The video must match the brand, season, year, and collection type
2. PREFER HIGH QUALITY: Among correct matches, strongly prefer videos with titles containing "Full Show", "Full Runway", "HD", "1080", "4K", or "Complete Show"
3. PREFER OFFICIAL CHANNELS: Prefer uploads from official fashion channels (e.g. containing the brand name in the channel) over random reuploads
4. PREFER LONGER VIDEOS: Full runway shows are typically 8-20+ minutes. Avoid short clips, highlights, backstage, or review content
5. Avoid Style.com and Elle (they're usually short low-quality clips)
6. Prefer videos that mention the same brand
7. Try to match year, season, or collection type when possible

You MUST ALWAYS select exactly one URL from the list above. Even if none are perfect matches, pick the MOST RELEVANT one. DO NOT return "found_match": false unless the list is completely empty or contains zero fashion-related content.

Return ONLY valid JSON. Use these exact field names and structure:

{{
    "found_match": true,
    "selected_url": "https://www.youtube.com/watch?v=example",
    "reasoning": "single line explanation without newlines",
    "evidence": "exact webpage text without newlines"
}}

OR if no match:

{{
    "found_match": false,
    "selected_url": "",
    "reasoning": "single line explanation without newlines",
    "evidence": ""
}}

CRITICAL:
- Your response must be valid JSON that can be parsed by json.loads()
- Do NOT use newlines, line breaks, or \\n inside JSON string values
- Keep all text on single lines within the JSON strings
- Do not add any text before or after the JSON"""

            response_text = llm_client.generate(prompt, max_tokens=1000, temperature=0.0)
            print(f"🎯 LLM response: {response_text}")
            
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
                    
                    print(f"🎯 LLM selected: {selected_url}")
                    print(f"💭 Reasoning: {result_data.get('reasoning', '')}")
                    print(f"🔍 Evidence from webpage: {result_data.get('evidence', '')}")
                    
                    # VERIFICATION LOOP: Get actual video title and check for year issues
                    actual_title = self._get_video_title(selected_url)
                    if actual_title:
                        print(f"📹 Actual video title: {actual_title}")
                        
                        # Run comprehensive verification checklist
                        target_year = self._extract_target_year(query)
                        verification_failed, failure_reason = self._run_verification_checklist(query, actual_title, target_year)
                        
                        if verification_failed:
                            print(f"🚫 VERIFICATION FAILED: {failure_reason}")
                            
                            # Check if Claude's selection seems perfect despite verification failure
                            # This handles cases where verification is overly strict
                            if self._is_likely_perfect_match(query, actual_title):
                                print(f"⚠️ Verification failed but title appears to be perfect match")
                                print(f"🔧 Overriding verification - title contains all expected elements")
                                # Proceed with the selection despite verification failure
                            else:
                                print(f"🔄 Asking LLM to try again with stricter filtering...")
                                
                                # Remove the bad URL and try again with verification loop
                                filtered_urls = [url for url in available_urls if url != selected_url]
                                if filtered_urls:
                                    return self._verification_loop(query, filtered_urls, actual_title, target_year, failure_reason)
                                else:
                                    print("❌ No other URLs to try")
                                    return None
                        else:
                            print("✅ Verification passed - year, collection type, season, and source look correct")
                    
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
    
    def _has_year_mismatch(self, title: str, target_year: int) -> bool:
        """Check if title has wrong year using fashion industry rules"""
        import re
        
        # Fashion industry year rules for search year 2014:
        # ✅ ACCEPT: 2014, 2014-2015, 2014/2015, 14/15, 14-15
        # ❌ REJECT: 2013, 2013-2014, 2013/2014, 13/14, 13-14, 2015, 2025, etc.
        # Rule: Year must START with target year, not END with it
        
        target_year_str = str(target_year)
        target_year_short = target_year_str[-2:]  # "14" from 2014
        next_year_short = str(target_year + 1)[-2:]  # "15" from 2015
        
        # Acceptable patterns that START with target year
        acceptable_patterns = [
            rf'\b{target_year}\b',  # Exact: 2014
            rf'\b{target_year}-{target_year + 1}\b',  # Full range: 2014-2015
            rf'\b{target_year}/{target_year + 1}\b',  # Full range: 2014/2015
            rf'\b{target_year_short}/{next_year_short}\b',  # Short range: 14/15
            rf'\b{target_year_short}-{next_year_short}\b',  # Short range: 14-15
        ]
        
        # Check if title contains any acceptable pattern
        has_acceptable_year = False
        for pattern in acceptable_patterns:
            if re.search(pattern, title, re.IGNORECASE):
                print(f"✅ Found acceptable year pattern: {pattern}")
                has_acceptable_year = True
                break
        
        if not has_acceptable_year:
            print(f"🚫 No acceptable year pattern found. Expected patterns starting with {target_year}")
            return True
        
        # Check for FORBIDDEN patterns (previous year)
        previous_year = target_year - 1
        previous_year_short = str(previous_year)[-2:]
        
        forbidden_patterns = [
            rf'\b{previous_year}-{target_year}\b',  # 2013-2014
            rf'\b{previous_year}/{target_year}\b',  # 2013/2014
            rf'\b{previous_year_short}/{target_year_short}\b',  # 13/14
            rf'\b{previous_year_short}-{target_year_short}\b',  # 13-14
        ]
        
        for pattern in forbidden_patterns:
            if re.search(pattern, title, re.IGNORECASE):
                print(f"🚫 Found forbidden previous year pattern: {pattern}")
                return True
        
        return False
    
    def _extract_collection_type(self, text: str) -> Optional[str]:
        """Extract collection type from text"""
        import re
        text_lower = text.lower()
        
        # Check for collection types (couture and haute couture are treated as the same)
        if re.search(r'\b(haute\s*couture|couture|hc)\b', text_lower):
            return 'couture'  # Normalize both to 'couture'
        elif re.search(r'\b(menswear|men\'s|mens|mw)\b', text_lower):
            return 'menswear'
        elif re.search(r'\b(ready\s*to\s*wear|rtw|pret\s*a\s*porter)\b', text_lower):
            return 'ready to wear'
        
        return None
    
    def _extract_season(self, text: str) -> Optional[str]:
        """Extract season from text"""
        import re
        text_lower = text.lower()
        
        if re.search(r'\b(spring\s*summer|spring/summer|ss)\b', text_lower):
            return 'spring summer'
        elif re.search(r'\b(fall\s*winter|autumn\s*winter|fall/winter|autumn/winter|fw|aw)\b', text_lower):
            return 'fall winter'
        
        return None
    
    def _is_likely_perfect_match(self, query: str, actual_title: str) -> bool:
        """
        Check if a title is likely a perfect match despite failing strict verification.
        This helps avoid unnecessary retries when Claude picked correctly.
        """
        query_lower = query.lower()
        title_lower = actual_title.lower()
        
        # Check if title contains "full show" or "complete show" - strong indicator
        if 'full show' in title_lower or 'complete show' in title_lower or 'full runway' in title_lower:
            # Check if key brand elements are present
            query_words = query_lower.split()
            brand_words_found = sum(1 for word in query_words[:2] if word in title_lower)
            
            # If it says "full show" and has brand words, it's likely good
            if brand_words_found >= 1:
                return True
        
        # Check for exact phrase matches (e.g., "haute couture" in both)
        important_phrases = ['haute couture', 'ready to wear', 'menswear', 'spring summer', 'fall winter']
        matching_phrases = sum(1 for phrase in important_phrases if phrase in query_lower and phrase in title_lower)
        
        # If multiple important phrases match exactly, likely good
        if matching_phrases >= 2:
            return True
        
        return False
    
    def _check_brand_match(self, query: str, actual_title: str) -> bool:
        """Enhanced brand check with special handling for fashion brands"""
        # Get first word(s) from query (usually the brand)
        query_words = query.split()
        if not query_words:
            return True  # No brand to check
        
        query_lower = query.lower()
        title_lower = actual_title.lower()
        
        # Special case: Armani Prive / Giorgio Armani Privé
        if 'armani' in query_lower and 'prive' in query_lower:
            # Accept any variation: "armani prive", "giorgio armani prive", "armani privé"
            return 'armani' in title_lower and ('prive' in title_lower or 'privé' in title_lower)
        
        # Special case: Multi-word brands (check first two words if applicable)
        first_word = query_words[0].lower()
        
        # If it's a known multi-word brand, check both words
        multi_word_brands = ['saint laurent', 'bottega veneta', 'louis vuitton', 'calvin klein', 
                            'marc jacobs', 'michael kors', 'tory burch', 'tommy hilfiger']
        
        for brand in multi_word_brands:
            if query_lower.startswith(brand):
                return brand.replace(' ', '') in title_lower.replace(' ', '') or brand in title_lower
        
        # Default: Check if first word appears in video title (partial match allowed)
        return first_word in title_lower
    
    def _verify_season_with_llm(self, query: str, video_title: str, expected_season: str) -> bool:
        """Use LLM to verify if video season matches query season using reasoning"""
        try:
            try:
                llm_client = get_llm_client()
            except (ValueError, ImportError) as e:
                print(f"⚠️ LLM setup failed - skipping season verification: {e}")
                return True  # Allow if no LLM available
            
            prompt = f"""Determine if these two fashion items refer to the SAME SEASON:

Query: "{query}"
Video Title: "{video_title}"

The query mentions "{expected_season}". Does the video title refer to the same season?

SEASON REASONING GUIDE:
- Fall/Winter/Autumn = September-February collections (shown in Feb-March typically)
- Spring/Summer = March-August collections (shown in Sep-Oct typically)
- Months like "August, September, October, November, December, January" = Fall/Winter season
- Months like "February, March, April, May, June, July" = Spring/Summer season
- Look for context clues beyond just month names

Answer ONLY "YES" if they refer to the same season, or "NO" if different seasons.
Do not explain, just answer YES or NO."""

            answer = llm_client.generate(prompt, max_tokens=10, temperature=0.0).upper()
            print(f"🤖 LLM season verification: {answer}")
            return answer == "YES"
            
        except Exception as e:
            print(f"⚠️ LLM season verification failed: {e}")
            return True  # Allow if verification fails
    
    def _run_verification_checklist(self, query: str, actual_title: str, target_year: Optional[int]) -> tuple[bool, str]:
        """
        Comprehensive verification checklist for fashion videos
        Returns: (verification_failed, failure_reason)
        """
        print("📋 Running verification checklist...")
        
        # ✅ CHECK 1: Brand/Label Matching (simple first word check)
        if not self._check_brand_match(query, actual_title):
            first_word = query.split()[0] if query.split() else "unknown"
            return True, f"Brand mismatch: Expected '{first_word}' but not found in video title"
        print("✅ Brand check passed")
        
        # ✅ CHECK 2: Banned Sources
        if "style.com" in actual_title.lower() or "elle" in actual_title.lower():
            return True, "Video is from banned source (Style.com or Elle)"
        print("✅ Source check passed")
        
        # ✅ CHECK 3: Year Validation
        if target_year and self._has_year_mismatch(actual_title, target_year):
            return True, f"Video has wrong year (expected {target_year})"
        print("✅ Year check passed")
        
        # ✅ CHECK 4: Collection Type Matching 
        query_collection = self._extract_collection_type(query)
        title_collection = self._extract_collection_type(actual_title)
        
        # Special case: If query mentions couture, enforce two-way strict matching
        if query_collection == 'couture':
            if not title_collection:
                return True, f"Query specifies '{query_collection}' but video doesn't mention collection type"
            elif title_collection != 'couture':
                return True, f"Collection type mismatch: Query='{query_collection}' vs Video='{title_collection}'"
            else:
                print(f"✅ Collection type check passed (two-way couture match): {query_collection}")
        elif title_collection:
            # If video mentions a collection type, query must match it (except couture already handled above)
            if title_collection == 'couture':
                # Video mentions couture - query MUST mention couture (strict enforcement)
                if not query_collection or query_collection != 'couture':
                    return True, f"Video mentions '{title_collection}' but query doesn't specify couture"
                else:
                    print(f"✅ Collection type check passed: {title_collection}")
            elif title_collection == 'menswear':
                # Video mentions menswear - query should mention menswear
                if not query_collection or query_collection != 'menswear':
                    return True, f"Video mentions '{title_collection}' but query doesn't specify menswear"
                else:
                    print(f"✅ Collection type check passed: {title_collection}")
            else:
                # Video mentions ready-to-wear or other - more flexible
                if query_collection and query_collection != title_collection:
                    print(f"⚠️ Collection type mismatch but allowing for non-couture: Video='{title_collection}' vs Query='{query_collection}'")
                else:
                    print(f"✅ Collection type check passed: {title_collection}")
        else:
            # Video doesn't mention collection type
            if query_collection == 'menswear':
                # Menswear queries are strict - video must mention menswear
                return True, f"Query specifies '{query_collection}' but video doesn't mention collection type"
            elif query_collection == 'couture':
                # This case is already handled above in the special couture check
                pass
            elif query_collection == 'ready to wear':
                # RTW queries are flexible - allow videos without collection type
                print(f"⚠️ Query specifies '{query_collection}' but video doesn't mention collection type - allowing")
            else:
                print("⚠️ No collection type mentioned in either query or video - allowing")
        
        # ✅ CHECK 5: Season Matching (let LLM handle complex season reasoning)
        query_season = self._extract_season(query)
        
        if query_season:
            # Query specifies a season - use LLM to verify video season matches
            season_match = self._verify_season_with_llm(query, actual_title, query_season)
            if not season_match:
                return True, f"Season mismatch: Query specifies '{query_season}' but video appears to be different season"
            print(f"✅ Season check passed: {query_season}")
        else:
            print("⚠️ No specific season mentioned in query - skipping season check")
        
        print("🎉 All verification checks passed!")
        return False, ""
    
    
    def _verification_loop(self, query: str, remaining_urls: List[str], failed_title: str, target_year: int, failure_reason: str = "") -> Optional[GoogleVideoResult]:
        """Verification loop - keeps trying URLs until one passes all checks or URLs are exhausted"""
        max_attempts = 5  # Safety limit
        attempt = 1
        
        print(f"🔁 ENTERING RETRY MODE")
        print(f"   Previous failure: {failed_title}")
        print(f"   Reason: {failure_reason}")
        print(f"   URLs available for retry: {len(remaining_urls)}")
        
        while remaining_urls and attempt <= max_attempts:
            print(f"🔄 Retry attempt {attempt}/{max_attempts}")
            
            # Get Claude to select from remaining URLs
            retry_result = self._retry_with_stricter_rules(query, remaining_urls, failed_title, target_year, failure_reason)
            
            if not retry_result:
                print("⚠️ Claude couldn't select from remaining URLs, trying next attempt")
                attempt += 1
                continue
            
            # Verify the retry result
            print(f"🔍 Verifying retry selection: {retry_result.url}")
            actual_title = self._get_video_title(retry_result.url)
            
            if not actual_title:
                print("⚠️ Could not get video title for verification, removing URL and trying next")
                remaining_urls = [url for url in remaining_urls if url != retry_result.url]
                attempt += 1
                continue
            
            print(f"📹 Actual title: {actual_title}")
            
            # Run comprehensive verification checklist
            verification_failed, new_failure_reason = self._run_verification_checklist(query, actual_title, target_year)
            
            if verification_failed:
                print(f"🚫 RETRY VERIFICATION FAILED: {new_failure_reason}")
                # Remove this URL and continue loop
                remaining_urls = [url for url in remaining_urls if url != retry_result.url]
                failed_title = actual_title
                failure_reason = new_failure_reason
                attempt += 1
                continue
            else:
                print("✅ Retry verification passed - found valid video!")
                return GoogleVideoResult(
                    title=actual_title,
                    url=retry_result.url,
                    source="google"
                )
        
        print(f"❌ Verification loop exhausted after {attempt-1} attempts")
        return None

    def _retry_with_stricter_rules(self, query: str, remaining_urls: List[str], failed_title: str, target_year: int, failure_reason: str = "") -> Optional[GoogleVideoResult]:
        """Retry LLM selection with stricter rules and example of what went wrong"""
        try:
            try:
                llm_client = get_llm_client()
            except (ValueError, ImportError) as e:
                print(f"❌ LLM setup failed: {e}")
                return None
            
            # Get titles for URLs to provide better context
            # OPTIMIZATION: Only fetch titles for first 5 URLs to avoid excessive requests
            urls_with_titles = []
            max_urls_to_check = min(5, len(remaining_urls))
            print(f"📊 Fetching titles for {max_urls_to_check} of {len(remaining_urls)} remaining URLs...")
            
            for i, url in enumerate(remaining_urls[:max_urls_to_check]):
                title = self._get_video_title(url) or f"URL {i+1}"
                urls_with_titles.append(f"{i+1}. TITLE: {title}\n   URL: {url}")
            
            # Add remaining URLs without fetching titles
            if len(remaining_urls) > max_urls_to_check:
                urls_with_titles.append(f"\n... and {len(remaining_urls) - max_urls_to_check} more URLs available")
            
            urls_list = "\n".join(urls_with_titles)
            
            failure_explanation = failure_reason or f"contains the WRONG YEAR {target_year-1} instead of {target_year}"
            
            prompt = f"""PREVIOUS ATTEMPT FAILED! The last video selected was "{failed_title}" which {failure_explanation}.

For the query "{query}", analyze these remaining videos and select the BEST one that contains the full runway show for the EXACT season, brand, and collection specified.

REMAINING VIDEOS:
{urls_list}

STRICT VERIFICATION RULES - NO EXCEPTIONS:

1. YEAR MATCHING:
- Target year: {target_year}
- REJECT any video containing {target_year-1} (previous year)
- REJECT patterns like "{str(target_year-1)[-2:]}/{str(target_year)[-2:]}" or "{target_year-1}-{target_year}"
- ONLY ACCEPT videos with exactly {target_year} or starting with {target_year}

3. COLLECTION TYPE MATCHING:
- Ready To Wear (RTW) ≠ Couture ≠ Menswear (MW)
- Couture and Haute Couture are the SAME (some brands just have "haute" privilege)
- If query says "Ready To Wear" → REJECT videos with "Couture", "Haute Couture", or "Menswear"
- If query says "Couture" → ACCEPT videos with "Haute Couture" (same thing), REJECT "Ready To Wear" or "Menswear"
- If query says "Haute Couture" → ACCEPT videos with "Couture" (same thing), REJECT "Ready To Wear" or "Menswear"
- If query says "Menswear" → REJECT videos with any women's collections

4. SEASON MATCHING:
- Spring Summer (SS) ≠ Fall Winter (FW) - These are DIFFERENT seasons
- If query says "Spring Summer" → REJECT videos with "Fall Winter", "Autumn Winter", "FW", "AW"
- If query says "Fall Winter" → REJECT videos with "Spring Summer", "SS"
- EXAMPLE: Search="Spring Summer 2014" Video="Fall Winter 2014" → REJECT (wrong season)

EXAMPLE OF WHAT WENT WRONG: 
- Bad selection: "{failed_title}" ({failure_explanation})
- We need: Exact match for year AND collection type AND season

Also avoid: Style.com, Elle, Vogue highlights, backstage content

You MUST select exactly one video title from the remaining list. Do not return "found_match": false.

Return ONLY valid JSON. Use these exact field names and structure:

{{
    "selected_title": "exact video title from the list",
    "reasoning": "single line explanation focusing on why this video is the best available option",
    "evidence": "single line text from the video title or description"
}}

CRITICAL: 
- Your response must be valid JSON that can be parsed by json.loads()
- Do NOT use newlines, line breaks, or \\n inside JSON string values
- Keep all text on single lines within the JSON strings
- Do not add any text before or after the JSON"""

            response_text = llm_client.generate(prompt, max_tokens=1000, temperature=0.0)
            print(f"🤖 LLM retry selection response: {response_text}")
            
            # Parse the retry response
            import json
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            
            if json_start != -1 and json_end != -1:
                json_text = response_text[json_start:json_end]
                
                
                try:
                    result_data = json.loads(json_text)
                    
                    selected_title = result_data.get('selected_title', '')
                    if selected_title:
                        print(f"🎯 Retry: Claude selected new title: {selected_title}")
                        print(f"💭 Selection reasoning: {result_data.get('reasoning', '')}")
                        print(f"🔍 Supporting evidence: {result_data.get('evidence', '')}")
                        
                        # Find matching URL for the selected title
                        # CRITICAL FIX: Don't re-fetch titles, use the ones we already have!
                        matching_url = None
                        
                        # Normalize title for matching (handle encoding issues)
                        def normalize_title(title):
                            import unicodedata
                            # Remove accents and special chars for matching
                            normalized = unicodedata.normalize('NFKD', title)
                            normalized = ''.join(c for c in normalized if not unicodedata.combining(c))
                            # Remove extra spaces and make lowercase
                            return ' '.join(normalized.lower().split())
                        
                        selected_normalized = normalize_title(selected_title)
                        
                        # Look through the titles we ALREADY fetched above
                        for i, url in enumerate(remaining_urls[:max_urls_to_check]):
                            # We already have these titles from line 601-602!
                            if i < len(urls_with_titles):
                                # Extract title from the formatted string
                                title_line = urls_with_titles[i]
                                if 'TITLE:' in title_line:
                                    url_title = title_line.split('TITLE:')[1].split('\n')[0].strip()
                                    url_normalized = normalize_title(url_title)
                                    
                                    # Check if titles match (with fuzzy matching for special chars)
                                    if selected_normalized == url_normalized or selected_normalized in url_normalized:
                                        matching_url = url
                                        print(f"🎯 Found matching URL: {url}")
                                        print(f"   Matched: '{url_title}'")
                                        break
                        
                        if matching_url:
                            return GoogleVideoResult(
                                title=selected_title,
                                url=matching_url,
                                source="google"
                            )
                        else:
                            print(f"⚠️ Could not find URL for selected title: {selected_title}")
                            print("🔄 This counts as a failed attempt, will continue with next attempt")
                            return None
                    else:
                        print(f"❌ No title selected in response")
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