import pytest

from backend.archive.domain.product import ProductRecord
from backend.archive.verify import assess, field_fill_rates


@pytest.mark.unit
def test_full_coverage_is_ok():
    cov = assess(291, {"bulk_json": 291, "sitemap": 291}, {"product_title": 1.0})
    assert cov.verdict == "ok" and cov.coverage_pct == 1.0 and cov.reasons == []


@pytest.mark.unit
def test_shortfall_degrades_with_reason():
    cov = assess(250, {"bulk_json": 291}, {"product_title": 1.0})
    assert cov.verdict == "degraded" and any("coverage" in r for r in cov.reasons)


@pytest.mark.unit
def test_zero_extracted_when_channel_reports_products_is_failed():
    """Regression guard: the old pipeline reported 0-URL runs as success (streaming.py:179)."""
    cov = assess(0, {"bulk_json": 291}, {})
    assert cov.verdict == "failed"


@pytest.mark.unit
def test_field_fill_counts_in_stock_false_as_filled():
    recs = [
        ProductRecord(itemurl="u1", product_title="A", price=10.0, in_stock=False),
        ProductRecord(itemurl="u2", product_title="B"),
    ]
    fill = field_fill_rates(recs)
    assert fill["product_title"] == 1.0
    assert fill["price"] == 0.5
    assert fill["in_stock"] == 0.5  # False is knowledge; None is absence


@pytest.mark.unit
def test_a_run_that_finds_nothing_is_a_failure_not_an_ok():
    cov = assess(0, {"sitemap": 0}, {})
    assert cov.verdict == "failed"
    assert cov.coverage_pct == 0.0
