"""Who a product is for: women, men, or not stated.

Measured over the live catalogue on 2026-10-02, before any of this existed: of 72,851
products, **80.5% carry no gender word anywhere** — not in the shop's category path, its
tags, the title or the URL. The reason is not that the shops are coy. meshki, tigermist,
iamgia and poster-girl never write "women" because every product they sell is womenswear;
a shop that sells one gender does not label it.

So the answer comes from two places, in this order:

  **the product**, when the shop's own words say so — 14,820 products across 22 brands,
  which is how a mixed shop like bode (1,026 women / 1,601 men) is split correctly;
  **the brand**, from `audience:` in `brands.yml` — the roster is already where this kind
  of judgement about a business is written down, beside `size`, which carries the note
  "Judgement about the business, not something a page announces, so it is written down
  rather than inferred".

A brand marked `all` is a judgement that it dresses everyone — eyewear, jewellery, bags —
and its silent products appear under **both** Women and Men. A brand with no audience at
all is a different thing: nobody has judged it, and its silent products appear under
neither, because putting 8,135 unsexed psylos1 products under Women would make the filter
useless rather than generous.

Kids are deliberately not a third answer. The page offers Women and Men; answering "men"
because the word "boys" appeared would be worse than answering nothing.
"""

from __future__ import annotations

import re
from typing import Any

from backend.archive.finder import looks_like_size

WOMEN = "women"
MEN = "men"
ALL = "all"  # a brand's answer, never a product's: for everyone, so shown under both
UNJUDGED = ""  # no one has said yet; shown under neither
GENDERS = (WOMEN, MEN)
BRAND_AUDIENCES = (WOMEN, MEN, ALL)

# Whole words only. "management" must not read as men, "mangrove" must not read as man.
_WORDS = {
    WOMEN: ("women", "womens", "women's", "woman", "womans", "female", "ladies", "ladys"),
    MEN: ("men", "mens", "men's", "man", "mans", "male"),
}
_PATTERNS = {
    g: re.compile(r"(?<![a-z])(?:" + "|".join(re.escape(w) for w in words) + r")(?![a-z])")
    for g, words in _WORDS.items()
}


def _read(text: str) -> str | None:
    """Which gender this text names, or None when it names both or neither."""
    if not text:
        return None
    found = [g for g, pattern in _PATTERNS.items() if pattern.search(text)]
    return found[0] if len(found) == 1 else None


def _get(record: Any, field: str):
    return record.get(field) if isinstance(record, dict) else getattr(record, field, None)


def _texts(record: Any) -> list[str]:
    """What this product can be read from, strongest evidence first.

    The category path is read leaf-first for the same reason the phrase book reads it
    that way: the leaf says what the thing is, the root says which part of the shop it
    sits in. Vivienne Westwood files men's gifts under `Women > Mens Gifts`, and the
    leaf is the truthful half.
    """
    path = [str(_get(record, f"category{i}") or "").lower() for i in range(1, 11)]
    out = [p for p in reversed(path) if p]
    for field in ("additional_tags", "product_title", "itemurl"):
        value = str(_get(record, field) or "").lower()
        if value:
            out.append(value)
    return out


def of_product(record: Any) -> str | None:
    """What the product's own words say, or None.

    Each source is read on its own and the first that names exactly one gender wins, so
    a tag list naming both does not cancel a category path that was clear.
    """
    for text in _texts(record):
        got = _read(text)
        if got:
            return got
    return None


def of(brand: str, record: Any, by_brand: dict[str, str]) -> str | None:
    """Who this product is for: its own words, else its brand's written-down audience."""
    said = of_product(record)
    if said:
        return said
    brand_says = (by_brand.get(brand) or "").lower()
    return brand_says if brand_says in GENDERS else None


# --- which sizes can actually be bought -------------------------------------------

_WS = re.compile(r"\s+")


def _split(value: Any) -> list[str]:
    if not value or not isinstance(value, str):
        return []
    return [_WS.sub(" ", part).strip() for part in value.split(",") if part.strip()]


# One spelling per size, so the page offers one chip rather than two for the same thing.
# The shops write M, medium and 2XL for sizes that are M, M and XXL; `size_info` keeps
# every shop's own words for the product page, and this column exists to be filtered on.
_SIZE_FOLD = {
    "SMALL": "S",
    "MEDIUM": "M",
    "LARGE": "L",
    "XSMALL": "XS",
    "X-SMALL": "XS",
    "XLARGE": "XL",
    "X-LARGE": "XL",
    "2XS": "XXS",
    "2XL": "XXL",
    "3XL": "XXXL",
    "4XS": "XXXXS",
    "ONE SIZE": "OS",
    "ONESIZE": "OS",
    "FREE SIZE": "OS",
    "O/S": "OS",
}


def size_label(token: str) -> str:
    """One spelling for one size, in the archive's words rather than each shop's."""
    up = _WS.sub(" ", token).strip().upper()
    return _SIZE_FOLD.get(up, up)


def sizes_in_stock(record: Any) -> list[str]:
    """The sizes a shopper could buy right now, in the shop's own spelling.

    A token that cannot be a size is dropped first, by the same shape rule the finder
    uses to judge a learned size rule. rosier.com stores its *size chart* in `size_info`
    — "measure, how, chart, cm, bust, waist" beside the real XXS..XXXL — on all 7,827 of
    its products, and without this the page would offer "chart" as a size to shop by.

    E0005 keeps `size_info` and `size_availability` as parallel comma-separated lists,
    and the pairing is only meaningful when they are the same length — a mismatch means
    one of them is not what we think, so every offered size is kept rather than guessed
    at. A product with sizes and no availability line is treated the same way: the shop
    lists the size and has not said otherwise, which is true of 45% of the catalogue.
    """
    sizes = [s for s in _split(_get(record, "size_info")) if looks_like_size(s)]
    if not sizes:
        return []
    flags = _split(_get(record, "size_availability"))
    if len(flags) != len(sizes):
        return _folded(sizes)
    buyable = [
        size
        for size, flag in zip(sizes, flags, strict=True)
        if "out_of_stock" not in flag.lower() and flag.lower() not in ("false", "no", "sold out")
    ]
    return _folded(buyable)


def _folded(sizes: list[str]) -> list[str]:
    """The same sizes, one spelling each, order kept."""
    return list(dict.fromkeys(size_label(s) for s in sizes))
