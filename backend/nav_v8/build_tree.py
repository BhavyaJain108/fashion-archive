"""
Build navigation tree from exploration_states.json

Creates:
- navigation_tree.json: Hierarchical JSON structure
- navigation_tree.txt: Human-readable tree with full links
"""

import json
import sys
from pathlib import Path
from urllib.parse import urljoin
from collections import Counter


def find_repeated_urls(states: list, threshold: int = 3) -> set:
    """Find URLs appearing in threshold+ states - these are likely footer/promo."""
    url_count = Counter()
    for state in states:
        for url in state.get("new_links", {}).values():
            url_count[url] += 1
    return {url for url, count in url_count.items() if count >= threshold}


def build_tree(states: list, base_url: str, filter_urls: set = None) -> dict:
    """
    Build a hierarchical tree from exploration states.

    Each node has:
    - name: category name
    - children: list of child nodes
    - links: list of {name, url} dicts
    """
    if filter_urls is None:
        filter_urls = set()

    tree = {"name": "root", "children": [], "links": []}

    for state in states:
        path = state.get("path", [])
        links = state.get("new_links", {})

        # Navigate to the correct node, creating as needed
        node = tree
        for segment in path:
            # Find or create child
            child = None
            for c in node["children"]:
                if c["name"].lower() == segment.lower():
                    child = c
                    break
            if not child:
                child = {"name": segment, "children": [], "links": []}
                node["children"].append(child)
            node = child

        # Add links to this node (avoid duplicates, skip filtered URLs)
        existing_urls = {link["url"] for link in node["links"]}
        for name, url in links.items():
            # Skip repeated/common URLs
            if url in filter_urls:
                continue
            # Make URL absolute
            full_url = urljoin(base_url, url) if not url.startswith("http") else url
            if full_url in filter_urls:
                continue
            if full_url not in existing_urls:
                node["links"].append({"name": name, "url": full_url})
                existing_urls.add(full_url)

    return tree


def dedupe_parent_child_links(node: dict) -> None:
    """
    Deduplicate links between parent and children.

    Rules:
    - Link in parent + 2+ children → keep in parent only
    - Link in parent + 1 child only → keep in that child only
    """
    if not node["children"]:
        return

    # First recurse into children
    for child in node["children"]:
        dedupe_parent_child_links(child)

    # Get parent URLs
    parent_urls = {link["url"] for link in node["links"]}

    # Count which children have each URL
    url_to_children = {}  # url -> list of child nodes that have it
    for child in node["children"]:
        child_urls = {link["url"] for link in child["links"]}
        for url in child_urls:
            if url not in url_to_children:
                url_to_children[url] = []
            url_to_children[url].append(child)

    # Find URLs in both parent and children
    shared_urls = parent_urls & set(url_to_children.keys())

    for url in shared_urls:
        children_with_url = url_to_children[url]

        if len(children_with_url) >= 2:
            # URL in parent + 2+ children → keep in parent, remove from children
            for child in children_with_url:
                child["links"] = [l for l in child["links"] if l["url"] != url]
        else:
            # URL in parent + 1 child → keep in child, remove from parent
            node["links"] = [l for l in node["links"] if l["url"] != url]


def tree_to_txt(node: dict, indent: int = 0, lines: list = None) -> list:
    """Convert tree to readable text format."""
    if lines is None:
        lines = []

    prefix = "  " * indent

    # Print node name (skip root)
    if node["name"] != "root":
        lines.append(f"{prefix}📁 {node['name']}")
        prefix = "  " * (indent + 1)

    # Print links (name and URL on same line)
    for link in node["links"]:
        lines.append(f"{prefix}🔗 {link['name']} → {link['url']}")

    # Print children recursively
    for child in node["children"]:
        tree_to_txt(child, indent + 1 if node["name"] != "root" else 0, lines)

    return lines


def process_brand(brand_dir: Path):
    """Process a single brand's extraction data."""
    states_file = brand_dir / "exploration_states.json"

    if not states_file.exists():
        print(f"No exploration_states.json found in {brand_dir}")
        return

    print(f"Processing {brand_dir.name}...")

    # Load states
    with open(states_file) as f:
        states = json.load(f)

    if not states:
        print(f"  Empty states file")
        return

    # Get base URL from first state
    base_url = states[0].get("url", "")
    if not base_url:
        print(f"  No base URL found")
        return

    # Find repeated URLs to filter out (appear 3+ times)
    repeated_urls = find_repeated_urls(states, threshold=3)
    print(f"  Filtering {len(repeated_urls)} repeated URLs")

    # Build tree
    tree = build_tree(states, base_url, filter_urls=repeated_urls)

    # Deduplicate parent-child links
    dedupe_parent_child_links(tree)

    # Save JSON
    json_file = brand_dir / "navigation_tree.json"
    with open(json_file, "w") as f:
        json.dump(tree, f, indent=2)
    print(f"  Saved: {json_file.name}")

    # Save TXT
    txt_lines = tree_to_txt(tree)
    txt_file = brand_dir / "navigation_tree.txt"
    with open(txt_file, "w") as f:
        f.write("\n".join(txt_lines))
    print(f"  Saved: {txt_file.name}")

    # Stats
    def count_links(node):
        total = len(node["links"])
        for child in node["children"]:
            total += count_links(child)
        return total

    def count_categories(node):
        total = len(node["children"])
        for child in node["children"]:
            total += count_categories(child)
        return total

    print(f"  Categories: {count_categories(tree)}, Links: {count_links(tree)}")


def main():
    extractions_dir = Path(__file__).parent / "extractions"

    if len(sys.argv) > 1:
        # Process specific brand
        brand = sys.argv[1]
        brand_dir = extractions_dir / brand
        if brand_dir.exists():
            process_brand(brand_dir)
        else:
            print(f"Brand not found: {brand}")
            print(f"Available: {[d.name for d in extractions_dir.iterdir() if d.is_dir()]}")
    else:
        # Process all brands
        for brand_dir in sorted(extractions_dir.iterdir()):
            if brand_dir.is_dir():
                process_brand(brand_dir)


if __name__ == "__main__":
    main()
