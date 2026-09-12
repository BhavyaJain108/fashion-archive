"""Field-fill report: what fraction of stored products carry each E0005 field.

The point of a scrape is not the row count, it is how much of each row is filled.
Run: python -m backend.archive.report [domain ...]
"""

import sys

from backend.archive.store.catalog import Catalog
from backend.archive.store.objects import object_store

FIELDS = (
    "product_title",
    "price",
    "currency",
    "in_stock",
    "all_images",
    "size_info",
    "size_availability",
    "color_info",
    "material_info",
    "description",
    "product_code",
)


def fill(rows: list[dict]) -> dict[str, float]:
    return {f: sum(1 for r in rows if r.get(f) not in (None, "", [])) / len(rows) for f in FIELDS}


def _lane(catalog: Catalog, domain: str) -> str:
    plan = catalog.load_plan(domain)
    if plan is None:
        return "—"
    # "t0xsitemapxstructured_dataxper_item" is the full composition; the middle two
    # are what actually decide what a brand yields.
    parts = plan.composition.split("\u00d7")
    return "×".join(parts[:3]) if len(parts) >= 3 else plan.composition


def main(argv: list[str]) -> int:
    catalog = Catalog(object_store())
    try:
        status = {r["domain"]: r for r in catalog.status_rows()}
        domains = argv or [d for d, r in status.items() if r["products"] or r["state"] != "new"]
        head = f"{'BRAND':<26}{'LANE':<34}{'STATE':<13}{'N':>6}  "
        head += "".join(f"{f[:9]:>10}" for f in FIELDS)
        print(head)
        for d in domains:
            row = status.get(d, {})
            state = row.get("state", "—")
            lane = _lane(catalog, d)
            rows = catalog.current_products(d)
            if not rows:
                print(f"{d:<26}{lane:<34}{state:<13}{0:>6}  (nothing stored)")
                continue
            pct = fill(rows)
            print(
                f"{d:<26}{lane:<34}{state:<13}{len(rows):>6}  "
                + "".join(f"{pct[f]:>9.0%} " for f in FIELDS)
            )
        return 0
    finally:
        catalog.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
