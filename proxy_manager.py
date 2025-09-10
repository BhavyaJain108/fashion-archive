#!/usr/bin/env python3
"""
Modular Proxy Management System

A reusable proxy rotation system that can be used for:
- YouTube video downloads (yt-dlp)
- Web scraping (requests, BeautifulSoup)
- API calls
- Any HTTP-based operations

Features:
- Free proxy aggregation from multiple sources
- Health monitoring and automatic failover
- Rate limiting and request throttling
- Easy upgrade path to paid proxy services

Author: Fashion Archive Team
License: MIT
"""

import requests
import random
import time
import threading
import json
import subprocess
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from pathlib import Path
from datetime import datetime, timedelta
import concurrent.futures
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class ProxyInfo:
    """Represents a proxy server with performance metrics"""
    ip: str
    port: int
    protocol: str  # 'http', 'https', 'socks4', 'socks5'
    country: str = ""
    anonymity: str = ""  # 'elite', 'anonymous', 'transparent'
    
    # Performance metrics
    response_time: float = 0.0  # seconds
    success_count: int = 0
    failure_count: int = 0
    last_used: Optional[datetime] = None
    last_tested: Optional[datetime] = None
    is_working: bool = False
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate percentage"""
        total = self.success_count + self.failure_count
        return (self.success_count / total * 100) if total > 0 else 0.0
    
    @property
    def proxy_url(self) -> str:
        """Get proxy URL for requests"""
        return f"{self.protocol}://{self.ip}:{self.port}"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for yt-dlp"""
        return {
            'http': self.proxy_url,
            'https': self.proxy_url
        }


class ProxyAggregator:
    """Fetches proxies from multiple free sources"""
    
    FREE_PROXY_SOURCES = [
        {
            'name': 'ProxyScrape',
            'url': 'https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=5000&country=all&format=textplain',
            'parser': 'simple_ip_port'
        },
        {
            'name': 'Proxy-List',
            'url': 'https://www.proxy-list.download/api/v1/get?type=http',
            'parser': 'simple_ip_port'
        },
        {
            'name': 'Free-Proxy-List',
            'url': 'https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt',
            'parser': 'simple_ip_port'
        },
        {
            'name': 'ProxyList-HTTP',
            'url': 'https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt',
            'parser': 'simple_ip_port'
        }
    ]
    
    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def fetch_all_proxies(self) -> List[ProxyInfo]:
        """Fetch proxies from all sources concurrently"""
        all_proxies = []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_source = {
                executor.submit(self._fetch_from_source, source): source
                for source in self.FREE_PROXY_SOURCES
            }
            
            for future in concurrent.futures.as_completed(future_to_source):
                source = future_to_source[future]
                try:
                    proxies = future.result(timeout=30)
                    logger.info(f"Fetched {len(proxies)} proxies from {source['name']}")
                    all_proxies.extend(proxies)
                except Exception as e:
                    logger.warning(f"Failed to fetch from {source['name']}: {e}")
        
        # Remove duplicates
        unique_proxies = self._deduplicate_proxies(all_proxies)
        logger.info(f"Total unique proxies fetched: {len(unique_proxies)}")
        
        return unique_proxies
    
    def _fetch_from_source(self, source: Dict[str, str]) -> List[ProxyInfo]:
        """Fetch proxies from a single source"""
        try:
            response = self.session.get(source['url'], timeout=self.timeout)
            response.raise_for_status()
            
            if source['parser'] == 'simple_ip_port':
                return self._parse_simple_ip_port(response.text, source['name'])
            
            return []
            
        except Exception as e:
            logger.warning(f"Error fetching from {source['name']}: {e}")
            return []
    
    def _parse_simple_ip_port(self, text: str, source_name: str) -> List[ProxyInfo]:
        """Parse simple IP:PORT format"""
        proxies = []
        
        for line in text.strip().split('\n'):
            line = line.strip()
            if ':' in line and len(line.split(':')) == 2:
                try:
                    ip, port = line.split(':')
                    proxy = ProxyInfo(
                        ip=ip.strip(),
                        port=int(port.strip()),
                        protocol='http',
                        country='unknown'
                    )
                    proxies.append(proxy)
                except ValueError:
                    continue
        
        return proxies
    
    def _deduplicate_proxies(self, proxies: List[ProxyInfo]) -> List[ProxyInfo]:
        """Remove duplicate proxies based on IP:PORT"""
        seen = set()
        unique = []
        
        for proxy in proxies:
            key = f"{proxy.ip}:{proxy.port}"
            if key not in seen:
                seen.add(key)
                unique.append(proxy)
        
        return unique


class ProxyTester:
    """Tests proxy connectivity and performance"""
    
    TEST_URLS = [
        'http://httpbin.org/ip',
        'https://api.ipify.org?format=json',
        'http://icanhazip.com'
    ]
    
    def __init__(self, timeout: int = 10, max_workers: int = 50):
        self.timeout = timeout
        self.max_workers = max_workers
    
    def test_proxies(self, proxies: List[ProxyInfo]) -> List[ProxyInfo]:
        """Test all proxies concurrently and return working ones"""
        logger.info(f"Testing {len(proxies)} proxies...")
        
        working_proxies = []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_proxy = {
                executor.submit(self._test_single_proxy, proxy): proxy
                for proxy in proxies
            }
            
            completed = 0
            for future in concurrent.futures.as_completed(future_to_proxy):
                proxy = future_to_proxy[future]
                completed += 1
                
                try:
                    is_working, response_time = future.result()
                    
                    proxy.last_tested = datetime.now()
                    proxy.response_time = response_time
                    proxy.is_working = is_working
                    
                    if is_working:
                        proxy.success_count += 1
                        working_proxies.append(proxy)
                    else:
                        proxy.failure_count += 1
                    
                    if completed % 50 == 0:
                        logger.info(f"Tested {completed}/{len(proxies)} proxies...")
                        
                except Exception as e:
                    proxy.failure_count += 1
                    proxy.is_working = False
                    proxy.last_tested = datetime.now()
        
        logger.info(f"Found {len(working_proxies)} working proxies out of {len(proxies)}")
        
        # Sort by response time (fastest first)
        working_proxies.sort(key=lambda p: p.response_time)
        
        return working_proxies
    
    def _test_single_proxy(self, proxy: ProxyInfo) -> Tuple[bool, float]:
        """Test a single proxy and return (is_working, response_time)"""
        try:
            proxies = proxy.to_dict()
            test_url = random.choice(self.TEST_URLS)
            
            start_time = time.time()
            
            response = requests.get(
                test_url,
                proxies=proxies,
                timeout=self.timeout,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
            )
            
            response_time = time.time() - start_time
            
            # Check if we got a valid response
            if response.status_code == 200 and response.text.strip():
                return True, response_time
            
            return False, response_time
            
        except Exception:
            return False, 999.0  # High response time for failed requests


class ProxyManager:
    """Main proxy management system with rotation and health monitoring"""
    
    def __init__(self, cache_file: str = "proxy_cache.json", 
                 min_proxies: int = 10, 
                 max_proxies: int = 100):
        self.cache_file = Path(cache_file)
        self.min_proxies = min_proxies
        self.max_proxies = max_proxies
        
        self.proxies: List[ProxyInfo] = []
        self.current_index = 0
        self.lock = threading.Lock()
        
        self.aggregator = ProxyAggregator()
        self.tester = ProxyTester()
        
        # Load cached proxies
        self._load_cache()
        
        # Start background refresh thread
        self.refresh_thread = threading.Thread(target=self._background_refresh, daemon=True)
        self.refresh_thread.start()
    
    def get_proxy(self) -> Optional[ProxyInfo]:
        """Get next proxy in rotation"""
        with self.lock:
            if not self.proxies:
                logger.warning("No working proxies available")
                return None
            
            # Remove failed proxies
            self.proxies = [p for p in self.proxies if p.is_working]
            
            if not self.proxies:
                logger.warning("All proxies failed, triggering refresh")
                self._trigger_refresh()
                return None
            
            # Get next proxy
            proxy = self.proxies[self.current_index]
            self.current_index = (self.current_index + 1) % len(self.proxies)
            
            proxy.last_used = datetime.now()
            return proxy
    
    def mark_proxy_failed(self, proxy: ProxyInfo):
        """Mark a proxy as failed"""
        with self.lock:
            proxy.failure_count += 1
            proxy.is_working = False
            
            # Remove if too many failures
            if proxy.failure_count >= 3:
                try:
                    self.proxies.remove(proxy)
                    logger.info(f"Removed failed proxy: {proxy.ip}:{proxy.port}")
                except ValueError:
                    pass
    
    def mark_proxy_success(self, proxy: ProxyInfo):
        """Mark a proxy as successful"""
        with self.lock:
            proxy.success_count += 1
            proxy.is_working = True
    
    def get_stats(self) -> Dict[str, Any]:
        """Get proxy pool statistics"""
        with self.lock:
            working = sum(1 for p in self.proxies if p.is_working)
            total = len(self.proxies)
            avg_response = sum(p.response_time for p in self.proxies) / total if total > 0 else 0
            
            return {
                'total_proxies': total,
                'working_proxies': working,
                'failed_proxies': total - working,
                'average_response_time': round(avg_response, 2),
                'current_index': self.current_index
            }
    
    def refresh_proxies(self):
        """Manually refresh proxy pool"""
        logger.info("Refreshing proxy pool...")
        
        # Fetch new proxies
        new_proxies = self.aggregator.fetch_all_proxies()
        
        if new_proxies:
            # Test them
            working_proxies = self.tester.test_proxies(new_proxies)
            
            # Limit to max_proxies
            working_proxies = working_proxies[:self.max_proxies]
            
            with self.lock:
                self.proxies = working_proxies
                self.current_index = 0
            
            # Save to cache
            self._save_cache()
            
            logger.info(f"Proxy pool refreshed: {len(working_proxies)} working proxies")
        else:
            logger.warning("No new proxies fetched during refresh")
    
    def _load_cache(self):
        """Load proxies from cache file"""
        if not self.cache_file.exists():
            return
        
        try:
            with open(self.cache_file, 'r') as f:
                cached_data = json.load(f)
            
            proxies = []
            for data in cached_data:
                proxy = ProxyInfo(**data)
                # Convert string dates back to datetime
                if proxy.last_used:
                    proxy.last_used = datetime.fromisoformat(proxy.last_used)
                if proxy.last_tested:
                    proxy.last_tested = datetime.fromisoformat(proxy.last_tested)
                proxies.append(proxy)
            
            # Only load recent proxies (less than 24 hours old)
            recent_proxies = []
            cutoff = datetime.now() - timedelta(hours=24)
            
            for proxy in proxies:
                if proxy.last_tested and proxy.last_tested > cutoff and proxy.is_working:
                    recent_proxies.append(proxy)
            
            if recent_proxies:
                self.proxies = recent_proxies
                logger.info(f"Loaded {len(recent_proxies)} cached proxies")
            
        except Exception as e:
            logger.warning(f"Failed to load proxy cache: {e}")
    
    def _save_cache(self):
        """Save proxies to cache file"""
        try:
            # Convert to serializable format
            cache_data = []
            for proxy in self.proxies:
                data = asdict(proxy)
                # Convert datetime to string
                if data['last_used']:
                    data['last_used'] = proxy.last_used.isoformat()
                if data['last_tested']:
                    data['last_tested'] = proxy.last_tested.isoformat()
                cache_data.append(data)
            
            with open(self.cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
                
        except Exception as e:
            logger.warning(f"Failed to save proxy cache: {e}")
    
    def _background_refresh(self):
        """Background thread to refresh proxies periodically"""
        while True:
            time.sleep(3600)  # Refresh every hour
            
            with self.lock:
                working_count = sum(1 for p in self.proxies if p.is_working)
            
            if working_count < self.min_proxies:
                logger.info(f"Only {working_count} working proxies, triggering refresh")
                self._trigger_refresh()
    
    def _trigger_refresh(self):
        """Trigger immediate proxy refresh"""
        threading.Thread(target=self.refresh_proxies, daemon=True).start()


class RequestManager:
    """Manages HTTP requests with proxy rotation"""
    
    def __init__(self, proxy_manager: ProxyManager, max_retries: int = 3):
        self.proxy_manager = proxy_manager
        self.max_retries = max_retries
    
    def get(self, url: str, **kwargs) -> Optional[requests.Response]:
        """Make GET request with proxy rotation"""
        return self._request_with_proxy('GET', url, **kwargs)
    
    def post(self, url: str, **kwargs) -> Optional[requests.Response]:
        """Make POST request with proxy rotation"""
        return self._request_with_proxy('POST', url, **kwargs)
    
    def _request_with_proxy(self, method: str, url: str, **kwargs) -> Optional[requests.Response]:
        """Make HTTP request with automatic proxy rotation and retry"""
        
        for attempt in range(self.max_retries):
            proxy = self.proxy_manager.get_proxy()
            
            if not proxy:
                logger.warning("No proxy available, trying direct connection")
                return self._make_direct_request(method, url, **kwargs)
            
            try:
                # Set proxy in requests
                kwargs['proxies'] = proxy.to_dict()
                kwargs['timeout'] = kwargs.get('timeout', 10)
                
                # Make request
                if method == 'GET':
                    response = requests.get(url, **kwargs)
                elif method == 'POST':
                    response = requests.post(url, **kwargs)
                else:
                    raise ValueError(f"Unsupported method: {method}")
                
                # Check if successful
                if response.status_code < 400:
                    self.proxy_manager.mark_proxy_success(proxy)
                    return response
                else:
                    logger.warning(f"HTTP {response.status_code} with proxy {proxy.ip}:{proxy.port}")
                    self.proxy_manager.mark_proxy_failed(proxy)
                    
            except Exception as e:
                logger.warning(f"Request failed with proxy {proxy.ip}:{proxy.port}: {e}")
                self.proxy_manager.mark_proxy_failed(proxy)
                
                # Wait before retry
                time.sleep(2 ** attempt)
        
        logger.error(f"All {self.max_retries} attempts failed for {url}")
        return None
    
    def _make_direct_request(self, method: str, url: str, **kwargs) -> Optional[requests.Response]:
        """Make direct request without proxy"""
        try:
            kwargs.pop('proxies', None)  # Remove proxy settings
            
            if method == 'GET':
                return requests.get(url, **kwargs)
            elif method == 'POST':
                return requests.post(url, **kwargs)
                
        except Exception as e:
            logger.error(f"Direct request failed for {url}: {e}")
            return None


# Example usage and testing
if __name__ == "__main__":
    # Initialize proxy manager
    proxy_manager = ProxyManager()
    
    # Initial refresh
    proxy_manager.refresh_proxies()
    
    # Show stats
    stats = proxy_manager.get_stats()
    print(f"Proxy stats: {stats}")
    
    # Test with request manager
    request_manager = RequestManager(proxy_manager)
    
    # Test a few requests
    test_urls = [
        'http://httpbin.org/ip',
        'https://api.ipify.org?format=json',
        'http://icanhazip.com'
    ]
    
    for url in test_urls:
        print(f"\nTesting {url}")
        response = request_manager.get(url)
        if response:
            print(f"Success: {response.text[:100]}")
        else:
            print("Failed")
    
    # Final stats
    final_stats = proxy_manager.get_stats()
    print(f"\nFinal stats: {final_stats}")