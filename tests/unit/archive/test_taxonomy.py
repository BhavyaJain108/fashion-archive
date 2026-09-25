"""The shared vocabulary: what a phrase is, and what one product answers to."""

import pytest

from backend.archive import taxonomy
from backend.archive.domain.product import ProductRecord
from backend.archive.store.objects import DirectoryObjectStore


def rec(**fields) -> ProductRecord:
    base = {"itemurl": "https://b.com/products/x", "product_title": "A Thing"}
    return ProductRecord(**{**base, **fields})


# --- what gets asked about -------------------------------------------------------


@pytest.mark.unit
def test_the_deepest_category_level_is_asked_first():
    """Vivienne Westwood files a necklace under Women > Jewellery > Necklaces. The
    leaf says what the thing is; the root says which section of the shop it sits in."""
    r = rec(category1="Women", category2="Jewellery", category3="Necklaces")
    assert taxonomy.phrases(r)[0] == "necklaces"
    assert "women" in taxonomy.phrases(r)


@pytest.mark.unit
def test_a_brand_with_no_categories_is_asked_about_its_title():
    """psylos1 has 7,939 products and not one category. The garment is the last word."""
    r = rec(product_title="Leopard Print Slit Skirt")
    assert "skirt" in taxonomy.phrases(r)


@pytest.mark.unit
def test_title_words_are_offered_right_to_left():
    """A title ending in a colour ("Corduroy Trousers - Black") must still reach the
    garment, so every trailing word is offered, nearest first."""
    got = taxonomy.phrases(rec(product_title="Corduroy Trousers Black"))
    assert got.index("black") < got.index("trousers")


@pytest.mark.unit
def test_a_categorised_product_still_offers_its_title():
    """The category can be a season ("FW26"). The title is the fallback, not a rival."""
    got = taxonomy.phrases(rec(category1="FW26", product_title="Wool Overcoat"))
    assert got[0] == "fw26" and "overcoat" in got


# --- what a phrase book answers --------------------------------------------------


@pytest.mark.unit
def test_the_first_phrase_the_book_knows_wins():
    book = taxonomy.PhraseBook({"skirt": ["skirts"], "black": ["not_a_garment"]})
    assert book.types_for(rec(product_title="Slit Skirt Black")) == ["skirts"]


@pytest.mark.unit
def test_a_phrase_may_answer_to_two_types():
    """ "set" is a top and a bottom, and the archive should show it under both."""
    book = taxonomy.PhraseBook({"set": ["tops", "trousers"]})
    assert book.types_for(rec(category1="Set")) == ["tops", "trousers"]


@pytest.mark.unit
def test_a_season_is_recorded_as_not_a_garment_and_answers_nothing():
    """The 550 products filed under FW26 and "adidas x entire studios" must fall
    through to the title rather than be forced into a garment bucket."""
    book = taxonomy.PhraseBook({"fw26": ["not_a_garment"], "overcoat": ["outerwear"]})
    assert book.types_for(rec(category1="FW26", product_title="Wool Overcoat")) == ["outerwear"]


@pytest.mark.unit
def test_a_product_the_book_cannot_place_answers_nothing():
    assert taxonomy.PhraseBook({}).types_for(rec()) == []


@pytest.mark.unit
def test_a_gift_card_is_placed_nowhere_even_though_the_book_knows_it():
    book = taxonomy.PhraseBook({"gift card": ["not_a_garment"]})
    assert book.types_for(rec(category1="Gift Card", product_title="Digital Gift Card")) == []


@pytest.mark.unit
def test_unknown_phrases_are_what_the_book_has_never_been_told():
    book = taxonomy.PhraseBook({"skirt": ["skirts"]})
    unknown = book.unknown([rec(product_title="Slit Skirt"), rec(product_title="Wool Coat")])
    assert "coat" in unknown and "skirt" not in unknown


@pytest.mark.unit
def test_a_phrase_is_asked_about_once_however_many_products_carry_it():
    """2,375 bode products carry 101 phrases. The call is about phrases, not products."""
    book = taxonomy.PhraseBook({})
    unknown = book.unknown([rec(category1="SHIRT") for _ in range(50)])
    assert unknown.count("shirt") == 1


# --- learning --------------------------------------------------------------------


@pytest.mark.unit
def test_learning_records_who_decided_and_when():
    book = taxonomy.PhraseBook({})
    book.learn({"clogs": ["shoes"]}, model="claude-haiku-4-5")
    assert book.entries["clogs"]["types"] == ["shoes"]
    assert book.entries["clogs"]["model"] == "claude-haiku-4-5"
    assert book.entries["clogs"]["decided_at"]


@pytest.mark.unit
def test_a_type_outside_the_vocabulary_is_refused():
    """The model maps onto our list; it does not get to invent a category."""
    book = taxonomy.PhraseBook({})
    book.learn({"clogs": ["footwear-ish"]}, model="m")
    assert "clogs" not in book.entries


@pytest.mark.unit
def test_a_phrase_already_decided_is_not_overwritten_by_a_later_run():
    book = taxonomy.PhraseBook({"clogs": ["shoes"]})
    book.learn({"clogs": ["bags"]}, model="m")
    assert book.types_for(rec(category1="Clogs")) == ["shoes"]


# --- the store -------------------------------------------------------------------


@pytest.mark.unit
def test_the_book_survives_a_round_trip(tmp_path):
    store = DirectoryObjectStore(tmp_path)
    book = taxonomy.load(store)
    book.learn({"clogs": ["shoes"]}, model="m")
    taxonomy.save(store, book)
    assert taxonomy.load(store).types_for(rec(category1="Clogs")) == ["shoes"]


@pytest.mark.unit
def test_two_workers_learning_at_once_keep_both_lessons(tmp_path):
    """Workers share one book. A blind write would drop whichever landed first, so a
    save merges into the stored copy rather than replacing it."""
    store = DirectoryObjectStore(tmp_path)
    first, second = taxonomy.load(store), taxonomy.load(store)
    first.learn({"clogs": ["shoes"]}, model="m")
    second.learn({"jorts": ["shorts"]}, model="m")
    taxonomy.save(store, first)
    taxonomy.save(store, second)
    stored = taxonomy.load(store)
    assert set(stored.entries) == {"clogs", "jorts"}


@pytest.mark.unit
def test_a_product_the_book_can_place_is_asked_about_nothing():
    """bode files a product under MENS SHIRTS; its title words are nobody's business."""
    book = taxonomy.PhraseBook({"mens shirts": ["shirts"]})
    r = rec(category1="MENS SHIRTS", product_title="1935 Cricket Shirt")
    assert book.unknown([r]) == []


@pytest.mark.unit
def test_an_unplaced_product_offers_one_phrase_at_a_time():
    """The answer to the first may place it, and then the rest never need asking."""
    book = taxonomy.PhraseBook({})
    assert book.unknown([rec(category1="FW26", product_title="Wool Overcoat")]) == ["fw26"]


@pytest.mark.unit
def test_the_next_round_reaches_the_title_once_the_season_is_known():
    book = taxonomy.PhraseBook({"fw26": ["not_a_garment"]})
    assert book.unknown([rec(category1="FW26", product_title="Wool Overcoat")]) == ["overcoat"]


@pytest.mark.unit
def test_a_precise_word_beats_the_shops_catch_all_drawer():
    """eightonline files a necklace under "Accessories". The title knows better."""
    book = taxonomy.PhraseBook({"accessories": ["accessories"], "necklace": ["jewellery"]})
    r = rec(category1="Accessories", product_title="LOGO NECKLACE")
    assert book.types_for(r) == ["jewellery"]


@pytest.mark.unit
def test_the_catch_all_still_answers_when_nothing_else_does():
    book = taxonomy.PhraseBook({"accessories": ["accessories"]})
    assert book.types_for(rec(category1="Accessories", product_title="Mystery")) == ["accessories"]


@pytest.mark.unit
def test_a_weak_entry_yields_to_anything_more_specific():
    """ "set" is a top and a bottom — unless the product says bikini."""
    book = taxonomy.PhraseBook(
        {"set": {"types": ["tops", "trousers"], "weak": True}, "bikini": {"types": ["swimwear"]}}
    )
    assert book.types_for(rec(product_title="Chichi Bikini Set")) == ["swimwear"]
    assert book.types_for(rec(product_title="ADRIA SET")) == ["tops", "trousers"]


# --- what is not merchandise at all ----------------------------------------------


@pytest.mark.unit
def test_a_gift_card_is_not_merchandise():
    """Not the same as "not a garment": FW26 is not a garment and its products are
    real. A gift card is a row in the shop that nobody should see on the page."""
    book = taxonomy.PhraseBook({"digital gift card": [taxonomy.NOT_A_PRODUCT]})
    r = rec(product_title="Digital Gift Card")
    assert book.is_product(r) is False
    assert book.types_for(r) == []


@pytest.mark.unit
def test_a_garment_is_merchandise():
    book = taxonomy.PhraseBook({"skirt": ["skirts"]})
    assert book.is_product(rec(product_title="Slit Skirt")) is True


@pytest.mark.unit
def test_a_product_nobody_has_placed_is_merchandise_until_shown_otherwise():
    """A blank is not evidence. Hiding an unplaced product would empty the archive."""
    assert taxonomy.PhraseBook({}).is_product(rec()) is True


@pytest.mark.unit
def test_a_garment_word_earlier_in_the_title_beats_a_later_fee_word():
    """"Card Holder" is a wallet; the word "card" alone must not hide it."""
    book = taxonomy.PhraseBook({"holder": ["wallets"], "card": [taxonomy.NOT_A_PRODUCT]})
    assert book.is_product(rec(product_title="Leather Card Holder")) is True


# --- asking past a vague answer ---------------------------------------------------


@pytest.mark.unit
def test_a_product_placed_only_by_a_drawer_word_keeps_being_asked_about():
    """bode files a barrette under ACCESSORIES. "accessories" is not an answer to
    what the thing is, so the question stays open."""
    book = taxonomy.PhraseBook({"accessories": ["accessories"]})
    r = rec(category1="ACCESSORIES", product_title="Sequin Pony Barrette")
    assert book.types_for(r) == ["accessories"]  # still answers, for now
    assert "barrette" in book.unknown([r])  # but has not stopped asking


@pytest.mark.unit
def test_a_specific_answer_closes_the_question():
    book = taxonomy.PhraseBook({"accessories": ["accessories"], "barrette": ["hair-accessories"]})
    r = rec(category1="ACCESSORIES", product_title="Sequin Pony Barrette")
    assert book.unknown([r]) == []
    assert book.types_for(r) == ["hair-accessories"]


# --- the last resort --------------------------------------------------------------


@pytest.mark.unit
def test_the_whole_title_is_offered_only_when_asked_for():
    """Asking about every title would be one question per product — the thing this
    design exists to avoid. It is the final fallback, not a phrase like the others."""
    r = rec(product_title="Romance Solitaire 1.00 Carat DVVS1")
    book = taxonomy.PhraseBook({})
    assert "romance solitaire 1 00 carat dvvs1" not in book.unknown([r])
    assert "romance solitaire 1 00 carat dvvs1" in book.unknown([r], last_resort=True)


@pytest.mark.unit
def test_a_placed_product_is_not_asked_about_by_title_even_at_the_last_resort():
    book = taxonomy.PhraseBook({"skirt": ["skirts"]})
    assert book.unknown([rec(product_title="Slit Skirt")], last_resort=True) == []
