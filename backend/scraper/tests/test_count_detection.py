"""Unit tests for collection count detection."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from brand import Brand


def test_brand_has_collection_count_selector_attribute():
    """New attributes should exist on Brand with correct defaults."""
    b = Brand("https://example.com")
    assert b.collection_count_selector is None
    assert b._count_selector_miss_count == 0


def test_count_result_dataclass():
    """CountResult should be a dataclass with count and source."""
    from count_detection import CountResult
    r = CountResult(count=47, source="jsonld")
    assert r.count == 47
    assert r.source == "jsonld"


if __name__ == "__main__":
    test_brand_has_collection_count_selector_attribute()
    test_count_result_dataclass()
    print("✅ all passed")
