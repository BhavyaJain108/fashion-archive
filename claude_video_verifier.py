#!/usr/bin/env python3
"""
Claude Video Verification System

AI-powered video verification for fashion show archives using Claude AI to ensure 
semantic matching between search queries and YouTube video content.

This module implements sophisticated fashion industry logic including:
- Couture vs Haute Couture distinction
- Year direction matching (2010 matches 2010-2011, not 2009-2010)
- Season and collection type validation
- Context-aware matching (runway shows vs reviews/reactions)

Author: Fashion Archive Team
License: MIT
"""

import os
import json
from typing import List, Optional, Dict
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv
from anthropic import Anthropic
from fashion_video_search import VideoResult

# Load environment variables from .env file
load_dotenv()


@dataclass
class VerificationResult:
    """Result of Claude's video verification"""
    is_match: bool
    confidence: float
    reasoning: str
    best_match_index: Optional[int] = None


class ClaudeVideoVerifier:
    """Uses Claude to verify if video search results match the search query intent"""
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize with Claude API key"""
        self.api_key = api_key or os.getenv('CLAUDE_API_KEY') or os.getenv('ANTHROPIC_API_KEY')
        if not self.api_key:
            raise ValueError("CLAUDE_API_KEY or ANTHROPIC_API_KEY environment variable is required")
        
        self.client = Anthropic(api_key=self.api_key)
    
    def verify_video_matches(self, search_query: str, videos: List[VideoResult]) -> VerificationResult:
        """
        Verify if any of the found videos actually match the search intent
        
        Args:
            search_query: Original search query
            videos: List of video results from search
            
        Returns:
            VerificationResult with match status and reasoning
        """
        if not videos:
            return VerificationResult(
                is_match=False,
                confidence=0.0,
                reasoning="No videos found in search results",
                best_match_index=None
            )
        
        # Prepare video titles for Claude (no scores, no URLs)
        video_titles = [video.title for video in videos]
        
        # Create verification prompt
        prompt = self._create_verification_prompt(search_query, video_titles)
        
        try:
            # Call Claude API
            response = self.client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=1000,
                temperature=0.0,  # Set to 0 for maximum consistency
                messages=[{
                    "role": "user", 
                    "content": prompt
                }]
            )
            
            # Parse response
            return self._parse_claude_response(response.content[0].text, len(videos))
            
        except Exception as e:
            print(f"Error calling Claude API: {e}")
            return VerificationResult(
                is_match=False,
                confidence=0.0,
                reasoning=f"API call failed: {str(e)}",
                best_match_index=None
            )
    
    def _create_verification_prompt(self, search_query: str, video_titles: List[str]) -> str:
        """Create the prompt for Claude to verify video matches"""
        videos_text = "\n".join([
            f"{i+1}. {title}"
            for i, title in enumerate(video_titles)
        ])
        
        prompt = f"""You are helping verify if YouTube search results match a user's search intent.

SEARCH QUERY: "{search_query}"

FOUND VIDEOS:
{videos_text}

YEAR MATCHING & COUTURE DISTINCTION ARE MANDATORY. NO EXCEPTIONS.

Search query analysis: Extract year and collection type from "{search_query}"

YEAR MATCHING RULES:
- If searching for 2010: ACCEPT 2010, 2010-2011, 2010/2011. REJECT 2009-2010, 2009/2010
- If searching for 2018: ACCEPT 2018, 2018-2019, 2018/2019. REJECT 2017-2018, 2017/2018
- If searching for 2019: ACCEPT 2019, 2019-2020, 2019/2020. REJECT 2018-2019, 2018/2019
- Rule: Year must START with the searched year, not END with it

COUTURE DISTINCTION (CRITICAL):
- "Couture" and "Haute Couture" are DIFFERENT collection types
- If search contains "Couture" (without "Haute") → Only match "Couture" videos
- If search contains "Haute Couture" → Only match "Haute Couture" videos  
- If search contains neither → Accept both types

MANDATORY STEPS:
1. Extract requested year from search query
2. Extract collection type (Haute Couture vs Couture vs Ready-to-Wear) from search query
3. For each video:
   - Extract year(s) from title
   - Extract collection type from title
   - Check if year STARTS with requested year
   - Check if collection type matches exactly
4. Only consider videos where BOTH year and collection type match
5. If no videos match → is_match: false

Examples:
- Search "2010 Couture" + Video "2010-2011 Haute Couture" = NO MATCH (wrong couture type)
- Search "2010 Haute Couture" + Video "2010 Couture" = NO MATCH (wrong couture type)  
- Search "2010" + Video "2009-2010" = NO MATCH (year starts with 2009)
- Search "2010" + Video "2010-2011" = POSSIBLE MATCH (year starts with 2010)

JSON format:
{{
    "is_match": true/false,
    "confidence": 0.0-1.0,
    "reasoning": "Year: searched [X], found [Y,Z]. Couture: searched [A], found [B,C]. Match=[result]",
    "best_match_index": null or 0-based index
}}"""
        
        return prompt
    
    def _parse_claude_response(self, response_text: str, num_videos: int) -> VerificationResult:
        """Parse Claude's JSON response into a VerificationResult"""
        try:
            # Extract JSON from response - find the JSON object
            response_text = response_text.strip()
            
            # Handle cases where Claude wraps JSON in markdown code blocks
            if response_text.startswith('```json'):
                response_text = response_text[7:]
            if response_text.endswith('```'):
                response_text = response_text[:-3]
            
            # Find JSON object in the response (look for { ... })
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                json_text = json_match.group()
                response_data = json.loads(json_text)
            else:
                # Fallback - try to parse the whole thing
                response_data = json.loads(response_text.strip())
            
            # Validate best_match_index
            best_match_index = response_data.get("best_match_index")
            if best_match_index is not None:
                if not (0 <= best_match_index < num_videos):
                    best_match_index = None
            
            return VerificationResult(
                is_match=bool(response_data.get("is_match", False)),
                confidence=float(response_data.get("confidence", 0.0)),
                reasoning=str(response_data.get("reasoning", "No reasoning provided")),
                best_match_index=best_match_index
            )
            
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            print(f"Error parsing Claude response: {e}")
            print(f"Raw response: {response_text}")
            
            return VerificationResult(
                is_match=False,
                confidence=0.0,
                reasoning=f"Failed to parse response: {str(e)}",
                best_match_index=None
            )


class EnhancedFashionVideoSearch:
    """Enhanced video search with Claude verification using exact search queries"""
    
    def __init__(self, claude_api_key: Optional[str] = None):
        from fashion_video_search import YouTubeVideoSearch
        
        self.youtube_search = YouTubeVideoSearch()
        self.verifier = ClaudeVideoVerifier(claude_api_key)
        
        # Create videos directory if it doesn't exist
        self.videos_dir = Path("videos")
        self.videos_dir.mkdir(exist_ok=True)
    
    def search_and_verify(self, search_query: str) -> Optional[VideoResult]:
        """
        Search using the exact query string and verify with Claude
        
        Args:
            search_query: Exact search query to use (no modifications)
            
        Returns:
            VideoResult if a good match is found, None otherwise
        """
        print(f"Search query: {search_query}")
        print(f"Searching YouTube for: {search_query}")
        
        # Use direct YouTube search with exact query
        videos = self.youtube_search.search_videos(search_query, max_results=5)
        
        if not videos:
            print("❌ No videos found")
            return None
        
        # Display search results
        self._display_search_results(videos)
        
        # Use Claude to verify matches
        print("\n🤖 Using Claude to verify matches...")
        
        verification = self.verifier.verify_video_matches(search_query, videos)
        
        print(f"Claude verification: {verification.reasoning}")
        print(f"Match found: {'✅ Yes' if verification.is_match else '❌ No'}")
        print(f"Confidence: {verification.confidence:.2f}")
        
        if verification.is_match and verification.best_match_index is not None:
            best_video = videos[verification.best_match_index]
            print(f"\n🏆 VERIFIED BEST MATCH: {best_video.title}")
            print(f"🔗 {best_video.url}")
            return best_video
        else:
            print("\n❌ No verified matches found")
            return None
    
    def search_verify_and_download(self, search_query: str) -> Optional[str]:
        """
        Search, verify with Claude, and download the best match
        
        Returns:
            Path to downloaded file if successful, None otherwise
        """
        print(f"🔍 SEARCHING AND DOWNLOADING: {search_query}")
        print("=" * 60)
        
        # First, search and verify
        best_video = self.search_and_verify(search_query)
        
        if not best_video:
            print("❌ No video to download")
            return None
        
        # Download the verified video
        print(f"\n📥 DOWNLOADING VERIFIED VIDEO...")
        print(f"Title: {best_video.title}")
        print(f"URL: {best_video.url}")
        
        try:
            downloaded_path = self._download_video(best_video)
            if downloaded_path:
                print(f"✅ DOWNLOAD COMPLETE: {downloaded_path}")
                return downloaded_path
            else:
                print("❌ Download failed")
                return None
                
        except Exception as e:
            print(f"❌ Download error: {e}")
            return None
    
    def _download_video(self, video: VideoResult) -> Optional[str]:
        """Download a video using yt-dlp with original YouTube title"""
        try:
            import subprocess
            
            # Use yt-dlp's default title templating to keep original name
            output_template = str(self.videos_dir / "%(title)s.%(ext)s")
            
            print(f"Downloading: {video.title}")
            print(f"To folder: {self.videos_dir}")
            
            # Run yt-dlp command
            cmd = [
                "yt-dlp",
                video.url,
                "--output", output_template,
                "--format", "best[height<=720]",  # Good quality but not huge files
                "--embed-metadata",  # Add metadata
                "--write-description",  # Save description
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                # Find the downloaded file by looking for the most recent file
                # that matches video format extensions
                video_files = []
                for ext in ['.mp4', '.mkv', '.webm', '.avi']:
                    video_files.extend(self.videos_dir.glob(f"*{ext}"))
                
                if video_files:
                    # Get the most recently created video file
                    latest_file = max(video_files, key=lambda f: f.stat().st_ctime)
                    print(f"Downloaded as: {latest_file.name}")
                    return str(latest_file)
                
                return None
            else:
                print(f"yt-dlp error: {result.stderr}")
                return None
                
        except Exception as e:
            print(f"Download error: {e}")
            return None
    
    def _display_search_results(self, videos: List[VideoResult]) -> None:
        """Display search results in a formatted way"""
        print(f"✅ Found {len(videos)} videos:")
        
        for i, video in enumerate(videos, 1):
            # Determine confidence emoji
            if video.confidence >= 0.8:
                emoji = "🟢"
            elif video.confidence >= 0.5:
                emoji = "🟡"
            else:
                emoji = "🔴"
            
            print(f"{i}. {emoji} [{video.confidence:.2f}] {video.title}")
            print(f"   🔗 {video.url}")


# Test the system
if __name__ == "__main__":
    # Test with the example that should show a mismatch
    exact_query = "aganovich fall 2019 paris fashion show runway"
    
    try:
        enhanced_search = EnhancedFashionVideoSearch()
        result = enhanced_search.search_and_verify(exact_query)
        
        print("=" * 60)
        if result:
            print(f"✅ FINAL RESULT: {result.title}")
        else:
            print("❌ No valid match found")
            
    except ValueError as e:
        print(f"Error: {e}")
        print("Please set CLAUDE_API_KEY environment variable")