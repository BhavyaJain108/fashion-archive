"""
UrlPatternMethod — regex over `memo.url` with one capture group.

This is the ONE regex-based method we allow, and it's restricted (by
convention in the discovery prompt + an enforced check in oneshot.verify)
to the `product_code` field.

Rationale: most fields' text content varies wildly across products of a
brand, so content regex never generalizes. But `product_code` lives in
the URL at a stable position for many brands (e.g. McQueen's
`/.../<slug>-870312QJAAC4003.html`), and the URL is structurally
predictable per brand. One regex extracts the SKU from every product
URL without re-discovery.

config:
  pattern : Python regex string. Must contain at least one capture group.
  group   : which capture group to return (default 1).
  transform: optional — null | "upper" | "lower" | "strip".

Production cost: ~microseconds. Same cost class as og_meta.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from ..catalog import Method, MethodResult, register_method
from ..memo import PageMemo


@register_method
class UrlPatternMethod(Method):
    """Regex one capture group out of `memo.url`."""

    kind = "url_pattern"
    cost_usd = 0.0
    latency_ms = 1

    def __init__(self, pattern: str, group: int = 1, transform: Optional[str] = None):
        self.pattern = pattern
        self.group = int(group)
        self.transform = transform
        try:
            self._compiled = re.compile(pattern)
        except re.error:
            self._compiled = None

    def _config_dict(self) -> Dict[str, Any]:
        return {"pattern": self.pattern, "group": self.group, "transform": self.transform}

    async def produce(self, memo: PageMemo, field_name: str) -> MethodResult:
        if self._compiled is None:
            return MethodResult(value=None)
        m = self._compiled.search(memo.url)
        if not m:
            return MethodResult(value=None)
        try:
            value = m.group(self.group)
        except (IndexError, re.error):
            return MethodResult(value=None)
        if value is None:
            return MethodResult(value=None)
        if self.transform == "upper":
            value = value.upper()
        elif self.transform == "lower":
            value = value.lower()
        elif self.transform == "strip":
            value = value.strip()
        return MethodResult(value=value, confidence=1.0)
