"""
TextRegexMethod — capture a fragment from any of the page's text sources.

Useful as a building block for `compose` when a field's value lives partially
inside a longer description (e.g. textile name embedded in body_html prose).

Sources:
  - "ld_json_description"   : LD+JSON Product `description` field
  - "body_html"             : Shopify `product.body_html`
  - "visible_text"          : rendered body innerText
  - "rendered_html"         : full rendered HTML
  - "url"                   : memo.url string
"""

from __future__ import annotations

import re
from typing import Any, Dict

from ..catalog import Method, MethodResult, register_method
from ..memo import PageMemo


@register_method
class TextRegexMethod(Method):
    kind = "text_regex"
    cost_usd = 0.0
    latency_ms = 5

    _SOURCES = ("ld_json_description", "body_html", "visible_text",
                "rendered_html", "url")

    def __init__(self, source: str, regex: str, group: int = 1, flags: str = ""):
        if source not in self._SOURCES:
            raise ValueError(f"unknown source {source!r}; want one of {self._SOURCES}")
        self.source = source
        self.regex = regex
        self.group = group
        self.flags = flags  # combination of "i", "s", "m" — passed to re

    def _config_dict(self) -> Dict[str, Any]:
        return {"source": self.source, "regex": self.regex,
                "group": self.group, "flags": self.flags}

    def _re_flags(self) -> int:
        out = 0
        if "i" in self.flags: out |= re.IGNORECASE
        if "s" in self.flags: out |= re.DOTALL
        if "m" in self.flags: out |= re.MULTILINE
        return out

    async def _get_text(self, memo: PageMemo) -> str:
        if self.source == "url":
            return memo.url
        if self.source == "visible_text":
            return await memo.visible_text()
        if self.source == "rendered_html":
            return await memo.rendered_html()
        if self.source == "ld_json_description":
            blob = await memo.ld_json_product()
            return (blob.get("description") if isinstance(blob, dict) else "") or ""
        if self.source == "body_html":
            from .shopify_json import ShopifyProductJsonMethod
            blob = await ShopifyProductJsonMethod._get_blob(memo)
            if not blob:
                return ""
            product = blob.get("product") if isinstance(blob, dict) else None
            return (product.get("body_html") if isinstance(product, dict) else "") or ""
        return ""

    async def produce(self, memo: PageMemo, field_name: str) -> MethodResult:
        text = await self._get_text(memo)
        if not text:
            return MethodResult(value=None)
        try:
            m = re.search(self.regex, text, self._re_flags())
        except re.error:
            return MethodResult(value=None)
        if not m:
            return MethodResult(value=None)
        try:
            value = m.group(self.group).strip()
        except (IndexError, AttributeError):
            return MethodResult(value=None)
        return MethodResult(value=value, confidence=0.85)
