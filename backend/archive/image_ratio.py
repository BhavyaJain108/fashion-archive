"""Each product's photograph proportions, known before the grid draws.

The shop grid keeps every photograph at its own proportions and wants same-shaped
pictures on the same row. That is only possible without anything moving on load if
the ratio is in the row the page reads, not measured in the browser.

Two sources. Shopify's product JSON carries width and height for every image, so
half the catalogue is one UPDATE. The rest is read off the small picture itself,
in the background, once. A picture that cannot be read is marked 0 so it is not
tried on every boot; the grid treats 0 as unknown.
"""

from __future__ import annotations

import io
import threading
from concurrent.futures import ThreadPoolExecutor

# The image entry whose src is the main photograph, else the first; only entries
# that carry both dimensions.
_FROM_RAW = """
UPDATE products p SET image_ratio = q.ratio
FROM (
  SELECT p.brand, p.itemurl, x.ratio
  FROM products p
  JOIN product_raw r ON r.brand = p.brand AND r.itemurl = p.itemurl
  CROSS JOIN LATERAL (
    SELECT (e.img->>'width')::real / NULLIF((e.img->>'height')::real, 0) AS ratio
    FROM jsonb_array_elements(
      CASE WHEN jsonb_typeof(r.raw->'images') = 'array' THEN r.raw->'images' ELSE '[]'::jsonb END
    ) WITH ORDINALITY AS e(img, n)
    WHERE e.img->>'width' IS NOT NULL AND e.img->>'height' IS NOT NULL
    ORDER BY (split_part(e.img->>'src', '?', 1) = split_part(coalesce(p.main_image_url, ''), '?', 1)) DESC, e.n
    LIMIT 1
  ) x
  WHERE p.image_ratio IS NULL
) q
WHERE q.brand = p.brand AND q.itemurl = p.itemurl AND q.ratio > 0
"""

_UNKNOWN = """
SELECT brand, itemurl, coalesce(p.main_image_url, p.all_images->>0) AS main_image_url,
       (SELECT i.stored_url FROM product_images i
          WHERE i.brand = p.brand AND i.itemurl = p.itemurl AND i.stored_url IS NOT NULL
          ORDER BY (i.url = p.main_image_url) DESC, i.updated_at LIMIT 1) AS stored_url
FROM products p
WHERE p.image_ratio IS NULL AND p.last_covered_run IS NOT NULL
  AND (p.main_image_url IS NOT NULL OR jsonb_array_length(p.all_images) > 0)
ORDER BY p.brand, p.itemurl
LIMIT %(limit)s
"""

_SET = (
    "UPDATE products SET image_ratio = %(ratio)s WHERE brand = %(brand)s AND itemurl = %(itemurl)s"
)


def fill_from_raw(pool) -> int:
    """Ratios the shops already published. Returns how many rows were filled."""
    with pool.connection() as conn:
        return conn.execute(_FROM_RAW).rowcount


def read_ratio(row: dict) -> float:
    """Open the small picture and divide. 0 when nothing readable."""
    from PIL import Image

    from backend.archive.tagging import fetch_image, photo_sources

    for src in photo_sources(row):
        try:
            got = fetch_image(src, width=200)
        except Exception:  # noqa: BLE001 — try the next source
            continue
        if got is None:
            continue
        try:
            w, h = Image.open(io.BytesIO(got[0])).size
        except Exception:  # noqa: BLE001
            continue
        if w > 0 and h > 0:
            return round(w / h, 4)
    return 0.0


def fill_by_reading(pool, *, limit: int = 30000, workers: int = 4, log=print) -> dict:
    """Read the rest off the pictures themselves. Writes each answer as it arrives."""
    with pool.connection() as conn:
        rows = [
            dict(zip(("brand", "itemurl", "main_image_url", "stored_url"), r, strict=True))
            for r in conn.execute(_UNKNOWN, {"limit": limit}).fetchall()
        ]
    if not rows:
        return {"read": 0, "unknown": 0}
    log(f"image ratio: reading {len(rows)} picture(s)")
    read = unknown = 0
    lock = threading.Lock()

    def one(row: dict) -> None:
        nonlocal read, unknown
        ratio = read_ratio(row)
        with pool.connection() as conn:
            conn.execute(_SET, {"ratio": ratio, "brand": row["brand"], "itemurl": row["itemurl"]})
        with lock:
            if ratio > 0:
                read += 1
            else:
                unknown += 1
            if (read + unknown) % 500 == 0:
                log(f"image ratio: {read + unknown}/{len(rows)}")

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, rows))
    log(f"image ratio: read {read}, unknown {unknown}")
    return {"read": read, "unknown": unknown}


def fill_on_boot(log=print) -> None:
    """On the Postgres backend: the SQL pass, then the pictures, in the background."""
    from backend.archive.store.pg_catalog import shared_pool

    pool = shared_pool()

    def go() -> None:
        try:
            n = fill_from_raw(pool)
            if n:
                log(f"image ratio: {n} from the shops' own image data")
            fill_by_reading(pool, log=log)
        except Exception as e:  # noqa: BLE001
            log(f"image ratio: stopped: {type(e).__name__}: {e}")

    threading.Thread(target=go, name="image-ratio", daemon=True).start()


if __name__ == "__main__":
    import argparse

    from backend.archive.store.pg_catalog import shared_pool

    ap = argparse.ArgumentParser(description="Fill products.image_ratio")
    ap.add_argument("--limit", type=int, default=30000)
    ap.add_argument("--dsn", default=None)
    a = ap.parse_args()
    p = shared_pool(a.dsn)
    print("from raw:", fill_from_raw(p))
    print(fill_by_reading(p, limit=a.limit))
