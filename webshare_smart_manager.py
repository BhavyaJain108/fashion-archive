#!/usr/bin/env python3
"""
WebShare-Enhanced Smart Proxy Manager

Integrates WebShare.io premium proxies with the smart proxy system.
Falls back to free proxies only if WebShare proxies are unavailable.

Author: Fashion Archive Team
License: MIT
"""

import os
import logging
from datetime import datetime
from typing import List, Optional

from smart_proxy_manager import SmartProxyManager, SmartProxy
from webshare_proxy_source import WebShareProxySource

logger = logging.getLogger(__name__)


class WebShareSmartManager(SmartProxyManager):
    """Smart proxy manager enhanced with WebShare.io premium proxies"""
    
    def __init__(self, 
                 cache_file: str = "webshare_proxy_cache.json",
                 target_working_proxies: int = 8,
                 prefer_webshare: bool = True):
        
        # Initialize base smart manager
        super().__init__(cache_file=cache_file, 
                        target_working_proxies=target_working_proxies,
                        max_test_batch=50)  # Smaller batch since we have premium proxies
        
        self.prefer_webshare = prefer_webshare
        self.webshare_source = None
        
        # Try to initialize WebShare
        try:
            self.webshare_source = WebShareProxySource()
            logger.info("✅ WebShare.io source initialized")
        except Exception as e:
            logger.warning(f"⚠️ WebShare.io not available: {e}")
            self.webshare_source = None
        
        # Load WebShare proxies if available
        if self.webshare_source:
            self._load_webshare_proxies()
    
    def _load_webshare_proxies(self):
        """Load WebShare proxies into the smart manager"""
        try:
            logger.info("🌐 Loading WebShare proxies...")
            webshare_proxies = self.webshare_source.get_proxy_list()
            
            if not webshare_proxies:
                logger.warning("No WebShare proxies available")
                return
            
            # Convert to SmartProxy objects with authentication
            webshare_smart_proxies = []
            for proxy_info in webshare_proxies:
                smart_proxy = SmartProxy(
                    ip=proxy_info['ip'],
                    port=proxy_info['port'],
                    protocol='http',
                    country=proxy_info['country'],
                    source='webshare',
                    discovered_at=datetime.now(),
                    quality_score=95,  # High quality premium proxies
                    is_working=True,   # Pre-validated by WebShare
                    success_count=1    # Start with success
                )
                
                # Add authentication info
                smart_proxy.username = proxy_info['username']
                smart_proxy.password = proxy_info['password']
                smart_proxy.auth_proxy_url = f"http://{proxy_info['username']}:{proxy_info['password']}@{proxy_info['ip']}:{proxy_info['port']}"
                
                webshare_smart_proxies.append(smart_proxy)
            
            # Add WebShare proxies to the pool (they'll be preferred due to high quality score)
            with self.lock:
                # Remove old WebShare proxies first
                self.proxies = [p for p in self.proxies if p.source != 'webshare']
                # Add new WebShare proxies
                self.proxies.extend(webshare_smart_proxies)
            
            logger.info(f"✅ Loaded {len(webshare_smart_proxies)} WebShare proxies")
            
            # Save to cache
            self._save_smart_cache()
            
        except Exception as e:
            logger.error(f"Failed to load WebShare proxies: {e}")
    
    def get_working_proxy(self) -> Optional[SmartProxy]:
        """Get next working proxy, preferring WebShare proxies"""
        with self.lock:
            # Separate WebShare and free proxies
            webshare_proxies = [p for p in self.proxies if p.source == 'webshare' and p.is_working and p.failure_streak < 2]
            free_proxies = [p for p in self.proxies if p.source != 'webshare' and p.is_working and p.failure_streak < 3]
            
            # Prefer WebShare proxies if available
            if self.prefer_webshare and webshare_proxies:
                # Sort WebShare proxies by quality
                webshare_proxies.sort(key=lambda p: p.quality_score, reverse=True)
                proxy = webshare_proxies[self.current_index % len(webshare_proxies)]
                proxy.last_used = datetime.now()
                self.current_index += 1
                return proxy
            
            # Fallback to free proxies
            elif free_proxies:
                free_proxies.sort(key=lambda p: p.quality_score, reverse=True)
                proxy = free_proxies[self.current_index % len(free_proxies)]
                proxy.last_used = datetime.now()
                self.current_index += 1
                return proxy
            
            logger.warning("No working proxies available")
            return None
    
    def ensure_working_proxies(self) -> bool:
        """Ensure we have working proxies, prioritizing WebShare"""
        webshare_count = len([p for p in self.proxies if p.source == 'webshare' and p.is_working])
        free_count = len([p for p in self.proxies if p.source != 'webshare' and p.is_working])
        total_working = webshare_count + free_count
        
        logger.info(f"Current proxy status: {webshare_count} WebShare, {free_count} free, {total_working} total working")
        
        # If we have enough WebShare proxies, we're good
        if webshare_count >= min(5, self.target_working_proxies):
            logger.info(f"✅ Sufficient WebShare proxies available ({webshare_count})")
            return True
        
        # Try to refresh WebShare proxies if source is available
        if self.webshare_source:
            logger.info("🔄 Refreshing WebShare proxies...")
            self._load_webshare_proxies()
            
            # Check again
            webshare_count = len([p for p in self.proxies if p.source == 'webshare' and p.is_working])
            if webshare_count > 0:
                logger.info(f"✅ WebShare proxies refreshed ({webshare_count} working)")
                return True
        
        # Fallback to free proxies if needed
        if total_working < self.target_working_proxies:
            logger.info("🆓 Falling back to free proxy sources...")
            return super().ensure_working_proxies()
        
        return total_working > 0
    
    def get_stats(self) -> dict:
        """Get enhanced stats including WebShare vs free proxy breakdown"""
        base_stats = super().get_stats()
        
        with self.lock:
            webshare_proxies = [p for p in self.proxies if p.source == 'webshare']
            webshare_working = [p for p in webshare_proxies if p.is_working]
            free_proxies = [p for p in self.proxies if p.source != 'webshare']
            free_working = [p for p in free_proxies if p.is_working]
            
            base_stats.update({
                'webshare_proxies': len(webshare_proxies),
                'webshare_working': len(webshare_working),
                'free_proxies': len(free_proxies),
                'free_working': len(free_working),
                'webshare_available': self.webshare_source is not None,
                'preferred_source': 'webshare' if self.prefer_webshare else 'mixed'
            })
        
        return base_stats
    
    def refresh_webshare(self):
        """Manually refresh WebShare proxies"""
        if self.webshare_source:
            logger.info("🔄 Manual WebShare refresh...")
            self._load_webshare_proxies()
        else:
            logger.warning("WebShare source not available for refresh")


# Update the proxy integration to use WebShare manager
def get_webshare_smart_manager():
    """Get WebShare-enhanced smart proxy manager"""
    return WebShareSmartManager(
        target_working_proxies=5,  # With WebShare, we need fewer total proxies
        prefer_webshare=True
    )


# Test the WebShare-enhanced manager
if __name__ == "__main__":
    print("🚀 WEBSHARE SMART MANAGER TEST")
    print("=" * 40)
    
    try:
        manager = WebShareSmartManager()
        
        # Ensure working proxies
        if manager.ensure_working_proxies():
            stats = manager.get_stats()
            print(f"📊 PROXY STATS:")
            print(f"  WebShare working: {stats['webshare_working']}")
            print(f"  Free working: {stats['free_working']}")
            print(f"  Total working: {stats['working_proxies']}")
            print(f"  Average quality: {stats['average_quality_score']}")
            
            # Get a proxy
            proxy = manager.get_working_proxy()
            if proxy:
                print(f"\n🎯 SELECTED PROXY:")
                print(f"  IP: {proxy.ip}:{proxy.port}")
                print(f"  Source: {proxy.source}")
                print(f"  Quality: {proxy.quality_score}")
                print(f"  Has auth: {hasattr(proxy, 'username')}")
                
                # Test the proxy
                if hasattr(proxy, 'auth_proxy_url'):
                    import requests
                    try:
                        response = requests.get(
                            'http://httpbin.org/ip',
                            proxies={'http': proxy.auth_proxy_url, 'https': proxy.auth_proxy_url},
                            timeout=10
                        )
                        if response.status_code == 200:
                            print(f"  ✅ Proxy test: {response.text[:50]}...")
                    except Exception as e:
                        print(f"  ❌ Proxy test failed: {e}")
            else:
                print("❌ No proxy available")
        else:
            print("❌ Could not ensure working proxies")
            
    except Exception as e:
        print(f"❌ Test error: {e}")
        import traceback
        traceback.print_exc()