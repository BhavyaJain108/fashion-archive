"""
Comprehensive brand discovery and verification test.

Runs discovery on all brands, shows full product details,
then verifies with remaining URLs to demonstrate speedup.

Usage:
    python test_discovery.py
    python test_discovery.py --brand "Alexander McQueen"  # Single brand
"""

import asyncio
import json
import time
import argparse
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional
from collections import defaultdict

from tabulate import tabulate

# Add paths for imports (must match what strategies use)
sys.path.insert(0, str(Path(__file__).parent))  # prod_page_v2
sys.path.insert(0, str(Path(__file__).parent.parent))  # backend
sys.path.insert(0, str(Path(__file__).parent.parent.parent))  # project root (for backend.scraper.*)

from extractor import ProductExtractor, MultiStrategyConfig, StrategyContribution
from models import Product, ExtractionResult, ExtractionStrategy

# Import LLMHandler for cost tracking (MUST use same path as strategies to share class-level counters)
try:
    from backend.scraper.llm_handler import LLMHandler
    HAS_LLM_TRACKING = True
    print(f"  [DEBUG] LLMHandler imported from backend.scraper.llm_handler")
except ImportError as e:
    print(f"  [DEBUG] Failed to import from backend.scraper: {e}")
    try:
        from scraper.llm_handler import LLMHandler
        HAS_LLM_TRACKING = True
        print(f"  [DEBUG] LLMHandler imported from scraper.llm_handler (WARNING: may not share counters)")
    except ImportError:
        HAS_LLM_TRACKING = False
        LLMHandler = None
        print(f"  [DEBUG] LLMHandler not available")


def section(title: str):
    """Print a major section header."""
    print(f"\n{'='*80}")
    print(f" {title}")
    print('='*80)


def subsection(title: str):
    """Print a subsection header."""
    print(f"\n{'-'*80}")
    print(f" {title}")
    print('-'*80)


def print_product_full(product: Product, indent: str = "  "):
    """Print ALL product data without any truncation."""
    print(f"{indent}Name: {product.name}")
    print(f"{indent}Price: {product.price} {product.currency}")
    print(f"{indent}Brand: {product.brand or 'N/A'}")
    print(f"{indent}SKU: {product.sku or 'N/A'}")
    print(f"{indent}Category: {product.category or 'N/A'}")
    print(f"{indent}Completeness Score: {product.completeness_score()}/100")

    if product.missing_fields.any_missing():
        print(f"{indent}Missing Fields: {product.missing_fields.to_list()}")

    print(f"\n{indent}Description:")
    if product.description:
        # Print full description, wrapped for readability
        desc_lines = product.description.split('\n')
        for line in desc_lines:
            print(f"{indent}  {line}")
    else:
        print(f"{indent}  N/A")

    print(f"\n{indent}Images ({len(product.images)}):")
    for i, img in enumerate(product.images, 1):
        print(f"{indent}  {i}. {img}")

    print(f"\n{indent}Variants ({len(product.variants)}):")
    if product.variants:
        for v in product.variants:
            parts = []
            if v.size:
                parts.append(f"Size: {v.size}")
            if v.color:
                parts.append(f"Color: {v.color}")
            if v.sku:
                parts.append(f"SKU: {v.sku}")
            if v.price is not None:
                parts.append(f"Price: {v.price}")
            if v.available is not None:
                parts.append(f"Available: {v.available}")
            if v.stock_count is not None:
                parts.append(f"Stock: {v.stock_count}")
            print(f"{indent}  • {', '.join(parts)}")
    else:
        print(f"{indent}  No variants found")


def print_contributions(contributions: List[StrategyContribution], indent: str = "  "):
    """Print strategy contributions."""
    print(f"\n{indent}Strategy Contributions:")
    for c in contributions:
        fields_str = ', '.join(sorted(c.fields)) if c.fields else 'none'
        print(f"{indent}  • {c.strategy.value} (score: {c.score}): {fields_str}")


def load_test_products() -> List[Dict[str, Any]]:
    """Load test products from JSON file."""
    path = Path(__file__).parent / "test_products.json"
    with open(path) as f:
        data = json.load(f)
    return data["brands"]


async def run_discovery_phase(
    extractor: ProductExtractor,
    brands: List[Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    """
    Phase 1: Run discovery on first URL for each brand.

    Returns dict mapping brand name to discovery results.
    """
    section("PHASE 1: DISCOVERY (Finding extraction patterns)")

    results = {}

    for brand_data in brands:
        brand_name = brand_data["name"]
        domain = brand_data["domain"]
        first_url = brand_data["products"][0]["url"]

        subsection(brand_name.upper())
        print(f"  Domain: {domain}")
        print(f"  URL: {first_url}")

        # Reset LLM usage tracking before this URL
        if HAS_LLM_TRACKING:
            LLMHandler.reset_usage()

        # Time the discovery
        start_time = time.perf_counter()
        contributions, extraction_results = await extractor.discover(first_url)
        discovery_time = time.perf_counter() - start_time

        # Get LLM usage for this URL
        llm_usage = None
        if HAS_LLM_TRACKING:
            llm_usage = LLMHandler.get_total_usage()

        print(f"\n  Time: {discovery_time:.2f}s")
        if llm_usage and llm_usage['call_count'] > 0:
            print(f"  LLM Calls: {llm_usage['call_count']}, Tokens: {llm_usage['total_tokens']:,}, Cost: ${llm_usage['estimated_cost_usd']:.4f}")

        # Get the primary strategy (highest score)
        primary_strategy = None
        if contributions:
            primary_strategy = contributions[0].strategy
            print(f"  Primary Method: {primary_strategy.value}")
        else:
            print("  Primary Method: NONE (all strategies failed)")

        # Merge results to get final product
        merged_product = extractor._merge_products(extraction_results, first_url)

        print("\n  PRODUCT DATA:")
        if merged_product.name:
            print_product_full(merged_product, indent="    ")
            print_contributions(contributions, indent="    ")
        else:
            print("    Failed to extract product data")

        # Store results for later phases
        results[brand_name] = {
            "domain": domain,
            "discovery_time": discovery_time,
            "contributions": contributions,
            "extraction_results": extraction_results,
            "merged_product": merged_product,
            "primary_strategy": primary_strategy,
            "urls": [p["url"] for p in brand_data["products"]],
            "llm_usage": llm_usage,
        }

        # Save config for verification phase - use MINIMAL strategy set
        if contributions:
            # Compute minimal set (skip redundant strategies)
            minimal_contributions = extractor._compute_minimal_strategies(contributions)

            config = MultiStrategyConfig(
                domain=domain,
                contributions=minimal_contributions,
                verified=True,  # Mark as verified so extract_single uses only active strategies
                discovery_url=first_url,
            )
            extractor._save_config(config)

    return results


async def run_verification_phase(
    extractor: ProductExtractor,
    discovery_results: Dict[str, Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    """
    Phase 2: Verify discovered patterns on remaining URLs.

    Shows timing improvement when using saved config.
    """
    section("PHASE 2: VERIFICATION (Testing with saved patterns)")

    verification_results = {}

    for brand_name, discovery in discovery_results.items():
        domain = discovery["domain"]
        urls = discovery["urls"]
        discovery_time = discovery["discovery_time"]

        if len(urls) < 2:
            print(f"\n  {brand_name}: Only 1 URL, skipping verification")
            continue

        subsection(f"{brand_name.upper()} - Verification")

        # Load the saved config
        config = extractor._load_config(domain)

        if not config:
            print(f"  No config found for {domain}, skipping")
            continue

        # Show which strategies will be used
        active_strategies = config.get_active_strategies()
        print(f"  Using {len(active_strategies)} active strategies: {', '.join(s.value for s in active_strategies)}")
        print(f"  (Discovery ran all 7 strategies)")

        verification_times = []
        verification_products = []
        verification_costs = []

        # Test on URLs 2 and 3
        for i, url in enumerate(urls[1:], start=2):
            print(f"\n  --- URL {i} ---")
            print(f"  URL: {url}")

            # Reset LLM usage tracking before this URL
            if HAS_LLM_TRACKING:
                LLMHandler.reset_usage()

            start_time = time.perf_counter()
            result = await extractor.extract_single(url, config)
            verify_time = time.perf_counter() - start_time

            # Get LLM usage for this URL
            url_llm_usage = None
            if HAS_LLM_TRACKING:
                url_llm_usage = LLMHandler.get_total_usage()

            verification_times.append(verify_time)
            verification_costs.append(url_llm_usage)

            speedup = discovery_time / verify_time if verify_time > 0 else 0
            print(f"  Time: {verify_time:.2f}s (Discovery was {discovery_time:.2f}s → {speedup:.1f}x faster)")
            if url_llm_usage and url_llm_usage['call_count'] > 0:
                print(f"  LLM Calls: {url_llm_usage['call_count']}, Tokens: {url_llm_usage['total_tokens']:,}, Cost: ${url_llm_usage['estimated_cost_usd']:.4f}")

            print("\n  PRODUCT DATA:")
            if result.success and result.product:
                print_product_full(result.product, indent="    ")
                verification_products.append(result.product)
            else:
                print(f"    Failed: {result.error}")
                verification_products.append(None)

        verification_results[brand_name] = {
            "times": verification_times,
            "products": verification_products,
            "discovery_time": discovery_time,
            "avg_verification_time": sum(verification_times) / len(verification_times) if verification_times else 0,
            "llm_costs": verification_costs,
        }

    return verification_results


def print_summary(
    discovery_results: Dict[str, Dict[str, Any]],
    verification_results: Dict[str, Dict[str, Any]]
):
    """Phase 3: Print summary statistics."""
    section("PHASE 3: SUMMARY")

    # Timing summary
    print("\n  TIMING SUMMARY:")
    discovery_times = [d["discovery_time"] for d in discovery_results.values()]
    verification_times = []
    for v in verification_results.values():
        verification_times.extend(v["times"])

    avg_discovery = sum(discovery_times) / len(discovery_times) if discovery_times else 0
    avg_verification = sum(verification_times) / len(verification_times) if verification_times else 0
    avg_speedup = avg_discovery / avg_verification if avg_verification > 0 else 0

    print(f"    Discovery average:     {avg_discovery:.2f}s (runs all 7 strategies)")
    print(f"    Verification average:  {avg_verification:.2f}s (runs only active strategies)")
    print(f"    Average speedup:       {avg_speedup:.1f}x")

    # Group brands by primary strategy
    print("\n  BRANDS BY PRIMARY STRATEGY:")
    strategy_brands = defaultdict(list)
    for brand_name, data in discovery_results.items():
        strategy = data["primary_strategy"]
        if strategy:
            strategy_brands[strategy.value].append(brand_name)
        else:
            strategy_brands["failed"].append(brand_name)

    for strategy, brands in sorted(strategy_brands.items()):
        print(f"\n    {strategy} ({len(brands)} brands):")
        for brand in brands:
            print(f"      • {brand}")

    # Completeness scores
    print("\n  EXTRACTION COMPLETENESS:")
    completeness_rows = []
    for brand_name, data in discovery_results.items():
        product = data["merged_product"]
        score = product.completeness_score() if product.name else 0
        missing = product.missing_fields.to_list() if product.name else ["all"]
        missing_str = ', '.join(missing) if missing else '-'
        completeness_rows.append([brand_name, score, missing_str])

    print(tabulate(completeness_rows, headers=["Brand", "Score", "Missing Fields"], tablefmt="simple_outline"))

    # Cost & Latency summary table
    print("\n  COST & LATENCY SUMMARY:")

    total_cost = 0.0
    total_tokens = 0
    cost_rows = []

    for brand_name, data in discovery_results.items():
        # Discovery time and cost
        d_time = data.get("discovery_time", 0)
        d_usage = data.get("llm_usage")
        d_cost = d_usage['estimated_cost_usd'] if d_usage and d_usage['call_count'] > 0 else 0.0
        d_tokens = d_usage['total_tokens'] if d_usage else 0
        d_cost_str = f"${d_cost:.4f}" if d_cost > 0 else "-"

        # Verification times and costs
        v_data = verification_results.get(brand_name, {})
        v_times = v_data.get("times", [])
        v_costs = v_data.get("llm_costs", [])

        url2_time_str = f"{v_times[0]:.1f}s" if len(v_times) >= 1 else "N/A"
        url3_time_str = f"{v_times[1]:.1f}s" if len(v_times) >= 2 else "N/A"

        url2_cost = 0.0
        url3_cost = 0.0
        url2_cost_str = "-"
        url3_cost_str = "-"

        if len(v_costs) >= 1 and v_costs[0] and v_costs[0]['call_count'] > 0:
            url2_cost = v_costs[0]['estimated_cost_usd']
            url2_cost_str = f"${url2_cost:.4f}"
            total_tokens += v_costs[0]['total_tokens']

        if len(v_costs) >= 2 and v_costs[1] and v_costs[1]['call_count'] > 0:
            url3_cost = v_costs[1]['estimated_cost_usd']
            url3_cost_str = f"${url3_cost:.4f}"
            total_tokens += v_costs[1]['total_tokens']

        brand_total = d_cost + url2_cost + url3_cost
        total_cost += brand_total
        total_tokens += d_tokens

        cost_rows.append([
            brand_name,
            f"{d_time:.1f}s",
            d_cost_str,
            url2_time_str,
            url2_cost_str,
            url3_time_str,
            url3_cost_str,
            f"${brand_total:.4f}"
        ])

    # Add total row
    cost_rows.append(["TOTAL", "", "", "", "", "", "", f"${total_cost:.4f}"])

    headers = ["Brand", "URL1 Time", "URL1 Cost", "URL2 Time", "URL2 Cost", "URL3 Time", "URL3 Cost", "Total"]
    print(tabulate(cost_rows, headers=headers, tablefmt="simple_outline"))
    print(f"\n  Total LLM tokens used: {total_tokens:,}")


async def main(brand_filter: Optional[str] = None):
    """Main test runner."""
    print("\n" + "="*80)
    print(" PRODUCT EXTRACTION - DISCOVERY & VERIFICATION TEST")
    print("="*80)

    # Load test products
    brands = load_test_products()

    # Filter if requested
    if brand_filter:
        brands = [b for b in brands if b["name"].lower() == brand_filter.lower()]
        if not brands:
            print(f"\nBrand '{brand_filter}' not found in test_products.json")
            return

    print(f"\nTesting {len(brands)} brand(s): {', '.join(b['name'] for b in brands)}")

    extractor = ProductExtractor()

    # Phase 1: Discovery
    discovery_results = await run_discovery_phase(extractor, brands)

    # Phase 2: Verification
    verification_results = await run_verification_phase(extractor, discovery_results)

    # Phase 3: Summary
    print_summary(discovery_results, verification_results)

    print("\n" + "="*80)
    print(" TEST COMPLETE")
    print("="*80 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run discovery and verification test")
    parser.add_argument("--brand", type=str, help="Test only a specific brand")
    args = parser.parse_args()

    asyncio.run(main(brand_filter=args.brand))
