"""The LLM half, tested with a fake client — no API key, no network."""

import pytest

from backend.archive.finder_llm import RECIPE_TOOL, learn_recipes

PAGE = """<html><head>
<script type="application/ld+json">{"@type":"Product","name":"Derby"}</script>
<style>.x{}</style></head><body>
<ul class="sizes"><li class="s">EU 39</li><li class="s">EU 40</li></ul>
<span class="col">Oxblood</span>
<script>var tracking = "noise";</script>
</body></html>"""


class FakeLLM:
    """Stands in for forced tool use: returns the tool input dict directly."""

    def __init__(self, payload, capture=None):
        self.payload = payload
        self.capture = capture if capture is not None else {}

    def propose(self, prompt: str):
        self.capture["prompt"] = prompt
        return self.payload


def rule(**kw) -> dict:
    base = {
        "field": "size_info",
        "kind": "css_all_text",
        "expression": "ul.sizes li.s",
        "expected": "EU 39, EU 40",
    }
    base.update(kw)
    return base


@pytest.mark.unit
def test_keeps_a_rule_that_replays_correctly():
    book = learn_recipes(
        PAGE,
        "https://x.com/products/a",
        "x.com",
        ["size_info"],
        client=FakeLLM({"recipes": [rule()]}),
    )
    assert book.fields() == {"size_info"}
    assert book.recipes[0].expression == "ul.sizes li.s"


@pytest.mark.unit
def test_discards_a_rule_whose_replay_does_not_match_the_prediction():
    """The model claims sizes are somewhere they are not — the rule must not survive."""
    invented = rule(kind="css_text", expression="div.size-picker", expected="XS, S, M")
    book = learn_recipes(PAGE, "u", "x.com", ["size_info"], client=FakeLLM({"recipes": [invented]}))
    assert book.recipes == []


@pytest.mark.unit
def test_ignores_rules_for_fields_we_did_not_ask_about():
    sneaky = rule(field="product_title", kind="css_text", expression="span.col", expected="Oxblood")
    book = learn_recipes(PAGE, "u", "x.com", ["size_info"], client=FakeLLM({"recipes": [sneaky]}))
    assert book.recipes == []


@pytest.mark.unit
def test_survives_anything_the_model_returns():
    for junk in (
        "not a dict",
        None,
        {},
        {"recipes": None},
        {"recipes": [{"field": "size_info"}]},
        {"recipes": [rule(kind="exec_shell")]},
    ):
        book = learn_recipes(PAGE, "u", "x.com", ["size_info"], client=FakeLLM(junk))
        assert book.recipes == []


@pytest.mark.unit
def test_no_missing_fields_means_no_call_at_all():
    """Brands whose free channels fill everything must never reach the LLM."""

    class Boom:
        def propose(self, prompt):
            raise AssertionError("must not be called")

    book = learn_recipes(PAGE, "u", "kuurth.com", [], client=Boom())
    assert book.recipes == [] and book.domain == "kuurth.com"


@pytest.mark.unit
def test_prompt_drops_tracking_scripts_but_keeps_json_ld():
    capture: dict = {}
    learn_recipes(
        PAGE,
        "https://x.com/products/a",
        "x.com",
        ["color_info"],
        client=FakeLLM({"recipes": []}, capture),
    )
    prompt = capture["prompt"]
    assert "var tracking" not in prompt  # noise removed
    assert "application/ld+json" in prompt  # a legal place for a rule to point
    assert "color_info" in prompt


@pytest.mark.unit
def test_tool_schema_constrains_the_answer():
    """Forced tool use is what removes the parse-prose-for-JSON step."""
    props = RECIPE_TOOL["input_schema"]["properties"]["recipes"]["items"]
    assert props["required"] == ["field", "kind", "expression", "expected"]
    assert "css_all_text" in props["properties"]["kind"]["enum"]
    assert "exec_shell" not in props["properties"]["kind"]["enum"]


@pytest.mark.unit
def test_api_key_is_read_from_config_env_when_not_exported(tmp_path, monkeypatch):
    """The key normally lives in config/.env; the package parses it without pulling in
    python-dotenv or anything from the legacy packages."""
    import backend.archive.finder_llm as fl

    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    fake_pkg = tmp_path / "backend" / "archive"
    fake_pkg.mkdir(parents=True)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / ".env").write_text(
        "# comment\nLLM_PROVIDER=claude\nCLAUDE_API_KEY=sk-ant-test123\n"
    )
    monkeypatch.setattr(fl, "__file__", str(fake_pkg / "finder_llm.py"))
    assert fl._api_key() == "sk-ant-test123"


@pytest.mark.unit
def test_exported_env_var_wins_over_the_file(monkeypatch):
    import backend.archive.finder_llm as fl

    monkeypatch.setenv("CLAUDE_API_KEY", "sk-ant-from-env")
    assert fl._api_key() == "sk-ant-from-env"
