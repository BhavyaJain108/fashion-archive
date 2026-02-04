"""
Build navigation tree from exploration_states.json

Creates:
- navigation_tree.json: Hierarchical JSON structure
- navigation_tree.txt: Human-readable tree with full links
"""

import json
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse


def find_cross_toplevel_urls(states: list) -> set:
    """Find URLs appearing across 2+ different top-level tabs - these are utility links."""
    # Group URLs by their top-level category
    url_to_toplevels = {}  # url -> set of top-level names
    for state in states:
        path = state.get("path", [])
        if not path:
            continue
        top_level = path[0]
        for url in state.get("new_links", {}).values():
            if url not in url_to_toplevels:
                url_to_toplevels[url] = set()
            url_to_toplevels[url].add(top_level)

    # Return URLs that appear in 2+ top-level tabs
    return {url for url, toplevels in url_to_toplevels.items() if len(toplevels) >= 2}


def is_homepage_url(url: str, base_url: str) -> bool:
    """Check if URL points to the homepage (root path of the site)."""
    # Handle relative URLs
    abs_url = urljoin(base_url, url) if not url.startswith("http") else url
    parsed = urlparse(abs_url)
    parsed_base = urlparse(base_url)
    # Same domain and root path (/ or empty)
    return parsed.netloc == parsed_base.netloc and parsed.path.rstrip("/") == ""


def is_product_link(url: str) -> bool:
    """Check if URL is a product page (not a category/collection)."""
    product_patterns = ['/product/', '/products/', '/p/', '/item/']
    return any(p in url.lower() for p in product_patterns)


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
        folder_name = path[-1].lower() if path else None

        for name, url in links.items():
            # If this link has the folder's name, always add it (for folder's own URL)
            is_folder_link = folder_name and name.lower() == folder_name

            # Skip repeated/common URLs (but NOT if it's the folder's own link)
            if not is_folder_link:
                if url in filter_urls:
                    continue
            # Make URL absolute
            full_url = urljoin(base_url, url) if not url.startswith("http") else url
            # Always skip homepage links
            if is_homepage_url(full_url, base_url):
                continue
            if not is_folder_link:
                if full_url in filter_urls:
                    continue
                # Skip product links (individual items, not categories)
                if is_product_link(full_url):
                    continue

            if full_url not in existing_urls:
                node["links"].append({"name": name, "url": full_url})
                existing_urls.add(full_url)
            elif is_folder_link:
                # Folder's own URL - add even if URL exists with different name
                # (ensures we can show the folder's URL in the tree)
                node["links"].append({"name": name, "url": full_url})

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


def hoist_common_links(node: dict) -> None:
    """
    Hoist links that appear in 2+ children up to the parent.

    If a link appears in multiple children but NOT in parent,
    move it to parent and remove from children.
    """
    if not node["children"]:
        return

    # First recurse into children (bottom-up)
    for child in node["children"]:
        hoist_common_links(child)

    # Get parent URLs
    parent_urls = {link["url"] for link in node["links"]}

    # Count which children have each URL, track the link info
    url_to_children = {}  # url -> list of child nodes
    url_to_link = {}  # url -> link dict (name, url)
    for child in node["children"]:
        for link in child["links"]:
            url = link["url"]
            if url not in url_to_children:
                url_to_children[url] = []
                url_to_link[url] = link
            url_to_children[url].append(child)

    # Find URLs in 2+ children but NOT in parent → hoist them
    for url, children_with_url in url_to_children.items():
        if len(children_with_url) >= 2 and url not in parent_urls:
            # Hoist to parent
            node["links"].append(url_to_link[url])
            # Remove from children
            for child in children_with_url:
                child["links"] = [l for l in child["links"] if l["url"] != url]


def strip_homepage_nodes(category_tree: list, base_url: str) -> list:
    """
    Remove nodes whose URL is the homepage from a standard category tree.
    Works on [{name, url, children}, ...] format (both static and dynamic origins).

    Exception: if the homepage node is the ONLY top-level node in the entire tree,
    keep it (the site has no real nav, homepage is all we found).
    """
    def _strip(nodes: list) -> list:
        filtered = []
        for node in (nodes or []):
            url = node.get("url")
            if url and is_homepage_url(url, base_url):
                continue
            children = node.get("children")
            if children:
                node["children"] = _strip(children) or None
            filtered.append(node)
        return filtered

    # If the tree has only one top-level node and it's the homepage, keep it
    if len(category_tree or []) == 1:
        only = category_tree[0]
        if only.get("url") and is_homepage_url(only["url"], base_url):
            return category_tree

    return _strip(category_tree)


def tree_to_txt(node: dict, indent: int = 0, lines: list = None) -> list:
    """Convert tree to readable text format."""
    if lines is None:
        lines = []

    prefix = "  " * indent
    own_url = None

    # Print node name (skip root)
    if node["name"] != "root":
        # Check if node has its own URL (link with same name as folder)
        for link in node["links"]:
            if link["name"].lower() == node["name"].lower():
                own_url = link["url"]
                break

        if own_url:
            lines.append(f"{prefix}📁 {node['name']} → {own_url}")
        else:
            lines.append(f"{prefix}📁 {node['name']}")
        prefix = "  " * (indent + 1)

    # Print links (name and URL on same line), skip folder's own link
    for link in node["links"]:
        # Skip if this link has the same name as the folder (already shown above)
        if node["name"] != "root" and link["name"].lower() == node["name"].lower():
            continue
        # Skip if this link has the same URL as the folder's own URL (duplicate)
        if own_url and link["url"] == own_url:
            continue
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

    # Find URLs that appear across 2+ top-level tabs (utility links to remove)
    cross_toplevel_urls = find_cross_toplevel_urls(states)
    print(f"  Filtering {len(cross_toplevel_urls)} cross-toplevel URLs")

    # Build tree
    tree = build_tree(states, base_url, filter_urls=cross_toplevel_urls)

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
