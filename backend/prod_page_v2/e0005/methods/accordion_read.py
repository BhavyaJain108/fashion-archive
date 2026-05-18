"""
AccordionReadMethod — click an accordion / "show more" trigger and read the
revealed text.

Discovered during Phase A of the ground-truth pass. Production replays the
same (trigger_selector, panel_selector) tuple so material_info / specs /
shipping info come through without an LLM call.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..catalog import Artifact, Method, MethodResult, register_method
from ..memo import PageMemo


@register_method
class AccordionReadMethod(Method):
    kind = "accordion_read"
    cost_usd = 0.0
    latency_ms = 600
    requires = frozenset({Artifact.RENDERED_HTML, Artifact.ACCORDION})

    def __init__(
        self,
        trigger_selector: str,
        panel_selector: Optional[str] = None,
        wait_ms: int = 500,
        max_chars: int = 1500,
    ):
        self.trigger_selector = trigger_selector
        self.panel_selector = panel_selector
        self.wait_ms = wait_ms
        self.max_chars = max_chars

    def _config_dict(self) -> Dict[str, Any]:
        return {
            "trigger_selector": self.trigger_selector,
            "panel_selector": self.panel_selector,
            "wait_ms": self.wait_ms,
            "max_chars": self.max_chars,
        }

    async def produce(self, memo: PageMemo, field_name: str) -> MethodResult:
        text = await memo.click_and_capture(
            trigger_selector=self.trigger_selector,
            panel_selector=self.panel_selector,
            wait_ms=self.wait_ms,
            key=self.trigger_selector,
        )
        if not text:
            return MethodResult(value=None)
        text = text.strip()
        if len(text) > self.max_chars:
            text = text[: self.max_chars]
        return MethodResult(value=text, confidence=0.85)
