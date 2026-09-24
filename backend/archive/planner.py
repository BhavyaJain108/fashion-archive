"""Compose a (T,D,F,C) coordinate into a ScrapePlan; escalation with memory (spec §4.0, §4.3, §4.3b)."""

from datetime import datetime, timedelta, timezone

from backend.archive.domain.brand import (
    Capability,
    ChangeSignal,
    DiscoveryChannel,
    FetchChannel,
    PlanAttempt,
    ScrapePlan,
    TransportLevel,
)

# A failed composition is remembered, not banned. After this long it is offered again:
# the failure may have been the host's bad hour or our own bug since fixed, and a
# memory that only ever tightened left every brand scarred by its worst day for good.
ATTEMPT_MEMORY_DAYS = 7


def _aware(iso: str) -> datetime:
    dt = datetime.fromisoformat(iso)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def still_counts(attempt: PlanAttempt, now: str) -> bool:
    """Whether this failure is recent enough to keep its composition off the ladder."""
    try:
        return _aware(attempt.failed_at) >= _aware(now) - timedelta(days=ATTEMPT_MEMORY_DAYS)
    except ValueError:
        return True  # an unreadable timestamp is not a reason to retry a known failure


def compose_plan(
    cap: Capability,
    tried: list[PlanAttempt] | None = None,
    now: str | None = None,
    browser: bool = False,
) -> ScrapePlan:
    tried = tried or []
    now = now or datetime.now(timezone.utc).isoformat()
    # The whole history stays on the plan; only the recent part blocks a rung.
    tried_compositions = {a.composition for a in tried if still_counts(a, now)}

    def plan(transport, discovery, fetch, change, status) -> ScrapePlan:
        return ScrapePlan(
            domain=cap.domain,
            transport=transport,
            discovery=discovery,
            fetch=fetch,
            change_signal=change,
            status=status,
            tried=tried,
            fingerprinted_at=now,
            sitemap_url=cap.sitemap_url,
            product_url_prefix=cap.product_url_prefix,
            currency=cap.currency,
            shop_domain=cap.shop_domain,
        )

    if cap.password_gated:
        return plan(
            TransportLevel.T4,
            DiscoveryChannel.BULK_JSON,
            FetchChannel.PLATFORM_JSON,
            ChangeSignal.NONE,
            "skip_gated",
        )

    # The cheap ladder: each rung is skipped when its capability is absent or its
    # composition has already failed for this brand (spec §4.3b). It is built on whichever
    # level actually answered — T0, or T1 when the brand refused Python's TLS handshake and
    # a browser-shaped one got in. Both are one request per page; neither renders anything.
    if cap.transport in (TransportLevel.T0, TransportLevel.T1):
        cheap = cap.transport
        rungs = []
        if cap.bulk_json:
            rungs.append(
                plan(
                    cheap,
                    DiscoveryChannel.BULK_JSON,
                    FetchChannel.PLATFORM_JSON,
                    ChangeSignal.PER_ITEM,
                    "ready",
                )
            )
        if cap.woo_api:
            rungs.append(
                plan(
                    cheap,
                    DiscoveryChannel.WOO_API,
                    FetchChannel.PLATFORM_JSON,
                    ChangeSignal.PER_ITEM,
                    "ready",
                )
            )
        if cap.sitemap_url and cap.ldjson_product:
            rungs.append(
                plan(
                    cheap,
                    DiscoveryChannel.SITEMAP,
                    FetchChannel.STRUCTURED_DATA,
                    ChangeSignal.PER_ITEM,
                    "ready",
                )
            )
        for candidate in rungs:
            if candidate.composition not in tried_compositions:
                return candidate

    # Browser rungs (opt-in): only offered when a browser transport is available, so HTTP-only
    # scheduled runs never produce a T2 plan they cannot execute.
    if browser:
        brungs = []
        # Only justified when HTTP was actually blocked — a "shopify" platform guess
        # can come from a stray marketing pixel (live bug: theoutnet, 2026-08-30).
        if cap.bulk_json or (cap.challenged and cap.platform == "shopify"):
            brungs.append(
                plan(
                    TransportLevel.T2,
                    DiscoveryChannel.BULK_JSON,
                    FetchChannel.PLATFORM_JSON,
                    ChangeSignal.PER_ITEM,
                    "ready",
                )
            )
        if cap.sitemap_url:
            brungs.append(
                plan(
                    TransportLevel.T2,
                    DiscoveryChannel.SITEMAP,
                    FetchChannel.STRUCTURED_DATA,
                    ChangeSignal.PER_ITEM,
                    "ready",
                )
            )
        for candidate in brungs:
            if candidate.composition not in tried_compositions:
                return candidate

    return plan(
        cap.transport,
        DiscoveryChannel.BULK_JSON,
        FetchChannel.PLATFORM_JSON,
        ChangeSignal.NONE,
        "needs_attention",
    )
