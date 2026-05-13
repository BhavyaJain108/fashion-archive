"""
OgMetaMethod — pull a value from a <meta name|property=...> tag.

Cheapest possible method. Many sites mirror their core fields in Open
Graph / Twitter Card / schema.org meta tags (product_title, image,
brand, price). Discovery learns which tag name maps to which E0005 field.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..catalog import Artifact, Method, MethodResult, register_method
from ..memo import PageMemo


@register_method
class OgMetaMethod(Method):
    kind = "og_meta"
    cost_usd = 0.0
    latency_ms = 1
    requires = frozenset({Artifact.META_TAGS})

    def __init__(self, name: str, transform: Optional[str] = None):
        self.name = name.lower()
        self.transform = transform

    def _config_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "transform": self.transform}

    async def produce(self, memo: PageMemo, field_name: str) -> MethodResult:
        metas = await memo.meta_tags()
        value = metas.get(self.name)
        if not value:
            return MethodResult(value=None)
        if self.transform == "to_float":
            try:
                return MethodResult(value=float(value), confidence=1.0)
            except ValueError:
                return MethodResult(value=None)
        if self.transform == "html_unescape":
            import html
            value = html.unescape(value)
        return MethodResult(value=value, confidence=1.0)
