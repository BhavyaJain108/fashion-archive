"""Checkout by handing the person to each shop's own cart.

Shopify: one URL carries the whole bag for that shop —
    https://<shop>/cart/<variant_id>:<qty>,<variant_id>:<qty>
and lands on the shop's checkout with those lines in it. It is a documented
"cart permalink"; the shop installs nothing and sees a normal order.

WooCommerce: one URL carries one line —
    https://<shop>/?add-to-cart=<variation or product id>&quantity=<qty>
because WooCommerce's add-to-cart handler takes a single id. A bag with three
lines from one Woo shop is three links, each of which adds to the same cart on
the shop's side (the cart is a cookie there), so opening them in order works
and the person checks out once. The frontend should open them one at a time.

Anything else, and any line without a variant id: the product page, and the
person picks the size again there.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from backend.api.checkout import Line, Link, ShopBag, ShopCheckout, ShopQuote, quote_from_lines


def shop_origin(shop: ShopBag) -> str:
    """Where the cart lives: the host the product URL is on, which for nearly every
    brand is the roster domain and for a few is a shop.<domain> in front of it."""
    for ln in shop.lines:
        host = urlsplit(ln.itemurl).netloc
        if host:
            return f"https://{host}"
    return f"https://{shop.brand}"


def shopify_cart_url(origin: str, lines: list[Line]) -> str:
    items = ",".join(f"{ln.variant_id}:{ln.qty}" for ln in lines)
    return f"{origin}/cart/{items}"


def woo_add_url(origin: str, line: Line) -> str:
    return f"{origin}/?add-to-cart={line.variant_id}&quantity={line.qty}"


class CartLinkAdapter:
    name = "cart_links"

    def quote(self, shops: list[ShopBag]) -> list[ShopQuote]:
        return [quote_from_lines(s) for s in shops]

    def checkout(self, shops: list[ShopBag]) -> list[ShopCheckout]:
        return [self._shop(s) for s in shops]

    def _shop(self, shop: ShopBag) -> ShopCheckout:
        origin = shop_origin(shop)
        with_id = [ln for ln in shop.lines if ln.variant_id]
        without = [ln for ln in shop.lines if not ln.variant_id]
        links: list[Link] = []
        note = None
        if shop.platform == "shopify" and with_id:
            links.append(Link(shopify_cart_url(origin, with_id), "cart", [ln.id for ln in with_id]))
        elif shop.platform == "woo" and with_id:
            links.extend(Link(woo_add_url(origin, ln), "add_to_cart", [ln.id]) for ln in with_id)
            if len(with_id) > 1:
                note = (
                    f"WooCommerce takes one item per link: open these {len(with_id)} links "
                    "in order, then check out once on the shop"
                )
        else:
            without = list(shop.lines)
        for ln in without:
            links.append(Link(ln.itemurl, "product", [ln.id]))
        if without and shop.platform in ("shopify", "woo"):
            note = (note + "; " if note else "") + (
                f"{len(without)} line(s) have no variant id and open the product page instead"
            )
        elif without and shop.platform not in ("shopify", "woo"):
            note = "no cart link for this shop's platform: each line opens its product page"
        return ShopCheckout(brand=shop.brand, kind="cart_links", links=links, note=note)
