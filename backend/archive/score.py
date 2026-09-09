"""How well did this run do — the same four numbers whether it ran live or on replay.

One function, used by both loops. If a replay scored differently from a live run the
offline loop would be worthless, so extraction is handed records and never told where
they came from.

    required_ok          the gate: a shop cannot sell without a name, a price, a stock
                         state and a picture, so a blank in one of those is our failure
                         and the run did not succeed, whatever else it collected
    fields_filled        share of E0005's 42 fields carrying a value, averaged per product
    images_per_product   and how many products have none at all
    cost_usd             what the run's LLM calls cost, taken from the API's own usage
    seconds_per_product  wall clock divided by what was stored
"""

from dataclasses import asdict, dataclass

from backend.archive.domain.product import E0005_FIELDS, is_complete

# Guaranteed by the sale: a shop cannot transact without these, so a blank is never the
# brand's choice. all_images sits here deliberately — a shop that sells clothes shows
# them, and "one image" is a hero shot rather than a gallery (is_complete knows this).
REQUIRED = (
    "itemurl",
    "product_title",
    "price",
    "in_stock",
    "main_image_url",
    "all_images",
)


@dataclass
class Scorecard:
    products: int
    required_ok: bool
    required_gaps: dict[str, float]  # field -> share of products missing it
    fields_filled: float
    field_fill: dict[str, float]  # per field, so a regression is visible at all
    images_per_product: float
    products_without_image: int
    cost_usd: float
    seconds_per_product: float

    def as_dict(self) -> dict:
        return asdict(self)


def score(records, seconds: float = 0.0, cost_usd: float = 0.0) -> Scorecard:
    """Score a set of product records. Works on live records or replayed ones."""
    n = len(records)
    if not n:
        return Scorecard(0, False, {}, 0.0, {}, 0.0, 0, cost_usd, 0.0)

    gaps = {}
    for field in REQUIRED:
        missing = sum(1 for r in records if not is_complete(r, field))
        if missing:
            gaps[field] = round(missing / n, 4)

    per_field = {
        f: round(sum(1 for r in records if is_complete(r, f)) / n, 4) for f in E0005_FIELDS
    }
    filled = sum(per_field.values()) / len(E0005_FIELDS)

    images = [len(r.image_list()) if hasattr(r, "image_list") else 0 for r in records]

    return Scorecard(
        products=n,
        required_ok=not gaps,
        required_gaps=gaps,
        fields_filled=round(filled, 4),
        field_fill=per_field,
        images_per_product=round(sum(images) / n, 2),
        products_without_image=sum(1 for i in images if i == 0),
        cost_usd=round(cost_usd, 4),
        seconds_per_product=round(seconds / n, 3) if seconds else 0.0,
    )


# A field has to have been worth something to have lost something, and small movements
# are a shop changing its stock rather than us breaking an extractor.
_WAS_WORKING = 0.20
_MATERIAL_DROP = 0.10


def regressions(before: dict, after: dict) -> list[tuple[str, float, float]]:
    """Fields that were being filled and are not any more.

    Clearing wiacollections' rules to start it cold lost the description rule with
    them: 98% to 0%, invisible in an aggregate that only moved a couple of points.
    """
    old, new = before.get("field_fill") or {}, after.get("field_fill") or {}
    out = []
    for field, was in old.items():
        now = new.get(field, 0.0)
        if was >= _WAS_WORKING and was - now >= _MATERIAL_DROP:
            out.append((field, was, now))
    return sorted(out, key=lambda x: x[1] - x[2], reverse=True)
