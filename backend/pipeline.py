#!/usr/bin/env python3
"""
Fashion Scraping Pipeline

Staged extraction pipeline with checkpointing.

Stages:
  1. nav      - Extract navigation/category tree
  2. urls     - Extract product URLs from categories
  3. products - Extract full product details

Usage:
  # Individual stages
  python pipeline.py nav <url>                    # Stage 1
  python pipeline.py urls <domain>                # Stage 2 (requires nav.json)
  python pipeline.py products <domain>            # Stage 3 (requires urls.json)

  # Combined stages
  python pipeline.py nav+urls <url>               # Stages 1+2
  python pipeline.py urls+products <domain>       # Stages 2+3
  python pipeline.py all <url>                    # Full pipeline

Examples:
  python pipeline.py nav https://eckhauslatta.com
  python pipeline.py urls eckhauslatta_com
  python pipeline.py products eckhauslatta_com
  python pipeline.py all https://www.khaite.com
"""

import sys
from pathlib import Path

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "stages"))
sys.path.insert(0, str(Path(__file__).parent / "scraper"))
sys.path.insert(0, str(Path(__file__).parent / "prod_page_v2"))

from stages.storage import get_domain


def run_nav(url: str) -> bool:
    """Run Stage 1: Navigation extraction."""
    from stages.navigation import extract_navigation

    result = extract_navigation(url)
    return result is not None


def run_urls(domain: str) -> bool:
    """Run Stage 2: URL extraction."""
    from stages.urls import extract_urls

    result = extract_urls(domain)
    return result is not None


def run_products(domain: str) -> bool:
    """Run Stage 3: Product extraction."""
    from stages.products import run_extract_products

    result = run_extract_products(domain)
    return result is not None and result.get("success")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1].lower()
    target = sys.argv[2]

    # Determine what stages to run
    stages = []

    if command == "nav":
        stages = ["nav"]
    elif command == "urls":
        stages = ["urls"]
    elif command == "products":
        stages = ["products"]
    elif command == "nav+urls":
        stages = ["nav", "urls"]
    elif command == "urls+products":
        stages = ["urls", "products"]
    elif command == "all":
        stages = ["nav", "urls", "products"]
    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)

    # Extract domain from URL if needed
    if target.startswith("http"):
        url = target
        domain = get_domain(url).replace('.', '_')
    else:
        domain = target.replace('.', '_')
        url = None

    # Validate inputs
    if "nav" in stages and not url:
        print("Error: nav stage requires a URL")
        print("Usage: python pipeline.py nav <url>")
        sys.exit(1)

    print(f"\n{'#'*60}")
    print(f"# FASHION SCRAPING PIPELINE")
    print(f"# Stages: {' -> '.join(stages)}")
    print(f"# Target: {url or domain}")
    print(f"{'#'*60}\n")

    success = True

    # Run stages
    for stage in stages:
        if stage == "nav":
            success = run_nav(url)
        elif stage == "urls":
            success = run_urls(domain)
        elif stage == "products":
            success = run_products(domain)

        if not success:
            print(f"\nStage '{stage}' failed. Stopping pipeline.")
            sys.exit(1)

    print(f"\n{'#'*60}")
    print(f"# PIPELINE COMPLETE")
    print(f"# Output: backend/extractions/{domain}/")
    print(f"{'#'*60}\n")


if __name__ == "__main__":
    main()
