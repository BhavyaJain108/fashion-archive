"""
ComposeMethod — combine outputs of multiple inner methods with a template.

Used when a field's value is split across page sources. The LLM proposes:

  {
    "kind": "compose",
    "config": {
      "parts": [
        {"kind": "text_regex", "config": {...}},
        {"kind": "shopify_product_json", "config": {...}}
      ],
      "template": "{0} ({1})"
    },
    "expected": "Cotton Silk Organza (53%SILK,47%COTTON)"
  }

Each part's runtime output is substituted positionally into `template` via
`str.format`. If ANY part returns None, the compose result is None.

Failure modes are silent: a malformed template, hydration error on any
part, or a None result anywhere → returns MethodResult(value=None). The
discovery verifier then discards the compose attempt.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..catalog import Method, MethodResult, hydrate_method, register_method
from ..memo import PageMemo


@register_method
class ComposeMethod(Method):
    kind = "compose"
    cost_usd = 0.0
    latency_ms = 10  # mostly the sum of its parts' latencies

    def __init__(self, parts: List[Dict[str, Any]], template: Optional[str] = None, separator: Optional[str] = None):
        # parts: list of {"kind": str, "config": dict}. We keep them as
        # config dicts and hydrate lazily so this method round-trips
        # through JSON without instantiation side-effects.
        self.parts_config = parts
        self.template = template
        self.separator = separator  # optional: when set, join part outputs with separator instead of using template
        self._parts: Optional[List[Method]] = None

    def _config_dict(self) -> Dict[str, Any]:
        return {
            "parts": self.parts_config,
            "template": self.template,
            "separator": self.separator,
        }

    def _hydrate(self) -> List[Method]:
        if self._parts is None:
            hydrated: List[Method] = []
            for p in self.parts_config:
                kind = p.get("kind")
                config = p.get("config", {}) or {}
                if not kind:
                    return []
                try:
                    hydrated.append(hydrate_method({"kind": kind, **config}))
                except Exception:
                    return []
            self._parts = hydrated
        return self._parts

    async def produce(self, memo: PageMemo, field_name: str) -> MethodResult:
        parts = self._hydrate()
        if not parts:
            return MethodResult(value=None)
        values: List[str] = []
        for part in parts:
            try:
                r = await part.produce(memo, field_name)
            except Exception:
                return MethodResult(value=None)
            if r.value is None or r.value == "":
                return MethodResult(value=None)
            values.append(str(r.value).strip())

        if self.separator is not None:
            composed = self.separator.join(values)
        elif self.template:
            try:
                composed = self.template.format(*values)
            except (KeyError, IndexError):
                return MethodResult(value=None)
        else:
            # No template AND no separator — fall back to concatenation with a space.
            composed = " ".join(values)
        return MethodResult(value=composed.strip(), confidence=0.9)
