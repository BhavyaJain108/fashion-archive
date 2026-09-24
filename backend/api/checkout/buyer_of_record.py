"""One checkout for every shop, through a provider that places the orders.

The shape only. A buyer-of-record provider (Rye is the one that takes an
arbitrary product URL in 2026; the others need the merchant to enrol — see
docs/handover/bag-and-buy.md) is handed the bag and the buyer's details,
quotes shipping and tax against a real address, takes the card on its own
hosted page, and places one order per shop. We would hold an order id and a
status, never a card number.

Nothing below talks to a provider. `quote` is the same arithmetic as cart
links, because until a provider is wired in that is the only number we have;
`checkout` says so instead of pretending. Wiring one in means: an API key in
the environment, a session created per bag with the lines as product URLs and
variant ids, the provider's hosted checkout URL returned as the one link, and
a webhook that records the order ids. The interface is here so the route and
the frontend do not change when that happens.
"""

from __future__ import annotations

from backend.api.checkout import ShopBag, ShopCheckout, ShopQuote, quote_from_lines


class BuyerOfRecordAdapter:
    name = "buyer_of_record"
    configured = False  # flipped by a real integration once it has a key and a session API

    def quote(self, shops: list[ShopBag]) -> list[ShopQuote]:
        # A provider would return landed cost here (item + shipping + tax against
        # the buyer's address). Without one, the catalogue's prices are the quote.
        return [quote_from_lines(s) for s in shops]

    def checkout(self, shops: list[ShopBag]) -> list[ShopCheckout]:
        return [
            ShopCheckout(
                brand=s.brand,
                kind="provider_session",
                links=[],
                note="buyer-of-record checkout is not configured; use cart_links",
            )
            for s in shops
        ]
