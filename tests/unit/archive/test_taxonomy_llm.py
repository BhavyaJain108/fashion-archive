"""Asking the model to place phrases in our vocabulary — hermetic, no network."""

import pytest

from backend.archive import taxonomy, taxonomy_llm


class FakeClient:
    """Answers like the forced-tool call does: one object, no prose."""

    def __init__(self, answers=None, fail_on=None):
        self.answers = answers or {}
        self.batches: list[list[str]] = []
        self._fail_on = fail_on or set()

    def decide(self, batch):
        self.batches.append(list(batch))
        if any(p in self._fail_on for p in batch):
            raise RuntimeError("overloaded")
        return {"placements": [{"phrase": p, "types": self.answers.get(p, [])} for p in batch]}


@pytest.mark.unit
def test_the_model_places_a_phrase_in_the_vocabulary():
    client = FakeClient({"clogs": ["shoes"]})
    assert taxonomy_llm.decide(["clogs"], client=client) == {"clogs": ["shoes"]}


@pytest.mark.unit
def test_phrases_go_up_in_batches_rather_than_one_call_each():
    client = FakeClient()
    taxonomy_llm.decide([f"phrase-{i}" for i in range(250)], client=client, batch=100)
    assert [len(b) for b in client.batches] == [100, 100, 50]


@pytest.mark.unit
def test_a_batch_that_fails_costs_only_that_batch():
    """An overloaded call on batch two must not throw away batch one's answers."""
    client = FakeClient({"a": ["tops"], "c": ["bags"]}, fail_on={"b"})
    got = taxonomy_llm.decide(["a", "b", "c"], client=client, batch=1)
    assert got == {"a": ["tops"], "c": ["bags"]}


@pytest.mark.unit
def test_an_invented_type_is_dropped_before_it_reaches_the_book():
    client = FakeClient({"clogs": ["footwear-ish", "shoes"]})
    assert taxonomy_llm.decide(["clogs"], client=client) == {"clogs": ["shoes"]}


@pytest.mark.unit
def test_a_phrase_the_model_declines_to_place_is_recorded_as_not_a_garment():
    """Silence would mean asking again next run, forever, and paying every time."""
    client = FakeClient({"mws_fee_generated": []})
    got = taxonomy_llm.decide(["mws_fee_generated"], client=client)
    assert got == {"mws_fee_generated": [taxonomy.NOT_A_GARMENT]}


@pytest.mark.unit
def test_an_answer_about_a_phrase_nobody_asked_about_is_ignored():
    client = FakeClient()
    client.decide = lambda batch: {"placements": [{"phrase": "invented", "types": ["tops"]}]}
    assert taxonomy_llm.decide(["clogs"], client=client) == {}


@pytest.mark.unit
def test_nothing_to_ask_means_no_call_at_all():
    client = FakeClient()
    assert taxonomy_llm.decide([], client=client) == {}
    assert client.batches == []


@pytest.mark.unit
def test_the_prompt_states_the_vocabulary_and_the_empty_answer():
    prompt = taxonomy_llm.PROMPT
    assert "t-shirts" in prompt and "not_a_garment" in prompt
