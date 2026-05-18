"""Synthetic JSON-LD samples for testing the count walker."""

FLAT_ITEMLIST = {
    "@context": "https://schema.org",
    "@type": "ItemList",
    "numberOfItems": 47,
}

NESTED_COLLECTION_PAGE = {
    "@context": "https://schema.org",
    "@type": "CollectionPage",
    "name": "Hoodies",
    "mainEntity": {
        "@type": "ItemList",
        "numberOfItems": 32,
        "itemListElement": [],
    },
}

TWO_ITEMLISTS_PICK_LARGEST = [
    {"@type": "ItemList", "numberOfItems": 5, "name": "Related"},
    {"@type": "ItemList", "numberOfItems": 47, "name": "Main grid"},
]

GRAPH_WITH_ITEMLIST = {
    "@context": "https://schema.org",
    "@graph": [
        {"@type": "BreadcrumbList", "itemListElement": []},
        {"@type": "ItemList", "numberOfItems": 12},
    ],
}

MISSING_NUMBEROFITEMS = {
    "@type": "ItemList",
    "itemListElement": [{"@type": "Product"}, {"@type": "Product"}],
}

IMPLAUSIBLE_COUNT = {
    "@type": "ItemList",
    "numberOfItems": 999999,
}

NEGATIVE_COUNT = {
    "@type": "ItemList",
    "numberOfItems": -3,
}

NOT_AN_ITEMLIST = {
    "@type": "Product",
    "name": "Hoodie",
    "offers": {"@type": "Offer", "price": "47.00"},
}
