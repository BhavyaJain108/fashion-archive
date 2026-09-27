from backend.archive import tagging


def test_normalise_is_lowercase_short_and_unique():
    got = tagging.normalise([" Cropped ", "cropped", "Funnel  Neck!", "", "x" * 41, "(cream)"])
    assert got == ["cropped", "funnel neck", "cream"]


def test_prompt_carries_only_what_the_shop_said():
    text = tagging.PROMPT.format(title="Harrington", price="125 USD", material="not stated", description="none")
    assert "Harrington" in text and "not stated" in text and "brand names" in text
