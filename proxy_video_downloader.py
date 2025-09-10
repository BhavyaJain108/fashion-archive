#!/usr/bin/env python3
"""
Proxy-Enabled Video Downloader

Extends the existing video download system with rotating proxy support.
Integrates with the modular ProxyManager for reliable YouTube downloads.

Author: Fashion Archive Team
License: MIT
"""

import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional, Dict, List
from dataclasses import dataclass
import logging

from proxy_manager import ProxyManager, RequestManager, ProxyInfo

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class VideoDownloadResult:
    """Result of video download attempt"""
    success: bool
    file_path: Optional[str] = None
    error_message: Optional[str] = None
    proxy_used: Optional[ProxyInfo] = None
    duration_seconds: Optional[int] = None


class ProxyVideoDownloader:
    """Video downloader with rotating proxy support"""
    
    def __init__(self, 
                 download_dir: str = "videos",
                 proxy_cache_file: str = "video_proxy_cache.json",
                 min_proxies: int = 5):
        
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(exist_ok=True)
        
        # Initialize proxy system
        self.proxy_manager = ProxyManager(
            cache_file=proxy_cache_file,
            min_proxies=min_proxies,
            max_proxies=50  # Reasonable limit for video downloads
        )
        
        # Initialize with fresh proxies if needed
        if self.proxy_manager.get_stats()['working_proxies'] < min_proxies:
            logger.info("Initializing proxy pool...")
            self.proxy_manager.refresh_proxies()
        
        self.request_manager = RequestManager(self.proxy_manager)
    
    def download_video(self, url: str, title: str = None, max_retries: int = 5) -> VideoDownloadResult:
        """
        Download video with rotating proxy support
        
        Args:
            url: YouTube video URL
            title: Optional custom title (will fetch from video if not provided)
            max_retries: Maximum number of proxy attempts
            
        Returns:
            VideoDownloadResult with success status and file path
        """
        logger.info(f"Starting proxy video download: {url}")
        
        for attempt in range(max_retries):
            proxy = self.proxy_manager.get_proxy()
            
            if not proxy:
                logger.warning(f"No proxy available for attempt {attempt + 1}")
                if attempt == max_retries - 1:
                    # Last attempt - try direct download
                    logger.info("Attempting direct download as fallback")
                    return self._download_direct(url, title)
                continue
            
            logger.info(f"Attempt {attempt + 1}: Using proxy {proxy.ip}:{proxy.port}")
            
            result = self._download_with_proxy(url, proxy, title)
            
            if result.success:
                self.proxy_manager.mark_proxy_success(proxy)
                logger.info(f"Download successful with proxy {proxy.ip}:{proxy.port}")
                return result
            else:
                self.proxy_manager.mark_proxy_failed(proxy)
                logger.warning(f"Download failed with proxy {proxy.ip}:{proxy.port}: {result.error_message}")
                
                # Wait before retry with exponential backoff
                wait_time = min(2 ** attempt, 30)  # Max 30 seconds
                time.sleep(wait_time)
        
        # All proxy attempts failed
        logger.error(f"All {max_retries} proxy attempts failed")
        return VideoDownloadResult(
            success=False,
            error_message=f"Failed after {max_retries} attempts with different proxies"
        )
    
    def _download_with_proxy(self, url: str, proxy: ProxyInfo, title: str = None) -> VideoDownloadResult:
        """Download video using specific proxy"""
        try:
            # Generate output filename
            if title:
                safe_title = self._sanitize_filename(title)
                output_template = str(self.download_dir / f"{safe_title}.%(ext)s")
            else:
                output_template = str(self.download_dir / "%(title)s.%(ext)s")
            
            # Build yt-dlp command with proxy
            cmd = [
                "yt-dlp",
                url,
                "--output", output_template,
                "--format", "worst[height>=360]/worst",  # Conservative quality
                "--proxy", proxy.proxy_url,
                "--concurrent-fragments", "2",   # Reduced concurrency
                "--retries", "2",               # Fewer retries per proxy
                "--fragment-retries", "2",
                "--sleep-interval", "1",
                "--max-sleep-interval", "3",
                "--restrict-filenames",
                "--no-check-certificates",
                "--socket-timeout", "30",       # 30 second timeout
                "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "--referer", "https://www.youtube.com/",
                "--no-warnings",               # Reduce noise
            ]
            
            logger.debug(f"Running: {' '.join(cmd)}")
            
            # Execute with timeout
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                timeout=600  # 10 minute timeout
            )
            
            if result.returncode == 0:
                # Find downloaded file
                downloaded_file = self._find_downloaded_file()
                
                if downloaded_file:
                    return VideoDownloadResult(
                        success=True,
                        file_path=str(downloaded_file),
                        proxy_used=proxy
                    )
                else:
                    return VideoDownloadResult(
                        success=False,
                        error_message="Download completed but file not found",
                        proxy_used=proxy
                    )
            else:
                # Parse error
                error_msg = self._parse_ytdlp_error(result.stderr)
                return VideoDownloadResult(
                    success=False,
                    error_message=error_msg,
                    proxy_used=proxy
                )
                
        except subprocess.TimeoutExpired:
            return VideoDownloadResult(
                success=False,
                error_message="Download timeout (10 minutes)",
                proxy_used=proxy
            )
        except Exception as e:
            return VideoDownloadResult(
                success=False,
                error_message=f"Subprocess error: {str(e)}",
                proxy_used=proxy
            )
    
    def _download_direct(self, url: str, title: str = None) -> VideoDownloadResult:
        """Fallback: Direct download without proxy"""
        try:
            logger.info("Attempting direct download without proxy")
            
            if title:
                safe_title = self._sanitize_filename(title)
                output_template = str(self.download_dir / f"{safe_title}.%(ext)s")
            else:
                output_template = str(self.download_dir / "%(title)s.%(ext)s")
            
            cmd = [
                "yt-dlp",
                url,
                "--output", output_template,
                "--format", "worst",  # Lowest quality for fallback
                "--retries", "3",
                "--restrict-filenames",
                "--no-check-certificates",
                "--socket-timeout", "60",
                "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "--sleep-interval", "2",
                "--max-sleep-interval", "5",
            ]
            
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                timeout=900  # 15 minutes for direct
            )
            
            if result.returncode == 0:
                downloaded_file = self._find_downloaded_file()
                if downloaded_file:
                    return VideoDownloadResult(
                        success=True,
                        file_path=str(downloaded_file)
                    )
            
            return VideoDownloadResult(
                success=False,
                error_message=f"Direct download failed: {result.stderr[:200]}"
            )
            
        except Exception as e:
            return VideoDownloadResult(
                success=False,
                error_message=f"Direct download error: {str(e)}"
            )
    
    def _find_downloaded_file(self) -> Optional[Path]:
        """Find the most recently downloaded video file"""
        video_extensions = ['.mp4', '.mkv', '.webm', '.avi', '.flv']
        
        video_files = []
        for ext in video_extensions:
            video_files.extend(self.download_dir.glob(f"*{ext}"))
        
        if video_files:
            # Return most recently created file
            return max(video_files, key=lambda f: f.stat().st_ctime)
        
        return None
    
    def _sanitize_filename(self, filename: str) -> str:
        """Sanitize filename for filesystem compatibility"""
        import re
        
        # Remove or replace problematic characters
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        filename = re.sub(r'[^\w\s-]', '', filename)
        filename = re.sub(r'[-\s]+', '-', filename)
        
        # Limit length
        return filename[:100].strip('-')
    
    def _parse_ytdlp_error(self, stderr: str) -> str:
        """Parse yt-dlp error output for meaningful messages"""
        if not stderr:
            return "Unknown error"
        
        # Common error patterns
        if "HTTP Error 403" in stderr:
            return "HTTP 403 Forbidden - IP may be blocked"
        elif "HTTP Error 429" in stderr:
            return "HTTP 429 Too Many Requests - Rate limited"
        elif "Unable to download webpage" in stderr:
            return "Unable to access video page"
        elif "Video unavailable" in stderr:
            return "Video is unavailable or private"
        elif "Sign in to confirm your age" in stderr:
            return "Age verification required"
        elif "timeout" in stderr.lower():
            return "Connection timeout"
        elif "connection" in stderr.lower():
            return "Connection error"
        
        # Return first error line
        lines = stderr.strip().split('\n')
        for line in lines:
            if 'ERROR:' in line:
                return line.replace('ERROR: ', '')
        
        return stderr[:200]  # First 200 chars
    
    def get_proxy_stats(self) -> Dict:
        """Get current proxy pool statistics"""
        return self.proxy_manager.get_stats()
    
    def refresh_proxies(self):
        """Manually refresh proxy pool"""
        self.proxy_manager.refresh_proxies()


# Integration with existing video download system
class EnhancedProxyVideoDownloader:
    """Enhanced version that integrates with existing claude_video_verifier system"""
    
    def __init__(self):
        self.proxy_downloader = ProxyVideoDownloader()
        
        # Load the existing search system
        try:
            from claude_video_verifier import EnhancedFashionVideoSearch
            self.enhanced_search = EnhancedFashionVideoSearch()
        except ImportError:
            logger.warning("Could not import claude_video_verifier - search functionality limited")
            self.enhanced_search = None
    
    def search_and_download_with_proxy(self, search_query: str) -> Optional[str]:
        """
        Search for fashion videos and download using proxy system
        
        Returns:
            Path to downloaded file if successful, None otherwise
        """
        logger.info(f"🔍 PROXY-ENABLED SEARCH AND DOWNLOAD: {search_query}")
        logger.info("=" * 60)
        
        if not self.enhanced_search:
            logger.error("Search system not available")
            return None
        
        # Use existing search to find video
        video_result = self.enhanced_search.search_and_verify(search_query)
        
        if not video_result:
            logger.warning("No video found by search system")
            return None
        
        logger.info(f"📹 Found video: {video_result.title}")
        logger.info(f"🔗 URL: {video_result.url}")
        
        # Download using proxy system
        logger.info("📥 Starting proxy-enabled download...")
        
        download_result = self.proxy_downloader.download_video(
            url=video_result.url,
            title=video_result.title,
            max_retries=5
        )
        
        if download_result.success:
            logger.info(f"✅ PROXY DOWNLOAD SUCCESS: {download_result.file_path}")
            if download_result.proxy_used:
                logger.info(f"🌐 Used proxy: {download_result.proxy_used.ip}:{download_result.proxy_used.port}")
            return download_result.file_path
        else:
            logger.error(f"❌ PROXY DOWNLOAD FAILED: {download_result.error_message}")
            return None
    
    def get_stats(self) -> Dict:
        """Get system statistics"""
        return {
            'proxy_stats': self.proxy_downloader.get_proxy_stats(),
            'download_directory': str(self.proxy_downloader.download_dir)
        }


# Example usage and testing
if __name__ == "__main__":
    # Test basic proxy downloader
    downloader = ProxyVideoDownloader()
    
    # Show proxy stats
    stats = downloader.get_proxy_stats()
    print(f"Proxy stats: {stats}")
    
    # Test download with a simple video
    test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"  # Rick Roll for testing
    result = downloader.download_video(test_url)
    
    if result.success:
        print(f"✅ Test download successful: {result.file_path}")
        if result.proxy_used:
            print(f"🌐 Used proxy: {result.proxy_used.ip}:{result.proxy_used.port}")
    else:
        print(f"❌ Test download failed: {result.error_message}")
    
    # Test enhanced system (if available)
    try:
        enhanced = EnhancedProxyVideoDownloader()
        enhanced_stats = enhanced.get_stats()
        print(f"Enhanced system stats: {enhanced_stats}")
    except Exception as e:
        print(f"Enhanced system not available: {e}")