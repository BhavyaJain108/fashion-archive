"""
NavTreeMethod — fill `category1`..`category10` from the brand's nav.json.

The nav extractor (Stage 1) already produced a tree of the brand's
categories with the URL each one points to. For any product URL, find
the deepest matching category path and emit its ancestor chain as
category1, category2, ... categoryN (depth 1 = top-most).

Non-LLM, very fast — just walks the cached nav tree.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..catalog import Method, MethodResult, register_method
from ..memo import PageMemo


@register_method
class NavTreeMethod(Method):
    """Resolve category1..category10 for the URL via the brand's nav tree."""

    kind = "nav_tree"
    cost_usd = 0.0
    latency_ms = 1

    # Module-level cache: nav.json path → loaded tree → URL→ancestor-chain index
    _index_cache: Dict[str, Dict[str, List[str]]] = {}

    def __init__(self, nav_json_path: str):
        self.nav_json_path = nav_json_path

    def _config_dict(self) -> Dict[str, Any]:
        return {"nav_json_path": self.nav_json_path}

    async def produce(self, memo: PageMemo, field_name: str) -> MethodResult:
        # Only fires for category1..category10
        if not field_name.startswith("category"):
            return MethodResult(value=None)
        try:
            level = int(field_name.replace("category", ""))
        except ValueError:
            return MethodResult(value=None)
        if not (1 <= level <= 10):
            return MethodResult(value=None)

        index = self._get_index(self.nav_json_path)
        if not index:
            return MethodResult(value=None)

        chain = self._best_match(memo.url, index)
        if not chain or level > len(chain):
            return MethodResult(value=None)
        return MethodResult(value=chain[level - 1], confidence=0.95)

    @classmethod
    def _get_index(cls, nav_json_path: str) -> Dict[str, List[str]]:
        if nav_json_path in cls._index_cache:
            return cls._index_cache[nav_json_path]
        path = Path(nav_json_path)
        if not path.exists():
            cls._index_cache[nav_json_path] = {}
            return {}
        try:
            tree = json.loads(path.read_text())
        except Exception:
            cls._index_cache[nav_json_path] = {}
            return {}
        # nav.json wraps the tree in {"category_tree": [...]} on some brands.
        if isinstance(tree, dict):
            for k in ("category_tree", "categories", "tree", "nav"):
                if k in tree and isinstance(tree[k], list):
                    tree = tree[k]
                    break
        index: Dict[str, List[str]] = {}
        cls._walk(tree, [], index)
        cls._index_cache[nav_json_path] = index
        return index

    @classmethod
    def _walk(cls, node: Any, ancestors: List[str], index: Dict[str, List[str]]) -> None:
        """Recursively walk the nav tree, recording each category's ancestor chain."""
        # nav.json shapes vary. Support both list-of-dicts and dict-with-children styles.
        if isinstance(node, list):
            for child in node:
                cls._walk(child, ancestors, index)
            return
        if not isinstance(node, dict):
            return
        name = node.get("name") or node.get("title") or node.get("text")
        url = node.get("url") or node.get("link") or node.get("href")
        new_chain = ancestors + [name] if name else ancestors
        if url and isinstance(url, str):
            index[url.rstrip("/")] = new_chain
        for key in ("children", "subcategories", "items"):
            if key in node:
                cls._walk(node[key], new_chain, index)

    @staticmethod
    def _best_match(url: str, index: Dict[str, List[str]]) -> Optional[List[str]]:
        """Find the best-matching category for a product URL.

        Strategy:
        1. Exact URL match (rare for product URLs).
        2. Prefix match, BUT only against category URLs with ≥3 path segments
           (otherwise the homepage / region-root matches every product).
        3. If no prefix match, try sharing the most path segments — useful
           when product URLs and category URLs diverge structurally (e.g.
           McQueen: `/pr/...` vs `/ca/...`). Falls back to None when there's
           no meaningful overlap.
        """
        from urllib.parse import urlparse
        url_norm = url.rstrip("/")
        if url_norm in index:
            return index[url_norm]

        url_parts = [p for p in urlparse(url_norm).path.split("/") if p]

        # 2. Longest prefix match, with a minimum-depth filter.
        best: Tuple[int, Optional[List[str]]] = (0, None)
        for cat_url, chain in index.items():
            cat_parts = [p for p in urlparse(cat_url).path.split("/") if p]
            if len(cat_parts) < 3:
                continue
            if url_norm.startswith(cat_url) and len(cat_url) > best[0]:
                best = (len(cat_url), chain)
        if best[1]:
            return best[1]

        # 3. Common path-segment overlap. Useful when product paths diverge
        # from category paths but share locale + section ("en-us", "women").
        best_overlap: Tuple[int, Optional[List[str]]] = (0, None)
        for cat_url, chain in index.items():
            cat_parts = [p for p in urlparse(cat_url).path.split("/") if p]
            if len(cat_parts) < 3:
                continue
            shared = 0
            for a, b in zip(url_parts, cat_parts):
                if a == b:
                    shared += 1
                else:
                    break
            if shared >= 2 and shared > best_overlap[0]:
                best_overlap = (shared, chain)
        return best_overlap[1]
