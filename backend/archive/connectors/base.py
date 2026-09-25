"""The one seam: every catalog channel implements this protocol (spec §4.1)."""

from typing import Protocol

from backend.archive.domain.brand import Brand
from backend.archive.domain.product import ProductRecord, ProductRef
from backend.archive.transport import Transport


class ChannelBlocked(Exception):
    """The channel exists but this transport may not use it (challenge/password)."""


class ChannelBusy(ChannelBlocked):
    """The channel is fine and said so — come back later.

    A rate limit is not evidence about a brand's shape, but it used to be treated as
    one: three re-scrapes of the same 24 Shopify stores inside an hour drew HTTP 429s,
    and each one marked that brand's plan stale and pushed it toward needs_attention.
    A transient answer must never rewrite a plan.
    """


class SkipProduct(Exception):
    """This ref should be skipped without failing the run."""


class NotAProduct(SkipProduct):
    """The page was read fine and is not a product: a retired item with no price, a
    category page in a product sitemap. Unlike a challenge or an HTTP error it says
    nothing about our access, so a run may decline a thousand of them and still be
    a complete read of the catalogue (Entire Studios: 987 of 1,377, 2026-09-25).
    """


class Connector(Protocol):
    kind: str

    def discover(self, brand: Brand, transport: Transport) -> list[ProductRef]: ...

    def fetch(self, ref: ProductRef, transport: Transport) -> ProductRecord: ...
