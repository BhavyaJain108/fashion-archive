"""Open tags for every product: what one photograph and the shop's own words say it is.

The model is asked for as many short phrases as truthfully describe the piece —
garment, cut, collar, closure, cloth, pattern, every colour it can see, mood,
season — and nothing it cannot see or read. No schema: the vocabulary is learned
later from what appears often, and a rare phrase still matches in search.

One 400px photograph is enough to see a collar, a hem and a colour, and costs a
quarter of an 800px one. Measured on the first product: 501 tokens in, 265 out,
three seconds, about $0.002 on Haiku.

Runs where the database is. At boot the API tags until TAG_TRIAL products carry
tags (a bounded spend); `python -m backend.archive.tagging` does the same by hand.
"""

from __future__ import annotations

import argparse
import os
import re
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast

from psycopg.types.json import Jsonb

MODEL = os.getenv("TAGGER_MODEL", "claude-haiku-4-5")
VERSION = "2"  # bump when the prompt changes; products are re-tagged under the new version
IMAGE_WIDTH = 400
IMAGE_BYTES_MAX = 2_000_000
# Haiku 4.5 list prices, dollars per million tokens, for the summary line only.
_USD_IN, _USD_OUT = 1.0, 5.0

PROMPT = """Tag this fashion product for a searchable archive. Give as many short lowercase
tags (single words or 2-3 word phrases) as truthfully describe it: garment type, cut
and fit, silhouette, length, collar or neckline, sleeve, closure, fabric look, pattern,
the garment's colours, details, style or mood, occasion, season, and the gender it is
presented for. Only what is visible in the photograph or stated in the text. Do not
guess fabric from a picture. No brand names, no sentences.

Leave out words that fit almost anything: casual, unisex, contemporary, modern, everyday,
stylish, versatile. Use one spelling: singular parts (long sleeve, short sleeve, crew
neck), "oversized" not "oversized fit", "women" and "men" not possessives, "grey" not
"gray", "t-shirt" not "tee". Name only the garment's colours, never the background.

Shop title: {title}
Price: {price}
Material, as the shop states it: {material}
Shop description: {description}"""

TAG_TOOL = {
    "name": "tag_product",
    "description": "Every short tag that truthfully describes the product.",
    "input_schema": {
        "type": "object",
        "properties": {
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "lowercase, short",
            }
        },
        "required": ["tags"],
    },
}

_WS = re.compile(r"\s+")
_EDGE = re.compile(r"^[^\w]+|[^\w]+$", re.UNICODE)


def normalise(tags: list[Any]) -> list[str]:
    """Lowercase, single-spaced, no leading or trailing punctuation, no repeats,
    nothing longer than a short phrase."""
    out: list[str] = []
    for t in tags:
        s = _EDGE.sub("", _WS.sub(" ", str(t).strip().lower()))
        if s and len(s) <= 40 and s not in out:
            out.append(s)
    return out


def fetch_image(url: str, width: int = IMAGE_WIDTH) -> tuple[bytes, str] | None:
    """The shop's photograph at a small width. Shopify's CDN resizes on `?width=`;
    other hosts get the original, capped by size."""
    if not url:
        return None
    base = url.split("?")[0]
    src = f"{base}?width={width}" if "cdn.shopify.com" in base else base
    req = urllib.request.Request(
        src, headers={"User-Agent": "Mozilla/5.0 (fashion-archive tagger)"}
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        data = r.read(IMAGE_BYTES_MAX + 1)
    if not data or len(data) > IMAGE_BYTES_MAX:
        return None
    if data[:4] == b"\x89PNG":
        return data, "image/png"
    if data[8:12] == b"WEBP":
        return data, "image/webp"
    if data[:3] == b"\xff\xd8\xff":
        return data, "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return data, "image/gif"  # some jewellery shops publish a turning-ring animation
    return None


def colours(data: bytes, keep: int = 3) -> list[list]:
    """The garment's own colours from the pixels: drop everything near the border
    colour (the studio background), quantise the rest, keep the biggest `keep` as
    [hex, share]. Deterministic and free; a black coat on white stays black, but a
    model's skin or a prop counts as garment — the tags say which."""
    import io
    from collections import Counter

    from PIL import Image

    im = Image.open(io.BytesIO(data)).convert("RGB")
    im.thumbnail((80, 80))
    w, h = im.size
    px = list(im.getdata())
    border = (
        px[:w]
        + px[(h - 1) * w :]
        + [px[r * w] for r in range(h)]
        + [px[r * w + w - 1] for r in range(h)]
    )
    bg = tuple(sorted(c[k] for c in border)[len(border) // 2] for k in range(3))
    kept = [c for c in px if sum((a - b) ** 2 for a, b in zip(c, bg, strict=True)) > 40**2]
    if len(kept) < 20:
        return []
    strip = Image.new("RGB", (len(kept), 1))
    strip.putdata(kept)
    q = strip.quantize(colors=4, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette() or []
    counts = Counter(q.getdata())
    total = sum(counts.values())
    out = []
    for idx, n in counts.most_common(keep):
        r, g, b = pal[idx * 3 : idx * 3 + 3]
        out.append([f"#{r:02x}{g:02x}{b:02x}", round(n / total, 2)])
    return out


class Tagger:
    def __init__(self, model: str = MODEL):
        import anthropic

        from backend.archive.finder_llm import _api_key, _workspace_id

        key = _api_key()
        if not key:
            raise RuntimeError("No API key: set ANTHROPIC_API_KEY or CLAUDE_API_KEY")
        workspace = _workspace_id()
        headers = {"anthropic-workspace-id": workspace} if workspace else None
        self._c = anthropic.Anthropic(api_key=key, default_headers=headers)
        self.model = model

    def tag(self, row: dict, image: tuple[bytes, str]) -> dict:
        import base64

        data, media = image
        price = (
            f"{row.get('price')} {row.get('currency') or ''}".strip()
            if row.get("price")
            else "not stated"
        )
        prompt = PROMPT.format(
            title=row.get("title") or "",
            price=price,
            material=(row.get("material_info") or "not stated")[:200],
            description=(row.get("description") or "none")[:700],
        )
        msg = self._c.messages.create(
            model=self.model,
            max_tokens=600,
            tools=cast(Any, [TAG_TOOL]),
            tool_choice=cast(Any, {"type": "tool", "name": TAG_TOOL["name"]}),
            messages=[
                {
                    "role": "user",
                    "content": cast(
                        Any,
                        [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media,
                                    "data": base64.b64encode(data).decode(),
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    ),
                }
            ],
        )
        tags: list[str] = []
        for block in msg.content:
            if block.type == "tool_use":
                tags = normalise(list(cast(dict, block.input).get("tags") or []))
        usage = getattr(msg, "usage", None)
        return {
            "tags": tags,
            "input_tokens": getattr(usage, "input_tokens", 0) or 0,
            "output_tokens": getattr(usage, "output_tokens", 0) or 0,
        }


# --- the database side --------------------------------------------------------

_CANDIDATES = """
SELECT brand, itemurl, title, description, price, currency, material_info, main_image_url, stored_url
FROM (
  SELECT p.brand, p.itemurl, p.title, p.description, p.price, p.currency, p.material_info,
         COALESCE(p.main_image_url, p.all_images->>0) AS main_image_url,
         (SELECT i.stored_url FROM product_images i
            WHERE i.brand = p.brand AND i.itemurl = p.itemurl AND i.stored_url IS NOT NULL
            ORDER BY (i.url = p.main_image_url) DESC, i.updated_at LIMIT 1) AS stored_url,
         row_number() OVER (PARTITION BY p.brand ORDER BY p.first_seen_run DESC, p.itemurl) AS n
  FROM products p
  JOIN catalogue_brands b ON b.brand = p.brand AND b.live_run = p.last_covered_run
  LEFT JOIN product_tags t ON t.brand = p.brand AND t.itemurl = p.itemurl AND t.version = %(version)s
  WHERE t.brand IS NULL AND (p.main_image_url IS NOT NULL OR jsonb_array_length(p.all_images) > 0)
    AND (%(brands)s::text[] IS NULL OR p.brand = ANY(%(brands)s::text[]))
) c
WHERE n <= %(per_brand)s
ORDER BY n, brand
LIMIT %(limit)s
"""


def photo_sources(row: dict) -> list[str]:
    """Where to read the photograph from, in order: the shop's own CDN (Shopify
    resizes it for us), then our archived copy — which is what a shop that answers
    403 or times out (viviennewestwood, vancleefarpels) leaves us with."""
    return [u for u in (row.get("main_image_url"), row.get("stored_url")) if u]


_UPSERT = """
INSERT INTO product_tags (brand, itemurl, version, tags, colours, model, image_url, input_tokens, output_tokens)
VALUES (%(brand)s, %(itemurl)s, %(version)s, %(tags)s, %(colours)s, %(model)s, %(image_url)s, %(in)s, %(out)s)
ON CONFLICT (brand, itemurl, version) DO UPDATE SET
  tags = EXCLUDED.tags, colours = EXCLUDED.colours, model = EXCLUDED.model, image_url = EXCLUDED.image_url,
  input_tokens = EXCLUDED.input_tokens, output_tokens = EXCLUDED.output_tokens, tagged_at = now()
"""


def candidates(pool, *, limit: int, per_brand: int, brands: list[str] | None = None) -> list[dict]:
    """Live, untagged products with a photograph, newest first, at most `per_brand`
    from any one brand so a trial sees the whole roster."""
    cols = (
        "brand",
        "itemurl",
        "title",
        "description",
        "price",
        "currency",
        "material_info",
        "main_image_url",
        "stored_url",
    )
    with pool.connection() as conn:
        rows = conn.execute(
            _CANDIDATES,
            {"version": VERSION, "brands": brands, "per_brand": per_brand, "limit": limit},
        ).fetchall()
    return [dict(zip(cols, r, strict=True)) for r in rows]


def tagged_count(pool, version: str = VERSION) -> int:
    with pool.connection() as conn:
        return conn.execute(
            "SELECT count(*) FROM product_tags WHERE version = %s", (version,)
        ).fetchone()[0]


def run(
    pool,
    *,
    limit: int = 200,
    per_brand: int = 40,
    brands: list[str] | None = None,
    workers: int = 4,
    model: str = MODEL,
    log=print,
) -> dict:
    """Tag up to `limit` products and write each answer as it arrives. Returns the
    count and the spend as the API reported it."""
    todo = candidates(pool, limit=limit, per_brand=per_brand, brands=brands)
    if not todo:
        log("tagging: nothing to tag")
        return {"tagged": 0, "failed": 0, "input_tokens": 0, "output_tokens": 0, "usd": 0.0}
    tagger = Tagger(model)
    done = failed = tin = tout = 0
    lock = threading.Lock()
    started = time.time()

    def one(row: dict) -> None:
        nonlocal done, failed, tin, tout
        try:
            image, seen, why = None, "", "no photograph"
            for src in photo_sources(row):
                try:
                    image = fetch_image(src)
                except Exception as e:  # noqa: BLE001 — try the next source
                    why = f"{type(e).__name__}: {e}"
                    continue
                if image is not None:
                    seen = src
                    break
                why = "not an image we can read"
            if image is None:
                raise RuntimeError(f"no usable photograph ({why})")
            got = tagger.tag(row, image)
            try:
                swatches = colours(image[0])
            except Exception:  # noqa: BLE001 — a photograph Pillow cannot open still gets its tags
                swatches = []
            with pool.connection() as conn:
                conn.execute(
                    _UPSERT,
                    {
                        "brand": row["brand"],
                        "itemurl": row["itemurl"],
                        "version": VERSION,
                        "tags": got["tags"],
                        "colours": Jsonb(swatches),
                        "model": model,
                        "image_url": seen,
                        "in": got["input_tokens"],
                        "out": got["output_tokens"],
                    },
                )
            with lock:
                done += 1
                tin += got["input_tokens"]
                tout += got["output_tokens"]
                if done % 25 == 0 or done == len(todo):
                    log(f"tagging: {done}/{len(todo)} in {time.time() - started:.0f}s")
        except Exception as e:  # noqa: BLE001 — one product's failure must not stop the pass
            with lock:
                failed += 1
            log(f"tagging: {row['brand']} {row['itemurl']}: {type(e).__name__}: {e}")

    log(
        f"tagging: {len(todo)} product(s) across {len({r['brand'] for r in todo})} brand(s), {model}"
    )
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, todo))
    usd = tin / 1e6 * _USD_IN + tout / 1e6 * _USD_OUT
    log(f"tagging: done {done}, failed {failed}, {tin} in / {tout} out, ~${usd:.2f}")
    return {
        "tagged": done,
        "failed": failed,
        "input_tokens": tin,
        "output_tokens": tout,
        "usd": usd,
    }


_running = False


def in_progress() -> bool:
    return _running


def tag_on_boot(log=print) -> None:
    """On the Postgres backend: tag in the background until TAG_TRIAL products carry
    tags under the current prompt version. A bounded spend per prompt version."""
    global _running
    want = int(os.getenv("TAG_TRIAL", "0") or 0)
    if want <= 0:
        return
    from backend.archive.store.pg_catalog import shared_pool

    pool = shared_pool()
    have = tagged_count(pool)
    if have >= want:
        return

    def go() -> None:
        global _running
        try:
            run(pool, limit=want - have, per_brand=max(1, (want - have) // 5), log=log)
        except Exception as e:  # noqa: BLE001
            log(f"tagging: stopped: {type(e).__name__}: {e}")
        finally:
            _running = False

    _running = True
    threading.Thread(target=go, name="catalogue-tagging", daemon=True).start()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Tag live products with open phrases")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--per-brand", type=int, default=40)
    ap.add_argument("--brand", action="append", help="only these roster domains")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--dsn", default=None, help="database URL (default: DATABASE_URL)")
    a = ap.parse_args()
    from backend.archive.store.pg_catalog import shared_pool

    run(shared_pool(a.dsn), limit=a.limit, per_brand=a.per_brand, brands=a.brand, workers=a.workers)
