"""Is each field holding the kind of thing it is supposed to hold?

The per-row invariants in audit.py catch a row that contradicts itself. They cannot catch
a field that is filled, self-consistent, and simply the wrong thing — staud.clothing's
`brand` read "STAUD SPRING DENIM 2026 SALE" on every row and nothing complained.

Those are caught by looking across a brand's whole catalogue, using one observation that
holds for shops in general:

    A field is either IDENTIFYING or CLASSIFYING.

    Identifying — itemurl, product_code, product_title, main_image_url, description.
    It picks out one product, so its values should be nearly all distinct. When many
    products share one value, the field is holding something generic.

    Classifying — brand, currency, category, sizes, colour, material. It says which
    group a product belongs to, so its values must REPEAT. When almost every product has
    its own value, the field is holding something specific, which means it was mapped
    from the wrong place.

Cardinality also says what kind of shop this is, which is why the same rule reads two
opposite results correctly: one distinct brand means a single-label store, hundreds of
unrelated ones means a retailer carrying many labels, and a handful sharing a prefix
("STAUD FALL 2026", "STAUD SUMMER 2026 SALE") means the shop is using the field for
merchandising campaigns and the real brand is the shop itself.

Run: python -m backend.archive.validate [domain ...]
"""

import sys
from collections import Counter
from pathlib import Path

from backend.archive.store.catalog import Catalog

# Should be nearly all distinct: each value points at one product.
IDENTIFYING = ("itemurl", "product_title", "product_code", "main_image_url", "description")
# Should repeat: each value names a group that many products belong to.
CLASSIFYING = (
    "brand",
    "currency",
    "category1",
    "category2",
    "size_info",
    "color_info",
    "material_info",
    "size_availability",
    "promotion_type",
    "unit_type",
)
NUMERIC = ("price", "full_price", "ppu", "quantity")

# Below this share of distinct values, an identifying field is repeating itself.
_MIN_DISTINCT = 0.5
# Above this share, a classifying field is not classifying anything.
_MAX_DISTINCT = 0.9
# Distributions are only meaningful once there are enough values to have one. Judging
# "nearly one value per product" from the 3 products in a catalogue that filled the
# field says nothing about the field; it says the field is mostly empty, which the
# audit already reports.
_MIN_ROWS = 20
_MIN_FILLED = 20


def _values(rows: list[dict], field: str) -> list:
    return [r[field] for r in rows if r.get(field) not in (None, "", [])]


def _shared_prefix(values: list[str]) -> str:
    first, last = min(values), max(values)
    i = 0
    while i < min(len(first), len(last)) and first[i] == last[i]:
        i += 1
    return first[:i].strip()


def check_brand(values: list[str]) -> str | None:
    """One distinct brand is a single-label shop; many unrelated ones a retailer.

    A handful that all start the same way is neither: the shop is putting campaign
    names in the field, and the brand is the shop.
    """
    distinct = sorted(set(values))
    if len(distinct) <= 1:
        return None  # a single-label shop, which is the common and correct case
    # A brand groups products. One value per product is the opposite of grouping:
    # www.thesupermade.com puts SKUs like "SP220224KTBH-US" in the field.
    if len(distinct) / len(values) > _MAX_DISTINCT:
        return (
            f"{len(distinct)} values for {len(values)} products — one each, so these "
            f"identify products rather than group them (e.g. {distinct[0]!r})"
        )
    # Count is the wrong discriminator: staud.clothing publishes 41 campaign names.
    # What separates a campaign list from a retailer's brand list is that campaigns all
    # start with the shop's own name, and unrelated labels share nothing.
    prefix = _shared_prefix(distinct)
    if len(prefix) >= 3:
        return (
            f"{len(distinct)} values that all begin {prefix!r} — merchandising "
            f"campaigns, not brands (e.g. {distinct[0]!r})"
        )
    return None


def brand_name_for(domain: str, values: list[str], display_name: str | None = None) -> str:
    """The best available plain-text brand name for a shop whose brand field is wrong.

    The campaign strings themselves usually carry the answer: "STAUD FALL 2026" and
    "STAUD SUMMER 2026 SALE" share the prefix "STAUD", which is the shop writing its own
    name in its own capitalisation. That is only trustworthy when the prefix matches the
    domain — thesupermade's codes share "SP2", which is not a name — so anything else
    falls back to the domain with its www. and suffix removed.
    """
    if display_name:
        return display_name
    stem = domain.removeprefix("www.").split(".")[0]
    prefix = _shared_prefix(sorted(set(values))) if values else ""
    letters = "".join(c for c in prefix if c.isalnum()).lower()
    if letters and letters == stem.lower():
        return prefix
    return stem


def check_field(field: str, rows: list[dict]) -> str | None:
    values = _values(rows, field)
    if len(values) < _MIN_FILLED or len(rows) < _MIN_ROWS:
        return None
    distinct = len(set(map(str, values)))
    share = distinct / len(values)

    if field == "brand":
        return check_brand([str(v) for v in values])

    if field in IDENTIFYING and share < _MIN_DISTINCT:
        common, n = Counter(map(str, values)).most_common(1)[0]
        return (
            f"only {distinct} distinct values across {len(values)} products; "
            f"{n} of them share {common[:48]!r}"
        )

    if field in CLASSIFYING and share > _MAX_DISTINCT:
        return (
            f"{distinct} distinct values across {len(values)} products — "
            f"nearly one per product, so it is not grouping anything "
            f"(e.g. {str(values[0])[:48]!r})"
        )

    if field in NUMERIC:
        numbers = [float(v) for v in values if isinstance(v, (int, float))]
        if numbers and min(numbers) <= 0:
            return f"{sum(1 for n in numbers if n <= 0)} products priced at or below zero"
        if len(set(numbers)) == 1 and len(numbers) >= _MIN_ROWS:
            return f"every product carries the same value ({numbers[0]})"
    return None


def check_axes(rows: list[dict]) -> str | None:
    """Sizes and colours must not be drawn from the same vocabulary.

    When they are, the shop's option axes were read in the wrong order and the two
    fields are describing each other.
    """
    sizes = {t.strip() for r in _values(rows, "size_info") for t in str(r).split(",")}
    colors = {t.strip() for r in _values(rows, "color_info") for t in str(r).split(",")}
    shared = {s for s in sizes & colors if s}
    if shared and len(shared) * 2 >= min(len(sizes), len(colors)):
        return f"sizes and colours share {len(shared)} values (e.g. {sorted(shared)[:3]})"
    return None


def check_brand_catalogue(rows: list[dict]) -> list[tuple[str, str]]:
    out = []
    for field in (*IDENTIFYING, *CLASSIFYING, *NUMERIC):
        problem = check_field(field, rows)
        if problem:
            out.append((field, problem))
    axes = check_axes(rows)
    if axes:
        out.append(("size_info/color_info", axes))
    return out


def main(argv: list[str]) -> int:
    catalog = Catalog(Path("backend/archive/data/catalog.db"))
    try:
        domains = argv or [r["domain"] for r in catalog.status_rows()]
        total = 0
        for d in domains:
            rows = catalog.current_products(d)
            if len(rows) < _MIN_ROWS:
                continue
            problems = check_brand_catalogue(rows)
            if not problems:
                continue
            print(f"\n{d}  ({len(rows)} products)")
            for field, problem in problems:
                print(f"   {field:<22}{problem}")
            total += len(problems)
        print(f"\n{total} suspect fields across {len(domains)} brands")
        return 0
    finally:
        catalog.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
