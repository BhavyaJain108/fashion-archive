"""Filtering a catalogue the way a shop's own page does: by what the brand offers.

A facet is one field read as a set of values — the colours a product comes in, the
sizes it is offered in, its material, category, the tags the brand put on it — and
the counts under the reader's current choices. Choosing within one facet widens
(any of these colours); choosing across facets narrows (this colour AND this size).
Counts for a facet are computed with every other facet's choices applied, so a chip
always says how many products a click would leave.

Values are the brand's own words, whitespace-collapsed, grouped without regard to
case. Sizes are ordered as a size chart would order them; everything else by count.
Nothing here is stored: it is read off the products the page already has.
"""

import re
from collections import Counter
from typing import Any

from backend.archive import taxonomy

# facet name -> the record field it reads. Every one is a comma-separated list in
# E0005 except category, which is a path (category1 is its first level).
LIST_FACETS = {
    # The archive's own vocabulary, the one facet that means the same thing on every
    # brand — bode's "MENS SHIRTS" and marrknull's "上衣" are both `shirts` here.
    "type": taxonomy.TYPE_FIELD,
    "colour": "color_info",
    "size": "size_info",
    "material": "material_info",
    "tag": "additional_tags",
}
PATH_FACETS = {"category": ("category1", "category2")}
DERIVED = ("stock", "sale")
FACETS = (*LIST_FACETS, *PATH_FACETS, *DERIVED)

MAX_VALUES = 40  # chips per facet; a brand with 200 tags shows the 40 that matter

_SIZE_ORDER = ["XXXS", "XXS", "XS", "S", "M", "L", "XL", "XXL", "XXXL", "4XL", "5XL"]
_SIZE_ALIASES = {"2XS": "XXS", "2XL": "XXL", "3XL": "XXXL", "ONE SIZE": "OS", "OS": "OS"}
_WS = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _WS.sub(" ", text).strip()


def _split(value: Any) -> list[str]:
    if not value or not isinstance(value, str):
        return []
    return [_norm(t) for t in value.split(",") if _norm(t)]


def values_of(row: dict, facet: str) -> list[str]:
    """The values one product carries for a facet, as the brand printed them."""
    if facet in LIST_FACETS:
        return _split(row.get(LIST_FACETS[facet]))
    if facet in PATH_FACETS:
        parts = [_norm(str(row.get(f) or "")) for f in PATH_FACETS[facet]]
        parts = [p for p in parts if p]
        # Both the first level and the two-level path, so a reader can pick either.
        out = []
        if parts:
            out.append(parts[0])
        if len(parts) > 1:
            out.append(" / ".join(parts[:2]))
        return out
    if facet == "stock":
        if row.get("in_stock") is None:
            return []
        return ["in stock" if row.get("in_stock") else "out of stock"]
    if facet == "sale":
        full, price = row.get("full_price"), row.get("price")
        on_sale = row.get("promotion_type") == "sale" or (
            isinstance(full, int | float) and isinstance(price, int | float) and full > price
        )
        return ["on sale"] if on_sale else []
    return []


def size_in_stock(row: dict, size: str) -> bool | None:
    """Whether one size is in stock on this product, from the two parallel lists.
    None when the product does not say."""
    sizes = _split(row.get("size_info"))
    flags = _split(row.get("size_availability"))
    if not sizes or len(sizes) != len(flags):
        return None
    for s, f in zip(sizes, flags, strict=True):
        if s.casefold() == size.casefold():
            return f == "in_stock"
    return None


def matches(row: dict, facet: str, wanted: set[str]) -> bool:
    """Whether the product carries any of the wanted values for the facet."""
    if not wanted:
        return True
    have = {v.casefold() for v in values_of(row, facet)}
    return any(w.casefold() in have for w in wanted)


def apply(
    rows: list[dict], selected: dict[str, set[str]], sized_in_stock: bool = False
) -> list[dict]:
    """The products that satisfy every chosen facet. With `sized_in_stock`, a chosen
    size must also be in stock on the product, not merely offered."""
    out = []
    for row in rows:
        if not all(
            matches(row, f, w) for f, w in selected.items() if f != "size" or not sized_in_stock
        ):
            continue
        if sized_in_stock and selected.get("size"):
            if not any(size_in_stock(row, s) for s in selected["size"]):
                continue
        out.append(row)
    return out


def price_range(rows: list[dict]) -> dict | None:
    prices = [r["price"] for r in rows if isinstance(r.get("price"), int | float)]
    if not prices:
        return None
    return {"min": min(prices), "max": max(prices)}


def within_price(rows: list[dict], low: float | None, high: float | None) -> list[dict]:
    if low is None and high is None:
        return rows
    out = []
    for r in rows:
        p = r.get("price")
        if not isinstance(p, int | float):
            continue
        if low is not None and p < low:
            continue
        if high is not None and p > high:
            continue
        out.append(r)
    return out


def _size_key(label: str) -> tuple:
    up = _SIZE_ALIASES.get(label.upper(), label.upper())
    if up in _SIZE_ORDER:
        return (0, _SIZE_ORDER.index(up), "")
    m = re.match(r"^(\d+(?:\.\d+)?)", label)
    if m:
        return (1, float(m.group(1)), label)
    return (2, 0, label.casefold())


def counts(
    rows: list[dict], selected: dict[str, set[str]], sized_in_stock: bool = False
) -> dict[str, list[dict]]:
    """For every facet, its values and how many products each would leave, given the
    choices made in the other facets."""
    out: dict[str, list[dict]] = {}
    for facet in FACETS:
        others = {f: w for f, w in selected.items() if f != facet}
        pool = apply(rows, others, sized_in_stock)
        tally: Counter = Counter()
        label: dict[str, str] = {}
        in_stock: Counter = Counter()
        for row in pool:
            seen = set()
            for v in values_of(row, facet):
                k = v.casefold()
                if k in seen:
                    continue
                seen.add(k)
                tally[k] += 1
                label.setdefault(k, v)
                if facet == "size" and size_in_stock(row, v):
                    in_stock[k] += 1
        chosen = {w.casefold() for w in selected.get(facet, set())}
        items: list[dict[str, Any]] = [
            {
                "value": label[k],
                "count": c,
                "selected": k in chosen,
                **({"in_stock": in_stock[k]} if facet == "size" else {}),
            }
            for k, c in tally.items()
        ]
        if facet == "size":
            items.sort(key=lambda i: _size_key(i["value"]))
        else:
            items.sort(key=lambda i: (-i["count"], i["value"].casefold()))
        # A chosen value stays visible even when it would fall off the end.
        head = items[:MAX_VALUES]
        tail = [i for i in items[MAX_VALUES:] if i["selected"]]
        if head or tail:
            out[facet] = head + tail
    return out
