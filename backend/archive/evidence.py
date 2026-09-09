"""What we looked at, so a blank field can be believed.

An empty field has always had two meanings stored identically: the brand does not
publish it, and we never went looking. The first is a fact worth keeping — a shop that
lists no fabric composition is telling you something about itself. The second is a gap in
our work wearing the same clothes.

A run therefore records, per field, which sources it consulted and how many products it
consulted them on. Sources run shallowest to deepest:

    channel        the bulk feed, Store API or JSON-LD node the connector parsed
    page_rules     the brand's learned rules replayed against the product page
    page_rendered  the same, against a browser-rendered page
    page_llm       the finder read the page and was asked for this field by name

page_llm is the strongest absence evidence available short of a person looking: a model
was given the whole page, asked for that field, and produced no rule that survived
replay.
"""

from backend.archive.domain.product import SOURCES


class SearchLog:
    """Counts, per (field, source), how many products were examined and how many yielded."""

    def __init__(self) -> None:
        self._counts: dict[tuple[str, str], list[int]] = {}

    def searched(self, source: str, fields, found=()) -> None:
        if source not in SOURCES:
            raise ValueError(f"unknown source {source!r}")
        found = set(found)
        for field in fields:
            entry = self._counts.setdefault((field, source), [0, 0])
            entry[0] += 1
            if field in found:
                entry[1] += 1

    def rows(self) -> list[tuple[str, str, int, int]]:
        return [(f, s, n, hits) for (f, s), (n, hits) in sorted(self._counts.items())]

    def __len__(self) -> int:
        return len(self._counts)


def describe(evidence: dict[tuple[str, str], tuple[int, int]], field: str) -> str:
    """How much a blank in this field is worth believing."""
    searched = [s for s in SOURCES if evidence.get((field, s), (0, 0))[0]]
    if not searched:
        return "never searched"
    if searched == ["channel"]:
        return "channel only — the page has not been read for this field"
    return "absent from " + ", ".join(searched)
