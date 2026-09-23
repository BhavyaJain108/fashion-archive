"""Placing unseen phrases in the archive's vocabulary — one cheap call per batch.

The work is reading short shop-speak and saying which garment it means: `s/s t-shirts`,
`women-jorts`, `短裤`, `Vintage Alhambra pendant`. That is the smallest, dullest model's
job, and the batch is what makes it nearly free — 1,300 phrases for the whole fleet on
the first pass, then only what a shop has newly invented, which is usually nothing.

The call is forced tool use, as in `finder_llm`: the model answers in the schema rather
than in prose we would have to dig JSON out of. Nothing here is trusted — a type outside
`taxonomy.TYPES` is dropped, and an answer about a phrase we did not ask about is
ignored. A phrase the model declines to place is written down as `not_a_garment` rather
than left blank, because a blank would be asked again on every future run.
"""

from __future__ import annotations

import os
from typing import Any, cast

from backend.archive import taxonomy
from backend.archive.finder_llm import _api_key, _workspace_id

MODEL = os.getenv("TAXONOMY_MODEL", "claude-haiku-4-5")
BATCH = 120  # phrases per call: short strings, so the answer stays well inside max_tokens

PROMPT = f"""You are sorting a fashion archive's category labels into one shared vocabulary.

Each phrase below is either a category label a shop published, or the tail of a product
title. Say which of these types it names:

{", ".join(taxonomy.TYPES)}

Rules:
- Use only the types listed. Never invent one.
- A phrase may name more than one type: "set" is a top and a bottom.
- Answer "{taxonomy.NOT_A_GARMENT}" for anything that is not a thing you wear or carry:
  seasons and drops (FW26, 2025-2, "back to 1980s"), collaboration and collection names,
  shop sections ("women", "new arrivals", "all"), and non-products (gift cards,
  insurance, shipping fees, "mws_fee_generated").
- A phrase naming only an audience ("mens", "womens", "kids") is {taxonomy.NOT_A_GARMENT}:
  it says who wears it, not what it is.
- Judge the words alone. Do not guess from a brand you think you recognise.

Phrases:
{{phrases}}"""

PLACEMENT_TOOL = {
    "name": "place_phrases",
    "description": "Place every phrase given, in the order given.",
    "input_schema": {
        "type": "object",
        "properties": {
            "placements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "phrase": {"type": "string", "description": "the phrase, copied exactly"},
                        "types": {
                            "type": "array",
                            "items": {"type": "string", "enum": list(taxonomy.TYPES)},
                            "description": "the types it names; not_a_garment if it names none",
                        },
                    },
                    "required": ["phrase", "types"],
                },
            }
        },
        "required": ["placements"],
    },
}


class _AnthropicClient:
    def __init__(self, model: str = MODEL, spend=None):
        import anthropic

        key = _api_key()
        if not key:
            raise RuntimeError("No API key. Put CLAUDE_API_KEY=... in config/.env or export it.")
        workspace = _workspace_id()
        headers = {"anthropic-workspace-id": workspace} if workspace else None
        self._c = anthropic.Anthropic(api_key=key, default_headers=headers)
        self._model = model
        self._spend = spend

    def decide(self, batch: list[str]) -> dict:
        msg = self._c.messages.create(
            model=self._model,
            max_tokens=8000,
            tools=cast(Any, [PLACEMENT_TOOL]),
            tool_choice=cast(Any, {"type": "tool", "name": PLACEMENT_TOOL["name"]}),
            messages=[
                {"role": "user", "content": PROMPT.format(phrases="\n".join(batch))},
            ],
        )
        usage = getattr(msg, "usage", None)
        if self._spend is not None and usage is not None:
            self._spend.add(
                getattr(usage, "input_tokens", 0) or 0,
                getattr(usage, "output_tokens", 0) or 0,
            )
        for block in msg.content:
            if block.type == "tool_use":
                return cast(dict, block.input)
        return {}


def default_client(spend=None):
    return _AnthropicClient(spend=spend)


def decide(
    phrases: list[str],
    client: Any = None,
    batch: int = BATCH,
    log=None,
) -> dict[str, list[str]]:
    """Place these phrases. Returns only what came back clean.

    A batch that fails costs that batch and nothing else: the model being busy should
    not throw away the placements already in hand, and the phrases it dropped will be
    asked about again on the next run, which is exactly the right outcome.
    """
    if not phrases:
        return {}
    client = client or default_client()
    asked = {p: True for p in phrases}
    out: dict[str, list[str]] = {}
    for start in range(0, len(phrases), batch):
        chunk = phrases[start : start + batch]
        try:
            answer = client.decide(chunk)
        except Exception as exc:  # noqa: BLE001 — a busy model is not a failed scrape
            if log:
                log("taxonomy-call-failed", phrases=len(chunk), error=str(exc)[:200])
            continue
        for placement in (answer or {}).get("placements", []):
            phrase = taxonomy._norm(placement.get("phrase", ""))
            if phrase not in asked:
                continue
            types = [t for t in dict.fromkeys(placement.get("types") or []) if t in taxonomy.VALID]
            out[phrase] = types or [taxonomy.NOT_A_GARMENT]
    return out
