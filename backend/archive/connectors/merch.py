"""Whether a catalogue row is something a person could wear or carry, or a line item.

Shops list things that are not merchandise beside the things that are: gift cards,
shipping protection, a tax line, a surcharge, an appointment, an ebook. On 2026-10-02
the live catalogue held 90 Shopify rows of that kind across 40 brands — "Shipping
Protection by Route" at 0.98, Supermade's "Tax" at 3.99, Oddli's "CUSTOM SURCHARGE",
Lorinaté's "Authentication Certificate" — counted in every brand's numbers and shown on
the deck. The site already hid some of them through the phrase book, which is a model's
reading of a phrase and only as good as the phrases it has been asked about.

This is the deterministic half, applied where a row is read, so it never enters the
catalogue at all. Two kinds of evidence, strongest first:

  the shop's own word: Shopify says per variant whether the thing ships, and calls its
                       product type "Gift Card", "Insurance", "Subscription". A product
                       none of whose variants ship is not a garment — unless the shop
                       filed it under a type of its own (Justine Clenquet's "Handbags",
                       a bag whose variants were mis-set), which is kept;
  the title:           a short list of phrases that only ever name a line item, and
                       a runway look's own page ("Look 13" — Marni's sitemap lists 16,
                       with no price and no photograph of their own). Narrow
                       on purpose: "Sticker Print Zip Sweatshirt", "CDG x New Balance",
                       "Fringe Tip Suede Sabot" and "Yale Postage Tote" are all garments,
                       and a word list wide enough to catch every gift card would take
                       them with it.

A mystery box ships and has a price, and is kept: it is merchandise, whatever is in it.
"""

from __future__ import annotations

import re

# Product types that are never merchandise, compared lower-cased and trimmed.
_TYPES = {
    "gift card",
    "gift cards",
    "giftcard",
    "gift voucher",
    "e-gift card",
    "insurance",
    "shipping",
    "shipping protection",
    "package protection",
    "subscription",
    "ebook",
    "e-book",
    "non physical product",
    "price difference",
    "mws_fee_generated",
    "service",
    "services",
    "fee",
    "deposit",
    "donation",
}
# Apps that sell protection through the shop's own catalogue.
_VENDORS = {"route", "seel", "swap commerce", "extend", "corso", "navidium", "redo"}

_TITLE = re.compile(
    r"""^\s*(?:
        (?:\S+\s+){0,3}(?:e-?\s?gift|digital\s+gift|physical\s+gift|gift)\s*(?:card|certificate|voucher)s?\b
        (?!\s*(?:holder|case|wallet|sleeve|pouch|organi[sz]er))
      | e-?voucher\b | gift\s+voucher\b
      | (?:shipping|package|parcel|order|delivery)\s+(?:protection|insurance)\b
      | worry-?free\s+purchase\b
      | .*\b(?:handling|restocking|shipping|service)\s+fee\b
      | .*\b(?:shipping|postage)\s*$
      | (?:custom\s+)?surcharge\b
      | price\s+(?:difference|adjustment)\b
      | (?:tax|taxes|duties|shipping|postage|tip|donation)\s*$
      | authentication\s+certificate\b
      | look\s*\d+\s*$
      | .*\bappointment\s*$
      | .*\b(?:e-?book)\b
    )""",
    re.I | re.X,
)


def not_merchandise(
    title: str | None,
    product_type: str | None = None,
    vendor: str | None = None,
    ships: bool | None = None,
) -> str | None:
    """Why this row is not merchandise, or None when it is (or when nothing says).

    `ships` is whether any of its variants needs shipping, when the shop says; None
    when the channel does not carry it, which is most of them, and then the title and
    the type decide alone.
    """
    kind = (product_type or "").strip().lower()
    if kind in _TYPES:
        return f"the shop files it as {product_type!r}"
    if (vendor or "").strip().lower() in _VENDORS:
        return f"sold by {vendor}, a protection app"
    if title and _TITLE.match(title):
        return f"{title!r} names a line item, not a garment"
    if ships is False and not kind:
        return "none of its variants ships"
    return None
