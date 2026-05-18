"""
DomSelectorMethod / DomAttrMethod — read text or attribute from rendered DOM.

Used when LD+JSON / OG meta don't carry the data (sizes, prices on
sale-only sites, sustainability badges, etc.). Selectors are discovered
per-brand by the LLM at catalog discovery time and saved in the catalog.

These methods require `rendered_html` (Playwright load) so they're more
expensive than LD+JSON/meta but still LLM-free at extraction time.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..catalog import Artifact, Method, MethodResult, register_method
from ..memo import PageMemo


@register_method
class DomSelectorMethod(Method):
    """Get innerText from one or more elements matching a CSS selector."""

    kind = "dom_selector"
    cost_usd = 0.0
    latency_ms = 50
    requires = frozenset({Artifact.RENDERED_HTML})

    def __init__(
        self,
        selector: str,
        mode: str = "first",                 # "first" | "all_join"
        transform: Optional[str] = None,     # "strip" | "to_float" | "split_size_list" | ...
        separator: str = ", ",
    ):
        self.selector = selector
        self.mode = mode
        self.transform = transform
        self.separator = separator

    def _config_dict(self) -> Dict[str, Any]:
        return {
            "selector": self.selector,
            "mode": self.mode,
            "transform": self.transform,
            "separator": self.separator,
        }

    async def produce(self, memo: PageMemo, field_name: str) -> MethodResult:
        # We need the live Playwright Page (rendered HTML alone doesn't let us
        # use Playwright's CSS engine reliably for :has-text selectors). The
        # memo has already rendered; reuse its page.
        await memo.rendered_html()  # ensures render happened
        page = memo._page
        if page is None:
            return MethodResult(value=None)
        try:
            if self.mode == "first":
                loc = page.locator(self.selector).first
                if await loc.count() == 0:
                    return MethodResult(value=None)
                text = (await loc.inner_text(timeout=2000)).strip()
            else:
                loc = page.locator(self.selector)
                count = await loc.count()
                if count == 0:
                    return MethodResult(value=None)
                texts = []
                for i in range(min(count, 50)):
                    try:
                        t = (await loc.nth(i).inner_text(timeout=1500)).strip()
                        if t:
                            texts.append(t)
                    except Exception:
                        continue
                text = self.separator.join(texts)
        except Exception:
            return MethodResult(value=None)
        if not text:
            return MethodResult(value=None)
        value = _transform_value(text, self.transform)
        if value is None:
            return MethodResult(value=None)
        return MethodResult(value=value, confidence=0.9)


@register_method
class DomAttrMethod(Method):
    """Get an attribute value from the first element matching a selector."""

    kind = "dom_attr"
    cost_usd = 0.0
    latency_ms = 50
    requires = frozenset({Artifact.RENDERED_HTML})

    def __init__(self, selector: str, attr: str, transform: Optional[str] = None):
        self.selector = selector
        self.attr = attr
        self.transform = transform

    def _config_dict(self) -> Dict[str, Any]:
        return {"selector": self.selector, "attr": self.attr, "transform": self.transform}

    async def produce(self, memo: PageMemo, field_name: str) -> MethodResult:
        await memo.rendered_html()
        page = memo._page
        if page is None:
            return MethodResult(value=None)
        try:
            loc = page.locator(self.selector).first
            if await loc.count() == 0:
                return MethodResult(value=None)
            val = await loc.get_attribute(self.attr, timeout=2000)
        except Exception:
            return MethodResult(value=None)
        if not val:
            return MethodResult(value=None)
        return MethodResult(value=_transform_value(val, self.transform), confidence=0.9)


def _transform_value(value: str, transform: Optional[str]) -> Any:
    if transform is None:
        return value.strip()
    if transform == "strip":
        return value.strip()
    if transform == "to_float":
        # Strip currency symbols + thousands separators.
        s = value.replace("$", "").replace("€", "").replace("£", "").replace(",", "").strip()
        try:
            return float(s)
        except ValueError:
            return None
    if transform == "split_size_list":
        # Normalize size buttons text like "38\n40\n42" or "38 40 42" → "38, 40, 42"
        parts = [p.strip() for p in value.replace("\n", " ").split() if p.strip()]
        return ", ".join(parts)
    return value.strip()
