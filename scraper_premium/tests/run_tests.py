#!/usr/bin/env python3
"""
Test Runner
===========

Simple test runner for manual testing and validation.
"""

import sys
import os
from datetime import datetime

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_navigation_analysis import test_all_brands, test_single_brand


def main():
    """Main test runner"""
    print("🚀 Scraper Premium Test Suite")
    print("=" * 50)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    try:
        # Run all brand tests
        results = test_all_brands()
        
        # Optional: Save results to file
        save_results = input("\n💾 Save results to file? (y/n): ").lower().strip()
        if save_results == 'y':
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"navigation_test_results_{timestamp}.txt"
            
            with open(filename, 'w') as f:
                f.write(f"Navigation Analysis Test Results\n")
                f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 50 + "\n\n")
                
                for result in results:
                    f.write(f"Brand: {result['brand']}\n")
                    f.write(f"URL: {result['url']}\n") 
                    f.write(f"Expected Style: {result['expected_style']}\n")
                    f.write(f"Detected Style: {result['detected_style']}\n")
                    f.write(f"Success: {result['success']}\n")
                    f.write(f"URLs Found: {result['url_count']}\n")
                    
                    if result['product_urls']:
                        f.write("Product URLs:\n")
                        for i, url in enumerate(result['product_urls'], 1):
                            f.write(f"  {i}. {url}\n")
                    
                    if result.get('error'):
                        f.write(f"Error: {result['error']}\n")
                    
                    f.write("\n" + "-" * 30 + "\n\n")
            
            print(f"✅ Results saved to: {filename}")
        
        print(f"\n🏁 Test suite completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
    except KeyboardInterrupt:
        print("\n⏹️  Test suite interrupted by user")
    except Exception as e:
        print(f"\n❌ Test suite failed: {e}")


if __name__ == "__main__":
    main()