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
  python pipeline.py nav <url>                    # Stage 1 (both extractors)
  python pipeline.py nav <url> --static           # Stage 1 (static only)
  python pipeline.py nav <url> --dynamic          # Stage 1 (dynamic only)
  python pipeline.py urls <domain>                # Stage 2 (requires nav.json)
  python pipeline.py products <domain>            # Stage 3 (requires urls.json)

  # Combined stages
  python pipeline.py nav+urls <url>               # Stages 1+2
  python pipeline.py urls+products <domain>       # Stages 2+3
  python pipeline.py all <url>                    # Full pipeline

Examples:
  python pipeline.py nav https://eckhauslatta.com
  python pipeline.py nav https://poolhousenewyork.com --dynamic
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

from stages.storage import get_domain, clean_previous_extraction
from stages.metrics import reset_all_tracking


def run_nav(url: str, mode: str = "both") -> bool:
    """Run Stage 1: Navigation extraction."""
    from stages.navigation import extract_navigation

    result = extract_navigation(url, mode=mode)
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


def run_streaming(url: str, nav_mode: str = "both") -> bool:
    """Run streaming pipeline: nav -> (urls + products in parallel).

    Products start extracting as soon as URLs become available,
    rather than waiting for all URL extraction to complete.
    """
    from stages.streaming import StreamingOrchestrator
    from stages.storage import load_navigation

    domain = get_domain(url).replace('.', '_')

    # Stage 1: Navigation (unchanged)
    print("\n" + "="*60)
    print("STAGE 1: NAVIGATION")
    print("="*60)
    if not run_nav(url, mode=nav_mode):
        print("Navigation extraction failed")
        return False

    # Load nav tree for streaming
    nav_tree = load_navigation(domain)
    if not nav_tree:
        print(f"Failed to load nav.json for {domain}")
        return False

    # Stage 2+3: Streaming URL -> Product extraction
    print("\n" + "="*60)
    print("STAGES 2+3: STREAMING URL & PRODUCT EXTRACTION")
    print("="*60)
    orchestrator = StreamingOrchestrator(domain, nav_tree)
    result = orchestrator.run()

    return result.success


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1].lower()
    target = sys.argv[2]

    # Determine what stages to run
    stages = []

    # Handle 'all' command specially (uses streaming)
    use_streaming = (command == "all")

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
        stages = ["streaming"]  # Special marker for streaming mode
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
    if ("nav" in stages or use_streaming) and not url:
        print("Error: This command requires a URL")
        print("Usage: python pipeline.py <command> <url>")
        sys.exit(1)

    # Parse nav mode flag
    nav_mode = "both"
    if "--static" in sys.argv:
        nav_mode = "static"
    elif "--dynamic" in sys.argv:
        nav_mode = "dynamic"

    print(f"\n{'#'*60}")
    print(f"# FASHION SCRAPING PIPELINE")
    if use_streaming:
        print(f"# Mode: STREAMING (nav -> urls+products parallel)")
    else:
        print(f"# Stages: {' -> '.join(stages)}")
    print(f"# Target: {url or domain}")
    if nav_mode != "both":
        print(f"# Nav Mode: {nav_mode}")
    print(f"{'#'*60}\n")

    # Reset all LLM tracking for this pipeline run
    reset_all_tracking()

    # Clean previous extraction artifacts to avoid stale data on rescrape
    clean_previous_extraction(domain, stages)

    success = True

    # Run stages
    if use_streaming:
        # Streaming mode: nav -> (urls + products in parallel)
        success = run_streaming(url, nav_mode)
        if not success:
            print(f"\nStreaming pipeline failed.")
            sys.exit(1)
    else:
        # Sequential mode for individual stages
        for stage in stages:
            if stage == "nav":
                success = run_nav(url, mode=nav_mode)
            elif stage == "urls":
                success = run_urls(domain)
            elif stage == "products":
                success = run_products(domain)

            if not success:
                print(f"\nStage '{stage}' failed. Stopping pipeline.")
                sys.exit(1)

    # Print pipeline summary with total costs
    from stages.metrics import load_metrics
    metrics = load_metrics(domain)
    if metrics:
        total_duration = 0
        total_cost = 0.0
        total_products = 0

        for stage_data in metrics.values():
            total_duration += stage_data.get("duration", 0)
            summary = stage_data.get("summary", {})
            total_cost += summary.get("cost", 0)
            total_products = max(total_products, stage_data.get("products", 0))

        print(f"\n{'#'*60}")
        print(f"# PIPELINE COMPLETE")
        print(f"# Output: backend/extractions/{domain}/")
        print(f"#")
        print(f"# Total Duration: {total_duration:.1f}s ({total_duration/60:.1f} min)")
        print(f"# Total LLM Cost: ${total_cost:.4f}")
        if total_products > 0:
            print(f"# Products: {total_products}")
            print(f"# Cost per Product: ${total_cost/total_products:.4f}")
        print(f"{'#'*60}\n")
    else:
        print(f"\n{'#'*60}")
        print(f"# PIPELINE COMPLETE")
        print(f"# Output: backend/extractions/{domain}/")
        print(f"{'#'*60}\n")


if __name__ == "__main__":
    main()
