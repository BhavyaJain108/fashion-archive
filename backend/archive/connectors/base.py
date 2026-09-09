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


class Connector(Protocol):
    kind: str

    def discover(self, brand: Brand, transport: Transport) -> list[ProductRef]: ...

    def fetch(self, ref: ProductRef, transport: Transport) -> ProductRecord: ...
