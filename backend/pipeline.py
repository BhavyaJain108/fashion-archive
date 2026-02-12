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
    """Run Stage 3: Product extraction (from existing urls.json).

    Uses the same streaming infrastructure as urls+products (browser pool,
    rate limiter, dashboard) but loads URLs from urls.json instead of
    extracting them fresh.
    """
    from stages.streaming import StreamingOrchestrator
    from stages.storage import load_urls

    urls_tree = load_urls(domain)
    if not urls_tree:
        print(f"Failed to load urls.json for {domain}")
        return False

    print("\n" + "="*60)
    print("STAGE 3: PRODUCT EXTRACTION")
    print("="*60)
    orchestrator = StreamingOrchestrator(domain, urls_tree=urls_tree)
    result = orchestrator.run()

    return result.success


def run_urls_and_products(domain: str) -> bool:
    """Run Stages 2+3 with streaming: products extract as URLs are found.

    Requires nav.json to exist. Uses StreamingOrchestrator so product
    extraction starts immediately as URLs become available.
    """
    from stages.streaming import StreamingOrchestrator
    from stages.storage import load_navigation

    nav_tree = load_navigation(domain)
    if not nav_tree:
        print(f"Failed to load nav.json for {domain}")
        return False

    print("\n" + "="*60)
    print("STAGES 2+3: STREAMING URL & PRODUCT EXTRACTION")
    print("="*60)
    orchestrator = StreamingOrchestrator(domain, nav_tree=nav_tree)
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

    if command == "nav":
        stages = ["nav"]
    elif command == "urls":
        stages = ["urls"]
    elif command == "products":
        stages = ["products"]
    elif command == "nav+urls":
        stages = ["nav", "urls"]
    elif command == "urls+products":
        stages = ["urls+products"]  # Streaming
    elif command == "all":
        stages = ["nav", "urls+products"]  # Nav then streaming
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
        print("Error: 'nav' stage requires a URL")
        print("Usage: python pipeline.py <command> <url>")
        sys.exit(1)

    # Parse nav mode flag
    nav_mode = "both"
    if "--static" in sys.argv:
        nav_mode = "static"
    elif "--dynamic" in sys.argv:
        nav_mode = "dynamic"

    # Determine if streaming is involved
    uses_streaming = "urls+products" in stages

    print(f"\n{'#'*60}")
    print(f"# FASHION SCRAPING PIPELINE")
    if uses_streaming:
        stage_names = [s if s != "urls+products" else "urls+products (streaming)" for s in stages]
        print(f"# Stages: {' -> '.join(stage_names)}")
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
    for stage in stages:
        if stage == "nav":
            success = run_nav(url, mode=nav_mode)
        elif stage == "urls":
            success = run_urls(domain)
        elif stage == "products":
            success = run_products(domain)
        elif stage == "urls+products":
            # Streaming: products start extracting as URLs are found
            success = run_urls_and_products(domain)

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
