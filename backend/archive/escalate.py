"""Fingerprint a brand at the cheapest transport that can actually read it.

A brand that refuses plain HTTP answers the probe with almost nothing: no sitemap, no
feed, no JSON-LD — so the planner sees no lane and files it under needs_attention. That is
what kept Vivienne Westwood and Van Cleef out of the archive. Neither was unreadable; both
simply would not talk to Python's TLS handshake, and nothing ever asked them a second time
in a different voice.

So probing climbs: plain HTTP, then the same single request with a browser's handshake,
then (only when a factory is supplied) a real browser. It stops at the first level that
comes back with something to read, and records that level on the Capability so the plan
built from it asks for the same transport at scrape time.

A timeout counts as a refusal here. Van Cleef never answered plain HTTP at all — no status,
just fifteen seconds of silence, which is indistinguishable from a host being down until
you try it another way.
"""

from backend.archive.domain.brand import Capability, TransportLevel
from backend.archive.fingerprint import probe
from backend.archive.transport import for_level

# The levels worth trying, cheapest first. T2 is only reached when a browser factory says
# a browser exists — the scraper image deliberately ships without one.
CHEAP_LEVELS = (TransportLevel.T1,)


def readable(cap: Capability) -> bool:
    """Did this probe find anything a connector could actually read?"""
    return bool(cap.bulk_json or cap.woo_api or cap.ldjson_product)


def escalating_prober(browser_factory=None, base=probe, levels=CHEAP_LEVELS, log=None):
    """A prober that climbs transports until the brand is readable.

    Signature matches `fingerprint.probe`, so it drops into run_brand's `prober` seam.
    """

    def prober(domain: str, transport) -> Capability:
        best = _attempt(domain, transport, base)
        if best is not None and (readable(best) or best.password_gated):
            return best

        for level in levels:
            climbed = for_level(level)
            try:
                cap = _attempt(domain, climbed, base)
            finally:
                _close(climbed)
            if cap is None:
                continue
            best = best or cap
            if readable(cap) or cap.password_gated:
                if log:
                    log("escalated", level=level.value, domain=domain)
                return cap.model_copy(update={"transport": level})

        if browser_factory is not None:
            browser = browser_factory()
            try:
                cap = _attempt(domain, browser, base)
            finally:
                _close(browser)
            if cap is not None and (readable(cap) or cap.password_gated):
                if log:
                    log("escalated", level="t2", domain=domain)
                return cap.model_copy(update={"transport": TransportLevel.T2})
            best = best or cap

        return best if best is not None else _unreachable(domain)

    return prober


def _attempt(domain: str, transport, base) -> Capability | None:
    """One probe. A refusal that arrives as an exception is still a refusal, and the next
    level is exactly what might get past it."""
    try:
        return base(domain, transport)
    except Exception:  # noqa: BLE001 — a timeout is a verdict here, not an error to raise
        return None


def _close(transport) -> None:
    closer = getattr(transport, "close", None)
    if callable(closer):
        try:
            closer()
        except Exception:  # noqa: BLE001
            pass


def _unreachable(domain: str) -> Capability:
    return Capability(domain=domain, transport=TransportLevel.T0, evidence={"probe": "no-answer"})
