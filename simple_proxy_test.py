#!/usr/bin/env python3
"""
Simple "First Working Proxy" Test

This approach:
1. Tests proxies ONE AT A TIME
2. STOPS as soon as it finds the first working one
3. Uses that proxy for download
4. Only finds replacement if it fails

This is simpler and faster for testing.

Author: Fashion Archive Team  
License: MIT
"""

import os
import sys
import time
import subprocess
import requests
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

def get_proxy_list() -> list:
    """Get list of proxies to test"""
    print("🔍 Fetching proxy list...")
    
    try:
        url = "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt"
        response = requests.get(url, timeout=10)
        
        proxies = []
        for line in response.text.strip().split('\n')[:100]:  # Only try first 100
            if ':' in line:
                ip, port = line.strip().split(':')
                proxies.append(f"http://{ip}:{port}")
        
        print(f"📋 Got {len(proxies)} proxies to test")
        return proxies
        
    except Exception as e:
        print(f"❌ Error fetching proxies: {e}")
        return []


def test_proxy(proxy_url: str) -> bool:
    """Test if a single proxy works"""
    try:
        print(f"🧪 Testing {proxy_url}...", end=" ")
        
        response = requests.get(
            'http://httpbin.org/ip',
            proxies={'http': proxy_url, 'https': proxy_url},
            timeout=8
        )
        
        if response.status_code == 200:
            print("✅ Working!")
            return True
        else:
            print(f"❌ Failed (status {response.status_code})")
            return False
            
    except Exception as e:
        print(f"❌ Failed ({str(e)[:30]}...)")
        return False


def find_first_working_proxy() -> str:
    """Find the FIRST working proxy and return it"""
    proxies = get_proxy_list()
    
    print("\n🔍 Testing proxies ONE BY ONE until we find a working one...")
    
    for i, proxy in enumerate(proxies):
        print(f"[{i+1}/{len(proxies)}]", end=" ")
        
        if test_proxy(proxy):
            print(f"\n🎯 FOUND WORKING PROXY: {proxy}")
            return proxy
    
    print("\n❌ No working proxies found")
    return None


def test_youtube_access(proxy_url: str) -> bool:
    """Test if proxy can access YouTube"""
    print(f"🌐 Testing YouTube access with {proxy_url}...")
    
    try:
        response = requests.get(
            'https://www.youtube.com',
            proxies={'http': proxy_url, 'https': proxy_url},
            timeout=15,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        
        if response.status_code == 200:
            print("✅ Proxy can access YouTube")
            return True
        else:
            print(f"❌ YouTube blocked proxy (status: {response.status_code})")
            return False
            
    except Exception as e:
        print(f"❌ YouTube access failed: {e}")
        return False


def download_with_proxy(proxy_url: str, video_url: str) -> bool:
    """Attempt actual download with the proxy"""
    print(f"📥 Attempting download with proxy {proxy_url}...")
    
    try:
        test_dir = Path("simple_test_downloads")
        test_dir.mkdir(exist_ok=True)
        
        cmd = [
            "yt-dlp",
            video_url,
            "--output", str(test_dir / "simple_test_%(title)s.%(ext)s"),
            "--format", "worst",  # Lowest quality to avoid blocks
            "--proxy", proxy_url,
            "--socket-timeout", "60",
            "--retries", "1",  # Only 1 retry since we'll handle failures
            "--restrict-filenames",
            "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        ]
        
        print("⏳ Downloading...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=240)  # 4 min timeout
        
        if result.returncode == 0:
            # Check for downloaded file
            video_files = list(test_dir.glob("simple_test_*.mp4")) + list(test_dir.glob("simple_test_*.webm"))
            if video_files:
                latest_file = max(video_files, key=lambda f: f.stat().st_ctime)
                file_size = latest_file.stat().st_size
                print(f"✅ DOWNLOAD SUCCESS!")
                print(f"  📁 File: {latest_file.name}")
                print(f"  📏 Size: {file_size:,} bytes ({file_size/1024/1024:.2f} MB)")
                print(f"  🌐 Used proxy: {proxy_url}")
                return True
        
        print(f"❌ Download failed: {result.stderr[:150]}...")
        return False
        
    except subprocess.TimeoutExpired:
        print("❌ Download timed out")
        return False
    except Exception as e:
        print(f"❌ Download error: {e}")
        return False


def main():
    """Simple proxy test: find first working proxy and use it"""
    print("🚀 SIMPLE PROXY TEST - First Working Proxy Only")
    print("=" * 60)
    
    video_url = "https://www.youtube.com/watch?v=QFqU4LWUX3w&ab_channel=ActionBronson"
    print(f"🎯 Target video: {video_url}\n")
    
    # Step 1: Find FIRST working proxy
    working_proxy = find_first_working_proxy()
    if not working_proxy:
        print("❌ No working proxy found - testing direct download...")
        
        # Test direct download for comparison
        if download_with_proxy("", video_url):  # Empty proxy = direct
            print("✅ Direct download works - proxy not needed for this video")
        else:
            print("❌ Both proxy and direct download failed")
        return
    
    # Step 2: Test YouTube access
    if not test_youtube_access(working_proxy):
        print("❌ Proxy can't access YouTube - finding another...")
        
        # Could implement "find next working proxy" here if needed
        print("💡 For now, testing direct download...")
        if download_with_proxy("", video_url):
            print("✅ Direct download works")
        return
    
    # Step 3: Attempt download with our working proxy
    print("\n🎬 DOWNLOAD TEST")
    print("=" * 30)
    
    if download_with_proxy(working_proxy, video_url):
        print(f"\n🎉 SUCCESS! Proxy system working!")
        print(f"✅ The proxy {working_proxy} successfully downloaded the video")
    else:
        print(f"\n❌ Download failed with {working_proxy}")
        print("💡 Proxy might be blocked by YouTube specifically")
        
        # Test direct as comparison
        print("\n🔄 Testing direct download for comparison...")
        if download_with_proxy("", video_url):
            print("✅ Direct works - confirms YouTube is blocking the proxy")
        else:
            print("❌ Direct also fails - might be video-specific issue")


if __name__ == "__main__":
    main()