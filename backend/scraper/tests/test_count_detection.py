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


def test_jsonld_walker_flat_itemlist():
    from count_detection import _extract_count_from_jsonld_objects
    from tests.fixtures.jsonld_samples import FLAT_ITEMLIST
    assert _extract_count_from_jsonld_objects([FLAT_ITEMLIST]) == 47


def test_jsonld_walker_nested_collection_page():
    from count_detection import _extract_count_from_jsonld_objects
    from tests.fixtures.jsonld_samples import NESTED_COLLECTION_PAGE
    assert _extract_count_from_jsonld_objects([NESTED_COLLECTION_PAGE]) == 32


def test_jsonld_walker_picks_largest_when_multiple():
    from count_detection import _extract_count_from_jsonld_objects
    from tests.fixtures.jsonld_samples import TWO_ITEMLISTS_PICK_LARGEST
    assert _extract_count_from_jsonld_objects(TWO_ITEMLISTS_PICK_LARGEST) == 47


def test_jsonld_walker_graph_array():
    from count_detection import _extract_count_from_jsonld_objects
    from tests.fixtures.jsonld_samples import GRAPH_WITH_ITEMLIST
    assert _extract_count_from_jsonld_objects([GRAPH_WITH_ITEMLIST]) == 12


def test_jsonld_walker_no_numberofitems_returns_none():
    from count_detection import _extract_count_from_jsonld_objects
    from tests.fixtures.jsonld_samples import MISSING_NUMBEROFITEMS
    assert _extract_count_from_jsonld_objects([MISSING_NUMBEROFITEMS]) is None


def test_jsonld_walker_implausible_count_returns_none():
    from count_detection import _extract_count_from_jsonld_objects
    from tests.fixtures.jsonld_samples import IMPLAUSIBLE_COUNT, NEGATIVE_COUNT
    assert _extract_count_from_jsonld_objects([IMPLAUSIBLE_COUNT]) is None
    assert _extract_count_from_jsonld_objects([NEGATIVE_COUNT]) is None


def test_jsonld_walker_unrelated_schema_returns_none():
    from count_detection import _extract_count_from_jsonld_objects
    from tests.fixtures.jsonld_samples import NOT_AN_ITEMLIST
    assert _extract_count_from_jsonld_objects([NOT_AN_ITEMLIST]) is None


def test_jsonld_walker_handles_empty_list():
    from count_detection import _extract_count_from_jsonld_objects
    assert _extract_count_from_jsonld_objects([]) is None


if __name__ == "__main__":
    test_brand_has_collection_count_selector_attribute()
    test_count_result_dataclass()
    test_jsonld_walker_flat_itemlist()
    test_jsonld_walker_nested_collection_page()
    test_jsonld_walker_picks_largest_when_multiple()
    test_jsonld_walker_graph_array()
    test_jsonld_walker_no_numberofitems_returns_none()
    test_jsonld_walker_implausible_count_returns_none()
    test_jsonld_walker_unrelated_schema_returns_none()
    test_jsonld_walker_handles_empty_list()
    print("✅ all passed")
