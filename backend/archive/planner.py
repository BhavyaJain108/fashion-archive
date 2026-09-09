"""Compose a (T,D,F,C) coordinate into a ScrapePlan; escalation with memory (spec §4.0, §4.3, §4.3b)."""

from datetime import datetime, timezone

from backend.archive.domain.brand import (
    Capability,
    ChangeSignal,
    DiscoveryChannel,
    FetchChannel,
    PlanAttempt,
    ScrapePlan,
    TransportLevel,
)


def compose_plan(
    cap: Capability,
    tried: list[PlanAttempt] | None = None,
    now: str | None = None,
    browser: bool = False,
) -> ScrapePlan:
    tried = tried or []
    now = now or datetime.now(timezone.utc).isoformat()
    tried_compositions = {a.composition for a in tried}

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
        )

    if cap.password_gated:
        return plan(
            TransportLevel.T4,
            DiscoveryChannel.BULK_JSON,
            FetchChannel.PLATFORM_JSON,
            ChangeSignal.NONE,
            "skip_gated",
        )

    # The T0 escalation ladder: each rung is skipped when its capability is absent
    # or its composition has already failed for this brand (spec §4.3b).
    if cap.transport == TransportLevel.T0:
        rungs = []
        if cap.bulk_json:
            rungs.append(
                plan(
                    TransportLevel.T0,
                    DiscoveryChannel.BULK_JSON,
                    FetchChannel.PLATFORM_JSON,
                    ChangeSignal.PER_ITEM,
                    "ready",
                )
            )
        if cap.woo_api:
            rungs.append(
                plan(
                    TransportLevel.T0,
                    DiscoveryChannel.WOO_API,
                    FetchChannel.PLATFORM_JSON,
                    ChangeSignal.PER_ITEM,
                    "ready",
                )
            )
        if cap.sitemap_url and cap.ldjson_product:
            rungs.append(
                plan(
                    TransportLevel.T0,
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
