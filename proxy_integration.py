#!/usr/bin/env python3
"""
Proxy Integration Layer

Clean, modular integration of proxy system with existing video downloaders.
Can be easily enabled/disabled without changing core application logic.

Author: Fashion Archive Team
License: MIT
"""

import os
import logging
from typing import Optional, List, Dict, Any
from pathlib import Path

# Set up logging
logger = logging.getLogger(__name__)

# Global proxy system instances
_proxy_downloader = None
_proxy_enabled = None


def is_proxy_enabled() -> bool:
    """Check if proxy system should be used"""
    global _proxy_enabled
    
    if _proxy_enabled is None:
        # Check environment variable or config
        _proxy_enabled = os.getenv('USE_PROXY', 'true').lower() in ('true', '1', 'yes')
        logger.info(f"Proxy system {'enabled' if _proxy_enabled else 'disabled'}")
    
    return _proxy_enabled


def get_proxy_downloader():
    """Get or initialize the smart proxy downloader instance"""
    global _proxy_downloader
    
    if not is_proxy_enabled():
        return None
    
    if _proxy_downloader is None:
        try:
            # Try WebShare-enhanced smart manager first, then fallbacks
            try:
                from webshare_smart_manager import WebShareSmartManager
                _proxy_downloader = WebShareSmartManager(target_working_proxies=5)
                logger.info("WebShare-enhanced smart proxy manager initialized")
            except ImportError:
                try:
                    from smart_proxy_manager import SmartProxyManager
                    _proxy_downloader = SmartProxyManager(target_working_proxies=5)
                    logger.info("Smart proxy manager initialized")
                except ImportError:
                    from proxy_video_downloader import ProxyVideoDownloader
                    _proxy_downloader = ProxyVideoDownloader()
                    logger.info("Standard proxy downloader initialized")
        except Exception as e:
            logger.error(f"Failed to initialize proxy system: {e}")
            _proxy_downloader = None
    
    return _proxy_downloader


def build_ytdlp_command_with_proxy(base_cmd: List[str], url: str) -> tuple[List[str], Optional[Any]]:
    """
    Enhance yt-dlp command with smart proxy if available
    
    Args:
        base_cmd: Base yt-dlp command list
        url: Video URL being downloaded
        
    Returns:
        Tuple of (enhanced_command, proxy_used)
        If no proxy available, returns (original_command, None)
    """
    if not is_proxy_enabled():
        return base_cmd, None
    
    proxy_manager = get_proxy_downloader()
    if not proxy_manager:
        return base_cmd, None
    
    # Ensure we have working proxies
    if hasattr(proxy_manager, 'ensure_working_proxies'):
        # Smart proxy manager
        if not proxy_manager.ensure_working_proxies():
            logger.warning("Smart proxy manager has no working proxies")
            return base_cmd, None
        
        proxy = proxy_manager.get_working_proxy()
    else:
        # Original proxy manager
        proxy = proxy_manager.proxy_manager.get_proxy() if hasattr(proxy_manager, 'proxy_manager') else None
    
    if not proxy:
        logger.warning("No proxy available, using direct connection")
        return base_cmd, None
    
    # Create enhanced command with proxy settings
    enhanced_cmd = base_cmd.copy()
    
    # Use authenticated proxy URL if available (WebShare), otherwise regular proxy URL
    proxy_url = getattr(proxy, 'auth_proxy_url', proxy.proxy_url)
    
    # Add proxy settings
    enhanced_cmd.extend([
        "--proxy", proxy_url,
        "--socket-timeout", "30",
        "--sleep-interval", "1" if hasattr(proxy, 'auth_proxy_url') else "2",  # WebShare proxies are faster
        "--max-sleep-interval", "3" if hasattr(proxy, 'auth_proxy_url') else "5", 
        "--no-check-certificates",  # Help with proxy SSL issues
    ])
    
    logger.info(f"Using proxy {proxy.ip}:{proxy.port} (score: {getattr(proxy, 'quality_score', 'N/A')}) for download")
    return enhanced_cmd, proxy


def handle_download_result(returncode: int, stderr: str, proxy_used: Optional[Any] = None):
    """
    Handle download result and update smart proxy statistics
    
    Args:
        returncode: Process return code
        stderr: Process stderr output  
        proxy_used: Proxy that was used (if any)
    """
    if not proxy_used:
        return
    
    proxy_manager = get_proxy_downloader()
    if not proxy_manager:
        return
    
    # Determine if download was successful and response time
    success = returncode == 0
    is_proxy_error = any(error in stderr.lower() for error in ['403', '429', 'timeout', 'connection', 'forbidden']) if stderr else False
    
    if hasattr(proxy_manager, 'mark_proxy_result'):
        # Smart proxy manager
        if success:
            proxy_manager.mark_proxy_result(proxy_used, True, response_time=0)
            logger.info(f"✅ Proxy {proxy_used.ip}:{proxy_used.port} successful")
        elif is_proxy_error:
            proxy_manager.mark_proxy_result(proxy_used, False, response_time=0)
            logger.warning(f"❌ Proxy {proxy_used.ip}:{proxy_used.port} failed (proxy-related error)")
        else:
            # Non-proxy error, don't heavily penalize the proxy
            logger.info(f"⚠️ Download failed but not proxy fault: {stderr[:100] if stderr else 'Unknown error'}")
    else:
        # Original proxy manager
        if success:
            proxy_manager.proxy_manager.mark_proxy_success(proxy_used)
        elif is_proxy_error:
            proxy_manager.proxy_manager.mark_proxy_failed(proxy_used)


def get_proxy_stats() -> Optional[Dict[str, Any]]:
    """Get smart proxy system statistics"""
    if not is_proxy_enabled():
        return None
    
    proxy_manager = get_proxy_downloader()
    if not proxy_manager:
        return None
    
    if hasattr(proxy_manager, 'get_stats'):
        # Smart proxy manager  
        return proxy_manager.get_stats()
    else:
        # Original proxy manager
        return proxy_manager.get_proxy_stats() if hasattr(proxy_manager, 'get_proxy_stats') else None


def refresh_proxies():
    """Manually refresh smart proxy pool"""
    if not is_proxy_enabled():
        return
    
    proxy_manager = get_proxy_downloader()
    if proxy_manager:
        if hasattr(proxy_manager, 'ensure_working_proxies'):
            # Smart proxy manager - force refresh
            proxy_manager.target_working_proxies = 10  # Get more proxies
            proxy_manager.ensure_working_proxies()
        elif hasattr(proxy_manager, 'refresh_proxies'):
            # Original proxy manager
            proxy_manager.refresh_proxies()


# Configuration functions
def enable_proxy():
    """Enable proxy system"""
    global _proxy_enabled
    _proxy_enabled = True
    os.environ['USE_PROXY'] = 'true'
    logger.info("Proxy system enabled")


def disable_proxy():
    """Disable proxy system"""
    global _proxy_enabled, _proxy_downloader
    _proxy_enabled = False
    _proxy_downloader = None
    os.environ['USE_PROXY'] = 'false'
    logger.info("Proxy system disabled")


# Context manager for temporary proxy control
class ProxyContext:
    """Context manager for temporary proxy enable/disable"""
    
    def __init__(self, enabled: bool):
        self.enabled = enabled
        self.original_state = None
    
    def __enter__(self):
        self.original_state = is_proxy_enabled()
        if self.enabled:
            enable_proxy()
        else:
            disable_proxy()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.original_state:
            enable_proxy()
        else:
            disable_proxy()


# Convenience functions
def with_proxy(func):
    """Decorator to ensure proxy is enabled for a function"""
    def wrapper(*args, **kwargs):
        with ProxyContext(True):
            return func(*args, **kwargs)
    return wrapper


def without_proxy(func):
    """Decorator to ensure proxy is disabled for a function"""
    def wrapper(*args, **kwargs):
        with ProxyContext(False):
            return func(*args, **kwargs)
    return wrapper