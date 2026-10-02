"""What is merchandise and what is a line item. Every case here was a live row on
2026-10-02, kept or dropped; the garments are the ones a wider word list would take."""

import pytest

from backend.archive.connectors.base import NotAProduct
from backend.archive.connectors.merch import not_merchandise
from backend.archive.connectors.shopify import map_product


@pytest.mark.unit
@pytest.mark.parametrize(
    "title",
    [
        "Gift Card",
        "KWAME ADUSEI E-GIFT CARD",
        "Maketh Thou Digital Gift Card",
        "RC Outdoor Supply® Gift Card",
        "Virtual Gift Card - CAD",
        "E-VOUCHER",
        "GIFT VOUCHER",
        "Shipping Protection",
        "Shipping insurance",
        "Worry-Free Purchase",
        "SHIPPING FEE",
        "Return Shipping Fee",
        "U.S. Warehouse Return Handling Fee",
        "Boxing Day Shipping",
        "CUSTOM SURCHARGE",
        "Price difference",
        "Tax",
        "Authentication Certificate",
        "Are You Am I Loft Appointment",
        "Look 13",
    ],
)
def test_a_line_item_is_named_by_its_title(title):
    assert not_merchandise(title)


@pytest.mark.unit
@pytest.mark.parametrize(
    "title",
    [
        "MIICHOUS | Heavyweight Cotton Sticker Print Zip Sweatshirt",
        "CDG Homme x New Balance 2010V (White)",
        "Fringe Tip Suede Sabot",
        "Yale Postage Tote",
        "Swatch Sweater - Peach",
        "Ourselvesremake | Repair Design Jeans",
        "Gift Card Holder in Black Leather",
        "Mystery Box 1",
        "SHIRT DIGITAL",
        "Disorder Balance Loose Tee",
        "Look Book Tote",
    ],
)
def test_a_garment_that_shares_a_word_with_a_line_item_is_kept(title):
    assert not_merchandise(title) is None


@pytest.mark.unit
def test_the_shops_own_word_decides_when_the_title_does_not():
    assert not_merchandise("JUMP THE LINE", product_type="Subscription")
    assert not_merchandise("SWAP Protect", vendor="SWAP Commerce")
    assert not_merchandise("Pattern Customization", ships=False)
    # A bag whose variants were mis-set to need no shipping, filed under a real type.
    assert not_merchandise("Marla burgundy bag", product_type="Handbags", ships=False) is None
    assert not_merchandise("A dress", ships=None) is None


@pytest.mark.unit
def test_the_shopify_mapper_declines_a_gift_card_and_keeps_a_dress():
    def product(title, product_type="", ships=True):
        return {
            "title": title,
            "handle": title.lower().replace(" ", "-"),
            "product_type": product_type,
            "vendor": "Shop",
            "variants": [{"price": "50.00", "available": True, "requires_shipping": ships}],
            "images": [{"src": "https://cdn.shopify.com/a.jpg"}],
            "options": [],
        }

    with pytest.raises(NotAProduct):
        map_product(product("Gift Card", "Gift Card", ships=False), "shop.com")
    with pytest.raises(NotAProduct):
        map_product(product("Shipping Protection by Route", "Insurance", ships=False), "shop.com")
    assert (
        map_product(product("Silk Slip Dress", "Dresses"), "shop.com").product_title
        == "Silk Slip Dress"
    )
