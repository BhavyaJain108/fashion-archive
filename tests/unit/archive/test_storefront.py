from backend.archive import storefront as sf


def test_classify_prefers_shop_category_then_title_and_checks_specific_first():
    assert sf.classify({"category1": "JACKETS", "product_title": "Blue denim"}) == (
        "Clothing",
        "Jackets & coats",
    )
    assert sf.classify({"product_title": "Navy Denim Jacket"}) == ("Clothing", "Jackets & coats")
    assert sf.classify({"product_title": "Wide leg jeans"}) == ("Clothing", "Jeans")
    assert sf.classify({"product_title": "Sunset print tee"}) == ("Clothing", "Tees")  # not "set"
    assert sf.classify({"product_title": "Gift card"}) == ("Everything else", "Everything else")
    assert sf.classify({"product_title": "Cashmere Rollneck - Grey"}) == ("Clothing", "Knitwear")
    assert sf.classify({"product_title": "Floral Bow Barrette"}) == ("Accessories", "Hair")
    assert sf.classify({"product_title": "Garden Party Pillowcases"}) == ("Everything else", "Home")


def test_colour_folds_text_and_calls_mixtures_multi():
    assert sf.colour({"color_info": "Cream"}) == "Tan"
    assert sf.colour({"color_info": "Black / White"}) == "Multi"
    assert sf.colour({"product_title": "Olive cargo pant"}) == "Green"
    assert sf.colour({"product_title": "Wool coat"}) is None
    # tags list every colourway; they only count when nothing else named a colour
    assert (
        sf.colour({"product_title": "Logo tee", "additional_tags": "BLACK, WHITE, NAVY"}) == "Black"
    )
    assert sf.colour({"color_info": "Cream", "additional_tags": "BLACK, WHITE"}) == "Tan"


def test_placeholder_prices_are_no_price():
    t = sf.tile(
        {"product_title": "Made to order set", "price": "99999"},
        brand_id="x",
        brand_name="X",
        first_seen=None,
        archived=[],
    )
    assert t["price"] is None


def _index():
    recs = [
        (
            {
                "product_title": "Denim jacket",
                "price": "300",
                "full_price": "400",
                "color_info": "Indigo",
                "itemurl": "a",
            },
            "2026-09-01",
        ),
        ({"product_title": "Wool sweater", "price": "200", "itemurl": "b"}, "2026-09-10"),
        (
            {
                "product_title": "Leather boot",
                "price": "500",
                "color_info": "Black",
                "itemurl": "c",
            },
            "2026-08-01",
        ),
    ]
    tiles = [
        sf.tile(r, brand_id="x.com", brand_name="X", first_seen=d, archived=[]) for r, d in recs
    ]
    return sf.Index(tiles=tiles, brands=[{"brand_id": "x.com", "name": "X", "products": 3}])


def test_query_sorts_filters_and_counts():
    ix = _index()
    latest = sf.query(ix)["products"]
    assert [t["title"] for t in latest] == ["Wool sweater", "Denim jacket", "Leather boot"]
    cheap = sf.query(ix, sort="price-asc")["products"]
    assert [t["price"] for t in cheap] == [200.0, 300.0, 500.0]
    sale = sf.query(ix, sale=True)
    assert sale["total"] == 1 and sale["products"][0]["discount"] == 0.25
    shoes = sf.query(ix, group="Shoes")
    assert shoes["total"] == 1
    # facets count along every axis except their own: the Shoes filter still lists Clothing
    assert {c["group"] for c in shoes["facets"]["categories"]} == {"Clothing", "Shoes"}
    assert shoes["facets"]["colours"] == [{"colour": "Black", "count": 1}]
    assert shoes["facets"]["designers"][0]["count"] == 1


def test_sizes_carry_the_variant_id_the_cart_takes():
    t = sf.tile(
        {
            "product_title": "Cap",
            "itemurl": "https://x.com/products/cap",
            "size_info": "S, M",
            "size_availability": "in_stock, out_of_stock",
            "platform": "shopify",
            "handle": "cap",
            "offers": [
                {"size": "S", "variant_id": "1", "available": False, "price": 40.0},
                {"size": "S", "variant_id": "2", "available": True, "price": 40.0},
                {"size": "M", "variant_id": "3", "available": False, "price": 40.0},
            ],
        },
        brand_id="x.com",
        brand_name="X",
        first_seen=None,
        archived=[],
    )
    assert t["platform"] == "shopify"
    # Two variants carry S; the one in stock is the one a size button should add.
    assert [(s["size"], s.get("variant_id")) for s in t["sizes"]] == [("S", "2"), ("M", "3")]
    assert len(t["offers"]) == 3
    assert "offers" not in sf.slim(t), "the grid does not carry every variant"


def test_a_record_without_offers_has_sizes_without_ids():
    t = sf.tile(
        {"product_title": "Tee", "itemurl": "https://x.com/p/tee", "size_info": "S"},
        brand_id="x.com",
        brand_name="X",
        first_seen=None,
        archived=[],
    )
    assert t["platform"] is None and t["offers"] == []
    assert t["sizes"] == [{"size": "S", "available": True}]


# --- the shared vocabulary reaching the shop front --------------------------------


def test_the_book_places_what_the_keyword_list_has_no_word_for():
    """Socks, fragrance and scarves have no keyword bucket, so 822 products the
    archive could already name were landing in Everything else."""
    from backend.archive import taxonomy

    book = taxonomy.PhraseBook({"shawl": ["scarves"], "long johns": ["underwear"]})
    assert sf.classify({"product_title": "Lawrence Shawl"}, book) == (
        "Accessories",
        "Scarves & gloves",
    )
    assert sf.classify({"product_title": "Long Johns"}, book) == ("Clothing", "Underwear & swim")


def test_the_keyword_list_still_answers_when_the_book_cannot():
    from backend.archive import taxonomy

    empty = taxonomy.PhraseBook({})
    assert sf.classify({"product_title": "Navy Denim Jacket"}, empty) == (
        "Clothing",
        "Jackets & coats",
    )


def test_the_shops_own_category_still_outranks_the_book():
    """A shop that says JACKETS is better evidence than a word in the title."""
    from backend.archive import taxonomy

    book = taxonomy.PhraseBook({"denim": ["jeans"]})
    assert sf.classify({"category1": "JACKETS", "product_title": "Blue denim"}, book) == (
        "Clothing",
        "Jackets & coats",
    )


def test_every_type_in_the_vocabulary_has_somewhere_to_go():
    """A type with no bucket would quietly land in Everything else — the bug this
    whole change exists to fix."""
    from backend.archive import taxonomy

    missing = [
        t
        for t in taxonomy.TYPES
        if t not in (taxonomy.NOT_A_GARMENT, taxonomy.NOT_A_PRODUCT)
        and t not in sf.BUCKET_OF_TYPE
    ]
    assert missing == []


def test_a_keyword_the_list_knows_beats_the_books_drawer_word():
    """bode files nine barrettes under ACCESSORIES. "Hair" is the better shelf, and
    the keyword list has always known the word — the book must not talk over it."""
    from backend.archive import taxonomy

    book = taxonomy.PhraseBook({"accessories": ["accessories"]})
    record = {"category1": "ACCESSORIES", "product_title": "Floral Bow Barrette"}
    assert sf.classify(record, book) == ("Accessories", "Hair")


def test_the_drawer_word_is_still_better_than_everything_else():
    """No keyword in the title, so the shop's drawer is all anyone has — and a drawer
    beats Everything else."""
    from backend.archive import taxonomy

    book = taxonomy.PhraseBook({"accessories": ["accessories"]})
    record = {"category1": "ACCESSORIES", "product_title": "Bayou Trinket"}
    assert sf.classify(record, book) == ("Accessories", "Accessories")
