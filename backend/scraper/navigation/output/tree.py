"""
Navigation tree data structure and pretty printing.

Represents the hierarchical structure of a website's navigation menu.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class NavNode:
    """A node in the navigation tree."""
    name: str
    url: Optional[str] = None  # None for intermediate nodes
    children: list['NavNode'] = field(default_factory=list)

    def add_child(self, name: str, url: str = None) -> 'NavNode':
        """Add a child node and return it."""
        child = NavNode(name=name, url=url)
        self.children.append(child)
        return child

    def find_child(self, name: str) -> Optional['NavNode']:
        """Find a direct child by name."""
        for child in self.children:
            if child.name == name:
                return child
        return None

    def get_or_create_child(self, name: str, url: str = None) -> 'NavNode':
        """Get existing child or create new one."""
        existing = self.find_child(name)
        if existing:
            # Update URL if provided and not set
            if url and not existing.url:
                existing.url = url
            return existing
        return self.add_child(name, url)

    def is_leaf(self) -> bool:
        """Check if this is a leaf node (has URL, no children)."""
        return self.url is not None and len(self.children) == 0

    def count_leaves(self) -> int:
        """Count leaf nodes (categories with URLs)."""
        if self.is_leaf():
            return 1
        return sum(child.count_leaves() for child in self.children)

    def count_all(self) -> int:
        """Count all nodes including intermediate ones."""
        return 1 + sum(child.count_all() for child in self.children)


class NavTree:
    """
    Navigation tree for a website.

    Supports:
    - Multiple root tabs (Women, Men, Kids)
    - Hierarchical categories
    - Pretty printing
    - Export to various formats
    """

    def __init__(self):
        self.roots: list[NavNode] = []

    def add_tab(self, name: str) -> NavNode:
        """Add a root tab (Women, Men, etc.) and return it."""
        tab = NavNode(name=name)
        self.roots.append(tab)
        return tab

    def get_tab(self, name: str) -> Optional[NavNode]:
        """Get a tab by name."""
        for root in self.roots:
            if root.name == name:
                return root
        return None

    def get_or_create_tab(self, name: str) -> NavNode:
        """Get existing tab or create new one."""
        existing = self.get_tab(name)
        if existing:
            return existing
        return self.add_tab(name)

    def add_path(self, path: list[str], url: str = None):
        """
        Add a category path to the tree.

        Args:
            path: List like ['Women', 'Clothing', 'Dresses']
            url: URL for the leaf node
        """
        if not path:
            return

        # First element is the tab
        current = self.get_or_create_tab(path[0])

        # Navigate/create intermediate nodes
        for i, name in enumerate(path[1:], 1):
            is_last = (i == len(path) - 1)
            current = current.get_or_create_child(
                name,
                url=url if is_last else None
            )

    def add_category(self, tab_name: str, category_name: str, url: str):
        """Add a flat category under a tab."""
        tab = self.get_or_create_tab(tab_name)
        tab.get_or_create_child(category_name, url)

    def print(self, show_urls: bool = True) -> str:
        """
        Pretty print the tree.

        Returns string like:
        Women
        ├── Clothing
        │   ├── Dresses → /women/dresses
        │   └── Tops → /women/tops
        └── Shoes
            └── Heels → /women/heels
        """
        lines = []
        for i, root in enumerate(self.roots):
            self._print_node(root, lines, "", i == len(self.roots) - 1, show_urls, is_root=True)
        return '\n'.join(lines)

    def _print_node(self, node: NavNode, lines: list, prefix: str, is_last: bool, show_urls: bool, is_root: bool = False):
        """Recursively print a node and its children."""
        # Build the line
        if is_root:
            # Root node (tab) - no connector
            line = node.name
            child_prefix = ""
        else:
            # Child node - use tree connectors
            connector = "└── " if is_last else "├── "
            line = prefix + connector + node.name
            child_prefix = prefix + ("    " if is_last else "│   ")

        # Add URL if present and requested
        if show_urls and node.url:
            line += f" → {node.url}"

        lines.append(line)

        # Print children
        for i, child in enumerate(node.children):
            self._print_node(child, lines, child_prefix, i == len(node.children) - 1, show_urls, is_root=False)

    def to_flat(self) -> dict:
        """
        Export as flat dict {name: url}.
        Backwards compatible with old format.
        """
        result = {}
        for root in self.roots:
            self._flatten_node(root, result)
        return result

    def _flatten_node(self, node: NavNode, result: dict):
        """Recursively flatten a node."""
        if node.url:
            result[node.name] = node.url
        for child in node.children:
            self._flatten_node(child, result)

    def to_dict(self) -> dict:
        """Export as nested dict structure."""
        return {
            'tabs': [self._node_to_dict(root) for root in self.roots]
        }

    def _node_to_dict(self, node: NavNode) -> dict:
        """Convert a node to dict."""
        d = {'name': node.name}
        if node.url:
            d['url'] = node.url
        if node.children:
            d['children'] = [self._node_to_dict(c) for c in node.children]
        return d

    def stats(self) -> dict:
        """Get tree statistics."""
        total_leaves = sum(root.count_leaves() for root in self.roots)
        total_nodes = sum(root.count_all() for root in self.roots)
        return {
            'tabs': len(self.roots),
            'total_categories': total_leaves,
            'total_nodes': total_nodes,
        }

    def __str__(self) -> str:
        return self.print()

    def __repr__(self) -> str:
        stats = self.stats()
        return f"NavTree({stats['tabs']} tabs, {stats['total_categories']} categories)"


def build_tree_from_results(results: dict) -> NavTree:
    """
    Build NavTree from explore_all_tabs() results.

    Args:
        results: Dict with 'tabs' and 'all_categories' from exploration

    Returns:
        NavTree with all categories organized hierarchically
    """
    tree = NavTree()

    tabs_data = results.get('tabs', {})

    for tab_name, tab_result in tabs_data.items():
        categories = tab_result.get('categories', {})

        for name, url in categories.items():
            # Check if name contains hierarchy indicator
            if ' > ' in name:
                # Hierarchical path like "Parent > Child > Subchild"
                parts = [p.strip() for p in name.split(' > ')]
                path = [tab_name] + parts
                tree.add_path(path, url)
            else:
                # Flat category
                tree.add_category(tab_name, name, url)

    return tree
