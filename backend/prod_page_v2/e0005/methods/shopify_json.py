"""
ShopifyProductJsonMethod — fetch /products/<slug>.json and read fields.

Every Shopify site exposes a JSON endpoint for each product at the same
URL with `.json` appended. The response includes the full product blob
with all variants, sizes, images, prices, availability, vendor, etc.

This is the highest-confidence method for Shopify brands. Discovery tries
it first; if it succeeds for any field, that's the catalog row used in
production (one HTTP call shared across every field it serves).
"""

from __future__ import annotations

import asyncio
import gzip
import json as _json
import re
import urllib.request
from typing import Any, Dict, List, Optional

from ..catalog import Method, MethodResult, register_method
from ..memo import PageMemo, USER_AGENT


@register_method
class ShopifyProductJsonMethod(Method):
    """Resolve a field from the Shopify product JSON endpoint."""

    kind = "shopify_product_json"
    cost_usd = 0.0
    latency_ms = 200

    # Per-page cache (URL → parsed product dict). Stored on the memo's scratch
    # area so multiple ShopifyProductJsonMethod instances on the same page
    # share the single HTTP fetch.
    _SCRATCH_KEY = "shopify_product_json"

    def __init__(self, field_path: str, transform: Optional[str] = None,
                 mode: str = "first"):
        self.field_path = field_path  # e.g. "product.title", "product.variants[].title:join_comma"
        self.transform = transform
        self.mode = mode

    def _config_dict(self) -> Dict[str, Any]:
        return {"field_path": self.field_path, "transform": self.transform, "mode": self.mode}

    async def produce(self, memo: PageMemo, field_name: str) -> MethodResult:
        blob = await self._get_blob(memo)
        if blob is None:
            return MethodResult(value=None)
        value = _resolve_path(blob, self.field_path)
        if value is None or (isinstance(value, (list, str)) and len(value) == 0):
            return MethodResult(value=None)
        value = _apply_transform(value, self.transform)
        if value is None:
            return MethodResult(value=None)
        return MethodResult(value=value, confidence=1.0)

    @classmethod
    async def _get_blob(cls, memo: PageMemo) -> Optional[dict]:
        scratch = memo.scratch()
        if cls._SCRATCH_KEY in scratch:
            return scratch[cls._SCRATCH_KEY]
        # Build the .json URL — strip query/anchor, append .json before any querystring.
        product_url = memo.url.split("?")[0].split("#")[0].rstrip("/")
        if not re.search(r"/products/[^/]+$", product_url):
            scratch[cls._SCRATCH_KEY] = None
            return None
        json_url = product_url + ".json"
        try:
            data = await asyncio.to_thread(cls._fetch, json_url)
            blob = _json.loads(data)
            scratch[cls._SCRATCH_KEY] = blob
            return blob
        except Exception:
            scratch[cls._SCRATCH_KEY] = None
            return None

    @staticmethod
    def _fetch(url: str) -> str:
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT, "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read()
            if r.headers.get("content-encoding") == "gzip":
                data = gzip.decompress(data)
            return data.decode("utf-8", errors="ignore")


# ---------------------------------------------------------------------------
# Path resolver with [] enumeration + :join_comma transform
# ---------------------------------------------------------------------------

def _resolve_path(obj: Any, path: str) -> Any:
    """Resolve `product.variants[].option1:join_comma` style paths.

    Syntax:
      foo.bar         — dot walk
      foo[].bar       — for each element of array foo, pull bar; returns list
      foo:join_comma  — emit comma-joined string from a list
      foo[0]          — index access
    """
    # Strip leading "$." / "$" so JSONPath-style paths from the LLM work as-is.
    if path.startswith("$."):
        path = path[2:]
    elif path == "$" or path.startswith("$"):
        path = path[1:]
    # Split off transform suffix `:transform`
    transform = None
    if ":" in path.rsplit(".", 1)[-1]:
        head, transform = path.rsplit(":", 1)
        path = head
    cur: Any = obj
    parts = path.split(".") if path else []
    for part in parts:
        if cur is None:
            return None
        # JSONPath wildcards: `*`, `[*]` and `[]` all mean "iterate list".
        if part == "*" or part == "[*]":
            if isinstance(cur, list):
                continue  # nothing to filter, keep iterating
            if isinstance(cur, dict):
                cur = list(cur.values())
                continue
            return None
        if "[*]" in part:
            part = part.replace("[*]", "[]")
        if "[]" in part:
            key = part.replace("[]", "")
            sub = cur.get(key) if isinstance(cur, dict) else None
            if not isinstance(sub, list):
                return None
            cur = sub  # list — subsequent dot-walks apply to each item
            continue
        if "[" in part and part.endswith("]"):
            key, idx_s = part.split("[", 1)
            idx = int(idx_s[:-1])
            if key:
                cur = cur.get(key) if isinstance(cur, dict) else None
            if isinstance(cur, list) and 0 <= idx < len(cur):
                cur = cur[idx]
            else:
                return None
            continue
        if isinstance(cur, list):
            # Apply this part to each element.
            cur = [(c.get(part) if isinstance(c, dict) else None) for c in cur]
            cur = [c for c in cur if c is not None]
            if not cur:
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    if transform == "join_comma" and isinstance(cur, list):
        # Flatten one level of nesting (handles `options[].values:join_comma`
        # producing list-of-lists across all options).
        flat: list = []
        for x in cur:
            if isinstance(x, list):
                flat.extend(v for v in x if v is not None)
            elif x is not None:
                flat.append(x)
        return ", ".join(str(v) for v in flat)
    if transform == "dedupe_join_comma" and isinstance(cur, list):
        flat: list = []
        for x in cur:
            if isinstance(x, list):
                flat.extend(v for v in x if v is not None)
            elif x is not None:
                flat.append(x)
        seen: list = []
        for v in flat:
            if v not in seen:
                seen.append(v)
        return ", ".join(str(v) for v in seen)
    if transform == "json" and isinstance(cur, (list, dict)):
        return _json.dumps(cur, ensure_ascii=False)
    if transform == "first" and isinstance(cur, list):
        # Pick first non-empty value (empty strings count as missing here —
        # this matters for Shopify compare_at_price which is "" not None).
        for x in cur:
            if x is not None and x != "":
                return x
        return None
    if transform == "any_truthy" and isinstance(cur, list):
        # Treat None as "unknown" rather than False — return None when every
        # element is None so the orchestrator can fall through to a DOM
        # method. Only return 0/1 when we have at least one known value.
        known = [x for x in cur if x is not None]
        if not known:
            return None
        return 1 if any(known) else 0
    return cur


def _apply_transform(value: Any, transform: Optional[str]) -> Any:
    if transform is None:
        return value
    if transform == "to_float":
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
    if transform == "to_int":
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return None
    if transform == "shopify_price_cents":
        # Shopify variant prices are sometimes "44.00" strings.
        try:
            return float(str(value).replace(",", ""))
        except (ValueError, TypeError):
            return None
    if transform == "html_strip":
        if isinstance(value, str):
            return re.sub(r"<[^>]+>", " ", value).strip()
    return value
