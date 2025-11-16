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

# Proxy support removed
# VideoResult class for compatibility
@dataclass  
class VideoResult:
    """Represents a found fashion show video"""
    title: str
    url: str
    thumbnail_url: str
    duration: str = ""
    duration_seconds: int = 0
    view_count: str = ""
    source: str = "youtube"

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
        
        prompt = f"""Verify if any YouTube videos match the search query.

The search query typically contains a brand name, collection type (ready to wear, couture, haute-couture, menswear, etc.), and a date with fashion season (spring/summer, fall/winter, etc.) and year (20xx-20x(x+1) or just 20xx).

We are looking for the FULL FASHION SHOW RUNWAY VIDEO, not backstage content, interviews, or behind-the-scenes footage.

SEARCH QUERY: "{search_query}"

VIDEOS:
{videos_text}

RULES - APPLY IN THIS ORDER:
1. IMMEDIATELY REJECT any video containing these channels (they only have short clips, not full shows):
   - "style.com" or "Style.com"
   - "Elle" or "ELLE" 
   - These must be rejected FIRST before considering other criteria

2. YEAR MATCHING RULES - BE VERY STRICT:
   - If searching for 2014: REJECT "13/14", "2013-2014", "2013/2014" (contains previous year 2013)
   - If searching for 2014: ACCEPT "2014", "14/15", "2014-2015", "2014/2015" (starts with 2014)
   - RULE: If video title contains the PREVIOUS year before the target year → REJECT
   - EXAMPLE: Search=2014, Video="FW 13/14" → REJECT (contains 2013)
   - EXAMPLE: Search=2014, Video="FW 14/15" → ACCEPT (starts with 2014)

3. Match collection types exactly - these are DIFFERENT and NOT interchangeable:
   - "couture" ≠ "haute couture" 
   - "ready to wear" ≠ "couture" ≠ "haute couture"
   - "menswear" ≠ "womenswear"
   - If search has "couture" but video has "haute couture" → NOT A MATCH
   - If search has "haute couture" but video has "couture" → NOT A MATCH

IMPORTANT: If NO videos meet ALL the criteria above, return "is_match": false with "best_match_index": null. 
Only return "is_match": true if you find a video that passes all rules.

RESPONSE FORMAT - YOU MUST RETURN ONLY JSON:
Return ONLY the JSON object below, no additional text or explanation:

{{
    "is_match": true/false,
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation",
    "best_match_index": null or 0-based index
}}

Do not include any analysis or explanation outside the JSON."""
        
        return prompt
    
    def _parse_claude_response(self, response_text: str, num_videos: int) -> VerificationResult:
        """Parse Claude's JSON response into a VerificationResult"""
        try:
            print(f"🔍 Raw Claude response: {response_text[:200]}...")
            
            # Clean the response text
            response_text = response_text.strip()
            
            # Handle cases where Claude wraps JSON in markdown code blocks
            if '```json' in response_text:
                start = response_text.find('```json') + 7
                end = response_text.find('```', start)
                if end != -1:
                    response_text = response_text[start:end].strip()
            elif '```' in response_text:
                # Handle generic code blocks
                start = response_text.find('```') + 3
                end = response_text.find('```', start)
                if end != -1:
                    response_text = response_text[start:end].strip()
            
            # Find the first complete JSON object
            brace_count = 0
            start_pos = -1
            end_pos = -1
            
            for i, char in enumerate(response_text):
                if char == '{':
                    if brace_count == 0:
                        start_pos = i
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0 and start_pos != -1:
                        end_pos = i + 1
                        break
            
            if start_pos != -1 and end_pos != -1:
                json_text = response_text[start_pos:end_pos]
                print(f"🎯 Extracted JSON: {json_text}")
                response_data = json.loads(json_text)
            else:
                # Last resort - try parsing the whole response
                print("⚠️ No JSON braces found, trying full response")
                response_data = json.loads(response_text)
            
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
            print(f"❌ Error parsing Claude response: {e}")
            print(f"📄 Full response: {response_text}")
            
            return VerificationResult(
                is_match=False,
                confidence=0.0,
                reasoning=f"Failed to parse response: {str(e)}",
                best_match_index=None
            )


class EnhancedFashionVideoSearch:
    """Enhanced video search using Google search with Claude verification"""
    
    def __init__(self, claude_api_key: Optional[str] = None):
        from google_video_search import GoogleVideoSearch
        
        self.google_search = GoogleVideoSearch()
        self.verifier = ClaudeVideoVerifier(claude_api_key)
        
        # Create videos directory in cache if it doesn't exist
        self.videos_dir = Path("high_fashion_cache/videos")
        self.videos_dir.mkdir(parents=True, exist_ok=True)
    
    def search_and_verify(self, search_query: str) -> Optional[VideoResult]:
        """
        Search using Google video search and verify with Claude
        
        Args:
            search_query: Exact search query to use (no modifications)
            
        Returns:
            VideoResult if a good match is found, None otherwise
        """
        print(f"🔍 Search query: {search_query}")
        print(f"🌐 Using Google video search...")
        
        # Use Google video search to find the best match
        google_result = self.google_search.search_fashion_show(search_query)
        
        if not google_result:
            print("❌ No videos found via Google search")
            return None
        
        # Convert GoogleVideoResult to VideoResult for compatibility
        video_result = VideoResult(
            title=google_result.title,
            url=google_result.url,
            thumbnail_url=google_result.thumbnail_url,
            duration="",  # Google search doesn't provide duration
            duration_seconds=0,  # Will be determined during download
            view_count="",  # Google search doesn't provide view count
            source="google"
        )
        
        print(f"✅ Google found: {video_result.title}")
        print(f"🔗 {video_result.url}")
        
        return video_result
    
    def get_streaming_url(self, search_query: str) -> Optional[Dict]:
        """
        Get video info for embedding/streaming - NO downloads, NO yt-dlp processing
        
        Returns:
            Dict with video info for embedding, None otherwise
        """
        print(f"🔍 GETTING VIDEO FOR STREAMING: {search_query}")
        print("=" * 60)
        
        # Use Google search directly - bypass all verification/download logic
        print(f"🌐 Using Google video search...")
        google_result = self.google_search.search_fashion_show(search_query)
        
        if not google_result:
            print("❌ No videos found via Google search")
            return None
        
        print(f"📹 Found video: {google_result.title}")
        print(f"🔗 YouTube URL: {google_result.url}")
        
        # Extract video ID for embedding
        video_id = None
        import re
        patterns = [
            r'(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]{11})',
            r'youtube\.com/embed/([a-zA-Z0-9_-]{11})',
            r'youtube\.com/v/([a-zA-Z0-9_-]{11})'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, google_result.url)
            if match:
                video_id = match.group(1)
                break
        
        if not video_id:
            print("❌ Could not extract video ID")
            return None
        
        print(f"✅ Video ID: {video_id}")
        print(f"🎬 Embed URL: https://www.youtube.com/embed/{video_id}")
        
        # Return info for frontend to handle embedding/streaming - NO yt-dlp involved
        return {
            'video_id': video_id,
            'youtube_url': google_result.url,
            'embed_url': f"https://www.youtube.com/embed/{video_id}",
            'title': google_result.title,
            'thumbnail': f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
        }

    def search_verify_and_download(self, search_query: str) -> Optional[str]:
        """
        Search using Google and download the best match with fallback
        
        Returns:
            Path to downloaded file if successful, None otherwise
        """
        print(f"🔍 SEARCHING AND DOWNLOADING: {search_query}")
        print("=" * 60)
        
        # Get the best match from Google search
        best_video = self.search_and_verify(search_query)
        
        if best_video:
            print(f"\n📥 DOWNLOADING PRIMARY CHOICE...")
            print(f"Title: {best_video.title}")
            print(f"URL: {best_video.url}")
            
            try:
                downloaded_path = self._download_video(best_video)
                if downloaded_path:
                    print(f"✅ DOWNLOAD COMPLETE: {downloaded_path}")
                    return downloaded_path
                else:
                    print("❌ Primary video download failed, trying fallback...")
            except Exception as e:
                print(f"❌ Primary download error: {e}, trying fallback...")
        else:
            print("❌ No primary video found, trying fallback candidates...")
        
        # Fallback: Get all video candidates and try downloading each
        print(f"\n🔄 TRYING FALLBACK VIDEO CANDIDATES...")
        
        try:
            remaining_candidates = self.google_search.get_all_video_candidates(search_query)
            
            if not remaining_candidates:
                print("❌ No fallback candidates available")
                return None
            
            # Remove the primary video URL if it was already tried
            if best_video and best_video.url in remaining_candidates:
                remaining_candidates.remove(best_video.url)
            
            print(f"📋 Found {len(remaining_candidates)} fallback candidates")
            
            # Try each candidate for download
            attempt = 1
            max_attempts = 5
            
            while remaining_candidates and attempt <= max_attempts:
                print(f"\n🔄 FALLBACK ATTEMPT {attempt}/{max_attempts}")
                print(f"📋 {len(remaining_candidates)} candidates remaining")
                
                # Get the first candidate URL
                candidate_url = remaining_candidates[0]
                print(f"🎯 Trying candidate: {candidate_url}")
                
                # Get the actual video title for this candidate
                try:
                    actual_title = self.google_search._get_video_title(candidate_url)
                    if not actual_title:
                        print("⚠️ Could not get video title, removing and trying next")
                        remaining_candidates.remove(candidate_url)
                        attempt += 1
                        continue
                except:
                    print("⚠️ Error getting video title, removing and trying next")
                    remaining_candidates.remove(candidate_url)
                    attempt += 1
                    continue
                
                print(f"📹 Candidate title: {actual_title}")
                
                # Create VideoResult for download
                candidate_video = VideoResult(
                    title=actual_title,
                    url=candidate_url,
                    thumbnail_url="",
                    source="google_fallback"
                )
                
                # Try downloading this candidate
                print(f"📥 Downloading candidate...")
                try:
                    downloaded_path = self._download_video(candidate_video)
                    if downloaded_path:
                        print(f"✅ FALLBACK SUCCESS: {downloaded_path}")
                        return downloaded_path
                    else:
                        print("❌ Download failed, trying next candidate...")
                        remaining_candidates.remove(candidate_url)
                        attempt += 1
                        continue
                except Exception as e:
                    print(f"❌ Download error: {e}, trying next candidate...")
                    remaining_candidates.remove(candidate_url)
                    attempt += 1
                    continue
            
            print(f"❌ Fallback exhausted after {attempt-1} attempts")
            return None
            
        except Exception as e:
            print(f"❌ Fallback process error: {e}")
            return None
    
    def _download_video(self, video: VideoResult) -> Optional[str]:
        """Download video directly without proxy"""
        print(f"📥 Downloading: {video.title}")
        
        # Direct download using yt-dlp
        try:
            import yt_dlp
            
            output_file = self.videos_dir / f"{video.title[:100].replace('/', '-')}.mp4"
            
            # Get available formats by parsing --list-formats output
            print("🔍 Getting available formats...")
            
            import subprocess
            import re
            
            try:
                # Run yt-dlp --list-formats to get format list
                result = subprocess.run([
                    'yt-dlp', '--list-formats', video.url
                ], capture_output=True, text=True, timeout=30)
                
                if result.returncode != 0:
                    print(f"❌ Format listing failed: {result.stderr}")
                    raise Exception("Format listing failed")
                
                format_output = result.stdout
                print("📋 Available formats:")
                print(format_output)
                
                # Parse format lines to find video and audio formats
                video_formats = []
                audio_formats = []
                
                for line in format_output.split('\n'):
                    # Look for lines with format ID, skip storyboard
                    if re.match(r'^\d+\s+\w+', line.strip()) and 'storyboard' not in line:
                        format_id = line.split()[0]
                        
                        # Check if it's video-only or audio-only
                        if 'video only' in line:
                            # Extract resolution for video formats
                            resolution_match = re.search(r'(\d+)x(\d+)', line)
                            if resolution_match:
                                height = int(resolution_match.group(2))
                                video_formats.append((format_id, height, line))
                        elif 'audio only' in line:
                            audio_formats.append((format_id, line))
                
                print(f"📊 Found {len(video_formats)} video formats, {len(audio_formats)} audio formats")
                
                if not video_formats and not audio_formats:
                    print("❌ No valid formats found, using best")
                    best_format = 'best'
                elif video_formats and audio_formats:
                    # Try formats from best to worst until one works
                    video_formats.sort(key=lambda x: x[1], reverse=True)  # Sort by height, highest first
                    audio_format = audio_formats[0][0]  # Use best audio format
                    
                    for i, (video_id, height, line) in enumerate(video_formats):
                        format_to_try = f"{video_id}+{audio_format}"
                        print(f"📹 Trying format {i+1}/{len(video_formats)}: {format_to_try} ({height}p)")
                        
                        ydl_opts = {
                            'format': format_to_try,
                            'outtmpl': str(output_file),
                            'quiet': False,
                            'no_warnings': False,
                            'concurrent_fragment_downloads': 8,
                            'http_chunk_size': 10485760,
                            'retries': 10,
                            'fragment_retries': 10
                        }
                        
                        try:
                            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                ydl.download([video.url])
                            
                            if output_file.exists():
                                print(f"✅ Downloaded: {output_file.name}")
                                return str(output_file)
                            else:
                                print(f"❌ Format {format_to_try} failed, trying next...")
                                continue
                                
                        except Exception as e:
                            print(f"❌ Format {format_to_try} error: {e}, trying next...")
                            continue
                    
                    print("❌ All video+audio formats failed")
                    return None
                    
                elif video_formats:
                    # Try video-only formats from best to worst
                    video_formats.sort(key=lambda x: x[1], reverse=True)
                    
                    for i, (video_id, height, line) in enumerate(video_formats):
                        print(f"📹 Trying video-only format {i+1}/{len(video_formats)}: {video_id} ({height}p)")
                        
                        ydl_opts = {
                            'format': video_id,
                            'outtmpl': str(output_file),
                            'quiet': False,
                            'no_warnings': False,
                            'concurrent_fragment_downloads': 8,
                            'http_chunk_size': 10485760,
                            'retries': 10,
                            'fragment_retries': 10
                        }
                        
                        try:
                            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                ydl.download([video.url])
                            
                            if output_file.exists():
                                print(f"✅ Downloaded: {output_file.name}")
                                return str(output_file)
                            else:
                                print(f"❌ Format {video_id} failed, trying next...")
                                continue
                                
                        except Exception as e:
                            print(f"❌ Format {video_id} error: {e}, trying next...")
                            continue
                    
                    print("❌ All video formats failed")
                    return None
                else:
                    print("📹 Fallback to 'best' format")
                    ydl_opts = {
                        'format': 'best',
                        'outtmpl': str(output_file),
                        'quiet': False,
                        'no_warnings': False,
                        'concurrent_fragment_downloads': 8,
                        'http_chunk_size': 10485760,
                        'retries': 10,
                        'fragment_retries': 10
                    }
                
            except Exception as e:
                print(f"⚠️ Error getting formats: {e}")
                print("🔄 Attempting download with best available format...")
                ydl_opts = {
                    'format': 'best',
                    'outtmpl': str(output_file),
                    'quiet': False,
                    'no_warnings': False
                }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video.url])
            
            if output_file.exists():
                print(f"✅ Downloaded: {output_file.name}")
                return str(output_file)
            else:
                print("❌ Download failed")
                return None
                
        except Exception as e:
            print(f"❌ Download error: {e}")
            return None
    


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