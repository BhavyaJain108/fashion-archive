"""Unit tests for dedupe_urls_by_path.

This is a pure function with no I/O — ideal first test. The dedupe logic is
load-bearing for Stage 2 (URL extraction): if it breaks, we double-count
products across query-param variants (color swatches, tracking params).
"""

from __future__ import annotations

import pytest
from stages.urls import dedupe_urls_by_path


@pytest.mark.unit
class TestDedupeUrlsByPath:
    def test_empty_input_returns_empty(self):
        deduped, original, removed = dedupe_urls_by_path([])
        assert deduped == []
        assert original == 0
        assert removed == 0

    def test_no_duplicates_keeps_everything(self):
        urls = [
            "https://brand.com/products/shirt",
            "https://brand.com/products/pants",
            "https://brand.com/products/dress",
        ]
        deduped, original, removed = dedupe_urls_by_path(urls)
        assert set(deduped) == set(urls)
        assert original == 3
        assert removed == 0

    def test_prefers_url_without_query_params(self):
        """When the same product appears with and without query params,
        keep the clean one. This is the main case: ?variant=red vs no query."""
        urls = [
            "https://brand.com/products/shirt?variant=red",
            "https://brand.com/products/shirt",
            "https://brand.com/products/shirt?variant=blue",
        ]
        deduped, original, removed = dedupe_urls_by_path(urls)
        assert deduped == ["https://brand.com/products/shirt"]
        assert original == 3
        assert removed == 2

    def test_when_all_have_queries_picks_shortest(self):
        """Fallback: if no clean URL exists, shortest wins (proxy for 'cleanest')."""
        urls = [
            "https://brand.com/products/shirt?variant=red&utm_source=google&utm_campaign=spring",
            "https://brand.com/products/shirt?variant=red",
            "https://brand.com/products/shirt?variant=red&size=m",
        ]
        deduped, _, removed = dedupe_urls_by_path(urls)
        assert deduped == ["https://brand.com/products/shirt?variant=red"]
        assert removed == 2

    def test_different_paths_not_collapsed(self):
        """Same query, different path — must stay separate. Regression guard:
        an earlier bug keyed on query only and collapsed unrelated products."""
        urls = [
            "https://brand.com/products/shirt?variant=red",
            "https://brand.com/products/pants?variant=red",
        ]
        deduped, _, removed = dedupe_urls_by_path(urls)
        assert set(deduped) == set(urls)
        assert removed == 0

    def test_different_hosts_not_collapsed(self):
        """Same path on different hosts is two different products."""
        urls = [
            "https://us.brand.com/products/shirt",
            "https://eu.brand.com/products/shirt",
        ]
        deduped, _, removed = dedupe_urls_by_path(urls)
        assert set(deduped) == set(urls)
        assert removed == 0
