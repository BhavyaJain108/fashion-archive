#!/usr/bin/env python3
"""
Full extraction pipeline runner.

Usage:
    python run_pipeline.py <url>
    python run_pipeline.py https://www.eckhauslatta.com
    python run_pipeline.py https://www.eckhauslatta.com --test
"""

import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from brand import Brand


def main():
    if len(sys.argv) < 2:
        print("Usage: python run_pipeline.py <url> [--test]")
        print("  --test: Run in test mode (limits extraction)")
        sys.exit(1)

    url = sys.argv[1]
    test_mode = "--test" in sys.argv

    print(f"\n{'='*60}")
    print(f"FULL EXTRACTION PIPELINE")
    print(f"{'='*60}")
    print(f"URL: {url}")
    print(f"Test mode: {test_mode}")
    print(f"{'='*60}\n")

    try:
        brand = Brand(url, test_mode=test_mode)
        results = brand.run_full_extraction_pipeline()

        print(f"\n{'='*60}")
        print("RESULTS")
        print(f"{'='*60}")
        print(f"Success: {results.get('success')}")

        summary = results.get('summary', {})
        print(f"Categories: {summary.get('total_categories', 0)}")
        print(f"Products: {summary.get('total_products', 0)}")
        print(f"Images: {summary.get('images_downloaded', 0)}")
        print(f"Time: {summary.get('extraction_time', 0):.1f}s")

        if results.get('error'):
            print(f"Error: {results.get('error')}")

    except Exception as e:
        print(f"\n❌ Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
