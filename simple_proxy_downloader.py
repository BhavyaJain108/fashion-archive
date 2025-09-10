#!/usr/bin/env python3
"""
Simple Proxy Video Downloader

Clean, minimal implementation for downloading videos through WebShare proxies
with direct fallback. No overcomplicated logic - just works.

Author: Fashion Archive Team
"""

import os
import requests
import subprocess
import logging
from typing import Optional, List
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class SimpleProxyDownloader:
    """Simple proxy downloader that tries WebShare proxies, then falls back to direct"""
    
    def __init__(self):
        self.webshare_api_key = os.getenv('WEBSHARE_API_KEY')
        self.proxies = []
        self.current_proxy_index = 0
        
        if self.webshare_api_key:
            self._load_webshare_proxies()
    
    def _load_webshare_proxies(self):
        """Load WebShare proxies from API"""
        try:
            headers = {"Authorization": f"Token {self.webshare_api_key}"}
            # Use the correct API endpoint with required parameters
            response = requests.get(
                "https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&page=1&page_size=100", 
                headers=headers, 
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                for proxy_data in data.get('results', []):
                    # Port is directly available, not nested
                    proxy_url = f"http://{proxy_data['username']}:{proxy_data['password']}@{proxy_data['proxy_address']}:{proxy_data['port']}"
                    self.proxies.append({
                        'url': proxy_url,
                        'ip': proxy_data['proxy_address'],
                        'port': proxy_data['port']
                    })
                
                logger.info(f"Loaded {len(self.proxies)} WebShare proxies")
            else:
                logger.warning(f"WebShare API failed: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Failed to load WebShare proxies: {e}")
    
    def get_next_proxy(self) -> Optional[dict]:
        """Get next proxy in rotation"""
        if not self.proxies:
            return None
        
        proxy = self.proxies[self.current_proxy_index % len(self.proxies)]
        self.current_proxy_index += 1
        return proxy
    
    def get_video_duration(self, url: str) -> Optional[float]:
        """
        Get video duration in seconds using yt-dlp
        Returns None if unable to fetch duration
        """
        try:
            cmd = [
                "yt-dlp",
                "--dump-json",
                "--no-warnings",
                url
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                import json
                video_info = json.loads(result.stdout)
                duration = video_info.get('duration', 0)
                return float(duration) if duration else None
            
        except Exception as e:
            logger.warning(f"Failed to get video duration: {e}")
        
        return None
    
    def download_video(self, url: str, output_dir: str = "videos", min_duration_seconds: float = 150) -> Optional[str]:
        """
        Download video with 4-stage quality waterfall:
        1. Proxy High Quality (1080p+audio)
        2. Proxy Lower Quality (480p+audio) 
        3. Direct High Quality (1080p+audio)
        4. Direct Low Quality (worst available)
        
        Args:
            url: YouTube video URL
            output_dir: Directory to save video
            min_duration_seconds: Minimum video duration in seconds (default 150 = 2.5 minutes)
        """
        os.makedirs(output_dir, exist_ok=True)
        output_template = f"{output_dir}/%(title)s.%(ext)s"
        
        print(f"📥 Downloading: {url}")
        
        # Check video duration first
        print(f"⏱️ Checking video duration...")
        duration = self.get_video_duration(url)
        
        if duration is not None:
            duration_minutes = duration / 60
            print(f"📊 Video duration: {duration_minutes:.1f} minutes")
            
            if duration < min_duration_seconds:
                print(f"❌ Video rejected: Duration {duration_minutes:.1f} minutes is less than minimum {min_duration_seconds/60:.1f} minutes")
                print(f"   This is likely a trailer or clip, not a full fashion show")
                return None
        else:
            print(f"⚠️ Could not determine video duration, proceeding with download...")
        
        # Define quality levels with robust format strings
        quality_levels = [
            {
                "name": "High Quality",
                "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
                "description": "Up to 1080p video + audio"
            },
            {
                "name": "Lower Quality", 
                "format": "bestvideo[height<=480]+bestaudio/best[height<=480]/18",
                "description": "Up to 480p video + audio"
            },
            {
                "name": "Low Quality Fallback",
                "format": "worst[height>=240]/worst/18",
                "description": "Lowest available quality (240p+)"
            }
        ]
        
        # Stage 1 & 2: Try with WebShare proxies (high then lower quality)
        if self.proxies:
            for quality_idx, quality in enumerate(quality_levels[:2]):  # Only first 2 qualities for proxy
                proxy = self.get_next_proxy()
                if proxy:
                    print(f"🌐 Stage {quality_idx + 1}: Trying proxy {proxy['ip']}:{proxy['port']} - {quality['description']}")
                    
                    cmd = [
                        "yt-dlp", url,
                        "--output", output_template,
                        "--format", quality['format'],
                        "--proxy", proxy['url'],
                        "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "--extractor-args", "youtube:player_client=android",
                        "--no-check-certificates",
                        "--socket-timeout", "30"
                    ]
                    
                    result = subprocess.run(cmd, capture_output=True, text=True)
                    
                    if result.returncode == 0:
                        downloaded_file = self._find_downloaded_file(output_dir, result.stdout)
                        if downloaded_file:
                            self._log_download_quality(result.stdout, "proxy", quality['name'])
                            print(f"✅ Downloaded via proxy ({quality['description']}): {downloaded_file}")
                            return downloaded_file
                    else:
                        print(f"❌ Proxy {proxy['ip']} failed ({quality['description']}): {result.stderr[:100]}")
        
        # Stage 3 & 4: Direct connection with high then low quality
        for quality_idx, quality in enumerate([quality_levels[0], quality_levels[2]]):  # High quality, then low fallback
            stage_num = 3 + quality_idx
            print(f"🔗 Stage {stage_num}: Direct connection - {quality['description']}")
            
            cmd = [
                "yt-dlp", url,
                "--output", output_template,
                "--format", quality['format'],
                "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "--extractor-args", "youtube:player_client=android"
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                downloaded_file = self._find_downloaded_file(output_dir, result.stdout)
                if downloaded_file:
                    self._log_download_quality(result.stdout, "direct", quality['name'])
                    print(f"✅ Downloaded directly ({quality['description']}): {downloaded_file}")
                    return downloaded_file
                else:
                    print(f"⚠️ Download succeeded but couldn't find file")
                    print(f"   📋 stdout: {result.stdout[-200:]}")
                    print(f"   📋 stderr: {result.stderr[:200] if result.stderr else 'None'}")
            else:
                print(f"❌ Direct connection failed ({quality['description']}): Return code {result.returncode}")
                if result.stderr:
                    print(f"   Error: {result.stderr[:200]}")
        
        print(f"❌ All 4 download stages failed")
        return None
    
    def _find_downloaded_file(self, output_dir: str, stdout: str) -> Optional[str]:
        """Find the downloaded file from yt-dlp output"""
        try:
            # First try to find from yt-dlp output
            lines = stdout.split('\n')
            for line in lines:
                if 'Destination:' in line:
                    # Extract filename from "Destination: path/file.ext"
                    parts = line.split('Destination: ')
                    if len(parts) > 1:
                        file_path = parts[1].strip()
                        if os.path.exists(file_path):
                            print(f"📁 Found file from destination: {os.path.basename(file_path)}")
                            return file_path
                
                # Look for download completion
                if '100%' in line and 'in ' in line:
                    # Try to extract filename from progress line
                    if output_dir in line:
                        potential_path = line.split()[0] if line.split() else ""
                        if os.path.exists(potential_path):
                            return potential_path
                
                # Alternative: look for merger output
                if 'Merging formats into' in line:
                    parts = line.split('"')
                    if len(parts) >= 2:
                        file_path = parts[1]
                        if os.path.exists(file_path):
                            print(f"📁 Found merged file: {os.path.basename(file_path)}")
                            return file_path
            
            # Fallback: find most recent file in output directory (within last 30 seconds)
            import glob
            import time
            current_time = time.time()
            
            files = glob.glob(f"{output_dir}/*.mp4") + glob.glob(f"{output_dir}/*.mkv") + glob.glob(f"{output_dir}/*.webm")
            recent_files = []
            
            for file_path in files:
                file_time = os.path.getctime(file_path)
                if current_time - file_time < 30:  # Only files from last 30 seconds
                    recent_files.append((file_path, file_time))
            
            if recent_files:
                # Return the most recent file
                most_recent = max(recent_files, key=lambda x: x[1])
                print(f"📁 Found recent file: {os.path.basename(most_recent[0])}")
                return most_recent[0]
                
        except Exception as e:
            logger.error(f"Error finding downloaded file: {e}")
        
        return None
    
    def _log_download_quality(self, stdout: str, method: str, quality_name: str):
        """Extract and log the actual quality downloaded"""
        try:
            lines = stdout.split('\n')
            format_info = None
            quality_info = None
            
            for line in lines:
                line = line.strip()
                
                # Look for format selection info like "[info] QFqU4LWUX3w: Downloading 1 format(s): 18"
                if 'Downloading 1 format(s):' in line:
                    format_id = line.split(':')[-1].strip()
                    format_info = f"Format ID: {format_id}"
                
                # Look for resolution info like "640x360" 
                if 'x' in line and any(char.isdigit() for char in line):
                    import re
                    resolution_match = re.search(r'(\d{3,4}x\d{3,4})', line)
                    if resolution_match:
                        quality_info = f"Resolution: {resolution_match.group(1)}"
                        break
                
                # Look for explicit format/quality info from --print
                if line and ' ' in line:
                    parts = line.split()
                    if len(parts) >= 2 and any(char.isdigit() for char in parts[1]):
                        if 'x' in parts[1]:  # Resolution format
                            quality_info = f"Resolution: {parts[1]}"
                            format_info = f"Format ID: {parts[0]}"
                            break
            
            # Print what we found
            if format_info or quality_info:
                info_parts = []
                if format_info:
                    info_parts.append(format_info)
                if quality_info:
                    info_parts.append(quality_info)
                print(f"📊 DOWNLOADED QUALITY ({method} - {quality_name}): {' | '.join(info_parts)}")
            else:
                print(f"📊 DOWNLOADED ({method} - {quality_name}): Quality info not parsed")
                
        except Exception as e:
            print(f"📊 DOWNLOADED ({method} - {quality_name}): Could not parse quality info")


# Simple test function
def test_simple_downloader():
    """Test the simple downloader"""
    downloader = SimpleProxyDownloader()
    
    test_url = "https://www.youtube.com/watch?v=QFqU4LWUX3w"
    result = downloader.download_video(test_url)
    
    if result:
        print(f"🎉 SUCCESS: Downloaded to {result}")
        file_size = os.path.getsize(result) / (1024 * 1024)
        print(f"📏 File size: {file_size:.2f} MB")
    else:
        print("❌ FAILED: Could not download video")


if __name__ == "__main__":
    test_simple_downloader()