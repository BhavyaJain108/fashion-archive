#!/usr/bin/env python3
"""
Fashion Video Search Module
Searches for fashion show videos online based on collection information.
"""

import re
import requests
from urllib.parse import quote_plus
from dataclasses import dataclass
from typing import List, Optional, Dict
from bs4 import BeautifulSoup


@dataclass
class VideoResult:
    """Represents a found fashion show video"""
    title: str
    url: str
    thumbnail_url: str
    duration: str = ""
    view_count: str = ""
    source: str = "youtube"
    confidence: float = 0.0


class CollectionNameParser:
    """Parses collection information to create good search queries"""
    
    def __init__(self):
        self.season_patterns = {
            'spring': ['spring', 'ss', 'spring-summer'],
            'summer': ['summer'],
            'fall': ['fall', 'autumn', 'fw', 'fall-winter'], 
            'winter': ['winter'],
            'resort': ['resort', 'pre-fall', 'cruise'],
            'pre-spring': ['pre-spring'],
            'couture': ['couture', 'haute-couture', 'hc']
        }
        
        self.cities = ['paris', 'milan', 'london', 'new-york', 'newyork']
        self.year_pattern = r'20\d{2}|19\d{2}'
        
    def parse_collection_info(self, collection_name: str, collection_url: str = "") -> Dict[str, str]:
        """Extract designer, season, year, city from collection data"""
        info = {
            'designer': '',
            'season': '',
            'year': '',
            'city': '',
            'original': collection_name
        }
        
        # Clean and normalize the name
        name_lower = collection_name.lower().replace('-', ' ').replace('_', ' ')
        
        # Try to extract from URL if provided
        if collection_url:
            url_parts = collection_url.lower().split('/')
            name_lower += ' ' + ' '.join(url_parts)
        
        # Extract year
        year_match = re.search(self.year_pattern, name_lower)
        if year_match:
            info['year'] = year_match.group()
        
        # Extract season
        for season, patterns in self.season_patterns.items():
            for pattern in patterns:
                if pattern in name_lower:
                    info['season'] = season
                    break
            if info['season']:
                break
        
        # Extract city
        for city in self.cities:
            if city in name_lower:
                info['city'] = city.replace('-', ' ')
                break
        
        # Extract designer (remaining significant words)
        words = name_lower.split()
        designer_words = []
        skip_words = {'fashion', 'week', 'show', 'runway', 'collection', 'ready', 'wear', 'to', 'the'}
        
        for word in words:
            if (len(word) > 2 and 
                word not in skip_words and
                word not in self.cities and
                not re.match(self.year_pattern, word) and
                not any(pattern in word for patterns in self.season_patterns.values() for pattern in patterns)):
                designer_words.append(word)
                if len(designer_words) >= 2:  # Limit to first 2 significant words
                    break
        
        info['designer'] = ' '.join(designer_words)
        
        return info
    
    def create_search_query(self, collection_info: Dict[str, str]) -> str:
        """Create optimized search query for fashion videos"""
        query_parts = []
        
        # Add designer name (most important)
        if collection_info['designer']:
            query_parts.append(collection_info['designer'])
        
        # Add season and year
        if collection_info['season'] and collection_info['year']:
            query_parts.append(f"{collection_info['season']} {collection_info['year']}")
        
        # Add city if available
        if collection_info['city']:
            query_parts.append(collection_info['city'])
        
        # Add fashion-specific terms
        query_parts.extend(['fashion show', 'runway'])
        
        return ' '.join(query_parts)


class YouTubeVideoSearch:
    """Searches for YouTube videos without requiring API key"""
    
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
    
    def search_videos(self, query: str, max_results: int = 5) -> List[VideoResult]:
        """Search YouTube for videos matching the query"""
        try:
            # Construct YouTube search URL
            search_url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
            
            print(f"Searching YouTube for: {query}")
            response = requests.get(search_url, headers=self.headers, timeout=10)
            response.raise_for_status()
            
            # Parse the response to extract video information
            videos = self._parse_youtube_results(response.text, max_results)
            
            # Calculate confidence scores
            for video in videos:
                video.confidence = self._calculate_confidence(video.title.lower(), query.lower())
            
            # Sort by confidence score
            videos.sort(key=lambda x: x.confidence, reverse=True)
            
            return videos
            
        except Exception as e:
            print(f"Error searching YouTube: {e}")
            return []
    
    def _parse_youtube_results(self, html_content: str, max_results: int) -> List[VideoResult]:
        """Parse YouTube search results from HTML"""
        videos = []
        
        try:
            # Look for video data in the HTML
            # YouTube uses JavaScript to load content, so we look for initial data
            
            # Pattern to find video IDs and titles
            video_pattern = r'"videoId":"([^"]+)".*?"title":{"runs":\[{"text":"([^"]+)"}]'
            thumbnail_pattern = r'"videoId":"([^"]+)".*?"thumbnails":\[{"url":"([^"]+)"'
            
            video_matches = re.findall(video_pattern, html_content)
            thumbnail_matches = dict(re.findall(thumbnail_pattern, html_content))
            
            for i, (video_id, title) in enumerate(video_matches[:max_results]):
                if video_id and title:
                    video_url = f"https://www.youtube.com/watch?v={video_id}"
                    thumbnail_url = thumbnail_matches.get(video_id, "")
                    
                    # Clean up title (remove HTML entities)
                    title = title.replace('\\u0026', '&').replace('\\u003c', '<').replace('\\u003e', '>')
                    
                    video = VideoResult(
                        title=title,
                        url=video_url,
                        thumbnail_url=thumbnail_url,
                        source="youtube"
                    )
                    videos.append(video)
            
        except Exception as e:
            print(f"Error parsing YouTube results: {e}")
        
        return videos
    
    def _calculate_confidence(self, video_title: str, query: str) -> float:
        """Calculate confidence score for video relevance"""
        score = 0.0
        query_words = query.lower().split()
        title_words = video_title.lower().split()
        
        # Check for exact matches
        for word in query_words:
            if word in title_words:
                score += 1.0
        
        # Bonus for fashion-specific terms
        fashion_terms = ['fashion', 'runway', 'show', 'collection', 'couture']
        for term in fashion_terms:
            if term in video_title:
                score += 0.5
        
        # Penalty for unwanted content
        unwanted_terms = ['review', 'reaction', 'haul', 'try-on', 'diy']
        for term in unwanted_terms:
            if term in video_title:
                score -= 1.0
        
        # Normalize score
        return max(0.0, score / len(query_words))


class FashionVideoSearchEngine:
    """Main class for searching fashion show videos"""
    
    def __init__(self):
        self.parser = CollectionNameParser()
        self.youtube_search = YouTubeVideoSearch()
    
    def search_for_collection(self, collection_name: str, collection_url: str = "") -> List[VideoResult]:
        """Search for videos related to a fashion collection"""
        try:
            # Parse collection information
            collection_info = self.parser.parse_collection_info(collection_name, collection_url)
            print(f"Parsed collection info: {collection_info}")
            
            # Create search query
            query = self.parser.create_search_query(collection_info)
            print(f"Search query: {query}")
            
            if not query.strip():
                print("Could not generate search query from collection name")
                return []
            
            # Search for videos
            videos = self.youtube_search.search_videos(query, max_results=5)
            
            return videos
            
        except Exception as e:
            print(f"Error in collection video search: {e}")
            return []
    
    def get_best_video(self, collection_name: str, collection_url: str = "") -> Optional[VideoResult]:
        """Get the most relevant video for a collection"""
        videos = self.search_for_collection(collection_name, collection_url)
        
        if videos and videos[0].confidence > 0.5:  # Minimum confidence threshold
            return videos[0]
        
        return None


# Test functionality
if __name__ == "__main__":
    engine = FashionVideoSearchEngine()
    
    # Test with some example collection names
    test_collections = [
        "chanel-spring-2024-ready-to-wear",
        "dior-fall-2023-couture-paris",
        "versace-spring-summer-2024"
    ]
    
    for collection in test_collections:
        print(f"\n--- Testing: {collection} ---")
        videos = engine.search_for_collection(collection)
        
        for video in videos[:3]:  # Show top 3 results
            print(f"Title: {video.title}")
            print(f"URL: {video.url}")
            print(f"Confidence: {video.confidence:.2f}")
            print("---")