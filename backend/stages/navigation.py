"""
Stage 1: Navigation Extraction

Extracts the category tree from a website using both static and dynamic methods.
Picks the better result (more categories).
"""

import asyncio
import sys
import time
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent))  # stages/
sys.path.insert(0, str(Path(__file__).parent.parent / "scraper"))
sys.path.insert(0, str(Path(__file__).parent.parent / "scraper" / "navigation"))

from stages.storage import (
    get_domain, save_navigation, count_categories,
    load_brand_meta, save_brand_meta
)
from stages.metrics import update_stage_metrics, calculate_cost


def run_static_extractor(url: str) -> dict:
    """Run static extractor synchronously."""
    from static_extractor import extract_tree

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(extract_tree(url))
        loop.close()

        # Handle both old (tree, links) and new (tree, links, llm_usage) return formats
        if len(result) >= 3:
            tree, _, llm_usage = result
        else:
            tree, _ = result
            llm_usage = {"input_tokens": 0, "output_tokens": 0}

        if tree:
            return {
                "category_tree": tree,
                "category_count": count_tree(tree),
                "method": "static",
                "llm_usage": llm_usage
            }
    except Exception as e:
        print(f"Static extractor failed: {e}")

    return None


def convert_dynamic_to_standard(node: dict) -> list:
    """
    Convert dynamic tree format to standard format.

    Dynamic: {name, children, links} where links is [{name, url}, ...]
    Standard: [{name, url, children}, ...] where each node has a url
    """
    result = []

    # Convert links to leaf nodes
    for link in node.get("links", []):
        result.append({
            "name": link.get("name", "Unknown"),
            "url": link.get("url", ""),
            "children": []
        })

    # Recursively convert children
    for child in node.get("children", []):
        child_nodes = convert_dynamic_to_standard(child)
        child_name = child.get("name", "Unknown")

        # Find node's own URL from its links (link where name matches node name)
        child_url = None
        for link in child.get("links", []):
            if link.get("name", "").lower() == child_name.lower():
                child_url = link.get("url")
                break

        if child_nodes:
            # If child has multiple nodes, wrap them
            if len(child_nodes) == 1 and not child_nodes[0].get("children"):
                # Single leaf - add directly
                result.append(child_nodes[0])
            else:
                # Multiple nodes or has children - create category node
                result.append({
                    "name": child_name,
                    "url": child_url,  # Include node's own URL if available
                    "children": child_nodes
                })
        elif child.get("links"):
            # Child has links but no nested children
            result.append({
                "name": child_name,
                "url": child_url,  # Include node's own URL if available
                "children": convert_dynamic_to_standard(child)
            })

    return result


def run_dynamic_extractor(url: str) -> dict:
    """Run dynamic extractor synchronously."""
    from dynamic_explorer import explore
    from build_tree import build_tree, find_cross_toplevel_urls, dedupe_parent_child_links, hoist_common_links

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(explore(url))
        loop.close()

        # Handle both old (states) and new (states, llm_usage) return formats
        if isinstance(result, tuple):
            states, llm_usage = result
        else:
            states = result
            llm_usage = {"input_tokens": 0, "output_tokens": 0}

        if states:
            # Build tree from states
            base_url = states[0].get("url", url) if states else url
            cross_toplevel_urls = find_cross_toplevel_urls(states)
            tree = build_tree(states, base_url, filter_urls=cross_toplevel_urls)
            hoist_common_links(tree)
            dedupe_parent_child_links(tree)

            # Convert to standard format (dynamic has {name, children, links})
            # Standard is [{name, url, children}, ...]
            standard_tree = convert_dynamic_to_standard(tree)

            return {
                "category_tree": standard_tree,
                "category_count": count_tree(standard_tree),
                "method": "dynamic",
                "llm_usage": llm_usage
            }
    except Exception as e:
        print(f"Dynamic extractor failed: {e}")
        import traceback
        traceback.print_exc()

    return None


def count_tree(tree) -> int:
    """Count categories in tree."""
    if not tree:
        return 0

    count = 0

    def count_node(node):
        nonlocal count
        count += 1
        for child in node.get("children", []):
            count_node(child)

    if isinstance(tree, list):
        for node in tree:
            count_node(node)
    elif isinstance(tree, dict):
        count_node(tree)

    return count


def extract_navigation(url: str, timeout: int = 120, mode: str = "both") -> dict:
    """
    Extract navigation tree using static and/or dynamic methods.

    Args:
        url: Website URL
        timeout: Max time per extractor in seconds
        mode: "static", "dynamic", or "both" (default)

    Returns:
        Navigation tree dict with category_tree, category_count, method
    """
    domain = get_domain(url)
    clean_domain = domain.replace('.', '_')
    stage_start_time = time.time()

    # Check for cached brand metadata (only when mode is "both")
    cached_method = None
    brand_meta = None
    if mode == "both":
        brand_meta = load_brand_meta(clean_domain)
        if brand_meta and brand_meta.get("nav", {}).get("winning_method"):
            cached_method = brand_meta["nav"]["winning_method"]
            print(f"\n[CACHE] Found cached nav method: {cached_method}")

    print(f"\n{'='*60}")
    print(f"STAGE 1: NAVIGATION EXTRACTION")
    print(f"{'='*60}")
    print(f"URL: {url}")
    print(f"Domain: {domain}")
    print(f"Mode: {mode}" + (f" (cached: {cached_method})" if cached_method else ""))
    print(f"{'='*60}\n")

    static_result = None
    dynamic_result = None

    # Determine effective mode (use cache if available)
    effective_mode = mode
    if cached_method and mode == "both":
        effective_mode = cached_method
        print(f"Using cached method: {cached_method}")

    if effective_mode == "static":
        # Run only static extractor
        print("Running static extractor only...")
        try:
            static_result = run_static_extractor(url)
            if static_result:
                print(f"  Static: {static_result['category_count']} categories")
            else:
                print(f"  Static: failed")
        except Exception as e:
            print(f"  Static: error - {e}")

    elif effective_mode == "dynamic":
        # Run only dynamic extractor
        print("Running dynamic extractor only...")
        try:
            dynamic_result = run_dynamic_extractor(url)
            if dynamic_result:
                print(f"  Dynamic: {dynamic_result['category_count']} categories")
            else:
                print(f"  Dynamic: failed")
        except Exception as e:
            print(f"  Dynamic: error - {e}")

    else:
        # Run both extractors in parallel
        with ThreadPoolExecutor(max_workers=2) as executor:
            print("Running static and dynamic extractors in parallel...")

            static_future = executor.submit(run_static_extractor, url)
            dynamic_future = executor.submit(run_dynamic_extractor, url)

            # Get static result
            try:
                static_result = static_future.result(timeout=timeout)
                if static_result:
                    print(f"  Static: {static_result['category_count']} categories")
                else:
                    print(f"  Static: failed")
            except FuturesTimeoutError:
                print(f"  Static: timeout")
            except Exception as e:
                print(f"  Static: error - {e}")

            # Get dynamic result
            try:
                dynamic_result = dynamic_future.result(timeout=timeout)
                if dynamic_result:
                    print(f"  Dynamic: {dynamic_result['category_count']} categories")
                else:
                    print(f"  Dynamic: failed")
            except FuturesTimeoutError:
                print(f"  Dynamic: timeout")
            except Exception as e:
                print(f"  Dynamic: error - {e}")

    # Pick better result
    # Prefer static when it found results — its LLM pass with screenshot filters
    # out non-product links (e.g. social media, music, video) more reliably than
    # dynamic which just DFS-clicks everything.
    if static_result and dynamic_result:
        if static_result["category_count"] > 0:
            result = static_result
            print(f"\nUsing static result ({result['category_count']} categories) — LLM-curated")
        elif dynamic_result["category_count"] > 0:
            result = dynamic_result
            print(f"\nUsing dynamic result ({result['category_count']} categories) — static empty")
        else:
            result = static_result
            print(f"\nUsing static result (both empty)")
    elif static_result:
        result = static_result
        print(f"\nUsing static result" + (" (dynamic failed)" if mode == "both" else ""))
    elif dynamic_result:
        result = dynamic_result
        print(f"\nUsing dynamic result" + (" (static failed)" if mode == "both" else ""))
    else:
        print("\nExtraction failed!")
        return None

    # Save brand metadata for future runs (remember which method won)
    new_meta = {
        "nav": {
            "winning_method": result.get("method", "unknown"),
        },
        "last_updated": datetime.now().isoformat()
    }
    save_brand_meta(clean_domain, new_meta)
    print(f"\n[CACHE] Saved winning method: {result.get('method')}")

    # Save results
    json_path, txt_path = save_navigation(domain, result)

    # Calculate timing and LLM usage
    stage_duration = time.time() - stage_start_time
    llm_usage = result.get("llm_usage", {"input_tokens": 0, "output_tokens": 0})
    llm_cost = calculate_cost(llm_usage.get("input_tokens", 0), llm_usage.get("output_tokens", 0))

    # Build and save metrics
    stage_data = {
        "run_time": datetime.now(),
        "duration": stage_duration,
        "extra_fields": {
            "Method": result.get("method", "unknown"),
            "Categories": result.get("category_count", 0)
        },
        "operations": [
            {
                "name": "navigation_extraction",
                "calls": 1,  # Approximate - actual calls tracked internally
                "input_tokens": llm_usage.get("input_tokens", 0),
                "output_tokens": llm_usage.get("output_tokens", 0),
                "cost": llm_cost
            }
        ],
        "summary": {
            "calls": 1,
            "input_tokens": llm_usage.get("input_tokens", 0),
            "output_tokens": llm_usage.get("output_tokens", 0),
            "cost": llm_cost
        }
    }

    metrics_path = update_stage_metrics(domain, "stage_1", stage_data)

    print(f"\nSaved: {json_path}")
    print(f"Saved: {txt_path}")
    print(f"Duration: {stage_duration:.1f}s")
    print(f"LLM Cost: ${llm_cost:.4f} ({llm_usage.get('input_tokens', 0) + llm_usage.get('output_tokens', 0):,} tokens)")
    print(f"Metrics: {metrics_path}")

    return result


async def extract_navigation_async(url: str, timeout: int = 120, mode: str = "both") -> dict:
    """Async wrapper for extract_navigation."""
    import functools
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, functools.partial(extract_navigation, url, timeout, mode))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python navigation.py <url> [--static|--dynamic]")
        print("  --static   Run only static extractor")
        print("  --dynamic  Run only dynamic extractor")
        print("  (default)  Run both and pick better result")
        sys.exit(1)

    url = sys.argv[1]

    # Parse mode flag
    mode = "both"
    if "--static" in sys.argv:
        mode = "static"
    elif "--dynamic" in sys.argv:
        mode = "dynamic"

    result = extract_navigation(url, mode=mode)

    if result:
        print(f"\nSuccess: {result['category_count']} categories extracted")
    else:
        print("\nFailed to extract navigation")
        sys.exit(1)
