"""
Stage 2: URL Extraction

Extracts product URLs from each category in the navigation tree.
Attaches URLs to tree nodes with counts.
"""

import sys
import io
import time
from pathlib import Path
from typing import Dict, List, Set, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent))  # stages/
sys.path.insert(0, str(Path(__file__).parent.parent / "scraper"))

from stages.storage import load_navigation, save_urls, get_domain, ensure_domain_dir
from llm_handler import LLMHandler
from stages.metrics import update_stage_metrics, calculate_cost
from brand import Brand


import re
from urllib.parse import urlparse, parse_qs


def _is_all_category(name: str) -> bool:
    """Check if category name is an 'all' type (View All, Shop All, etc.)."""
    # Match standalone word "all" (case insensitive)
    return bool(re.search(r'\ball\b', name, re.IGNORECASE))


def get_leaf_categories(tree: list, parent_path: str = "", _skipped: list = None) -> List[Dict]:
    """Extract all leaf categories (no children) from tree.

    Skips 'View All' type categories if they have at least 2 siblings,
    since they're aggregates of their sibling categories.

    Returns list of dicts with name, url, path.
    """
    # Track skipped categories at top level
    if _skipped is None:
        _skipped = []

    leaves = []

    # Count leaves at this level (for sibling detection)
    leaves_at_level = [n for n in tree if not n.get("children") and n.get("url")]

    for node in tree:
        name = node.get("name", "Unknown")
        url = node.get("url", "")
        children = node.get("children", [])

        current_path = f"{parent_path}/{name}" if parent_path else name

        if children:
            # Recurse into children
            leaves.extend(get_leaf_categories(children, current_path, _skipped))
        else:
            # This is a leaf
            if url:
                # Skip "all" categories if they have 2+ siblings (3+ leaves at this level)
                if _is_all_category(name) and len(leaves_at_level) >= 3:
                    _skipped.append({"name": name, "path": current_path})
                    continue
                leaves.append({
                    "name": name,
                    "url": url,
                    "path": current_path
                })

    return leaves


def get_leaf_categories_with_stats(tree: list) -> tuple:
    """Get leaf categories and stats about skipped 'all' categories.

    Returns (leaves, skipped_count, skipped_names).
    """
    skipped = []
    leaves = get_leaf_categories(tree, "", skipped)
    return leaves, len(skipped), [s["name"] for s in skipped]


def extract_urls_from_category(category_url: str, category_name: str, brand_instance=None) -> Dict:
    """Extract product URLs from a single category page.

    Returns dict with: urls, logs, extraction_time, llm_usage.
    """
    from url_extractor import extract_urls_from_category as extract_category

    # Use quiet=True to suppress console output during parallel extraction
    # Generate a simple log entry instead
    log_lines = []
    log_lines.append(f"Category: {category_name}")
    log_lines.append(f"URL: {category_url}")
    log_lines.append("=" * 60)

    try:
        result = extract_category(category_url, brand_instance=brand_instance, quiet=True)
        urls = [p.url for p in result.product_urls]
        extraction_time = result.extraction_time
        llm_usage = getattr(result, 'llm_usage', {"calls": 0, "input_tokens": 0, "output_tokens": 0})

        log_lines.append(f"Products found: {len(urls)}")
        log_lines.append(f"Extraction time: {result.extraction_time:.2f}s")

        # Scroll/extraction stats
        discovery = getattr(result, 'discovery_info', {})
        if discovery:
            log_lines.append("")
            log_lines.append("=" * 40)
            log_lines.append("SCROLL STATS")
            log_lines.append("=" * 40)
            log_lines.append(f"Initial links: {discovery.get('initial_load_count', 0)}")
            log_lines.append(f"After scrolling: {discovery.get('after_scroll_count', 0)}")
            log_lines.append(f"After load more: {discovery.get('after_load_more_count', 0)}")
            pagination = discovery.get('pagination_detected')
            if pagination:
                log_lines.append(f"Pagination element: {pagination.get('pagination_selector', 'none')}")
                if pagination.get('pagination_found'):
                    log_lines.append(f"Multi-page: {pagination.get('total_pages', 1)} pages detected")

        if result.llm_filtering_stats:
            stats = result.llm_filtering_stats
            log_lines.append("")
            log_lines.append("=" * 40)
            log_lines.append("CLASSIFICATION STATS")
            log_lines.append("=" * 40)
            log_lines.append(f"Total links found on page: {stats.get('total_links_found', 0)}")
            log_lines.append(f"Product links approved: {stats.get('product_links_approved', 0)}")
            log_lines.append(f"Links rejected: {stats.get('links_rejected', 0)}")
            log_lines.append(f"Pre-approved (from memory): {stats.get('pre_approved_count', 0)}")
            log_lines.append(f"Newly classified by LLM: {stats.get('newly_classified_count', 0)}")

            # Show approved lineages (DOM patterns that are products)
            approved_lineages = stats.get('lineages_approved', [])
            if approved_lineages:
                log_lines.append("")
                log_lines.append(f"APPROVED LINEAGES ({len(approved_lineages)}):")
                for lineage in approved_lineages:
                    log_lines.append(f"  ✓ {lineage}")

            # Show rejected lineages with their URLs
            rejected_by_lineage = stats.get('rejected_by_lineage', {})
            if rejected_by_lineage:
                log_lines.append("")
                log_lines.append(f"REJECTED LINEAGES ({len(rejected_by_lineage)}):")
                for lineage, rejected_links in rejected_by_lineage.items():
                    log_lines.append(f"")
                    log_lines.append(f"  ✗ LINEAGE: {lineage}")
                    log_lines.append(f"    URLs ({len(rejected_links)}):")
                    for link in rejected_links:
                        text = link.get('link_text', '')[:50]
                        text_display = f' "{text}"' if text else ''
                        log_lines.append(f"      - {link.get('url', '')}{text_display}")

        if result.errors:
            log_lines.append("")
            log_lines.append(f"ERRORS: {result.errors}")

        log_lines.append("")
        log_lines.append("=" * 40)
        log_lines.append("PRODUCT URLs")
        log_lines.append("=" * 40)
        for url in urls:
            log_lines.append(f"  - {url}")

        return {
            "urls": urls,
            "logs": "\n".join(log_lines),
            "extraction_time": extraction_time,
            "llm_usage": llm_usage
        }
    except Exception as e:
        import traceback
        log_lines.append(f"ERROR: {e}")
        log_lines.append(traceback.format_exc())
        return {
            "urls": [],
            "logs": "\n".join(log_lines),
            "extraction_time": 0.0,
            "llm_usage": {"calls": 0, "input_tokens": 0, "output_tokens": 0},
            "error": str(e)
        }


def attach_urls_to_tree(tree: list, url_map: Dict[str, List[str]]) -> list:
    """Attach product URLs to tree nodes.

    Args:
        tree: Navigation tree
        url_map: Dict mapping category URL to list of product URLs

    Returns:
        Tree with products and product_count added to each node
    """
    result = []

    for node in tree:
        new_node = {
            "name": node.get("name", "Unknown"),
            "url": node.get("url", ""),
        }

        # Get products for this category
        category_url = node.get("url", "")
        products = url_map.get(category_url, [])
        new_node["product_count"] = len(products)
        new_node["products"] = products

        # Recurse into children
        children = node.get("children", [])
        if children:
            new_node["children"] = attach_urls_to_tree(children, url_map)

            # Aggregate sibling products into "all" type categories that were skipped
            _aggregate_into_all_categories(new_node["children"])
        else:
            new_node["children"] = []

        result.append(new_node)

    return result


def _aggregate_into_all_categories(siblings: list):
    """Aggregate products from siblings into 'all' type categories with no products.

    Modifies siblings in place.
    """
    if len(siblings) < 3:
        # Need at least 3 siblings (all + 2 others) for aggregation to make sense
        return

    # Find "all" type categories with no products (they were skipped during extraction)
    all_categories = [s for s in siblings if _is_all_category(s["name"]) and not s["products"]]

    if not all_categories:
        return

    # Collect all products from non-"all" siblings
    aggregated = []
    seen = set()
    for sibling in siblings:
        if not _is_all_category(sibling["name"]):
            for url in sibling.get("products", []):
                if url not in seen:
                    seen.add(url)
                    aggregated.append(url)

    # Assign aggregated products to each "all" category
    for all_cat in all_categories:
        all_cat["products"] = aggregated
        all_cat["product_count"] = len(aggregated)


def filter_empty_categories(tree: list) -> tuple:
    """Remove categories with no products from tree.

    Returns:
        (filtered_tree, empty_categories) where empty_categories is a list
        of category names with no products
    """
    filtered = []
    empty = []

    for node in tree:
        name = node.get("name", "Unknown")
        url = node.get("url", "")
        products = node.get("products", [])
        children = node.get("children", [])

        # Recursively filter children
        if children:
            filtered_children, child_empty = filter_empty_categories(children)
            empty.extend(child_empty)
        else:
            filtered_children = []

        # Check if this node has products or has children with products
        has_products = len(products) > 0
        has_children_with_products = len(filtered_children) > 0

        if has_products or has_children_with_products:
            new_node = {
                "name": name,
                "url": url,
                "product_count": len(products),
                "products": products,
                "children": filtered_children
            }
            filtered.append(new_node)
        else:
            # Empty category - track it
            if url:  # Only track if it has a URL (actual category)
                empty.append({"name": name, "url": url})

    return filtered, empty


def clean_redundant_parent_urls(tree: list, parent_path: str = "") -> list:
    """Remove parent URLs that match child URLs (redundant).

    If a parent's URL is the same as one of its children's URLs,
    set the parent's URL to null - it's just a category container,
    the child will handle that URL.

    Returns list of removed parent names for logging.
    """
    removed = []

    for node in tree:
        name = node.get("name", "Unknown")
        url = node.get("url")
        children = node.get("children", [])
        current_path = f"{parent_path} > {name}" if parent_path else name

        if children:
            # Check if parent URL matches any child URL
            child_urls = {c.get("url") for c in children if c.get("url")}
            if url and url in child_urls:
                node["url"] = None
                removed.append(current_path)

            # Recurse into children
            child_removed = clean_redundant_parent_urls(children, current_path)
            removed.extend(child_removed)

    return removed


def dedupe_urls_by_path(urls: List[str]) -> Tuple[List[str], int, int]:
    """Deduplicate URLs by path, ignoring query parameters.

    Many sites show the same product with different query params (e.g., color variants).
    This function keeps only one URL per unique path, preferring URLs without query params.

    Args:
        urls: List of product URLs

    Returns:
        (deduped_urls, original_count, removed_count)
    """
    if not urls:
        return [], 0, 0

    original_count = len(urls)

    # Group URLs by path (scheme + netloc + path, ignoring query)
    path_to_urls: Dict[str, List[str]] = {}
    for url in urls:
        parsed = urlparse(url)
        # Normalize path key: scheme://netloc/path (no query, no fragment)
        path_key = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if path_key not in path_to_urls:
            path_to_urls[path_key] = []
        path_to_urls[path_key].append(url)

    # Pick the best URL for each path (prefer no query params)
    deduped = []
    for path_key, url_list in path_to_urls.items():
        # Sort: URLs without query params first, then by length (shorter = cleaner)
        url_list.sort(key=lambda u: (bool(urlparse(u).query), len(u)))
        deduped.append(url_list[0])

    removed_count = original_count - len(deduped)
    return deduped, original_count, removed_count


def extract_urls(domain: str, max_workers: int = 4) -> dict:
    """
    Extract product URLs from all categories.

    Loads nav.json, extracts URLs from each leaf category,
    attaches to tree, saves urls.json and urls.txt.

    Args:
        domain: Domain name (e.g., "eckhauslatta_com" or "eckhauslatta.com")
        max_workers: Parallel workers for extraction

    Returns:
        URLs tree dict
    """
    # Normalize domain
    domain = domain.replace('.', '_').replace('_com', '.com').replace('_', '.')
    if not '.' in domain:
        domain = domain.replace('_', '.') + '.com'

    clean_domain = domain.replace('.', '_')

    print(f"\n{'='*60}")
    print(f"STAGE 2: URL EXTRACTION")
    print(f"{'='*60}")
    print(f"Domain: {domain}")
    print(f"{'='*60}\n")

    # Load navigation tree
    nav_tree = load_navigation(clean_domain)
    if not nav_tree:
        print(f"Error: nav.json not found for {clean_domain}")
        print(f"Run stage 1 first: python pipeline.py nav <url>")
        return None

    # Clean redundant parent URLs (where parent URL = child URL)
    tree = nav_tree.get("category_tree", [])
    removed_parents = clean_redundant_parent_urls(tree)
    if removed_parents:
        print(f"Removed {len(removed_parents)} redundant parent URLs:")
        for path in removed_parents:
            print(f"  - {path}")
        print()

    # Create Brand instance for shared state (load more detection, lineage caching)
    brand_instance = Brand(url=f"https://{domain}/")
    print(f"Brand instance created for: {domain}")
    leaves, skipped_count, skipped_names = get_leaf_categories_with_stats(tree)

    unique_category_urls = len(set(leaf["url"] for leaf in leaves))

    # Build info message
    info_parts = []
    if unique_category_urls < len(leaves):
        info_parts.append(f"{len(leaves) - unique_category_urls} duplicate URLs")
    if skipped_count > 0:
        info_parts.append(f"{skipped_count} 'All' categories skipped")

    if info_parts:
        print(f"Found {len(leaves)} leaf categories ({', '.join(info_parts)})")
    else:
        print(f"Found {len(leaves)} leaf categories to process")
    print()

    # Reset and snapshot LLM usage before extraction
    LLMHandler.reset_usage()
    llm_snapshot_before = LLMHandler.get_snapshot()
    stage_start_time = time.time()

    # Extract URLs from each category (parallel)
    url_map: Dict[str, List[str]] = {}
    all_urls: Set[str] = set()
    all_raw_urls: List[str] = []  # All URLs before dedup (for full_urls.txt)
    results: List[Dict] = []  # Collect results for summary
    category_logs: Dict[str, str] = {}  # Collect logs per category
    category_metrics: List[Dict] = []  # Collect per-category metrics
    dedup_stats = {"total_raw": 0, "total_deduped": 0, "total_removed": 0}  # Track dedup

    # Track which category URLs we've already submitted (avoid extracting same URL twice)
    submitted_urls: Dict[str, any] = {}  # url -> future

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_leaf = {}
        for leaf in leaves:
            if leaf["url"] in submitted_urls:
                # Reuse the existing future for this URL
                future_to_leaf[submitted_urls[leaf["url"]]].append(leaf)
            else:
                # Submit new extraction task
                future = executor.submit(extract_urls_from_category, leaf["url"], leaf["name"], brand_instance)
                future_to_leaf[future] = [leaf]  # List to handle multiple leaves with same URL
                submitted_urls[leaf["url"]] = future

        completed = 0
        for future in as_completed(future_to_leaf):
            leaves_for_future = future_to_leaf[future]
            completed += len(leaves_for_future)

            # Show progress counter (same line)
            print(f"\r  Extracting... {completed}/{len(leaves)}", end="", flush=True)

            try:
                result_data = future.result()
                raw_urls = result_data["urls"]
                logs = result_data["logs"]
                extraction_time = result_data.get("extraction_time", 0.0)
                llm_usage = result_data.get("llm_usage", {})

                # Track raw URLs for full_urls.txt
                all_raw_urls.extend(raw_urls)

                # Dedupe URLs by path (removes color variants, etc.)
                urls, raw_count, removed_count = dedupe_urls_by_path(raw_urls)
                dedup_stats["total_raw"] += raw_count
                dedup_stats["total_deduped"] += len(urls)
                dedup_stats["total_removed"] += removed_count

                # Apply results to all leaves that share this URL
                for leaf in leaves_for_future:
                    url_map[leaf["url"]] = urls
                    all_urls.update(urls)
                    dedup_note = f" (deduped from {raw_count})" if removed_count > 0 else ""
                    results.append({"name": leaf["name"], "count": len(urls), "raw_count": raw_count, "error": None})
                    category_logs[leaf["name"]] = logs

                # Track metrics only once per actual extraction
                category_metrics.append({
                    "name": leaves_for_future[0]["name"],
                    "duration": extraction_time,
                    "products": len(urls),
                    "llm_calls": llm_usage.get("calls", 0),
                    "llm_cost": calculate_cost(
                        llm_usage.get("input_tokens", 0),
                        llm_usage.get("output_tokens", 0)
                    )
                })
            except Exception as e:
                for leaf in leaves_for_future:
                    url_map[leaf["url"]] = []
                    results.append({"name": leaf["name"], "count": 0, "error": str(e)})
                    category_logs[leaf["name"]] = f"Error: {e}"
                category_metrics.append({
                    "name": leaves_for_future[0]["name"],
                    "duration": 0.0,
                    "products": 0,
                    "llm_calls": 0,
                    "llm_cost": 0.0
                })

    print()  # Newline after progress

    # Capture stage timing and LLM usage
    stage_duration = time.time() - stage_start_time
    llm_snapshot_after = LLMHandler.get_snapshot()

    # Save full_urls.txt (all raw URLs before dedup)
    domain_dir = ensure_domain_dir(clean_domain)
    full_urls_path = domain_dir / "full_urls.txt"
    with open(full_urls_path, 'w') as f:
        for url in all_raw_urls:
            f.write(f"{url}\n")
    print(f"  Saved raw URLs: {full_urls_path}")

    # Dedup warning if >70% removed
    if dedup_stats["total_raw"] > 0:
        removal_pct = (dedup_stats["total_removed"] / dedup_stats["total_raw"]) * 100
        if removal_pct > 70:
            print(f"\n  ⚠️  WARNING: {removal_pct:.1f}% of URLs removed by dedup ({dedup_stats['total_removed']}/{dedup_stats['total_raw']})")
            print(f"     This may indicate an issue with URL structure or excessive variants.")

    # Save logs to files
    logs_dir = domain_dir / "logs"
    logs_dir.mkdir(exist_ok=True)

    # Save individual category logs
    for cat_name, logs in category_logs.items():
        safe_name = cat_name.lower().replace(" ", "-").replace("/", "-")
        safe_name = ''.join(c for c in safe_name if c.isalnum() or c == '-')
        log_file = logs_dir / f"{safe_name}.log"
        with open(log_file, 'w') as f:
            f.write(f"Category: {cat_name}\n")
            f.write(f"Time: {datetime.now().isoformat()}\n")
            f.write("=" * 60 + "\n\n")
            f.write(logs)

    # Save combined log
    combined_log = logs_dir / "extraction.log"
    with open(combined_log, 'w') as f:
        f.write(f"URL Extraction Log\n")
        f.write(f"Domain: {domain}\n")
        f.write(f"Time: {datetime.now().isoformat()}\n")
        f.write(f"Categories: {len(leaves)}\n")
        f.write("=" * 60 + "\n\n")

        for r in sorted(results, key=lambda x: -x["count"]):
            f.write(f"\n{'='*60}\n")
            f.write(f"CATEGORY: {r['name']}\n")
            f.write(f"Products: {r['count']}\n")
            f.write(f"{'='*60}\n\n")
            f.write(category_logs.get(r["name"], "No logs"))
            f.write("\n")

    print(f"  Logs saved to: {logs_dir}/")

    # Print summary table
    print(f"\n  {'Category':<35} {'Products':>10} {'Raw':>8}")
    print(f"  {'-'*35} {'-'*10} {'-'*8}")
    for r in sorted(results, key=lambda x: -x["count"]):
        if r["error"]:
            print(f"  {r['name'][:35]:<35} {'ERROR':>10} {'-':>8}")
        elif r["count"] > 0:
            raw_count = r.get("raw_count", r["count"])
            dedup_marker = "*" if raw_count > r["count"] else ""
            print(f"  {r['name'][:35]:<35} {r['count']:>10}{dedup_marker} {raw_count:>8}")

    # Show empty categories count
    empty_count = sum(1 for r in results if r["count"] == 0 and not r["error"])
    if empty_count:
        print(f"  {f'({empty_count} categories with 0 products)':<35}")

    # Attach URLs to tree
    urls_tree = attach_urls_to_tree(tree, url_map)

    # Filter out empty categories and track them separately
    urls_tree, empty_categories = filter_empty_categories(urls_tree)

    # Calculate totals
    total_products = sum(len(urls) for urls in url_map.values())
    unique_products = len(all_urls)

    result = {
        "category_tree": urls_tree,
        "total_products": total_products,
        "unique_products": unique_products,
        "empty_categories": empty_categories
    }

    # Save results
    json_path, txt_path = save_urls(clean_domain, result)

    # Calculate LLM usage delta
    llm_input_tokens = llm_snapshot_after["input_tokens"] - llm_snapshot_before["input_tokens"]
    llm_output_tokens = llm_snapshot_after["output_tokens"] - llm_snapshot_before["output_tokens"]
    llm_calls = llm_snapshot_after["call_count"] - llm_snapshot_before["call_count"]
    llm_cost = calculate_cost(llm_input_tokens, llm_output_tokens)

    # Build and save metrics
    stage_data = {
        "run_time": datetime.now(),
        "duration": stage_duration,
        "extra_fields": {
            "Categories": len(leaves),
            "Unique Products": unique_products
        },
        "operations": [
            {
                "name": "url_extraction",
                "calls": llm_calls,
                "input_tokens": llm_input_tokens,
                "output_tokens": llm_output_tokens,
                "cost": llm_cost
            }
        ],
        "categories": sorted(category_metrics, key=lambda x: -x["products"]),
        "summary": {
            "calls": llm_calls,
            "input_tokens": llm_input_tokens,
            "output_tokens": llm_output_tokens,
            "cost": llm_cost
        },
        "products": unique_products
    }

    metrics_path = update_stage_metrics(clean_domain, "stage_2", stage_data)

    print(f"\n{'='*60}")
    print(f"URL EXTRACTION COMPLETE")
    print(f"{'='*60}")
    print(f"Raw URLs: {dedup_stats['total_raw']}")
    print(f"After dedup: {dedup_stats['total_deduped']} ({dedup_stats['total_removed']} removed)")
    print(f"Unique products: {unique_products}")
    print(f"Duration: {stage_duration:.1f}s")
    print(f"LLM Cost: ${llm_cost:.4f} ({llm_calls} calls, {llm_input_tokens + llm_output_tokens:,} tokens)")
    print(f"Saved: {json_path}")
    print(f"Saved: {txt_path}")
    print(f"Saved: {full_urls_path}")
    print(f"Metrics: {metrics_path}")
    print(f"{'='*60}\n")

    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python urls.py <domain>")
        print("Example: python urls.py eckhauslatta_com")
        sys.exit(1)

    domain = sys.argv[1]
    result = extract_urls(domain)

    if result:
        print(f"Success: {result['unique_products']} unique products found")
    else:
        print("Failed to extract URLs")
        sys.exit(1)
