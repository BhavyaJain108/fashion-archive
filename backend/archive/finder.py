"""Fill in fields the free channels missed (S4).

Two halves:
  apply_recipes  — deterministic, no LLM. Runs saved rules against a page.
  verify_recipe  — a rule is only kept if replaying it reproduces the value the
                   finder predicted. This is what stops invented selectors.

The LLM half (learning new rules) lives in finder_llm.py so this module stays
importable and testable without an API key.
"""

import json
import re

from bs4 import BeautifulSoup

from backend.archive.domain.recipe import Recipe

_MAX_VALUE_LEN = 2000


def apply_recipes(
    html: str, recipes: list[Recipe], context: dict | None = None, hits: dict | None = None
) -> dict[str, str]:
    """Run the rules against the page; a field keeps the first value that holds up.

    A brand accumulates several rules per field, because one storefront lays the same
    field out differently across its catalogue — a sneaker page's size buttons are not
    a dress page's dropdown. The rules are strategies to try in order, not one answer.
    """
    soup = BeautifulSoup(html, "lxml")
    out: dict[str, str] = {}
    for r in recipes:
        if r.field in out:
            continue  # an earlier strategy already produced a usable value
        try:
            value = _run(r, html, soup)
        except Exception:
            continue  # a broken rule never breaks a scrape
        if value and is_plausible(r.field, value, context):
            out[r.field] = value[:_MAX_VALUE_LEN]
            if hits is not None:
                key = (r.field, r.expression)
                hits[key] = hits.get(key, 0) + 1
    return out


# Rule kinds that collect every match, so their value is a list.
_LIST_KINDS = ("css_all_text", "css_all_attr")


# A regex with no metacharacters is not a pattern, it is a value someone copied off one
# page: theoutnet.com learned material_info rules reading "Kaschmirmischung" and
# "Linen-blend gauze", which matched 1% of its catalogue.
_REGEX_META = set(".*+?[]()|\\^$")


def _is_literal(recipe: Recipe) -> bool:
    return recipe.kind == "regex" and not (set(recipe.expression) & _REGEX_META)


def verify_recipe(recipe: Recipe, html: str) -> bool:
    """Keep a rule only if it reproduces what the finder said it would produce.

    A list-valued rule may be verified against the first entries alone. Demanding the
    whole value made galleries impossible to propose: psylos1's holds 18 image URLs,
    about 1,800 characters the model would have to reproduce exactly, so it correctly
    said nothing rather than risk a wrong rule. The check still does its real job —
    an invented selector matches nothing, so it cannot produce a prefix either.
    """
    if not recipe.expected or _is_literal(recipe):
        return False
    got = apply_recipes(html, [recipe]).get(recipe.field)
    if got is None:
        return False
    actual, expected = _norm(got), _norm(recipe.expected)
    if actual == expected:
        return True
    return bool(recipe.kind in _LIST_KINDS and expected and actual.startswith(expected))


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _text(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()


def _run(r: Recipe, html: str, soup: BeautifulSoup) -> str | None:
    if r.kind == "css_text":
        el = soup.select_one(r.expression)
        return _text(el) if el else None

    if r.kind == "css_all_text":
        vals = [_text(el) for el in soup.select(r.expression)]
        vals = [v for v in dict.fromkeys(vals) if v]
        return ", ".join(vals) or None

    if r.kind == "css_attr":
        el = soup.select_one(r.expression)
        if not el or not r.attribute:
            return None
        v = el.get(r.attribute)
        return " ".join(v) if isinstance(v, list) else v

    if r.kind == "css_all_attr":
        if not r.attribute:
            return None
        vals = []
        for el in soup.select(r.expression):
            v = el.get(r.attribute)
            if isinstance(v, list):
                v = " ".join(v)
            if v:
                vals.append(v.strip())
        return ", ".join(dict.fromkeys(vals)) or None

    if r.kind == "regex":
        m = re.search(r.expression, html, re.S | re.I)
        if not m:
            return None
        return (m.group(1) if m.groups() else m.group(0)).strip()

    if r.kind == "json_ld_path":
        node = _product_node(html)
        if node is None:
            return None
        cur = node
        for part in r.expression.split("."):
            if not part:
                continue
            if isinstance(cur, list):
                try:
                    cur = cur[int(part)]
                    continue
                except (ValueError, IndexError):
                    return None
            if not isinstance(cur, dict) or part not in cur:
                return None
            cur = cur[part]
        if isinstance(cur, list):
            return ", ".join(str(x) for x in cur if x) or None
        return str(cur) if cur not in (None, "") else None

    return None


_LD = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)


def _product_node(html: str):
    for block in _LD.findall(html):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        for node in _walk(data):
            types = node.get("@type", "")
            types = types if isinstance(types, list) else [types]
            if "Product" in types or "ProductGroup" in types:
                return node
    return None


def _walk(data):
    if isinstance(data, dict):
        yield data
        yield from _walk(data.get("@graph", []))
    elif isinstance(data, list):
        for x in data:
            yield from _walk(x)


# --- field shapes -----------------------------------------------------------------
#
# Replay verification proves a rule reproduces the value the model predicted. It does
# not prove the value means anything: theoutnet.com's learned size rule read the
# sold-out badge, and every product's size came back "Sold out". A shape is the cheap,
# brand-independent statement of what a field can look like — checked at runtime, never
# configured per brand. Shapes reject what is structurally impossible for a field, not
# merely unusual, because over-rejecting loses real data.

# Interface copy: never a value, except where the field is about stock.
_UI_PHRASES = (
    "sold out",
    "out of stock",
    "in stock",
    "add to cart",
    "add to bag",
    "add to basket",
    "select size",
    "choose size",
    "size guide",
    "size chart",
    "notify me",
    "coming soon",
    "unavailable",
    "sign up",
    "final sale",
)

# A size token carries a number, a letter code, or a regional prefix. psylos1 sells
# sizes written "US 3.5 MEN / US 5 WOMEN=IT 35", so tokens are allowed to be long.
_SIZE_HINT = re.compile(
    r"\d"  # 38, US 5.5, 3XL
    r"|^(?:x{0,3}s|m|x{0,3}l|os|u|f)$"  # XS  S  M  L  XXL
    r"|^(?:small|medium|large|petite|plus|tall|short|regular|one\s?size|free\s?size)$"
    r"|\b(?:us|uk|eu|it|fr|jp|cn|au|de)\b",
    re.I,
)
_STOCK_WORD = re.compile(
    r"^(?:true|false|yes|no|0|1|in\s?stock|out\s?of\s?stock|sold\s?out|available|"
    r"unavailable|instock|outofstock|low\s?stock|backorder|pre-?order)$",
    re.I,
)
_SENTENCE = re.compile(r"[.!?](?:\s|$)")
# Words that hold a sentence together. A size or a colour never needs them, so two or
# more of them means the rule picked up prose ("Free shipping on all orders over 100").
_PROSE_WORDS = frozenset(
    "a an the on in at of to for with and or from your our all over under by is are "
    "this that these those you we it be will can more than up off".split()
)


def _is_prose(token: str) -> bool:
    words = re.findall(r"[a-z']+", token.lower())
    return sum(1 for w in words if w in _PROSE_WORDS) >= 2


def _tokens(text: str) -> list[str]:
    return [t.strip() for t in text.split(",") if t.strip()]


def _shape_size_info(text: str) -> bool:
    tokens = _tokens(text)
    if not tokens or any(len(t) > 40 for t in tokens):
        return False
    if any(_is_prose(t) for t in tokens):
        return False
    # "XS/S" and "M/L" are one size written as a pair, so score each half.
    hits = sum(1 for t in tokens if all(_SIZE_HINT.search(h) for h in t.split("/") if h.strip()))
    return hits * 2 >= len(tokens)  # a majority must actually look like sizes


def _shape_size_availability(text: str) -> bool:
    tokens = _tokens(text)
    return bool(tokens) and all(_STOCK_WORD.match(t) for t in tokens)


def _shape_color(text: str) -> bool:
    tokens = _tokens(text)
    if not tokens:
        return False
    return all(
        len(t) <= 30 and len(t.split()) <= 6 and not _SENTENCE.search(t) and not _is_prose(t)
        for t in tokens
    )


def _shape_material(text: str) -> bool:
    # "75% ХЛОПОК 25% ПОЛИАМИД" is a composition in any language, but a percentage
    # buried in prose is not: wiacollections' whole 289-character short description
    # contains "100%CO" and would otherwise pass as a material.
    if re.search(r"\d\s*%", text) and len(text) <= 160:
        return True
    return len(text) <= 120 and not _SENTENCE.search(text[:-1])


def _shape_product_code(text: str) -> bool:
    return len(text) <= 40 and len(text.split()) <= 3 and not _SENTENCE.search(text)


_IMAGE_URL = re.compile(r"^https?://\S+$", re.I)


def _shape_image(text: str) -> bool:
    """Image fields hold URLs. A gallery rule that returns alt text or a data: blob is
    not an image, however reliably it reproduces itself."""
    urls = [t.strip() for t in text.split(",") if t.strip()]
    return bool(urls) and all(_IMAGE_URL.match(u) for u in urls)


_SHAPES = {
    "main_image_url": _shape_image,
    "all_images": _shape_image,
    "size_info": _shape_size_info,
    "size_availability": _shape_size_availability,
    "color_info": _shape_color,
    "material_info": _shape_material,
    "product_code": _shape_product_code,
}
# Fields whose real values are stock words, so the interface-copy list does not apply.
_STOCK_FIELDS = ("size_availability", "in_stock")


# The words a storefront uses to *label* a field. A value made only of these is the
# heading above the value: psylos1 learned a material rule that returned the text of
# the accordion button, "Fabrics & Materials", on every product.
_LABEL_WORDS = {
    "size_info": {"size", "sizes", "sizing", "select", "choose", "fit"},
    "size_availability": set(),
    "color_info": {"color", "colour", "colors", "colours", "shade", "select", "choose"},
    "material_info": {
        "material",
        "materials",
        "fabric",
        "fabrics",
        "composition",
        "care",
        "details",
        "description",
        "info",
        "information",
    },
    "product_code": {"sku", "code", "reference", "ref", "style", "item"},
}
_JOINERS = {"and", "or", "the", "of", "&", "/", "-", "+"}


def _is_label(field: str, text: str) -> bool:
    vocabulary = _LABEL_WORDS.get(field)
    if not vocabulary:
        return False
    words = re.findall(r"[a-z&/+-]+", text.lower())
    if not words:
        return False
    return all(w in vocabulary or w in _JOINERS for w in words)


def is_plausible(field: str, value: str, context: dict | None = None) -> bool:
    """Could this text be a real value for this field?

    Three questions, cheapest first: is it interface copy, does it fit the field's
    shape, and is it just an echo of text the record already carries elsewhere.
    """
    text = " ".join(value.split()).strip()
    if not text:
        return False
    low = text.lower()
    if field not in _STOCK_FIELDS and any(
        low == phrase or low.startswith(phrase + ",") for phrase in _UI_PHRASES
    ):
        return False
    if _is_label(field, text):
        return False
    shape = _SHAPES.get(field)
    if shape is not None and not shape(text):
        return False
    return not (context and _echoes(field, text, context))


def _echoes(field: str, text: str, context: dict) -> bool:
    """True when the value is really the product's title or description in disguise.

    A rule that grabs the wrong element usually grabs the most prominent text on the
    page. wiacollections.com learned a colour rule that returned "Pink heavyweight
    T-shirt" for a product titled "Lucky Pink Big White T-shirt": a fine-looking colour,
    and the title. Descriptions are exempt — a description is meant to read like one.
    """
    if field == "description":
        return False
    words = set(re.findall(r"[a-z0-9]+", text.lower()))
    # One or two words that also appear in the title are normal: a pink t-shirt's
    # colour is "Pink". A whole phrase of them is the title wearing a disguise.
    if len(words) < 3:
        return False
    for key in ("product_title", "description"):
        other = context.get(key) or ""
        other_words = set(re.findall(r"[a-z0-9]+", other.lower()[: len(text) + 40]))
        if other_words and len(words & other_words) * 2 >= len(words):
            return True
    return False
