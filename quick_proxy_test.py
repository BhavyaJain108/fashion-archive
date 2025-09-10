#!/usr/bin/env python3
"""
Quick Proxy Test - Fast Implementation

Instead of testing 38,000+ proxies, this:
1. Gets a small sample of proxies (50-100)
2. Tests them quickly in parallel
3. Uses the first few working ones
4. Tests actual video download

This is much faster for development/testing.

Author: Fashion Archive Team
License: MIT
"""

import os
import sys
import time
import subprocess
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Tuple

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

def get_sample_proxies(max_proxies=100) -> List[dict]:
    """Get a small sample of proxies for quick testing"""
    print("🔍 Fetching sample proxies for quick testing...")
    
    proxies = []
    
    # Get from a single fast source
    try:
        url = "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt"
        response = requests.get(url, timeout=10)
        
        lines = response.text.strip().split('\n')[:max_proxies]  # Only take first N
        
        for line in lines:
            if ':' in line:
                ip, port = line.strip().split(':')
                proxies.append({
                    'ip': ip,
                    'port': int(port),
                    'url': f"http://{ip}:{port}"
                })
    except Exception as e:
        print(f"⚠️  Error fetching proxies: {e}")
    
    print(f"📋 Got {len(proxies)} sample proxies to test")
    return proxies


def test_single_proxy(proxy: dict) -> Tuple[bool, dict, float]:
    """Test a single proxy quickly"""
    try:
        start_time = time.time()
        
        response = requests.get(
            'http://httpbin.org/ip',
            proxies={'http': proxy['url'], 'https': proxy['url']},
            timeout=8  # Shorter timeout
        )
        
        response_time = time.time() - start_time
        
        if response.status_code == 200:
            return True, proxy, response_time
            
    except:
        pass
    
    return False, proxy, 999.0


def find_working_proxies(sample_proxies: List[dict], max_workers=20) -> List[dict]:
    """Find working proxies from sample using parallel testing"""
    print(f"🧪 Testing {len(sample_proxies)} proxies in parallel...")
    
    working_proxies = []
    tested = 0
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tests
        future_to_proxy = {executor.submit(test_single_proxy, proxy): proxy for proxy in sample_proxies}
        
        for future in as_completed(future_to_proxy):
            tested += 1
            is_working, proxy, response_time = future.result()
            
            if is_working:
                proxy['response_time'] = response_time
                working_proxies.append(proxy)
                print(f"✅ Found working proxy: {proxy['ip']}:{proxy['port']} ({response_time:.2f}s)")
                
                # Stop after finding 5 good ones
                if len(working_proxies) >= 5:
                    print(f"🎯 Found {len(working_proxies)} working proxies, stopping search")
                    break
            
            if tested % 10 == 0:
                print(f"📊 Tested {tested}/{len(sample_proxies)}, found {len(working_proxies)} working")
    
    # Sort by response time (fastest first)
    working_proxies.sort(key=lambda p: p['response_time'])
    
    print(f"✅ Found {len(working_proxies)} working proxies total")
    return working_proxies


def test_proxy_with_youtube(proxy: dict, video_url: str) -> bool:
    """Test if proxy can access YouTube"""
    print(f"🌐 Testing proxy {proxy['ip']}:{proxy['port']} with YouTube...")
    
    try:
        # Test basic YouTube access
        response = requests.get(
            'https://www.youtube.com',
            proxies={'http': proxy['url'], 'https': proxy['url']},
            timeout=15,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        
        if response.status_code == 200 and 'youtube' in response.text.lower():
            print(f"✅ Proxy can access YouTube")
            return True
        else:
            print(f"❌ Proxy blocked by YouTube (status: {response.status_code})")
            return False
            
    except Exception as e:
        print(f"❌ Proxy failed YouTube test: {e}")
        return False


def test_yt_dlp_with_proxy(proxy: dict, video_url: str) -> bool:
    """Test actual yt-dlp download with proxy"""
    print(f"📥 Testing yt-dlp download with proxy {proxy['ip']}:{proxy['port']}...")
    
    try:
        # Create test directory
        test_dir = Path("test_downloads")
        test_dir.mkdir(exist_ok=True)
        
        # Test with yt-dlp simulation (no actual download)
        cmd = [
            "yt-dlp",
            "--simulate",
            "--proxy", proxy['url'],
            "--print", "title",
            "--socket-timeout", "30",
            video_url
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        
        if result.returncode == 0 and result.stdout.strip():
            title = result.stdout.strip().split('\n')[0]
            print(f"✅ yt-dlp simulation successful: {title[:50]}...")
            return True
        else:
            print(f"❌ yt-dlp failed: {result.stderr[:100]}...")
            return False
            
    except subprocess.TimeoutExpired:
        print("❌ yt-dlp timeout")
        return False
    except Exception as e:
        print(f"❌ yt-dlp error: {e}")
        return False


def test_actual_download(proxy: dict, video_url: str) -> Optional[str]:
    """Test actual video download with proxy"""
    print(f"🚀 Attempting actual download with proxy {proxy['ip']}:{proxy['port']}...")
    
    try:
        test_dir = Path("test_downloads")
        test_dir.mkdir(exist_ok=True)
        
        # Download with very conservative settings
        cmd = [
            "yt-dlp",
            video_url,
            "--output", str(test_dir / "test_%(title)s.%(ext)s"),
            "--format", "worst",  # Lowest quality
            "--proxy", proxy['url'],
            "--socket-timeout", "60",
            "--retries", "2",
            "--fragment-retries", "2",
            "--sleep-interval", "2",
            "--max-sleep-interval", "5",
            "--restrict-filenames",
            "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        ]
        
        print("⏳ Download in progress...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)  # 5 min timeout
        
        if result.returncode == 0:
            # Find downloaded file
            video_files = list(test_dir.glob("test_*.mp4")) + list(test_dir.glob("test_*.webm"))
            if video_files:
                latest_file = max(video_files, key=lambda f: f.stat().st_ctime)
                file_size = latest_file.stat().st_size
                print(f"✅ DOWNLOAD SUCCESSFUL!")
                print(f"  📁 File: {latest_file.name}")
                print(f"  📏 Size: {file_size:,} bytes ({file_size/1024/1024:.2f} MB)")
                return str(latest_file)
            else:
                print("❌ Download completed but no file found")
                return None
        else:
            print(f"❌ Download failed: {result.stderr[:200]}...")
            return None
            
    except subprocess.TimeoutExpired:
        print("❌ Download timed out")
        return None
    except Exception as e:
        print(f"❌ Download error: {e}")
        return None


def main():
    """Quick proxy test with actual video"""
    print("🚀 QUICK PROXY TEST")
    print("=" * 50)
    
    video_url = "https://www.youtube.com/watch?v=QFqU4LWUX3w&ab_channel=ActionBronson"
    print(f"🎯 Target: {video_url}")
    
    # Step 1: Get sample proxies (fast)
    sample_proxies = get_sample_proxies(50)  # Only test 50 proxies
    if not sample_proxies:
        print("❌ No proxies to test")
        return
    
    # Step 2: Find working proxies (parallel, fast)
    working_proxies = find_working_proxies(sample_proxies)
    if not working_proxies:
        print("❌ No working proxies found")
        return
    
    # Step 3: Test YouTube access
    youtube_proxies = []
    for proxy in working_proxies[:3]:  # Test top 3
        if test_proxy_with_youtube(proxy, video_url):
            youtube_proxies.append(proxy)
    
    if not youtube_proxies:
        print("❌ No proxies can access YouTube")
        return
    
    print(f"✅ Found {len(youtube_proxies)} YouTube-compatible proxies")
    
    # Step 4: Test yt-dlp simulation
    ytdlp_proxies = []
    for proxy in youtube_proxies:
        if test_yt_dlp_with_proxy(proxy, video_url):
            ytdlp_proxies.append(proxy)
    
    if not ytdlp_proxies:
        print("❌ No proxies work with yt-dlp")
        return
    
    print(f"✅ Found {len(ytdlp_proxies)} yt-dlp-compatible proxies")
    
    # Step 5: Actual download test
    print("\n🎬 ATTEMPTING ACTUAL DOWNLOAD")
    print("=" * 50)
    
    for i, proxy in enumerate(ytdlp_proxies[:2]):  # Try top 2
        print(f"\n📥 Download attempt {i+1} with {proxy['ip']}:{proxy['port']}")
        
        downloaded_file = test_actual_download(proxy, video_url)
        
        if downloaded_file:
            print(f"\n🎉 SUCCESS! Proxy system is working!")
            print(f"📁 Downloaded: {Path(downloaded_file).name}")
            print(f"🌐 Working proxy: {proxy['ip']}:{proxy['port']}")
            return
        else:
            print(f"❌ Download failed with this proxy")
    
    print("\n❌ All download attempts failed")
    print("💡 This might mean YouTube is blocking the proxy IPs")


if __name__ == "__main__":
    main()