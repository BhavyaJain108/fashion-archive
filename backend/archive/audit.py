"""E0005 completeness audit — offline, no network, no LLM.

A fill percentage is not an answer, because E0005's 42 fields are not one kind of thing.
They differ by where the truth lives, and that decides how each one is obtained and what
a blank means:

  A GUARANTEED   The shop cannot transact without it — a name, a link, a price, a
                 picture. A blank here is always our bug, never the brand's choice.
  B EDITORIAL    Published when the brand bothers. twofoldvintage's descriptions are
                 literally "<p> </p>". A blank is a fact about the brand; the honest
                 measure is recall against what the brand actually publishes.
  C VARIANT      One structure written five ways. Labels and availability are public —
                 you cannot sell a size nobody can select. Exact counts are commercially
                 secret: Shopify strips inventory_quantity from its public feed on
                 purpose, so those blanks are withheld, not missed.
  D DERIVED      Nothing to extract. A promotion exists iff full_price > price. These
                 are computed in the mapper or they are wrong.
  E CODES        A code without its type is noise: "4901234567894" only means something
                 labelled gtin13. Written as pairs or not at all.
  F TAXONOMY     A path, root to leaf. Tags are a flat set and are NOT a path — filling
                 category6..10 from leftover tags manufactures a hierarchy that does not
                 exist, which is worse than leaving them blank.
  G NOT APPAREL  E0005 is a general commerce schema. A t-shirt has no price-per-litre.
                 Declared not-applicable once, not measured per brand forever.

Every product keeps its channel payload, so "we never mapped it" can be told apart from
"the channel never said it" without fetching anything.

Run: python -m backend.archive.audit [domain ...]
"""

import json
import sys

from backend.archive.domain.product import E0005_FIELDS, ProductRecord
from backend.archive.evidence import describe
from backend.archive.store.catalog import Catalog
from backend.archive.store.objects import object_store

A_GUARANTEED = (
    "itemurl",
    "product_title",
    "product_code",
    "brand",
    "price",
    "in_stock",
    "main_image_url",
    "all_images",
)
B_EDITORIAL = ("description", "additional_content", "specifications", "color_info", "material_info")
C_VARIANT = ("size_info", "size_availability", "size_stock_counts", "variant_info", "quantity")
D_DERIVED = ("full_price", "promotion_type", "promotion_end_date")
E_CODES = (
    ("additional_code_1", "additional_code_1_type"),
    ("additional_code_2", "additional_code_2_type"),
    ("additional_code_3", "additional_code_3_type"),
)
F_TAXONOMY = tuple(f"category{i}" for i in range(1, 11))
G_NOT_APPAREL = ("ppu", "unit_type", "package_desc", "delivery")
H_TAGS = ("additional_tags",)

CLASSES = (
    ("A  guaranteed by the sale", A_GUARANTEED, "must be 100% — a blank is our bug"),
    ("B  editorial", B_EDITORIAL, "recall against what the brand publishes"),
    ("C  variant structure", C_VARIANT, "labels public, counts withheld"),
    ("D  derived", D_DERIVED, "computed from other fields, never extracted"),
    ("E  codes", tuple(f for pair in E_CODES for f in pair), "written as code+type pairs"),
    ("F  taxonomy", F_TAXONOMY, "a path — no holes, no tags stuffed in"),
    ("G  not applicable to apparel", G_NOT_APPAREL, "declared N/A, not chased"),
    ("H  tags", H_TAGS, "the brand's own flat labels"),
)

MODELLED = frozenset(ProductRecord.model_fields) - {"raw", "currency"}

# Where a value would already be sitting in the payload we stored. Key names only: the
# search is recursive, so one table covers Shopify product JSON, WooCommerce objects and
# schema.org JSON-LD without needing to know which is which.
PAYLOAD_KEYS: dict[str, tuple[str, ...]] = {
    "specifications": ("additionalProperty", "specifications"),
    # NOT body_html: that is the description, and a field already carried elsewhere is
    # not "held data" for a field defined as whatever no other field captures.
    # Barcode-style only. The brand's own sku is product_code, not one of these.
    "additional_code_1": ("barcode", "gtin13", "gtin12", "gtin8", "gtin", "ean", "upc", "mpn"),
    "variant_info": ("variants", "hasVariant", "options"),
    "promotion_type": ("compare_at_price", "sale_price", "on_sale"),
    "promotion_end_date": ("sale_price_dates_to", "priceValidUntil"),
    "additional_tags": ("tags", "keywords"),
    "brand": ("vendor", "brand"),
    "color_info": ("color", "colour"),
    "material_info": ("material", "fabric"),
    "quantity": ("inventory_quantity", "stock_quantity", "quantityAvailable"),
    "size_stock_counts": ("inventory_quantity", "stock_quantity", "quantityAvailable"),
    "delivery": ("shippingDetails", "shipping"),
    # NOT weight/grams: shipping weight is not multipack or packaging information.
    "unit_type": ("unitCode",),
}


def filled(value) -> bool:
    return value not in (None, "", [], {})


def payload_has(raw, keys: tuple[str, ...]) -> bool:
    """Is any of these keys present with a non-empty value, anywhere in the payload?"""
    if isinstance(raw, dict):
        for key, value in raw.items():
            if key in keys and filled(value):
                return True
            if payload_has(value, keys):
                return True
        return False
    if isinstance(raw, list):
        return any(payload_has(item, keys) for item in raw)
    return False


def _parts(value) -> list[str]:
    return [p.strip() for p in (value or "").split(",")] if value else []


def check_invariants(row: dict) -> list[str]:
    """Contradictions inside a single stored row.

    These are the checks that say whether the data can be trusted at all. A row can have
    every field filled and still be nonsense if its fields disagree with each other.
    """
    bad = []
    sizes, avail, counts = (
        _parts(row.get(f)) for f in ("size_info", "size_availability", "size_stock_counts")
    )
    if avail and len(avail) != len(sizes):
        bad.append("size_availability not parallel to size_info")
    if counts and len(counts) != len(sizes):
        bad.append("size_stock_counts not parallel to size_info")
    if avail and row.get("in_stock") is not None:
        any_available = any("in_stock" in a or a.lower() in ("true", "yes") for a in avail)
        if any_available != bool(row["in_stock"]):
            bad.append("in_stock disagrees with size_availability")
    # A category path with a hole means the levels no longer describe a hierarchy.
    path = [row.get(f) for f in F_TAXONOMY if f in MODELLED]
    seen_blank = False
    for level in path:
        if not filled(level):
            seen_blank = True
        elif seen_blank:
            bad.append("category path has a hole")
            break
    if filled(row.get("full_price")) and filled(row.get("price")):
        if float(row["full_price"]) <= float(row["price"]):
            bad.append("full_price not above price")
    images = row.get("all_images")
    if filled(images) and filled(row.get("main_image_url")):
        try:
            # An image CDN serves renditions of one asset off one path: the gallery
            # entry carries "&width=2048&crop=center" where the channel's URL does not.
            # Comparing whole URLs called 300 identical photographs a contradiction.
            gallery = {u.split("?")[0] for u in json.loads(str(images))}
            if row["main_image_url"].split("?")[0] not in gallery:
                bad.append("main_image_url missing from all_images")
        except (json.JSONDecodeError, TypeError):
            bad.append("all_images is not a JSON array")
    return bad


def verdict(field: str, rows: list[dict]) -> tuple[str, float]:
    """One verdict per field for one brand, plus its fill rate."""
    if field in MODELLED:
        hits = sum(1 for r in rows if filled(r.get(field)))
        if hits:
            return "filled", hits / len(rows)
    keys = PAYLOAD_KEYS.get(field)
    in_payload = bool(keys) and any(payload_has(r.get("raw") or {}, keys or ()) for r in rows)
    if field not in MODELLED:
        return ("unmapped, data held" if in_payload else "unmapped"), 0.0
    return ("empty, data held" if in_payload else "channel silent"), 0.0


def main(argv: list[str]) -> int:
    catalog = Catalog(object_store())
    try:
        domains = argv or [
            r["domain"] for r in catalog.status_rows() if catalog.current_products(r["domain"])
        ]
        brands = {d: catalog.current_products(d) for d in domains}
        brands = {d: rows for d, rows in brands.items() if rows}
        if not brands:
            print("nothing stored")
            return 0
        total = sum(len(r) for r in brands.values())
        print(f"E0005 audit — {len(brands)} brands, {total} products\n")

        for title, fields, rule in CLASSES:
            print(f"{title}  ({rule})")
            for field in fields:
                verdicts = [verdict(field, rows) for rows in brands.values()]
                complete = sum(1 for v, pct in verdicts if pct >= 0.999)
                partial = sum(1 for v, pct in verdicts if 0 < pct < 0.999)
                held = sum(1 for v, _ in verdicts if "data held" in v)
                silent = sum(1 for v, _ in verdicts if v == "channel silent")
                note = []
                if complete:
                    note.append(f"{complete} complete")
                if partial:
                    note.append(f"{partial} partial")
                if held:
                    note.append(f"{held} DATA ALREADY HELD")
                if silent:
                    note.append(f"{silent} channel silent")
                unmapped = "" if field in MODELLED else "  [not in ProductRecord]"
                print(f"   {field:<24}{', '.join(note) or 'nothing':<44}{unmapped}")
            print()

        print("INVARIANTS — rows that contradict themselves")
        tally: dict[str, int] = {}
        worst: dict[str, str] = {}
        for d, rows in brands.items():
            for row in rows:
                for problem in check_invariants(row):
                    tally[problem] = tally.get(problem, 0) + 1
                    worst.setdefault(problem, d)
        if not tally:
            print("   none")
        for problem, n in sorted(tally.items(), key=lambda x: -x[1]):
            print(f"   {problem:<44}{n:>6} rows   (first seen: {worst[problem]})")

        print("\nWHY A FIELD IS BLANK — what each run actually searched")
        ev = {d: catalog.load_evidence(d) for d in brands}
        unsearched: dict[str, int] = {}
        evidenced: dict[str, int] = {}
        for field in E0005_FIELDS:
            for d, rows in brands.items():
                if any(filled(r.get(field)) for r in rows):
                    continue
                verdict_text = describe(ev.get(d, {}), field)
                if verdict_text.startswith("absent from"):
                    evidenced[field] = evidenced.get(field, 0) + 1
                else:
                    unsearched[field] = unsearched.get(field, 0) + 1
        if not ev or not any(ev.values()):
            print("   no evidence recorded yet — re-run the brands to collect it")
        else:
            print(f"   {'FIELD':<26}{'BLANK+EVIDENCED':>16}{'BLANK+UNSEARCHED':>18}")
            for field in E0005_FIELDS:
                if evidenced.get(field) or unsearched.get(field):
                    print(
                        f"   {field:<26}{evidenced.get(field, 0):>16}{unsearched.get(field, 0):>18}"
                    )

        print("\nCLASS A — the fields that must never be blank")
        for d, rows in sorted(brands.items()):
            gaps = [
                f"{f} {sum(1 for r in rows if filled(r.get(f))) / len(rows):.0%}"
                for f in A_GUARANTEED
                if f in MODELLED and sum(1 for r in rows if filled(r.get(f))) < len(rows)
            ]
            if gaps:
                print(f"   {d:<26}{', '.join(gaps)}")
        return 0
    finally:
        catalog.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
