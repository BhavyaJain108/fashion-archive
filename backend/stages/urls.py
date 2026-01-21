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


def get_leaf_categories(tree: list, parent_path: str = "") -> List[Dict]:
    """Extract all leaf categories (no children) from tree.

    Returns list of dicts with name, url, path.
    """
    leaves = []

    for node in tree:
        name = node.get("name", "Unknown")
        url = node.get("url", "")
        children = node.get("children", [])

        current_path = f"{parent_path}/{name}" if parent_path else name

        if children:
            # Recurse into children
            leaves.extend(get_leaf_categories(children, current_path))
        else:
            # This is a leaf
            if url:
                leaves.append({
                    "name": name,
                    "url": url,
                    "path": current_path
                })

    return leaves


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
        else:
            new_node["children"] = []

        result.append(new_node)

    return result


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


def extract_urls(domain: str, max_workers: int = 8) -> dict:
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

    # Create Brand instance for shared state (load more detection, lineage caching)
    brand_instance = Brand(url=f"https://{domain}/")
    print(f"Brand instance created for: {domain}")

    # Get leaf categories
    tree = nav_tree.get("category_tree", [])
    leaves = get_leaf_categories(tree)
    print(f"Found {len(leaves)} leaf categories to process\n")

    # Reset and snapshot LLM usage before extraction
    LLMHandler.reset_usage()
    llm_snapshot_before = LLMHandler.get_snapshot()
    stage_start_time = time.time()

    # Extract URLs from each category (parallel)
    url_map: Dict[str, List[str]] = {}
    all_urls: Set[str] = set()
    results: List[Dict] = []  # Collect results for summary
    category_logs: Dict[str, str] = {}  # Collect logs per category
    category_metrics: List[Dict] = []  # Collect per-category metrics

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_leaf = {
            executor.submit(extract_urls_from_category, leaf["url"], leaf["name"], brand_instance): leaf
            for leaf in leaves
        }

        completed = 0
        for future in as_completed(future_to_leaf):
            leaf = future_to_leaf[future]
            completed += 1

            # Show progress counter (same line)
            print(f"\r  Extracting... {completed}/{len(leaves)}", end="", flush=True)

            try:
                result_data = future.result()
                urls = result_data["urls"]
                logs = result_data["logs"]
                extraction_time = result_data.get("extraction_time", 0.0)
                llm_usage = result_data.get("llm_usage", {})

                url_map[leaf["url"]] = urls
                all_urls.update(urls)
                results.append({"name": leaf["name"], "count": len(urls), "error": None})
                category_logs[leaf["name"]] = logs

                # Track per-category metrics
                category_metrics.append({
                    "name": leaf["name"],
                    "duration": extraction_time,
                    "products": len(urls),
                    "llm_calls": llm_usage.get("calls", 0),
                    "llm_cost": calculate_cost(
                        llm_usage.get("input_tokens", 0),
                        llm_usage.get("output_tokens", 0)
                    )
                })
            except Exception as e:
                url_map[leaf["url"]] = []
                results.append({"name": leaf["name"], "count": 0, "error": str(e)})
                category_logs[leaf["name"]] = f"Error: {e}"
                category_metrics.append({
                    "name": leaf["name"],
                    "duration": 0.0,
                    "products": 0,
                    "llm_calls": 0,
                    "llm_cost": 0.0
                })

    print()  # Newline after progress

    # Capture stage timing and LLM usage
    stage_duration = time.time() - stage_start_time
    llm_snapshot_after = LLMHandler.get_snapshot()

    # Save logs to files
    logs_dir = ensure_domain_dir(clean_domain) / "logs"
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
    print(f"\n  {'Category':<35} {'Products':>10}")
    print(f"  {'-'*35} {'-'*10}")
    for r in sorted(results, key=lambda x: -x["count"]):
        if r["error"]:
            print(f"  {r['name'][:35]:<35} {'ERROR':>10}")
        elif r["count"] > 0:
            print(f"  {r['name'][:35]:<35} {r['count']:>10}")

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
    print(f"Total products: {total_products}")
    print(f"Unique products: {unique_products}")
    print(f"Duration: {stage_duration:.1f}s")
    print(f"LLM Cost: ${llm_cost:.4f} ({llm_calls} calls, {llm_input_tokens + llm_output_tokens:,} tokens)")
    print(f"Saved: {json_path}")
    print(f"Saved: {txt_path}")
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
