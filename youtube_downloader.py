#!/usr/bin/env python3
"""
YouTube Downloader
A tool for downloading YouTube videos by reverse engineering the video player.
"""

import os
import sys
import re
import json
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class YouTubeDownloader:
    """YouTube video downloader that reverse engineers the player to get video URLs."""
    
    def __init__(self):
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        self.headers = {"User-Agent": self.user_agent}
    
    def extract_video_id(self, url: str) -> Optional[str]:
        """Extract video ID from YouTube URL."""
        patterns = [
            r'(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]{11})',
            r'youtube\.com/embed/([a-zA-Z0-9_-]{11})',
            r'youtube\.com/v/([a-zA-Z0-9_-]{11})'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None
    
    def get_page_content(self, video_id: str) -> str:
        """Fetch YouTube page content for video analysis."""
        url = f"https://www.youtube.com/watch?v={video_id}"
        req = urllib.request.Request(url, headers=self.headers)
        
        try:
            with urllib.request.urlopen(req) as response:
                return response.read().decode('utf-8')
        except Exception as e:
            raise Exception(f"Failed to fetch page content: {e}")
    
    def extract_player_config(self, page_content: str) -> Dict:
        """Extract player configuration from YouTube page HTML/JavaScript."""
        patterns = [
            r'ytInitialPlayerResponse\s*=\s*({.+?});',
            r'var\s+ytInitialPlayerResponse\s*=\s*({.+?});',
            r'"playerConfig"\s*:\s*({.+?})'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, page_content, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    continue
        
        raise Exception("Could not extract player configuration")
    
    def decrypt_signature(self, encrypted_sig: str, player_url: str) -> str:
        """Decrypt YouTube signature (basic implementation)."""
        # This is a simplified version - real implementation would need to 
        # fetch and parse the player JavaScript for signature decryption
        return encrypted_sig[::-1]  # Simple reverse for demonstration
    
    def parse_stream_urls(self, player_config: Dict) -> List[Dict]:
        """Parse available video stream URLs from player configuration."""
        streams = []
        
        try:
            streaming_data = player_config.get('streamingData', {})
            
            # Extract adaptive formats (video + audio separate)
            adaptive_formats = streaming_data.get('adaptiveFormats', [])
            for fmt in adaptive_formats:
                url = None
                
                # Check for direct URL
                if 'url' in fmt:
                    url = fmt['url']
                # Check for encrypted signature
                elif 'signatureCipher' in fmt or 'cipher' in fmt:
                    cipher_data = fmt.get('signatureCipher') or fmt.get('cipher')
                    cipher_params = urllib.parse.parse_qs(cipher_data)
                    
                    if 'url' in cipher_params:
                        base_url = cipher_params['url'][0]
                        if 's' in cipher_params:
                            # Would need proper signature decryption here
                            print(f"Warning: Encrypted signature found for itag {fmt.get('itag')}")
                            continue
                        url = base_url
                
                if url:
                    streams.append({
                        'url': url,
                        'quality': fmt.get('qualityLabel', 'Unknown'),
                        'format': fmt.get('mimeType', '').split('/')[1].split(';')[0],
                        'type': 'video' if 'video' in fmt.get('mimeType', '') else 'audio',
                        'itag': fmt.get('itag'),
                        'filesize': fmt.get('contentLength')
                    })
            
            # Extract regular formats (video + audio combined)
            formats = streaming_data.get('formats', [])
            for fmt in formats:
                url = None
                
                # Check for direct URL
                if 'url' in fmt:
                    url = fmt['url']
                # Check for encrypted signature
                elif 'signatureCipher' in fmt or 'cipher' in fmt:
                    cipher_data = fmt.get('signatureCipher') or fmt.get('cipher')
                    cipher_params = urllib.parse.parse_qs(cipher_data)
                    
                    if 'url' in cipher_params:
                        base_url = cipher_params['url'][0]
                        if 's' in cipher_params:
                            print(f"Warning: Encrypted signature found for itag {fmt.get('itag')}")
                            continue
                        url = base_url
                
                if url:
                    streams.append({
                        'url': url,
                        'quality': fmt.get('qualityLabel', 'Unknown'),
                        'format': fmt.get('mimeType', '').split('/')[1].split(';')[0],
                        'type': 'combined',
                        'itag': fmt.get('itag'),
                        'filesize': fmt.get('contentLength')
                    })
        
        except KeyError as e:
            raise Exception(f"Error parsing stream data: {e}")
        
        return streams
    
    def get_video_info(self, video_id: str) -> Dict:
        """Get video metadata information."""
        page_content = self.get_page_content(video_id)
        player_config = self.extract_player_config(page_content)
        
        video_details = player_config.get('videoDetails', {})
        
        return {
            'title': video_details.get('title', 'Unknown Title'),
            'author': video_details.get('author', 'Unknown Author'),
            'length': video_details.get('lengthSeconds', '0'),
            'description': video_details.get('shortDescription', ''),
            'view_count': video_details.get('viewCount', '0'),
            'video_id': video_id
        }
    
    def download_stream(self, url: str, filename: str, chunk_size: int = 8192) -> None:
        """Download video stream from URL."""
        req = urllib.request.Request(url, headers=self.headers)
        
        print(f"Downloading: {filename}")
        
        try:
            with urllib.request.urlopen(req) as response:
                total_size = int(response.headers.get('Content-Length', 0))
                downloaded = 0
                
                with open(filename, 'wb') as f:
                    while True:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        if total_size > 0:
                            percent = (downloaded / total_size) * 100
                            print(f"\rProgress: {percent:.1f}%", end='', flush=True)
                
                print(f"\nDownload completed: {filename}")
        
        except Exception as e:
            raise Exception(f"Download failed: {e}")
    
    def download_video(self, url: str, output_dir: str = "downloads", 
                      quality: str = "highest") -> str:
        """Main method to download YouTube video."""
        video_id = self.extract_video_id(url)
        if not video_id:
            raise Exception("Invalid YouTube URL")
        
        # Create output directory
        Path(output_dir).mkdir(exist_ok=True)
        
        # Get video information
        video_info = self.get_video_info(video_id)
        print(f"Title: {video_info['title']}")
        print(f"Author: {video_info['author']}")
        print(f"Duration: {video_info['length']} seconds")
        
        # Get available streams
        page_content = self.get_page_content(video_id)
        player_config = self.extract_player_config(page_content)
        streams = self.parse_stream_urls(player_config)
        
        if not streams:
            raise Exception("No downloadable streams found")
        
        # Filter and select best stream
        video_streams = [s for s in streams if s['type'] in ['combined', 'video']]
        
        if quality == "highest":
            selected_stream = max(video_streams, 
                                key=lambda x: int(x.get('filesize', 0) or 0))
        else:
            # Find stream matching quality
            quality_streams = [s for s in video_streams if quality in s['quality']]
            selected_stream = quality_streams[0] if quality_streams else video_streams[0]
        
        # Generate filename
        safe_title = re.sub(r'[^\w\s-]', '', video_info['title']).strip()
        safe_title = re.sub(r'[-\s]+', '-', safe_title)
        filename = f"{safe_title}.{selected_stream['format']}"
        filepath = os.path.join(output_dir, filename)
        
        # Download the video
        self.download_stream(selected_stream['url'], filepath)
        
        return filepath


def main():
    """Main function for YouTube downloader."""
    if len(sys.argv) < 2:
        print("Usage: python youtube_downloader.py <youtube_url> [quality] [output_dir]")
        print("Quality options: highest, 720p, 480p, 360p, etc.")
        print("\nNote: This is a basic implementation for educational purposes.")
        print("For production use, consider yt-dlp: pip install yt-dlp")
        sys.exit(1)
    
    url = sys.argv[1]
    quality = sys.argv[2] if len(sys.argv) > 2 else "highest"
    output_dir = sys.argv[3] if len(sys.argv) > 3 else "downloads"
    
    downloader = YouTubeDownloader()
    
    try:
        filepath = downloader.download_video(url, output_dir, quality)
        print(f"Successfully downloaded: {filepath}")
    except Exception as e:
        print(f"Error: {e}")
        print("\nThis video may have encrypted signatures that require advanced decryption.")
        print("Try using yt-dlp instead: yt-dlp " + url)
        sys.exit(1)


if __name__ == "__main__":
    main()