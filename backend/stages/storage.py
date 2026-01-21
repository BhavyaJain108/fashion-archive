"""
Storage utilities for pipeline stages.

Handles save/load operations and path management.
"""

import json
from pathlib import Path
from urllib.parse import urlparse
from typing import Optional


# Base directory for all extractions
EXTRACTIONS_DIR = Path(__file__).parent.parent / "extractions"


def get_domain(url: str) -> str:
    """Extract clean domain from URL."""
    parsed = urlparse(url)
    domain = parsed.netloc.replace('www.', '')
    return domain


def get_domain_dir(domain: str) -> Path:
    """Get extraction directory for a domain."""
    clean_domain = domain.replace('.', '_')
    return EXTRACTIONS_DIR / clean_domain


def ensure_domain_dir(domain: str) -> Path:
    """Create and return domain directory."""
    domain_dir = get_domain_dir(domain)
    domain_dir.mkdir(parents=True, exist_ok=True)
    return domain_dir


# ============================================================
# Stage 1: Navigation
# ============================================================

def save_navigation(domain: str, nav_tree: dict):
    """Save navigation tree as JSON and readable TXT."""
    domain_dir = ensure_domain_dir(domain)

    # Save JSON
    json_path = domain_dir / "nav.json"
    with open(json_path, 'w') as f:
        json.dump(nav_tree, f, indent=2)

    # Save readable TXT
    txt_path = domain_dir / "nav.txt"
    readable = nav_to_readable(nav_tree)
    with open(txt_path, 'w') as f:
        f.write(readable)

    return json_path, txt_path


def load_navigation(domain: str) -> Optional[dict]:
    """Load navigation tree from JSON."""
    domain_dir = get_domain_dir(domain)
    json_path = domain_dir / "nav.json"

    if not json_path.exists():
        return None

    with open(json_path) as f:
        return json.load(f)


def nav_to_readable(nav_tree: dict, indent: int = 0) -> str:
    """Convert navigation tree to readable text format."""
    lines = []
    prefix = "  " * indent

    tree = nav_tree.get("category_tree", nav_tree)
    if isinstance(tree, dict) and "category_tree" in tree:
        tree = tree["category_tree"]

    if isinstance(tree, list):
        for node in tree:
            name = node.get("name", "Unknown")
            url = node.get("url", "")
            lines.append(f"{prefix}{name} | {url}")

            children = node.get("children", [])
            if children:
                lines.append(nav_to_readable({"category_tree": children}, indent + 1))

    # Add category count at root level
    if indent == 0:
        count = nav_tree.get("category_count", count_categories(nav_tree))
        lines.append("")
        lines.append(f"Categories: {count}")

    return "\n".join(lines)


def count_categories(nav_tree: dict) -> int:
    """Count total categories in tree."""
    count = 0
    tree = nav_tree.get("category_tree", [])

    def count_node(node):
        nonlocal count
        count += 1
        for child in node.get("children", []):
            count_node(child)

    for node in tree:
        count_node(node)

    return count


# ============================================================
# Stage 2: URLs
# ============================================================

def save_urls(domain: str, urls_tree: dict):
    """Save URLs tree as JSON and readable TXT."""
    domain_dir = ensure_domain_dir(domain)

    # Save JSON
    json_path = domain_dir / "urls.json"
    with open(json_path, 'w') as f:
        json.dump(urls_tree, f, indent=2)

    # Save readable TXT
    txt_path = domain_dir / "urls.txt"
    readable = urls_to_readable(urls_tree)
    with open(txt_path, 'w') as f:
        f.write(readable)

    return json_path, txt_path


def load_urls(domain: str) -> Optional[dict]:
    """Load URLs tree from JSON."""
    domain_dir = get_domain_dir(domain)
    json_path = domain_dir / "urls.json"

    if not json_path.exists():
        return None

    with open(json_path) as f:
        return json.load(f)


def urls_to_readable(urls_tree: dict, indent: int = 0) -> str:
    """Convert URLs tree to readable text format."""
    lines = []
    prefix = "  " * indent

    tree = urls_tree.get("category_tree", urls_tree)
    if isinstance(tree, dict) and "category_tree" in tree:
        tree = tree["category_tree"]

    if isinstance(tree, list):
        for node in tree:
            name = node.get("name", "Unknown")
            url = node.get("url", "")
            product_count = node.get("product_count", len(node.get("products", [])))
            lines.append(f"{prefix}{name} | {url} ({product_count})")

            # List products
            for product_url in node.get("products", []):
                lines.append(f"{prefix}  - {product_url}")

            # Recurse children
            children = node.get("children", [])
            if children:
                lines.append(urls_to_readable({"category_tree": children}, indent + 1))

    # Add totals and empty categories at root level
    if indent == 0:
        total = urls_tree.get("total_products", 0)
        unique = urls_tree.get("unique_products", 0)
        lines.append("")
        lines.append(f"Total: {total} | Unique: {unique}")

        # Add empty categories section
        empty_categories = urls_tree.get("empty_categories", [])
        if empty_categories:
            lines.append("")
            lines.append("=" * 40)
            lines.append(f"Categories with no products ({len(empty_categories)}):")
            lines.append("=" * 40)
            for cat in empty_categories:
                lines.append(f"  - {cat.get('name', 'Unknown')} | {cat.get('url', '')}")

    return "\n".join(lines)


# ============================================================
# Stage 3: Products
# ============================================================

def save_config(domain: str, config: dict):
    """Save extraction config."""
    domain_dir = ensure_domain_dir(domain)
    config_path = domain_dir / "config.json"

    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)

    return config_path


def load_config(domain: str) -> Optional[dict]:
    """Load extraction config."""
    domain_dir = get_domain_dir(domain)
    config_path = domain_dir / "config.json"

    if not config_path.exists():
        return None

    with open(config_path) as f:
        return json.load(f)


def save_product(domain: str, product: dict, category_path: str, source_url: str = None):
    """Save product to category folder.

    Args:
        domain: Domain name
        product: Product data dict
        category_path: Path like "women/tops" or "men"
        source_url: Original URL from urls.json (used for filename to preserve variants)
    """
    domain_dir = ensure_domain_dir(domain)
    products_dir = domain_dir / "products" / category_path
    products_dir.mkdir(parents=True, exist_ok=True)

    # Create filename from source URL (preserves variant URLs) or fallback to name
    if source_url:
        # Extract slug from original URL to preserve variant identifier
        slug = source_url.rstrip('/').split('/')[-1].split('?')[0]
    else:
        name = product.get("name", "")
        url = product.get("url", "")

        if name:
            slug = name.lower().replace(" ", "-").replace("/", "-")
            slug = ''.join(c for c in slug if c.isalnum() or c == '-')
        else:
            # Extract from URL
            slug = url.rstrip('/').split('/')[-1]

    filepath = products_dir / f"{slug}.json"

    with open(filepath, 'w') as f:
        json.dump(product, f, indent=2)

    return filepath


def get_category_path_for_url(product_url: str, urls_tree: dict) -> str:
    """Find category path for a product URL.

    Returns path like "women/tops" based on where the URL appears in the tree.
    """
    def search_tree(nodes, path_parts):
        for node in nodes:
            name = node.get("name", "unknown").lower().replace(" ", "-")
            name = ''.join(c for c in name if c.isalnum() or c == '-')
            current_path = path_parts + [name]

            # Check if URL is in this node's products
            if product_url in node.get("products", []):
                return "/".join(current_path)

            # Recurse into children
            children = node.get("children", [])
            if children:
                result = search_tree(children, current_path)
                if result:
                    return result

        return None

    tree = urls_tree.get("category_tree", [])
    result = search_tree(tree, [])

    return result or "uncategorized"
