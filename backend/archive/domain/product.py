"""Product models in the E0005 schema — the same field names the frontend and the old
pipeline use. One vocabulary, no mapping layer.

E0005 is a flat export standard: variant data lives in parallel comma-separated strings
aligned 1:1 by position, images are a JSON-encoded array, categories are numbered columns.
The helpers below are the only place that shape is constructed.
"""

import json

from pydantic import BaseModel, Field

# The E0005 export standard, in order. This tuple is the definition: it used to cite
# prod_page_v2/e0005/field_specs.py as the authority, and that file went with the
# generation it belonged to. Order matters — a flat export is read by position.
E0005_FIELDS = (
    "itemurl",
    "product_title",
    "product_code",
    "brand",
    "description",
    "specifications",
    "additional_code_1",
    "additional_code_1_type",
    "additional_code_2",
    "additional_code_2_type",
    "additional_code_3",
    "additional_code_3_type",
    "size_info",
    "size_availability",
    "size_stock_counts",
    "color_info",
    "material_info",
    "variant_info",
    "price",
    "full_price",
    "promotion_type",
    "promotion_end_date",
    "ppu",
    "unit_type",
    "package_desc",
    "in_stock",
    "quantity",
    *(f"category{i}" for i in range(1, 11)),
    "main_image_url",
    "all_images",
    "additional_tags",
    "delivery",
    "additional_content",
)

# Where a field can be looked for, shallowest first. A blank is only trustworthy when we
# can say which of these were consulted: "the brand does not publish it" and "we never
# looked at the page" are different facts and used to be stored identically.
SOURCES = ("channel", "page_rules", "page_rendered", "page_llm")

# Fields whose value is a list, so "how much do we have" is a count and not a yes/no.
LIST_FIELDS = ("all_images",)


def completeness(record, field: str) -> int:
    """How much of this field we hold: 0 for nothing, else how many values.

    One definition, used everywhere. The pipeline used to answer "is this field done?"
    in three places and disagree: the gap check called theoutnet.com's single image
    incomplete, the fill step called it filled and refused to overwrite, and the
    invariant compared whole URLs. So a gallery rule was learned on every run, never
    applied, and broke a check the one time it was.
    """
    value = record.get(field) if isinstance(record, dict) else getattr(record, field, None)
    if value in (None, "", [], {}):
        return 0
    if field in LIST_FIELDS:
        try:
            return len(json.loads(value)) if isinstance(value, str) else len(value)
        except (json.JSONDecodeError, TypeError):
            return 0
    return 1


def is_complete(record, field: str) -> bool:
    """Do we have an answer for this field at all?

    One measure, two questions, and they are not the same one. A shop with a single
    photograph of a garment has answered the question — humanbynature publishes between
    1 and 20 images per product and every count is the truth. Judging that a failure
    called 15 brands broken for photographing their stock the way they chose to.
    """
    return completeness(record, field) >= 1


def is_worth_chasing(record, field: str) -> bool:
    """Could there be more of this field than we hold?

    The other question. A list of one may be all there is, or it may be a hero shot
    where the channel never mentioned the gallery — theoutnet.com stored exactly one
    image for all 300 products while its pages showed six. Worth one look; not a
    failure if the look finds nothing.
    """
    held = completeness(record, field)
    return held == 0 or (field in LIST_FIELDS and held < 2)


WATCHED_FIELDS = ("price", "full_price", "in_stock", "size_availability")

MAX_CATEGORY_LEVELS = 10  # E0005 carries a ten-level navigation path


class ProductRef(BaseModel):
    url: str
    change_hint: str | None = None
    payload: dict | None = None  # bulk feeds carry the full record along


class ProductRecord(BaseModel):
    # identity
    itemurl: str
    product_title: str
    product_code: str | None = None
    brand: str | None = None
    description: str | None = None
    # commerce
    price: float | None = None
    full_price: float | None = None
    currency: str | None = None
    promotion_type: str | None = None
    promotion_end_date: str | None = None
    ppu: float | None = None  # price per unit, where a shop sells by measure
    unit_type: str | None = None  # the unit ppu is expressed in
    package_desc: str | None = None  # multipack / packaging info
    in_stock: bool | None = None
    quantity: int | None = None  # stock count shown on the page (rare)
    specifications: str | None = None  # technical/visual specs listed for the product
    # barcode-style identifiers (GTIN / UPC / EAN / ASIN / MPN / ISBN), each with the
    # label that says which one it is — a code without its type is unusable
    additional_code_1: str | None = None
    additional_code_1_type: str | None = None
    additional_code_2: str | None = None
    additional_code_2_type: str | None = None
    additional_code_3: str | None = None
    additional_code_3_type: str | None = None
    # variants — parallel, aligned 1:1 by position
    size_info: str | None = None  # "S, M, L"
    size_availability: str | None = None  # "in_stock, out_of_stock, in_stock"
    size_stock_counts: str | None = None  # "3, 0, 7"
    color_info: str | None = None
    material_info: str | None = None
    variant_info: str | None = None  # variant axes that are neither size nor colour
    # media
    main_image_url: str | None = None
    all_images: str | None = None  # JSON-encoded array of URLs
    additional_tags: str | None = None  # labels/badges shown on the page
    delivery: str | None = None  # shipping text shown on this product's page
    additional_content: str | None = None  # product information no other field carries
    # taxonomy
    category1: str | None = None
    category2: str | None = None
    category3: str | None = None
    category4: str | None = None
    category5: str | None = None
    category6: str | None = None
    category7: str | None = None
    category8: str | None = None
    category9: str | None = None
    category10: str | None = None
    raw: dict = Field(default_factory=dict)

    def image_list(self) -> list[str]:
        """Decode all_images back to a list (for the image archiver)."""
        if not self.all_images:
            return []
        try:
            return json.loads(self.all_images)
        except (json.JSONDecodeError, TypeError):
            return []


def pack_sizes(sizes: list[dict]) -> dict:
    """[{size, available, count}] → the three aligned E0005 strings.

    Returns a dict of field values ready to splat into ProductRecord.
    """
    labels = [str(s.get("size")) for s in sizes if s.get("size") not in (None, "")]
    if not labels:
        return {"size_info": None, "size_availability": None, "size_stock_counts": None}
    avail, counts = [], []
    for s in sizes:
        if s.get("size") in (None, ""):
            continue
        a = s.get("available")
        avail.append("in_stock" if a else "out_of_stock" if a is not None else "")
        counts.append("" if s.get("count") is None else str(s["count"]))
    return {
        "size_info": ", ".join(labels),
        "size_availability": ", ".join(avail) if any(avail) else None,
        "size_stock_counts": ", ".join(counts) if any(counts) else None,
    }


def pack_images(urls: list[str]) -> dict:
    urls = [u for u in urls if u]
    return {
        "main_image_url": urls[0] if urls else None,
        "all_images": json.dumps(urls) if urls else None,
    }


def pack_categories(names: list[str]) -> dict:
    names = [n for n in names if n][:MAX_CATEGORY_LEVELS]
    return {f"category{i + 1}": n for i, n in enumerate(names)}
