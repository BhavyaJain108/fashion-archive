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
    assert b._count_selector_miss_count == 0


def test_cached_selector_returns_none_when_no_selector():
    from count_detection import _detect_count_from_cached_selector
    from brand import Brand
    b = Brand("https://example.com")
    page = _FakePageWithSelector("47 products")
    assert _detect_count_from_cached_selector(page, b) is None


def test_cached_selector_increments_miss_count_on_no_text():
    from count_detection import _detect_count_from_cached_selector
    from brand import Brand
    b = Brand("https://example.com")
    b.collection_count_selector = ".count"
    page = _FakePageWithSelector(None)
    assert _detect_count_from_cached_selector(page, b) is None
    assert b._count_selector_miss_count == 1


def test_cached_selector_invalidates_after_three_misses():
    from count_detection import _detect_count_from_cached_selector
    from brand import Brand
    b = Brand("https://example.com")
    b.collection_count_selector = ".count"
    page = _FakePageWithSelector(None)
    for _ in range(3):
        _detect_count_from_cached_selector(page, b)
    assert b.collection_count_selector is None
    assert b._count_selector_miss_count == 0


def test_cached_selector_returns_none_for_implausible_number():
    from count_detection import _detect_count_from_cached_selector
    from brand import Brand
    b = Brand("https://example.com")
    b.collection_count_selector = ".count"
    page = _FakePageWithSelector("999999 reviews")
    assert _detect_count_from_cached_selector(page, b) is None
    assert b._count_selector_miss_count == 1


class _FakeLLMHandler:
    """Captures the structured vision call and returns a canned response dict.

    Mirrors LLMHandler.call_with_image_structured: caller passes a pydantic
    `response_model`; we return `{"data": <pre-validated dict>, "success": True}`
    on success or `{"success": False, "error": ...}` on failure. This matches
    the contract the production code now relies on.
    """
    def __init__(self, canned_response):
        self._canned = canned_response
        self.last_prompt = None
        self.last_image_b64 = None
        self.last_response_model = None

    def call_with_image_structured(self, prompt, image_b64, response_model,
                                   media_type="image/png", max_tokens=1500,
                                   operation="vision_structured"):
        self.last_prompt = prompt
        self.last_image_b64 = image_b64
        self.last_response_model = response_model
        return self._canned


class _FakePageScreenshot:
    """Fake page with screenshot(), evaluate(), and wait_for_timeout()."""
    def screenshot(self, **kwargs):
        return b"\x89PNG\r\n\x1a\nfake-screenshot-bytes"

    def evaluate(self, _js):
        # Scroll-to-top no-op for tests.
        return None

    def wait_for_timeout(self, _ms):
        return None


def test_vision_stage_returns_count_and_caches_selector_on_high_confidence():
    from count_detection import _detect_count_from_vision
    from brand import Brand
    b = Brand("https://example.com")
    llm = _FakeLLMHandler({
        "success": True,
        "data": {"count": 47, "selector": ".collection-count",
                 "confidence": "high", "reasoning": "saw it"},
        "usage": {"input_tokens": 100, "output_tokens": 20},
    })
    page = _FakePageScreenshot()

    count = _detect_count_from_vision(page, "Hoodies", b, llm)
    assert count == 47
    assert b.collection_count_selector == ".collection-count"


def test_vision_stage_does_not_cache_on_medium_confidence():
    from count_detection import _detect_count_from_vision
    from brand import Brand
    b = Brand("https://example.com")
    llm = _FakeLLMHandler({
        "success": True,
        "data": {"count": 47, "selector": ".count",
                 "confidence": "medium", "reasoning": "maybe"},
        "usage": {"input_tokens": 100, "output_tokens": 20},
    })
    page = _FakePageScreenshot()

    count = _detect_count_from_vision(page, "Hoodies", b, llm)
    assert count == 47
    assert b.collection_count_selector is None


def test_vision_stage_returns_none_when_llm_returns_null_count():
    from count_detection import _detect_count_from_vision
    from brand import Brand
    b = Brand("https://example.com")
    llm = _FakeLLMHandler({
        "success": True,
        "data": {"count": None, "selector": None,
                 "confidence": "low", "reasoning": "no count visible"},
        "usage": {"input_tokens": 100, "output_tokens": 20},
    })
    page = _FakePageScreenshot()

    count = _detect_count_from_vision(page, "Hoodies", b, llm)
    assert count is None
    assert b.collection_count_selector is None


def test_vision_stage_returns_none_on_llm_failure():
    from count_detection import _detect_count_from_vision
    from brand import Brand
    b = Brand("https://example.com")
    llm = _FakeLLMHandler({"success": False, "error": "API error"})
    page = _FakePageScreenshot()

    count = _detect_count_from_vision(page, "Hoodies", b, llm)
    assert count is None


class _StagedFakePage:
    """Fake page that responds differently depending on what's queried."""
    def __init__(self, jsonld_texts=None, selector_text=None):
        self._jsonld = jsonld_texts or []
        self._selector_text = selector_text

    def evaluate(self, js):
        if 'application/ld+json' in js:
            return self._jsonld
        if 'querySelector' in js:
            return self._selector_text
        return None

    def screenshot(self, **kwargs):
        return b"\x89PNG\r\n\x1a\nfake"

    def wait_for_timeout(self, _ms):
        return None


def test_orchestrator_returns_jsonld_result_when_available():
    from count_detection import detect_collection_count, CountResult
    from brand import Brand
    b = Brand("https://example.com")
    page = _StagedFakePage(jsonld_texts=['{"@type":"ItemList","numberOfItems":47}'])
    llm = _FakeLLMHandler({"success": False})
    result = detect_collection_count(page, "Hoodies", b, llm)
    assert result == CountResult(count=47, source="jsonld")


def test_orchestrator_falls_through_to_cached_selector():
    from count_detection import detect_collection_count, CountResult
    from brand import Brand
    b = Brand("https://example.com")
    b.collection_count_selector = ".count"
    page = _StagedFakePage(jsonld_texts=[], selector_text="32 items")
    llm = _FakeLLMHandler({"success": False})
    result = detect_collection_count(page, "Tops", b, llm)
    assert result == CountResult(count=32, source="cached_selector")


def test_orchestrator_falls_through_to_vision():
    from count_detection import detect_collection_count, CountResult
    from brand import Brand
    b = Brand("https://example.com")
    page = _StagedFakePage(jsonld_texts=[], selector_text=None)
    llm = _FakeLLMHandler({
        "success": True,
        "data": {"count": 18, "selector": ".c",
                 "confidence": "high", "reasoning": "x"},
        "usage": {"input_tokens": 50, "output_tokens": 10},
    })
    result = detect_collection_count(page, "THORN", b, llm)
    assert result == CountResult(count=18, source="vision")


def test_orchestrator_returns_none_when_all_stages_miss():
    from count_detection import detect_collection_count
    from brand import Brand
    b = Brand("https://example.com")
    page = _StagedFakePage(jsonld_texts=[], selector_text=None)
    llm = _FakeLLMHandler({
        "success": True,
        "data": {"count": None, "selector": None,
                 "confidence": "low", "reasoning": "none"},
        "usage": {"input_tokens": 50, "output_tokens": 10},
    })
    assert detect_collection_count(page, "Mystery", b, llm) is None


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
    test_cached_selector_increments_miss_count_on_no_text()
    test_cached_selector_invalidates_after_three_misses()
    test_cached_selector_returns_none_for_implausible_number()
    test_vision_stage_returns_count_and_caches_selector_on_high_confidence()
    test_vision_stage_does_not_cache_on_medium_confidence()
    test_vision_stage_returns_none_when_llm_returns_null_count()
    test_vision_stage_returns_none_on_llm_failure()
    test_orchestrator_returns_jsonld_result_when_available()
    test_orchestrator_falls_through_to_cached_selector()
    test_orchestrator_falls_through_to_vision()
    test_orchestrator_returns_none_when_all_stages_miss()
    print("✅ all passed")
