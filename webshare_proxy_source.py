#!/usr/bin/env python3
"""
WebShare.io Proxy Source

Integrates WebShare.io paid proxy service with the smart proxy manager.
WebShare provides 10 free high-quality proxies that work well with YouTube.

Author: Fashion Archive Team
License: MIT
"""

import os
import requests
import logging
from datetime import datetime
from typing import List, Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)


class WebShareProxySource:
    """WebShare.io proxy service integration"""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv('WEBSHARE_API_KEY')
        if not self.api_key:
            raise ValueError("WEBSHARE_API_KEY not found in environment variables")
        
        self.base_url = "https://proxy.webshare.io/api/v2"
        self.headers = {
            "Authorization": f"Token {self.api_key}"
        }
        
        logger.info("WebShare proxy source initialized")
    
    def get_proxy_list(self) -> List[dict]:
        """Get proxy list from WebShare.io API"""
        try:
            logger.info("Fetching proxies from WebShare.io...")
            
            # Use the correct API endpoint with required parameters
            url = f"{self.base_url}/proxy/list/?mode=direct&page=1&page_size=100"
            
            try:
                logger.info(f"Fetching from endpoint: {url}")
                response = requests.get(url, headers=self.headers, timeout=10)
                if response.status_code != 200:
                    logger.warning(f"API returned {response.status_code}: {response.text[:200]}")
            except Exception as e:
                logger.warning(f"API request failed: {e}")
                response = None
            
            if not response or response.status_code != 200:
                logger.error("All WebShare API endpoints failed")
                return []
            
            data = response.json()
            logger.info(f"API Response keys: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
            logger.info(f"API Response preview: {str(data)[:200]}...")
            
            proxies = []
            
            for proxy_data in data.get('results', []):
                # WebShare provides username/password authentication
                # Port is provided directly, not nested
                proxy_info = {
                    'ip': proxy_data['proxy_address'],
                    'port': proxy_data['port'],
                    'username': proxy_data['username'],
                    'password': proxy_data['password'],
                    'protocol': 'http',  # WebShare supports HTTP/HTTPS
                    'country': proxy_data.get('country_code', 'Unknown'),
                    'source': 'webshare',
                    'quality_score': 95,  # High quality paid proxies
                    'discovered_at': datetime.now().isoformat()
                }
                proxies.append(proxy_info)
            
            logger.info(f"Retrieved {len(proxies)} WebShare proxies")
            return proxies
            
        except requests.RequestException as e:
            logger.error(f"Failed to fetch WebShare proxies: {e}")
            return []
        except Exception as e:
            logger.error(f"WebShare API error: {e}")
            return []
    
    def test_proxy_auth(self, proxy_info: dict) -> bool:
        """Test if proxy authentication works"""
        try:
            proxy_url = f"http://{proxy_info['username']}:{proxy_info['password']}@{proxy_info['ip']}:{proxy_info['port']}"
            
            response = requests.get(
                'http://httpbin.org/ip',
                proxies={'http': proxy_url, 'https': proxy_url},
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info(f"✅ WebShare proxy {proxy_info['ip']} authentication successful")
                return True
            else:
                logger.warning(f"❌ WebShare proxy {proxy_info['ip']} auth failed: {response.status_code}")
                return False
                
        except Exception as e:
            logger.warning(f"❌ WebShare proxy {proxy_info['ip']} test error: {e}")
            return False
    
    def get_account_info(self) -> dict:
        """Get WebShare account information and limits"""
        try:
            url = f"{self.base_url}/profile/"
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            
            return response.json()
            
        except Exception as e:
            logger.error(f"Failed to get WebShare account info: {e}")
            return {}


def integrate_webshare_with_smart_manager():
    """Update SmartProxyManager to use WebShare proxies"""
    try:
        from smart_proxy_manager import SmartProxyManager, SmartProxy
        
        # Create WebShare source
        webshare = WebShareProxySource()
        
        # Get WebShare proxies
        webshare_proxies = webshare.get_proxy_list()
        
        if not webshare_proxies:
            logger.warning("No WebShare proxies available")
            return None
        
        # Convert to SmartProxy objects
        smart_proxies = []
        for proxy_info in webshare_proxies:
            # Test authentication first
            if webshare.test_proxy_auth(proxy_info):
                smart_proxy = SmartProxy(
                    ip=proxy_info['ip'],
                    port=proxy_info['port'],
                    protocol='http',
                    country=proxy_info['country'],
                    source='webshare',
                    discovered_at=datetime.now(),
                    quality_score=95,  # High quality
                    is_working=True,
                    success_count=1  # Pre-validated
                )
                
                # Store authentication info (we'll need this for yt-dlp)
                smart_proxy.username = proxy_info['username']
                smart_proxy.password = proxy_info['password']
                smart_proxy.auth_proxy_url = f"http://{proxy_info['username']}:{proxy_info['password']}@{proxy_info['ip']}:{proxy_info['port']}"
                
                smart_proxies.append(smart_proxy)
        
        logger.info(f"✅ Successfully integrated {len(smart_proxies)} WebShare proxies")
        return smart_proxies
        
    except Exception as e:
        logger.error(f"Failed to integrate WebShare proxies: {e}")
        return None


# Test the WebShare integration
if __name__ == "__main__":
    print("🌐 WEBSHARE PROXY TEST")
    print("=" * 30)
    
    try:
        # Test WebShare API
        webshare = WebShareProxySource()
        
        # Get account info
        account_info = webshare.get_account_info()
        if account_info:
            print(f"📊 Account: {account_info.get('username', 'N/A')}")
            print(f"💰 Plan: {account_info.get('package', 'N/A')}")
        
        # Get proxy list
        proxies = webshare.get_proxy_list()
        print(f"📋 Found {len(proxies)} WebShare proxies")
        
        if proxies:
            # Test first proxy
            first_proxy = proxies[0]
            print(f"\n🧪 Testing first proxy: {first_proxy['ip']}:{first_proxy['port']}")
            
            if webshare.test_proxy_auth(first_proxy):
                print("✅ WebShare proxy authentication works!")
                
                # Test YouTube access
                try:
                    proxy_url = f"http://{first_proxy['username']}:{first_proxy['password']}@{first_proxy['ip']}:{first_proxy['port']}"
                    
                    response = requests.get(
                        "https://www.youtube.com/",
                        proxies={'http': proxy_url, 'https': proxy_url},
                        timeout=15,
                        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                    )
                    
                    if response.status_code == 200 and 'youtube' in response.text.lower():
                        print("🎉 WEBSHARE PROXY CAN ACCESS YOUTUBE!")
                    else:
                        print(f"⚠️ YouTube access limited: HTTP {response.status_code}")
                        
                except Exception as e:
                    print(f"❌ YouTube test failed: {e}")
            else:
                print("❌ WebShare proxy authentication failed")
        
        # Test integration
        print(f"\n🔧 Testing Smart Manager Integration...")
        smart_proxies = integrate_webshare_with_smart_manager()
        
        if smart_proxies:
            print(f"✅ Integrated {len(smart_proxies)} proxies into smart manager")
            
            # Show first proxy details
            first_smart = smart_proxies[0]
            print(f"📍 Example: {first_smart.ip}:{first_smart.port} (score: {first_smart.quality_score})")
        else:
            print("❌ Integration failed")
        
    except Exception as e:
        print(f"❌ WebShare test error: {e}")
        import traceback
        traceback.print_exc()