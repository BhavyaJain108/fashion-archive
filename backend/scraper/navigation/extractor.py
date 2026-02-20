"""
Unified navigation extractor.

Runs static and dynamic extractors in parallel, returns the tree with more links.
Converts output to scraper-compatible format.
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent.parent / 'config' / '.env')

# Add backend to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scraper.navigation.static_extractor import extract_tree as static_extract_tree
from scraper.navigation.step_explorer import explore as step_explore
from scraper.navigation.build_tree import strip_homepage_nodes, build_hierarchy_from_urls, dedupe_parent_child_links


# =============================================================================
# Tree link counting
# =============================================================================

def count_links_static(node: dict) -> int:
    """Count URLs in static extractor tree (url directly on each node)."""
    count = 1 if node.get("url") else 0
    for child in node.get("children", []):
        count += count_links_static(child)
    return count


def count_links_dynamic(node: dict) -> int:
    """Count URLs in dynamic extractor tree (links array on nodes)."""
    count = len(node.get("links", []))
    for child in node.get("children", []):
        count += count_links_dynamic(child)
    return count


def count_links(tree) -> int:
    """Count total URLs in a tree. Handles both static and dynamic formats."""
    if tree is None:
        return 0

    if isinstance(tree, list):
        # Static format - list of nodes with url field
        return sum(count_links_static(node) for node in tree)
    else:
        # Dynamic format - dict with root and links arrays
        return count_links_dynamic(tree)


# =============================================================================
# Format conversion
# =============================================================================

def convert_to_scraper_format(tree) -> dict:
    """
    Convert nav_v8 tree to scraper's expected format.

    Handles both:
    - Static: [{"name": "...", "url": "...", "children": [...]}] (list, URLs on nodes)
    - Dynamic: {"name": "root", "children": [...], "links": [...]} (dict with root)

    Returns:
    {
        "category_tree": [...],
        "excluded_count": 0
    }
    """

    def convert_static_node(node: dict) -> dict:
        """Convert static extractor node (has url on node itself)."""
        children = []
        for child in node.get("children", []):
            children.append(convert_static_node(child))

        return {
            "name": node["name"],
            "url": node.get("url"),
            "reasoning": "Extracted from navigation",
            "children": children if children else None
        }

    def convert_dynamic_node(node: dict) -> dict:
        """Convert dynamic extractor node (has links array)."""
        children = []

        # Process existing children first
        for child in node.get("children", []):
            children.append(convert_dynamic_node(child))

        # Build hierarchy from links based on URL structure
        # This handles flat mega-menus where all links appear at once
        # but have parent-child relationships in their URLs
        links = node.get("links", [])
        if links:
            hierarchical_links = build_hierarchy_from_urls(links)

            # Convert hierarchical links to children format
            def convert_link_node(link_node):
                link_children = [convert_link_node(c) for c in link_node.get("children", [])]
                return {
                    "name": link_node["name"],
                    "url": link_node["url"],
                    "reasoning": "Extracted from navigation",
                    "children": link_children if link_children else None
                }

            for link_node in hierarchical_links:
                children.append(convert_link_node(link_node))

        return {
            "name": node["name"],
            "url": None,  # Dynamic nodes don't have direct URLs
            "reasoning": "Category node",
            "children": children if children else None
        }

    # Detect format and convert
    if isinstance(tree, list):
        # Static extractor format - list of root nodes
        category_tree = [convert_static_node(node) for node in tree]
    else:
        # Dynamic extractor format - dict with "root" wrapper
        root_children = tree.get("children", [])
        category_tree = [convert_dynamic_node(child) for child in root_children]

    return {
        "category_tree": category_tree,
        "excluded_count": 0
    }


# =============================================================================
# Extraction runners
# =============================================================================

async def run_static(url: str) -> Optional[list]:
    """Run static extractor and return tree."""
    try:
        print(f"      [Static] Starting extraction for {url}")
        tree, _, _ = await static_extract_tree(url)
        print(f"      [Static] Completed - found {count_links(tree)} links")
        return tree
    except Exception as e:
        print(f"      [Static] Failed: {e}")
        return None


async def run_dynamic(url: str) -> Optional[dict]:
    """Run step explorer and return tree."""
    try:
        print(f"      [Dynamic] Starting step exploration for {url}")

        # Run step explorer
        tree, stats = await step_explore(url)

        if not tree:
            print(f"      [Dynamic] No tree captured")
            return None

        # Post-process: dedupe
        dedupe_parent_child_links(tree)

        link_count = count_links(tree)
        print(f"      [Dynamic] Completed - found {link_count} links")
        return tree

    except Exception as e:
        print(f"      [Dynamic] Failed: {e}")
        import traceback
        traceback.print_exc()
        return None


# =============================================================================
# Main entry point
# =============================================================================

async def extract_navigation_tree_async(url: str) -> dict:
    """
    Run static and dynamic extractors in parallel.
    Return the tree with more links.
    If one fails, use the other. If both fail, raise exception.

    Returns scraper-compatible format:
    {
        "category_tree": [...],
        "excluded_count": int
    }
    """
    print(f"\n      🔍 Navigation Discovery")
    print(f"      URL: {url}")
    print(f"      Running static and dynamic extractors in parallel...\n")

    # Run both in parallel
    static_task = asyncio.create_task(run_static(url))
    dynamic_task = asyncio.create_task(run_dynamic(url))

    static_result, dynamic_result = await asyncio.gather(
        static_task, dynamic_task, return_exceptions=True
    )

    # Handle failures gracefully - use whichever succeeds
    static_ok = not isinstance(static_result, Exception) and static_result is not None
    dynamic_ok = not isinstance(dynamic_result, Exception) and dynamic_result is not None

    if not static_ok and not dynamic_ok:
        raise Exception("Both static and dynamic navigation extraction failed")

    # Count links in successful trees
    static_count = count_links(static_result) if static_ok else 0
    dynamic_count = count_links(dynamic_result) if dynamic_ok else 0

    # Pick larger tree (or whichever succeeded)
    if static_count >= dynamic_count and static_ok:
        winner = static_result
        method = "static"
    else:
        winner = dynamic_result
        method = "dynamic"

    print(f"\n      ✅ Using {method} extractor (static: {static_count}, dynamic: {dynamic_count} links)")

    # Convert to scraper format
    result = convert_to_scraper_format(winner)

    # Strip any homepage links from final tree
    result["category_tree"] = strip_homepage_nodes(result["category_tree"], url)

    return result


def extract_navigation_tree(url: str) -> dict:
    """
    Synchronous wrapper for extract_navigation_tree_async.

    This is the main entry point for brand.py to call.
    """
    try:
        # Try to get running event loop
        loop = asyncio.get_running_loop()
        # If we're here, a loop is running - use thread executor
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, extract_navigation_tree_async(url))
            return future.result()
    except RuntimeError:
        # No event loop running, safe to use asyncio.run
        return asyncio.run(extract_navigation_tree_async(url))


# =============================================================================
# Output helpers
# =============================================================================

def tree_to_readable(nodes, indent=0) -> list:
    """Convert category_tree to readable text lines."""
    lines = []
    prefix = "  " * indent

    for node in (nodes or []):
        name = node.get("name", "Unknown")
        url = node.get("url")
        children = node.get("children")

        if url:
            lines.append(f"{prefix}🔗 {name} → {url}")
        else:
            lines.append(f"{prefix}📁 {name}")

        if children:
            lines.extend(tree_to_readable(children, indent + 1))

    return lines


def count_category_urls(nodes) -> int:
    """Count total URLs in category tree."""
    total = 0
    for node in (nodes or []):
        if node.get("url"):
            total += 1
        total += count_category_urls(node.get("children"))
    return total


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import json

    if len(sys.argv) < 2:
        print("Usage: python extractor.py <url>")
        sys.exit(1)

    url = sys.argv[1]

    try:
        result = extract_navigation_tree(url)

        # Extract domain for output folder
        domain = urlparse(url).netloc.replace('www.', '').replace('.', '_')
        output_dir = Path(__file__).parent / 'extractions' / domain
        output_dir.mkdir(parents=True, exist_ok=True)

        # Save JSON
        json_file = output_dir / 'navigation_tree.json'
        with open(json_file, 'w') as f:
            json.dump(result, f, indent=2)
        print(f"\n✅ Saved: {json_file}")

        # Save readable text
        readable_lines = tree_to_readable(result.get('category_tree', []))
        txt_file = output_dir / 'navigation_tree.txt'
        with open(txt_file, 'w') as f:
            f.write('\n'.join(readable_lines))
        print(f"✅ Saved: {txt_file}")

        # Summary
        url_count = count_category_urls(result.get('category_tree', []))
        print(f"📊 Total category URLs: {url_count}")

        # Print tree
        print(f"\n{'='*60}")
        print('\n'.join(readable_lines))

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
