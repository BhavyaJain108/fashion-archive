#!/usr/bin/env python3
"""
Smart Proxy Manager - Fast & Efficient

Key improvements:
1. Tests only 100-200 proxies at a time (not 40k!)
2. Stops as soon as it finds 5-10 working proxies
3. Uses multiple proxy sources with quality ranking
4. Implements smart caching and freshness tracking
5. Easy upgrade path to paid services

Author: Fashion Archive Team
License: MIT
"""

import requests
import random
import time
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class SmartProxy:
    """Enhanced proxy info with smart metrics"""
    ip: str
    port: int
    protocol: str = "http"
    country: str = ""
    source: str = ""  # Which source provided this proxy
    
    # Performance metrics
    response_time: float = 0.0
    success_count: int = 0
    failure_count: int = 0
    last_used: Optional[datetime] = None
    last_tested: Optional[datetime] = None
    
    # Smart tracking
    discovered_at: Optional[datetime] = None
    quality_score: float = 0.0  # 0-100 based on performance
    is_working: bool = False
    failure_streak: int = 0  # Consecutive failures
    
    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return (self.success_count / total * 100) if total > 0 else 0.0
    
    @property
    def proxy_url(self) -> str:
        return f"{self.protocol}://{self.ip}:{self.port}"
    
    @property
    def is_fresh(self) -> bool:
        """Check if proxy was discovered recently (last 6 hours)"""
        if not self.discovered_at:
            return False
        return datetime.now() - self.discovered_at < timedelta(hours=6)
    
    def update_quality_score(self):
        """Calculate quality score based on multiple factors"""
        score = 0.0
        
        # Success rate (40% weight)
        score += self.success_rate * 0.4
        
        # Response time (30% weight) - faster = better
        if self.response_time > 0:
            time_score = max(0, 100 - (self.response_time * 10))  # 10s = 0 score
            score += time_score * 0.3
        
        # Freshness (20% weight)
        if self.is_fresh:
            score += 20
        
        # Reliability (10% weight) - low failure streak = better
        if self.failure_streak == 0:
            score += 10
        elif self.failure_streak < 3:
            score += 5
        
        self.quality_score = min(100, score)


class SmartProxySource:
    """Represents a proxy source with quality ranking"""
    
    def __init__(self, name: str, url: str, parser: str, quality_rank: int = 5):
        self.name = name
        self.url = url  
        self.parser = parser
        self.quality_rank = quality_rank  # 1-10, higher = better quality
        self.last_fetch_time: Optional[datetime] = None
        self.last_proxy_count = 0
        self.consecutive_failures = 0
    
    @property
    def is_reliable(self) -> bool:
        """Check if this source is reliable (low failure rate)"""
        return self.consecutive_failures < 3


class SmartProxyManager:
    """Intelligent proxy management with fast testing and quality tracking"""
    
    # High-quality proxy sources (tested and verified)
    SMART_PROXY_SOURCES = [
        SmartProxySource("ProxyList-Premium", "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt", "simple_ip_port", 8),
        SmartProxySource("SpeedX-Fresh", "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt", "simple_ip_port", 7),
        SmartProxySource("Free-Proxy-List", "https://www.proxy-list.download/api/v1/get?type=http", "simple_ip_port", 6),
        SmartProxySource("ProxyScrape-HTTP", "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=5000&country=all&format=textplain", "simple_ip_port", 5),
    ]
    
    def __init__(self, 
                 cache_file: str = "smart_proxy_cache.json",
                 target_working_proxies: int = 8,
                 max_test_batch: int = 150,
                 max_concurrent_tests: int = 30):
        
        self.cache_file = Path(cache_file)
        self.target_working_proxies = target_working_proxies
        self.max_test_batch = max_test_batch  # Don't test more than 150 at once
        self.max_concurrent_tests = max_concurrent_tests
        
        self.proxies: List[SmartProxy] = []
        self.current_index = 0
        self.lock = threading.Lock()
        
        # Load cached proxies
        self._load_smart_cache()
        
        logger.info(f"Smart Proxy Manager initialized with {len(self.proxies)} cached proxies")
    
    def get_working_proxy(self) -> Optional[SmartProxy]:
        """Get next working proxy with smart rotation"""
        with self.lock:
            # Filter to only working proxies and sort by quality
            working_proxies = [p for p in self.proxies if p.is_working and p.failure_streak < 3]
            
            if not working_proxies:
                logger.warning("No working proxies available")
                return None
            
            # Sort by quality score (best first)
            working_proxies.sort(key=lambda p: p.quality_score, reverse=True)
            
            # Use round-robin among top 50% of proxies
            top_proxies = working_proxies[:max(1, len(working_proxies)//2)]
            proxy = top_proxies[self.current_index % len(top_proxies)]
            
            self.current_index += 1
            proxy.last_used = datetime.now()
            
            return proxy
    
    def mark_proxy_result(self, proxy: SmartProxy, success: bool, response_time: float = 0):
        """Mark proxy result and update quality metrics"""
        with self.lock:
            if success:
                proxy.success_count += 1
                proxy.failure_streak = 0
                proxy.is_working = True
                if response_time > 0:
                    # Update response time with exponential moving average
                    if proxy.response_time == 0:
                        proxy.response_time = response_time
                    else:
                        proxy.response_time = (proxy.response_time * 0.7) + (response_time * 0.3)
            else:
                proxy.failure_count += 1
                proxy.failure_streak += 1
                
                # Mark as non-working if too many consecutive failures
                if proxy.failure_streak >= 3:
                    proxy.is_working = False
            
            # Update quality score
            proxy.update_quality_score()
            
            # Remove if completely unreliable
            if proxy.failure_streak >= 5:
                try:
                    self.proxies.remove(proxy)
                    logger.info(f"Removed unreliable proxy: {proxy.ip}:{proxy.port}")
                except ValueError:
                    pass
    
    def ensure_working_proxies(self) -> bool:
        """Ensure we have enough working proxies, fetch more if needed"""
        working_count = len([p for p in self.proxies if p.is_working])
        
        if working_count >= self.target_working_proxies:
            logger.info(f"Already have {working_count} working proxies")
            return True
        
        logger.info(f"Need more proxies: {working_count}/{self.target_working_proxies}")
        
        # Try to get fresh proxies
        new_proxies = self._fetch_smart_sample()
        if not new_proxies:
            logger.warning("No new proxies found")
            return working_count > 0
        
        # Test new proxies quickly
        working_new = self._test_proxy_batch(new_proxies, target_count=self.target_working_proxies - working_count)
        
        if working_new:
            with self.lock:
                self.proxies.extend(working_new)
            
            logger.info(f"Added {len(working_new)} new working proxies")
            self._save_smart_cache()
            return True
        
        logger.warning("No working proxies found in new batch")
        return working_count > 0
    
    def _fetch_smart_sample(self) -> List[SmartProxy]:
        """Fetch a smart sample of proxies from best sources"""
        logger.info("Fetching smart proxy sample...")
        
        all_new_proxies = []
        
        # Sort sources by quality rank (best first)
        sources = sorted([s for s in self.SMART_PROXY_SOURCES if s.is_reliable], 
                        key=lambda s: s.quality_rank, reverse=True)
        
        for source in sources[:3]:  # Only use top 3 sources
            try:
                logger.info(f"Fetching from {source.name} (quality: {source.quality_rank})")
                
                response = requests.get(source.url, timeout=10, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                })
                response.raise_for_status()
                
                new_proxies = self._parse_proxy_response(response.text, source)
                
                # Take random sample to avoid testing same proxies repeatedly
                if len(new_proxies) > 50:
                    new_proxies = random.sample(new_proxies, 50)
                
                all_new_proxies.extend(new_proxies)
                source.consecutive_failures = 0
                source.last_fetch_time = datetime.now()
                source.last_proxy_count = len(new_proxies)
                
                logger.info(f"Got {len(new_proxies)} proxies from {source.name}")
                
                # Stop if we have enough to test
                if len(all_new_proxies) >= self.max_test_batch:
                    break
                    
            except Exception as e:
                logger.warning(f"Failed to fetch from {source.name}: {e}")
                source.consecutive_failures += 1
        
        # Remove duplicates and existing proxies
        all_new_proxies = self._deduplicate_proxies(all_new_proxies)
        
        logger.info(f"Total unique new proxies to test: {len(all_new_proxies)}")
        return all_new_proxies[:self.max_test_batch]  # Limit batch size
    
    def _parse_proxy_response(self, text: str, source: SmartProxySource) -> List[SmartProxy]:
        """Parse proxy response based on source format"""
        proxies = []
        now = datetime.now()
        
        for line in text.strip().split('\n'):
            line = line.strip()
            if ':' in line and len(line.split(':')) == 2:
                try:
                    ip, port = line.split(':')
                    proxy = SmartProxy(
                        ip=ip.strip(),
                        port=int(port.strip()),
                        protocol='http',
                        source=source.name,
                        discovered_at=now,
                        quality_score=source.quality_rank * 10  # Initial score based on source quality
                    )
                    proxies.append(proxy)
                except ValueError:
                    continue
        
        return proxies
    
    def _deduplicate_proxies(self, new_proxies: List[SmartProxy]) -> List[SmartProxy]:
        """Remove duplicates and proxies we already have"""
        existing_keys = set(f"{p.ip}:{p.port}" for p in self.proxies)
        
        unique_proxies = []
        seen_keys = set()
        
        for proxy in new_proxies:
            key = f"{proxy.ip}:{proxy.port}"
            if key not in existing_keys and key not in seen_keys:
                unique_proxies.append(proxy)
                seen_keys.add(key)
        
        return unique_proxies
    
    def _test_proxy_batch(self, proxies: List[SmartProxy], target_count: int = 5) -> List[SmartProxy]:
        """Test a batch of proxies quickly, stopping when we have enough"""
        logger.info(f"Testing {len(proxies)} proxies (target: {target_count} working)")
        
        working_proxies = []
        tested_count = 0
        
        with ThreadPoolExecutor(max_workers=self.max_concurrent_tests) as executor:
            # Submit all tests
            future_to_proxy = {executor.submit(self._test_single_proxy, proxy): proxy 
                             for proxy in proxies}
            
            # Process results as they complete
            for future in as_completed(future_to_proxy):
                proxy = future_to_proxy[future]
                tested_count += 1
                
                try:
                    is_working, response_time = future.result()
                    
                    if is_working:
                        proxy.success_count += 1
                        proxy.is_working = True
                        proxy.response_time = response_time
                        proxy.last_tested = datetime.now()
                        proxy.update_quality_score()
                        
                        working_proxies.append(proxy)
                        logger.info(f"✅ Working proxy found: {proxy.ip}:{proxy.port} ({response_time:.2f}s, score: {proxy.quality_score:.1f})")
                        
                        # Stop early if we have enough working proxies
                        if len(working_proxies) >= target_count:
                            logger.info(f"🎯 Found {len(working_proxies)} working proxies, stopping test")
                            # Cancel remaining futures
                            for remaining_future in future_to_proxy:
                                if remaining_future != future:
                                    remaining_future.cancel()
                            break
                    else:
                        proxy.failure_count += 1
                        proxy.is_working = False
                        proxy.failure_streak += 1
                
                except Exception:
                    proxy.failure_count += 1
                    proxy.is_working = False
                    proxy.failure_streak += 1
                
                # Progress update
                if tested_count % 20 == 0:
                    logger.info(f"📊 Tested {tested_count}/{len(proxies)}, found {len(working_proxies)} working")
        
        logger.info(f"✅ Proxy testing complete: {len(working_proxies)}/{tested_count} working")
        
        # Sort by quality score
        working_proxies.sort(key=lambda p: p.quality_score, reverse=True)
        return working_proxies
    
    def _test_single_proxy(self, proxy: SmartProxy) -> Tuple[bool, float]:
        """Test a single proxy quickly"""
        try:
            start_time = time.time()
            
            response = requests.get(
                'http://httpbin.org/ip',
                proxies={'http': proxy.proxy_url, 'https': proxy.proxy_url},
                timeout=6,  # Shorter timeout for speed
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            )
            
            response_time = time.time() - start_time
            
            if response.status_code == 200 and response.text.strip():
                return True, response_time
            
            return False, response_time
            
        except Exception:
            return False, 999.0
    
    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive proxy statistics"""
        with self.lock:
            working = [p for p in self.proxies if p.is_working]
            total = len(self.proxies)
            
            if working:
                avg_quality = sum(p.quality_score for p in working) / len(working)
                avg_response_time = sum(p.response_time for p in working if p.response_time > 0) / len(working)
            else:
                avg_quality = 0
                avg_response_time = 0
            
            return {
                'total_proxies': total,
                'working_proxies': len(working),
                'failed_proxies': total - len(working),
                'average_quality_score': round(avg_quality, 1),
                'average_response_time': round(avg_response_time, 2),
                'target_proxies': self.target_working_proxies,
                'fresh_proxies': len([p for p in working if p.is_fresh]),
                'sources_status': {s.name: {'reliable': s.is_reliable, 'last_count': s.last_proxy_count} 
                                 for s in self.SMART_PROXY_SOURCES}
            }
    
    def _load_smart_cache(self):
        """Load proxies from cache with smart filtering"""
        if not self.cache_file.exists():
            return
        
        try:
            with open(self.cache_file, 'r') as f:
                cached_data = json.load(f)
            
            proxies = []
            cutoff_time = datetime.now() - timedelta(hours=12)  # Only load recent proxies
            
            for data in cached_data:
                proxy = SmartProxy(**{k: v for k, v in data.items() if k != 'last_used' and k != 'last_tested' and k != 'discovered_at'})
                
                # Convert string dates back to datetime
                if data.get('last_used'):
                    try:
                        proxy.last_used = datetime.fromisoformat(data['last_used'])
                    except:
                        pass
                if data.get('last_tested'):
                    try:
                        proxy.last_tested = datetime.fromisoformat(data['last_tested'])
                    except:
                        pass
                if data.get('discovered_at'):
                    try:
                        proxy.discovered_at = datetime.fromisoformat(data['discovered_at'])
                    except:
                        pass
                
                # Only keep recent, working proxies
                if (proxy.is_working and 
                    proxy.last_tested and 
                    proxy.last_tested > cutoff_time and
                    proxy.failure_streak < 2):
                    proxies.append(proxy)
            
            self.proxies = sorted(proxies, key=lambda p: p.quality_score, reverse=True)
            logger.info(f"Loaded {len(proxies)} good cached proxies")
            
        except Exception as e:
            logger.warning(f"Failed to load proxy cache: {e}")
    
    def _save_smart_cache(self):
        """Save proxies to cache with smart selection"""
        try:
            # Only cache the best proxies
            cache_worthy = [p for p in self.proxies 
                          if p.is_working and p.quality_score > 20 and p.failure_streak < 2]
            
            cache_data = []
            for proxy in cache_worthy:
                data = asdict(proxy)
                # Convert datetime to string
                for field in ['last_used', 'last_tested', 'discovered_at']:
                    if data.get(field):
                        data[field] = data[field].isoformat()
                cache_data.append(data)
            
            with open(self.cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
            
            logger.info(f"Cached {len(cache_data)} quality proxies")
            
        except Exception as e:
            logger.warning(f"Failed to save proxy cache: {e}")


# Example usage and testing
if __name__ == "__main__":
    manager = SmartProxyManager(target_working_proxies=5)
    
    print("🚀 Smart Proxy Manager Test")
    print("=" * 40)
    
    # Ensure we have working proxies
    if manager.ensure_working_proxies():
        stats = manager.get_stats()
        print(f"📊 Stats: {stats}")
        
        # Test getting a proxy
        proxy = manager.get_working_proxy()
        if proxy:
            print(f"🎯 Got proxy: {proxy.ip}:{proxy.port} (score: {proxy.quality_score})")
        else:
            print("❌ No working proxy available")
    else:
        print("❌ Could not get working proxies")
        
        # This is where we'd switch to paid service
        print("💡 This is where we would switch to a paid proxy service")