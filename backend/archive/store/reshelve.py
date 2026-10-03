"""Re-derive the shop columns for rows already in the catalogue.

Everything here is computed from fields the rows already hold, so nothing is fetched and
no scrape is needed. It exists because derived columns are written at scrape time, and a
change to how they are derived would otherwise reach a product only on its next run —
which for 72,851 products is days, and for a paused brand is never.

Three columns, and the reason each needs a pass:

  `shop_group` / `shop_bucket` — `storefront.classify` has consulted the shared phrase
  book since 2026-10-02, and the Postgres write path had been calling it without the book
  since the migration. 3,226 products sat in "Everything else" that the book could name.
  `product_gender` — new, and derivable from the shop's own words.
  `sizes_in_stock` — new, derivable from the two parallel size lists.

    python -m backend.archive.store.reshelve --dry-run
    python -m backend.archive.store.reshelve

Rows are read and written in batches of `BATCH`, with one UPDATE ... FROM (VALUES …) per
batch rather than a statement per row: a round trip per product is an hour of waiting.
Only rows whose columns actually change are written.
"""

from __future__ import annotations

import argparse
import os

from backend.archive import audience, taxonomy
from backend.archive import storefront as shop

BATCH = 1000

_READ = """
SELECT brand, itemurl, categories, title, additional_tags, color_info,
       size_info, size_availability, shop_group, shop_bucket, shop_colour,
       product_gender, sizes_in_stock
FROM products ORDER BY brand, itemurl
"""

# The computed rows are streamed into a temporary table with COPY and applied in one
# statement at the end. The first version sent a batch of 1,000 as parallel arrays and
# joined on them per batch: the planner would not use the primary key for that join, and
# 13,000 rows took half an hour. A COPY plus one indexed UPDATE is the whole table in
# seconds.
_TMP = """
CREATE TEMP TABLE reshelve_tmp (
    brand text, itemurl text, shop_group text, shop_bucket text, shop_colour text,
    product_gender text, sizes_text text
) ON COMMIT DROP
"""

_APPLY = """
UPDATE products AS p SET
    shop_group = v.shop_group, shop_bucket = v.shop_bucket, shop_colour = v.shop_colour,
    product_gender = v.product_gender,
    -- a row's sizes travel as one string: a column of arrays cannot be unnested per
    -- row, and no size contains the separator (they were split on commas upstream)
    sizes_in_stock = CASE WHEN v.sizes_text = '' THEN '{}'::text[]
                         ELSE string_to_array(v.sizes_text, E'\\x1f') END
FROM reshelve_tmp AS v
WHERE p.brand = v.brand AND p.itemurl = v.itemurl
"""

_COLS = (
    "brand",
    "itemurl",
    "categories",
    "title",
    "additional_tags",
    "color_info",
    "size_info",
    "size_availability",
    "shop_group",
    "shop_bucket",
    "shop_colour",
    "product_gender",
    "sizes_in_stock",
)


def shelf_of(row: dict, book) -> tuple:
    """What the five derived columns should be for one row.

    The record is rebuilt from the columns rather than read from `record`, which is the
    biggest field in the table: classify and colour only look at the category path, the
    title, the colour text and the tags, and all four are columns of their own.
    """
    record = {f"category{i + 1}": c for i, c in enumerate(row["categories"] or [])}
    record.update(
        product_title=row["title"],
        additional_tags=row["additional_tags"],
        color_info=row["color_info"],
        size_info=row["size_info"],
        size_availability=row["size_availability"],
        itemurl=row["itemurl"],
    )
    group, bucket = shop.classify(record, book)
    return (
        group,
        bucket,
        shop.colour(record),
        audience.of_product(record),
        audience.sizes_in_stock(record),
    )


def _plan(pool, book, log) -> tuple[list[tuple], int, int]:
    """Read every row and work out which ones need new columns.

    The read is a server-side cursor so 72,851 rows are never all in the client at
    once; what is kept is one small tuple per row that actually changes.
    """
    rows: list[tuple] = []
    seen = moved_out_of_other = 0
    with pool.connection() as conn, conn.cursor(name="reshelve") as cur:
        cur.itersize = BATCH
        cur.execute(_READ)
        for r in cur:
            row = dict(zip(_COLS, r, strict=True))
            seen += 1
            want = shelf_of(row, book)
            have = (
                row["shop_group"],
                row["shop_bucket"],
                row["shop_colour"],
                row["product_gender"],
                list(row["sizes_in_stock"] or []),
            )
            if want == have:
                continue
            if (row["shop_group"], row["shop_bucket"]) == shop.OTHER and want[:2] != shop.OTHER:
                moved_out_of_other += 1
            rows.append(
                (
                    row["brand"],
                    row["itemurl"],
                    want[0],
                    want[1],
                    want[2],
                    want[3],
                    "\x1f".join(want[4]),
                )
            )
            if len(rows) % 10000 == 0:
                log(f"  {seen} read, {len(rows)} to write")
    return rows, seen, moved_out_of_other


def reshelve(pool, store, *, dry_run: bool = False, log=print) -> dict:
    book = taxonomy.load(store)
    log(f"phrase book: {len(book.entries)} phrases")
    rows, seen, moved_out_of_other = _plan(pool, book, log)

    written = 0
    if rows and not dry_run:
        with pool.connection() as conn:
            conn.execute(_TMP)
            with conn.cursor().copy(
                "COPY reshelve_tmp (brand, itemurl, shop_group, shop_bucket, shop_colour,"
                " product_gender, sizes_text) FROM STDIN"
            ) as copier:
                for row in rows:
                    copier.write_row(row)
            with conn.cursor() as cur:
                cur.execute(_APPLY)
                written = cur.rowcount
        log(f"  applied in one statement: {written} rows")
    out = {
        "read": seen,
        "changed": len(rows),
        "written": written,
        "left_everything_else": moved_out_of_other,
        "dry_run": dry_run,
    }
    log(f"reshelve: {out}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="count what would change, write nothing")
    ap.add_argument("--dsn", default=os.environ.get("DATABASE_URL"))
    args = ap.parse_args()

    from backend.archive.store.objects import object_store
    from backend.archive.store.pg_catalog import shared_pool

    reshelve(shared_pool(args.dsn), object_store(None), dry_run=args.dry_run)


if __name__ == "__main__":
    main()
