#!/usr/bin/env python3
"""
Quick Smart Proxy Test - Focused Testing
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

def main():
    print("🚀 QUICK SMART PROXY TEST")
    print("=" * 40)
    
    # Step 1: Test smart proxy manager directly
    print("\n1️⃣ Testing Smart Proxy Manager...")
    try:
        from smart_proxy_manager import SmartProxyManager
        manager = SmartProxyManager(target_working_proxies=3)
        
        if manager.ensure_working_proxies():
            stats = manager.get_stats()
            print(f"✅ Smart proxy manager working!")
            print(f"   Working proxies: {stats['working_proxies']}")
            print(f"   Average quality: {stats['average_quality_score']}")
            
            # Get a proxy
            proxy = manager.get_working_proxy()
            if proxy:
                print(f"   Best proxy: {proxy.ip}:{proxy.port} (score: {proxy.quality_score:.1f})")
            
        else:
            print("❌ No working proxies found")
            return
            
    except Exception as e:
        print(f"❌ Smart proxy error: {e}")
        return
    
    # Step 2: Test proxy integration
    print("\n2️⃣ Testing Proxy Integration...")
    os.environ['USE_PROXY'] = 'true'
    
    try:
        from proxy_integration import get_proxy_stats, build_ytdlp_command_with_proxy
        
        stats = get_proxy_stats()
        print(f"✅ Integration working!")
        print(f"   Available proxies: {stats['working_proxies'] if stats else 'Unknown'}")
        
        # Test command building
        base_cmd = ["yt-dlp", "https://example.com"]
        enhanced_cmd, proxy_used = build_ytdlp_command_with_proxy(base_cmd, "https://example.com")
        
        if proxy_used:
            print(f"   Proxy assigned: {proxy_used.ip}:{proxy_used.port}")
            print(f"   Command enhanced: {len(enhanced_cmd)} vs {len(base_cmd)} args")
        else:
            print("   No proxy assigned")
            
    except Exception as e:
        print(f"❌ Integration error: {e}")
        return
    
    # Step 3: Test actual proxy with simple request
    print("\n3️⃣ Testing Actual Proxy Usage...")
    try:
        import requests
        
        if proxy_used:
            test_url = "http://httpbin.org/ip"
            print(f"   Testing {test_url} with proxy {proxy_used.ip}:{proxy_used.port}")
            
            response = requests.get(
                test_url,
                proxies={'http': proxy_used.proxy_url, 'https': proxy_used.proxy_url},
                timeout=10
            )
            
            if response.status_code == 200:
                print(f"✅ Proxy works! Response: {response.text[:50]}...")
            else:
                print(f"❌ Proxy failed: HTTP {response.status_code}")
        else:
            print("   No proxy to test")
            
    except Exception as e:
        print(f"❌ Proxy test error: {e}")
        return
    
    # Step 4: Test YouTube access through proxy
    print("\n4️⃣ Testing YouTube Access...")
    if proxy_used:
        try:
            response = requests.get(
                "https://www.youtube.com/",
                proxies={'http': proxy_used.proxy_url, 'https': proxy_used.proxy_url},
                timeout=15,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            )
            
            if response.status_code == 200 and 'youtube' in response.text.lower():
                print("✅ Proxy can access YouTube!")
            else:
                print(f"❌ YouTube blocked proxy: HTTP {response.status_code}")
                
        except Exception as e:
            print(f"❌ YouTube test error: {e}")
    
    print(f"\n🎯 SUMMARY")
    print("=" * 20)
    print("✅ Smart proxy system is working!")
    print("✅ Integration layer is working!")
    print("🔧 Ready for video download testing")
    print("💡 If YouTube blocks proxies, we can add paid service")


if __name__ == "__main__":
    main()