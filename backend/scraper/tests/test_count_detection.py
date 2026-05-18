"""Unit tests for collection count detection."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from brand import Brand


def test_brand_has_collection_count_selector_attribute():
    """New attributes should exist on Brand with correct defaults."""
    b = Brand("https://example.com")
    assert b.collection_count_selector is None


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


class _FakePage:
    """A minimal page stand-in for testing the JSON-LD stage."""
    def __init__(self, jsonld_strings):
        self._jsonld_strings = jsonld_strings

    def evaluate(self, _js):
        return self._jsonld_strings


def test_jsonld_stage_returns_count_for_well_formed():
    from count_detection import _detect_count_from_jsonld
    page = _FakePage(['{"@type":"ItemList","numberOfItems":47}'])
    assert _detect_count_from_jsonld(page) == 47


def test_jsonld_stage_returns_none_when_no_scripts():
    from count_detection import _detect_count_from_jsonld
    page = _FakePage([])
    assert _detect_count_from_jsonld(page) is None


def test_jsonld_stage_skips_malformed_json():
    from count_detection import _detect_count_from_jsonld
    page = _FakePage([
        'not valid json {',
        '{"@type":"ItemList","numberOfItems":24}',
    ])
    assert _detect_count_from_jsonld(page) == 24


def test_jsonld_stage_returns_none_when_only_malformed():
    from count_detection import _detect_count_from_jsonld
    page = _FakePage(['not valid', '{also not valid'])
    assert _detect_count_from_jsonld(page) is None


class _FakePageWithSelector(_FakePage):
    """Fake page that returns a textContent value for a queryable selector."""
    def __init__(self, selector_text):
        super().__init__([])
        self._selector_text = selector_text

    def evaluate(self, js):
        if 'querySelector' in js:
            return self._selector_text
        return []


def test_cached_selector_returns_count_when_text_has_number():
    from count_detection import _detect_count_from_cached_selector
    from brand import Brand
    b = Brand("https://example.com")
    b.collection_count_selector = ".count"
    page = _FakePageWithSelector("47 products")
    assert _detect_count_from_cached_selector(page, b) == 47


def test_cached_selector_returns_none_when_no_selector():
    from count_detection import _detect_count_from_cached_selector
    from brand import Brand
    b = Brand("https://example.com")
    page = _FakePageWithSelector("47 products")
    assert _detect_count_from_cached_selector(page, b) is None


def test_cached_selector_preserves_selector_on_null_text():
    """A null/empty page result means 'no count on this page' — the cached
    selector must NOT be invalidated, since other categories may still show
    the count via the same selector."""
    from count_detection import _detect_count_from_cached_selector
    from brand import Brand
    b = Brand("https://example.com")
    b.collection_count_selector = ".count"
    page = _FakePageWithSelector(None)
    for _ in range(5):
        assert _detect_count_from_cached_selector(page, b) is None
    # Selector survives indefinitely.
    assert b.collection_count_selector == ".count"


def test_cached_selector_returns_none_for_implausible_number():
    from count_detection import _detect_count_from_cached_selector
    from brand import Brand
    b = Brand("https://example.com")
    b.collection_count_selector = ".count"
    page = _FakePageWithSelector("999999 reviews")
    assert _detect_count_from_cached_selector(page, b) is None
    # Implausible counts also don't invalidate the selector.
    assert b.collection_count_selector == ".count"


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
    test_jsonld_stage_returns_count_for_well_formed()
    test_jsonld_stage_returns_none_when_no_scripts()
    test_jsonld_stage_skips_malformed_json()
    test_jsonld_stage_returns_none_when_only_malformed()
    test_cached_selector_returns_count_when_text_has_number()
    test_cached_selector_returns_none_when_no_selector()
    test_cached_selector_preserves_selector_on_null_text()
    test_cached_selector_returns_none_for_implausible_number()
    print("✅ all passed")
