"""Immune system: channel counts and field fill → verdicts (spec §4.5)."""

from backend.archive.domain.product import ProductRecord
from backend.archive.domain.run import Coverage

_FILL_FIELDS = (
    "product_title",
    "price",
    "in_stock",
    "all_images",
    "size_info",
    "description",
    "category1",
)


def field_fill_rates(records: list[ProductRecord]) -> dict[str, float]:
    if not records:
        return {}
    fill: dict[str, float] = {}
    for f in _FILL_FIELDS:
        filled = sum(
            1
            for r in records
            if getattr(r, f) is not None and getattr(r, f) != [] and getattr(r, f) != ""
        )
        fill[f] = filled / len(records)
    return fill


def assess(
    extracted: int, channel_counts: dict[str, int], field_fill: dict[str, float]
) -> Coverage:
    expected = max(channel_counts.values()) if channel_counts else extracted
    coverage_pct = 1.0 if expected == 0 else extracted / expected
    reasons: list[str] = []
    if expected == 0:
        # outlw.xyz returned a green "ok" on a run that found nothing at all,
        # because zero of zero is one. A channel that reports no products is broken.
        return Coverage(
            extracted=0,
            channel_counts=channel_counts,
            coverage_pct=0.0,
            field_fill=field_fill,
            verdict="failed",
            reasons=["the channel reported no products"],
        )
    if extracted == 0 and expected > 0:
        reasons.append(f"extracted 0 of {expected} channel-reported products")
        verdict = "failed"
    elif coverage_pct < 0.6:
        reasons.append(f"coverage {coverage_pct:.0%} below 60%")
        verdict = "failed"
    else:
        if coverage_pct < 0.95:
            reasons.append(f"coverage {coverage_pct:.0%} below 95%")
        if field_fill.get("product_title", 1.0) < 1.0:
            reasons.append("product_title fill below 100%")
        verdict = "degraded" if reasons else "ok"
    return Coverage(
        extracted=extracted,
        channel_counts=channel_counts,
        coverage_pct=round(coverage_pct, 4),
        field_fill=field_fill,
        verdict=verdict,
        reasons=reasons,
    )
