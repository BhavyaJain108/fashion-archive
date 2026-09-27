from backend.archive import tagging


def test_normalise_is_lowercase_short_and_unique():
    got = tagging.normalise([" Cropped ", "cropped", "Funnel  Neck!", "", "x" * 41, "(cream)"])
    assert got == ["cropped", "funnel neck", "cream"]


def test_prompt_carries_only_what_the_shop_said():
    text = tagging.PROMPT.format(
        title="Harrington", price="125 USD", material="not stated", description="none"
    )
    assert "Harrington" in text and "not stated" in text and "brand names" in text


def test_photo_sources_try_the_shop_then_our_copy():
    row = {
        "main_image_url": "https://cdn.shopify.com/a.jpg",
        "stored_url": "https://images.example/b.jpg",
    }
    assert tagging.photo_sources(row) == [row["main_image_url"], row["stored_url"]]
    assert tagging.photo_sources({"main_image_url": None, "stored_url": None}) == []
