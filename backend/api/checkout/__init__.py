"""Checkout adapters: how a bag becomes money changing hands somewhere else.

This site never holds a card. Every adapter answers the same two questions about
a bag that has been grouped by shop —

    quote(shops)    -> what each shop will charge, in that shop's currency
    checkout(shops) -> where to send the person so the shop takes the money

— and differs only in *where* that is. `cart_links` builds each shop's own
add-to-cart URL and the person pays on the shop's checkout, once per shop.
`buyer_of_record` is the shape of the other answer — one checkout for every
shop, through a provider that places the orders — and is a stub: see
docs/handover/bag-and-buy.md for what exists in 2026 and what it costs.

The adapter in use is chosen by CHECKOUT_PROVIDER; unset means cart links.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class Line:
    """One bag line as an adapter sees it: the id the shop's cart takes, and the
    price the total is built from (the catalogue's current one, else the price
    at add time)."""

    id: int
    brand: str
    itemurl: str
    variant_id: str | None
    size: str | None
    qty: int
    price: float | None
    available: bool | None  # None when the catalogue could not be asked


@dataclass
class ShopBag:
    brand: str  # the shop's domain
    brand_name: str
    platform: str | None  # "shopify" | "woo" | None
    currency: str | None
    lines: list[Line] = field(default_factory=list)


@dataclass
class ShopQuote:
    brand: str
    currency: str | None
    subtotal: float  # of the lines that have a price, in `currency`
    lines_priced: int
    lines_unpriced: int  # the shop's cart will say; we cannot
    lines_unavailable: int
    # What a shop total does not include: shipping and tax are decided at the
    # shop's checkout, from an address we never see.
    excludes: tuple[str, ...] = ("shipping", "tax", "duties")

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["excludes"] = list(self.excludes)
        return d


@dataclass
class Link:
    url: str
    kind: str  # "cart" (whole shop in one URL) | "add_to_cart" (one line) | "product" (no cart id)
    line_ids: list[int]


@dataclass
class ShopCheckout:
    brand: str
    kind: str  # "cart_links" | "provider_session"
    links: list[Link]
    note: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class CheckoutAdapter(Protocol):
    name: str

    def quote(self, shops: list[ShopBag]) -> list[ShopQuote]: ...

    def checkout(self, shops: list[ShopBag]) -> list[ShopCheckout]: ...


def quote_from_lines(shop: ShopBag) -> ShopQuote:
    """The one arithmetic every adapter shares: sum what has a price."""
    priced = [ln for ln in shop.lines if ln.price is not None]
    return ShopQuote(
        brand=shop.brand,
        currency=shop.currency,
        subtotal=round(sum(ln.price * ln.qty for ln in priced if ln.price is not None), 2),
        lines_priced=len(priced),
        lines_unpriced=len(shop.lines) - len(priced),
        lines_unavailable=sum(1 for ln in shop.lines if ln.available is False),
    )


def adapter(name: str | None = None) -> CheckoutAdapter:
    """The adapter CHECKOUT_PROVIDER names; cart links unless told otherwise."""
    from backend.api.checkout import buyer_of_record, cart_links

    chosen = (name or os.environ.get("CHECKOUT_PROVIDER") or "cart_links").strip().lower()
    if chosen == "cart_links":
        return cart_links.CartLinkAdapter()
    if chosen == "buyer_of_record":
        return buyer_of_record.BuyerOfRecordAdapter()
    raise ValueError(f"CHECKOUT_PROVIDER={chosen!r}: expected cart_links or buyer_of_record")
