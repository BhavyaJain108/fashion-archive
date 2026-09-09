import json

import pytest

from backend.archive.audit import E_CODES, MODELLED, check_invariants, payload_has, verdict


def row(**kw) -> dict:
    base = {"itemurl": "https://x.test/p", "product_title": "Tee", "raw": {}}
    base.update(kw)
    return base


@pytest.mark.unit
def test_a_clean_row_has_nothing_to_report():
    assert check_invariants(
        row(
            size_info="S, M, L",
            size_availability="in_stock, out_of_stock, in_stock",
            in_stock=True,
            price=40.0,
            full_price=60.0,
            main_image_url="https://x.test/a.jpg",
            all_images=json.dumps(["https://x.test/a.jpg", "https://x.test/b.jpg"]),
            category1="Womenswear",
            category2="Tops",
        )
    ) == []


@pytest.mark.unit
def test_the_size_strings_must_stay_parallel():
    problems = check_invariants(row(size_info="S, M, L", size_availability="in_stock, out_of_stock"))
    assert "size_availability not parallel to size_info" in problems


@pytest.mark.unit
def test_in_stock_must_agree_with_the_sizes():
    """A product cannot be in stock when every one of its sizes is sold out."""
    problems = check_invariants(
        row(size_info="S, M", size_availability="out_of_stock, out_of_stock", in_stock=True)
    )
    assert "in_stock disagrees with size_availability" in problems
    assert check_invariants(
        row(size_info="S, M", size_availability="out_of_stock, in_stock", in_stock=True)
    ) == []


@pytest.mark.unit
def test_a_category_path_may_not_have_a_hole():
    """category3 without category2 is not a hierarchy — it is two unrelated labels."""
    problems = check_invariants(row(category1="Womenswear", category3="Coats"))
    assert "category path has a hole" in problems
    assert check_invariants(row(category1="Womenswear", category2="Outerwear")) == []


@pytest.mark.unit
def test_full_price_below_price_is_not_a_sale():
    problems = check_invariants(row(price=80.0, full_price=60.0))
    assert "full_price not above price" in problems


@pytest.mark.unit
def test_the_main_image_must_be_one_of_the_images():
    problems = check_invariants(
        row(main_image_url="https://x.test/a.jpg", all_images=json.dumps(["https://x.test/b.jpg"]))
    )
    assert "main_image_url missing from all_images" in problems


@pytest.mark.unit
def test_payload_search_finds_a_value_at_any_depth():
    shopify = {"variants": [{"sku": "TEE-S"}, {"sku": ""}], "tags": []}
    assert payload_has(shopify, ("sku",)) is True
    assert payload_has(shopify, ("tags",)) is False  # present but empty is not held data
    assert payload_has(shopify, ("barcode",)) is False


@pytest.mark.unit
def test_verdict_separates_our_gap_from_the_channel_saying_nothing():
    held = [row(raw={"variants": [{"barcode": "4901234567894"}]})]
    silent = [row(raw={"variants": [{"price": "10"}]})]
    # a modelled field we did not fill, whose value is sitting in the payload
    assert verdict("additional_code_1", held) == ("empty, data held", 0.0)
    assert verdict("material_info", silent)[0] == "channel silent"
    # the schema can still grow: a field the record does not carry yet reads as unmapped
    assert verdict("future_e0005_field", silent) == ("unmapped", 0.0)


@pytest.mark.unit
def test_every_code_is_paired_with_a_type_in_the_schema():
    """A code without its type is noise: "4901234567894" only means something as gtin13."""
    for code, kind in E_CODES:
        assert kind.startswith(code)
        assert (code in MODELLED) == (kind in MODELLED)  # added together or not at all


@pytest.mark.unit
def test_a_blank_says_whether_anyone_looked():
    """The point of the evidence: "the brand does not publish it" and "we never opened
    the page" used to be stored identically."""
    from backend.archive.evidence import SearchLog, describe

    log = SearchLog()
    log.searched("channel", ["material_info", "size_info"], found=["size_info"])
    ev = {(f, s): (n, hits) for f, s, n, hits in log.rows()}
    assert describe(ev, "material_info").startswith("channel only")
    assert describe(ev, "color_info") == "never searched"

    log.searched("page_llm", ["material_info"])  # the model read the page, found nothing
    ev = {(f, s): (n, hits) for f, s, n, hits in log.rows()}
    assert describe(ev, "material_info") == "absent from channel, page_llm"


@pytest.mark.unit
def test_the_search_log_counts_products_examined_and_yielded():
    from backend.archive.evidence import SearchLog

    log = SearchLog()
    for i in range(3):
        log.searched("channel", ["price", "material_info"], found=["price"])
    assert dict(((f, s), (n, h)) for f, s, n, h in log.rows()) == {
        ("material_info", "channel"): (3, 0),
        ("price", "channel"): (3, 3),
    }


@pytest.mark.unit
def test_an_unknown_source_is_refused():
    from backend.archive.evidence import SearchLog

    with pytest.raises(ValueError):
        SearchLog().searched("vibes", ["price"])


@pytest.mark.unit
def test_a_cdn_rendition_of_the_same_photo_is_not_a_contradiction():
    """theoutnet's gallery entries carry &width=2048&crop=center; the channel's URL for
    the same photograph does not."""
    assert check_invariants(
        row(
            main_image_url="https://cdn.x/files/photo.jpg?v=1784029772",
            all_images=json.dumps(
                ["https://cdn.x/files/photo.jpg?v=1784029772&width=2048&crop=center"]
            ),
        )
    ) == []
    # a genuinely different photograph is still reported
    assert check_invariants(
        row(
            main_image_url="https://cdn.x/files/a.jpg",
            all_images=json.dumps(["https://cdn.x/files/b.jpg"]),
        )
    ) == ["main_image_url missing from all_images"]
