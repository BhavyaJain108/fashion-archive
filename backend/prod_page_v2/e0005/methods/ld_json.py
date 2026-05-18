"""
LdJsonPathMethod — read a value from the page's LD+JSON Product blob.

The most common cheap method: the @type=Product blob carries name, brand,
sku, price, description, etc. on virtually every modern e-commerce site.
One LD+JSON parse per page is shared by every LdJsonPathMethod via the
PageMemo cache.

JSONPath is intentionally simple (dot-walk + index): `$.name`,
`$.offers.price`, `$.brand.name`, `$.image[0]`. We don't need full
JSONPath features and rolling our own keeps the catalog round-trippable
to JSON without depending on a JSONPath library that may not match the
LLM's mental model of the path.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..catalog import Artifact, Method, MethodResult, register_method
from ..memo import PageMemo


@register_method
class LdJsonPathMethod(Method):
    kind = "ld_json_path"
    cost_usd = 0.0
    latency_ms = 1
    requires = frozenset({Artifact.LD_JSON})

    def __init__(self, path: str, transform: Optional[str] = None):
        # Path syntax: $.foo.bar[0].baz — dot-walk + numeric index.
        self.path = path
        self.transform = transform

    def _config_dict(self) -> Dict[str, Any]:
        return {"path": self.path, "transform": self.transform}

    async def produce(self, memo: PageMemo, field_name: str) -> MethodResult:
        product = await memo.ld_json_product()
        if product is None:
            return MethodResult(value=None)
        value = _walk(product, self.path)
        if value is None:
            return MethodResult(value=None)
        if self.transform:
            value = _apply_transform(value, self.transform)
        return MethodResult(value=value, confidence=1.0)


def _walk(obj: Any, path: str) -> Any:
    """Resolve a dot-path against a parsed LD+JSON Product blob.

    Supported syntax (matches the shopify_product_json resolver):
      $.foo.bar          dot-walk
      $.foo[0]           numeric index
      $.foo[]            list iterate (each element gets subsequent walks)
      $.foo[*] / $.*     wildcard iterate (alias for [] / iterate dict values)
    Returns the value (scalar, list, or dict). The caller applies any
    `transform` separately via _apply_transform.
    """
    if not path.startswith("$"):
        return None
    cur: Any = obj
    parts = path[1:].lstrip(".").split(".") if len(path) > 1 else []
    for part in parts:
        if cur is None:
            return None
        # Bare wildcards: `*` / `[*]` → iterate. On a list, no-op; on a
        # dict, take all values.
        if part in ("*", "[*]"):
            if isinstance(cur, list):
                continue
            if isinstance(cur, dict):
                cur = list(cur.values())
                continue
            return None
        # Normalize `foo[*]` → `foo[]` for the list-iterate path.
        if "[*]" in part:
            part = part.replace("[*]", "[]")
        # List-iterate: foo[]  — pull `foo` from each subsequent element.
        if "[]" in part:
            key = part.replace("[]", "")
            sub = cur.get(key) if isinstance(cur, dict) else (cur if key == "" else None)
            if not isinstance(sub, list):
                return None
            cur = sub
            continue
        # Numeric index: foo[0]
        if "[" in part and part.endswith("]"):
            key, idx_s = part.split("[", 1)
            try:
                idx = int(idx_s[:-1])
            except ValueError:
                return None
            if key:
                cur = cur.get(key) if isinstance(cur, dict) else None
            if isinstance(cur, list) and 0 <= idx < len(cur):
                cur = cur[idx]
            else:
                return None
            continue
        # On a list-shaped cur, apply this part to each element.
        if isinstance(cur, list):
            cur = [(c.get(part) if isinstance(c, dict) else None) for c in cur]
            cur = [c for c in cur if c is not None]
            if not cur:
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _apply_transform(value: Any, transform: str) -> Any:
    if transform == "to_float":
        try:
            return float(value) if value is not None else None
        except (ValueError, TypeError):
            return None
    if transform == "to_int":
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return None
    if transform == "strip":
        return value.strip() if isinstance(value, str) else value
    if transform == "join_comma" and isinstance(value, list):
        return ", ".join(str(x) for x in value if x)
    if transform == "json":
        import json as _json
        return _json.dumps(value, ensure_ascii=False)
    return value
