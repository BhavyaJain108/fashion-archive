#!/usr/bin/env python3
"""
Proxy Management Utility

Simple command-line tool to manage the proxy system for fashion archive video downloads.

Usage:
    python manage_proxy.py enable    # Enable proxy system
    python manage_proxy.py disable   # Disable proxy system  
    python manage_proxy.py status    # Show proxy status
    python manage_proxy.py refresh   # Refresh proxy pool
    python manage_proxy.py test      # Test video download

Author: Fashion Archive Team
License: MIT
"""

import sys
import os
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))


def show_status():
    """Show proxy system status"""
    try:
        from proxy_integration import is_proxy_enabled, get_proxy_stats
        
        print("🔍 PROXY SYSTEM STATUS")
        print("=" * 40)
        
        enabled = is_proxy_enabled()
        print(f"Status: {'🟢 ENABLED' if enabled else '🔴 DISABLED'}")
        print(f"Environment: USE_PROXY={os.getenv('USE_PROXY', 'not set')}")
        
        if enabled:
            stats = get_proxy_stats()
            if stats:
                print(f"Working Proxies: {stats['working_proxies']}")
                print(f"Total Proxies: {stats['total_proxies']}")
                print(f"Failed Proxies: {stats['failed_proxies']}")
                print(f"Avg Response Time: {stats['average_response_time']}s")
            else:
                print("Proxy manager not initialized")
        else:
            print("Proxy statistics not available (disabled)")
            
    except ImportError:
        print("❌ Proxy system modules not available")
    except Exception as e:
        print(f"❌ Error checking status: {e}")


def enable_proxy():
    """Enable proxy system"""
    try:
        from proxy_integration import enable_proxy
        enable_proxy()
        print("✅ Proxy system ENABLED")
        show_status()
    except Exception as e:
        print(f"❌ Error enabling proxy: {e}")


def disable_proxy():
    """Disable proxy system"""
    try:
        from proxy_integration import disable_proxy
        disable_proxy()
        print("✅ Proxy system DISABLED")
        show_status()
    except Exception as e:
        print(f"❌ Error disabling proxy: {e}")


def refresh_proxies():
    """Refresh proxy pool"""
    try:
        from proxy_integration import refresh_proxies
        print("🔄 Refreshing proxy pool...")
        refresh_proxies()
        print("✅ Proxy pool refreshed")
        show_status()
    except Exception as e:
        print(f"❌ Error refreshing proxies: {e}")


def test_download():
    """Test video download with current proxy settings"""
    try:
        from claude_video_verifier import EnhancedFashionVideoSearch
        
        print("🧪 TESTING VIDEO DOWNLOAD")
        print("=" * 40)
        
        # Test with a simple fashion show query
        test_query = "Chanel Spring Summer 2020 Paris Fashion Show"
        print(f"Test Query: {test_query}")
        
        enhanced_search = EnhancedFashionVideoSearch()
        
        # Just test search (without actual download)
        print("🔍 Testing search functionality...")
        video_result = enhanced_search.search_and_verify(test_query)
        
        if video_result:
            print(f"✅ Search successful: {video_result.title}")
            print(f"🔗 URL: {video_result.url}")
            print("ℹ️  To test actual download, use the full system")
        else:
            print("❌ Search failed - no video found")
            
    except ImportError:
        print("❌ Video search system not available")
    except Exception as e:
        print(f"❌ Test error: {e}")


def show_help():
    """Show usage help"""
    print("""
🎬 FASHION ARCHIVE PROXY MANAGER

Usage:
    python manage_proxy.py <command>

Commands:
    enable      Enable proxy system for video downloads
    disable     Disable proxy system (use direct connections)
    status      Show current proxy system status
    refresh     Refresh proxy pool from free sources
    test        Test video search functionality
    help        Show this help message

Examples:
    python manage_proxy.py status
    python manage_proxy.py enable
    python manage_proxy.py refresh
    
Configuration:
    Set USE_PROXY=true/false in environment or .env file
    """)


def main():
    """Main function"""
    if len(sys.argv) != 2:
        show_help()
        return
    
    command = sys.argv[1].lower()
    
    if command == "status":
        show_status()
    elif command == "enable":
        enable_proxy()
    elif command == "disable":
        disable_proxy()
    elif command == "refresh":
        refresh_proxies()
    elif command == "test":
        test_download()
    elif command == "help":
        show_help()
    else:
        print(f"❌ Unknown command: {command}")
        show_help()


if __name__ == "__main__":
    main()