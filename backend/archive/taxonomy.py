"""One vocabulary across every brand (S4c).

`category1..10` holds the path the shop itself published, and it stays that way — bode
says `MENS SHIRTS`, degreeofdenim says `Shirts`, twofold says `SHIRT`, marrknull says
`上衣`. Four shops, one garment, and no way to ask the archive for shirts.

This is the layer that answers that question without touching what the brands said. The
unit it works in is a **phrase**, not a product: the levels of a shop's category path,
and — for the brands that publish no categories at all — the trailing words of the
product title, which is where the garment almost always is ("Leopard Print Slit Skirt").
Measured over the fleet on 2026-09-23: 309 distinct category strings and 958 distinct
title last-words cover 22,597 products. One entry per phrase means the model is asked
about 1,300 short strings once, not about every product forever.

Three rules the data argued for:

  a phrase may answer to **more than one** type — "set" is a top and a bottom;
  a phrase may answer to **none** — `fw26`, `2025-2`, `adidas x entire studios` and
  `mws_fee_generated` are a season, a drop, a collaboration and a payment line. Those are
  recorded as `not_a_garment` rather than left absent, so the next run knows they were
  considered and does not pay to ask again;
  a phrase that is not a garment falls through to the next phrase, which is why the
  title is offered even when a category exists — otherwise Entire Studios' 380 products
  would be filed under `FW26` forever.

The book is one fleet-wide object. A phrase learned on bode is free on twofold.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from backend.archive.store.objects import Conflict, ObjectStore, dumps, loads

KEY = "taxonomy/phrases.json"

# The vocabulary. Written here rather than induced by the model: a list the model
# invents drifts every run, and the whole point is that twenty brands answer to the
# same word. `not_a_garment` is a real answer, not a failure to answer.
NOT_A_GARMENT = "not_a_garment"
TYPES = (
    "t-shirts",
    "shirts",
    "tops",
    "knitwear",
    "sweatshirts",
    "trousers",
    "jeans",
    "shorts",
    "skirts",
    "dresses",
    "outerwear",
    "suits",
    "jumpsuits",
    "underwear",
    "swimwear",
    "sleepwear",
    "activewear",
    "shoes",
    "bags",
    "hats",
    "belts",
    "scarves",
    "gloves",
    "socks",
    "jewellery",
    "watches",
    "eyewear",
    "hair-accessories",
    "wallets",
    "accessories",
    "homeware",
    "fragrance",
    "beauty",
    "kidswear",
    "petwear",
    NOT_A_GARMENT,
)
VALID = frozenset(TYPES)

# Types that describe a drawer rather than a thing. A shop's own top level is full of
# them, and they lose to anything more specific the product says about itself.
CATCH_ALL = frozenset({"accessories"})

# How many trailing title words are offered. Four reaches the garment in compounds like
# "Low-Rise Loose Wide-Leg Pants" while staying short enough that the phrase list over a
# whole catalogue stays in the hundreds.
TITLE_WORDS = 4

_WORD = re.compile(r"[^\w\s/&-]+", re.UNICODE)
_WS = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _WS.sub(" ", _WORD.sub(" ", str(text or "").lower())).strip()


def _get(record: Any, field: str):
    return record.get(field) if isinstance(record, dict) else getattr(record, field, None)


def phrases(record: Any) -> list[str]:
    """Everything worth asking about this product, best answer first.

    Order is the whole argument: the deepest category level (the leaf says what the
    thing *is*, the root says which part of the shop it sits in), then the rest of the
    path, then the title's trailing words nearest-last. A `ProductRecord` or the dict
    the store holds; both are read the same way.
    """
    out: list[str] = []
    path = [_norm(_get(record, f"category{i}") or "") for i in range(1, 11)]
    path = [p for p in path if p]
    out.extend(reversed(path))
    words = _norm(_get(record, "product_title") or "").split()
    out.extend(reversed(words[-TITLE_WORDS:]))
    return list(dict.fromkeys(out))


class PhraseBook:
    """What each phrase answers to, and what has never been asked."""

    def __init__(self, entries: dict[str, Any] | None = None):
        # Accepts both the stored shape ({"types": [...], "model": ..}) and a bare
        # list of types, so a test and a caller can state the same thing plainly.
        self.entries: dict[str, dict] = {
            phrase: (value if isinstance(value, dict) else {"types": list(value)})
            for phrase, value in (entries or {}).items()
        }

    def types_for(self, record: Any) -> list[str]:
        """The canonical types this product answers to, or nothing.

        The first phrase the book knows decides it — and a phrase known to be
        `not_a_garment` decides it too, by handing the question to the next phrase.

        With one exception, which the first live pass earned: some phrases describe a
        drawer rather than a thing, and a precise word elsewhere in the product beats
        them. Two kinds, both held as a fallback and used only if nothing better turns
        up — an answer, but the last one asked:

          a catch-all *type* — eightonline files a necklace under `Accessories`, and
          answering "accessories" when the title says *necklace* is worse than the
          product already had;
          an entry marked `weak` — "set" means a top and a bottom 291 times over and
          swimwear in "Chichi Bikini Set". Marking it weak keeps both right.
        """
        fallback: list[str] = []
        for phrase in phrases(record):
            known = self.entries.get(phrase)
            if not known:
                continue
            types = [t for t in known.get("types", []) if t != NOT_A_GARMENT]
            if not types:
                continue
            if known.get("weak") or all(t in CATCH_ALL for t in types):
                fallback = fallback or types
                continue
            return types
        return fallback

    def unknown(self, records: list[Any]) -> list[str]:
        """The phrases worth asking about next, deduplicated.

        Lazy on purpose, and the fleet's numbers are why. Asking about every phrase in
        every product meant 8,149 questions across 22,597 products — most of them words
        like `1776`, `cricket` and `quilt`, asked about products bode already files under
        `MENS SHIRTS`. So:

          a product the book can already place is asked about nothing;
          an unplaced one offers its *first* unknown phrase and stops, because the answer
          to that one may place it and make the rest moot.

        A caller that wants a brand fully placed asks again after learning — each round
        is one cheap call, and the rounds stop as soon as nothing is left to ask.
        """
        out: list[str] = []
        seen: set[str] = set()
        for record in records:
            for phrase in phrases(record):
                known = self.entries.get(phrase)
                if known is None:
                    if phrase not in seen:
                        seen.add(phrase)
                        out.append(phrase)
                    break  # its answer may settle this product; the rest can wait
                if [t for t in known.get("types", []) if t != NOT_A_GARMENT]:
                    break  # already placed
        return out

    def learn(self, decided: dict[str, list[str]], model: str) -> int:
        """Record decisions, dropping anything outside the vocabulary.

        A phrase already decided is left alone: the book is the record of what we have
        settled, and a later run re-litigating it would make the archive's categories
        change under a reader for no reason anyone asked for. Correcting one is an edit
        to the object, deliberate and visible.
        """
        now = datetime.now(timezone.utc).isoformat()
        added = 0
        for phrase, types in (decided or {}).items():
            key = _norm(phrase)
            if not key or key in self.entries:
                continue
            clean = [t for t in dict.fromkeys(types or []) if t in VALID]
            if not clean:
                continue
            self.entries[key] = {"types": clean, "model": model, "decided_at": now}
            added += 1
        return added

    def as_dict(self) -> dict:
        return dict(self.entries)


def load(store: ObjectStore) -> PhraseBook:
    found = store.get(KEY)
    return PhraseBook(loads(found[0]) if found else {})


def save(store: ObjectStore, book: PhraseBook, attempts: int = 10) -> None:
    """Merge this book into the stored one.

    Two workers scraping two brands both learn phrases, and a blind write would drop
    whichever landed first — the same compare-and-swap the fleet object uses, for the
    same reason. Merging entries rather than replacing the map is what makes the retry
    safe; a phrase already in the store wins, so nobody's decision is rewritten.
    """
    for _ in range(attempts):
        found = store.get(KEY)
        stored = loads(found[0]) if found else {}
        etag = found[1] if found else None
        merged = {**book.as_dict(), **stored}
        if merged == stored:
            return
        try:
            store.put(KEY, dumps(merged), if_match=etag)
            book.entries = merged
            return
        except Conflict:
            continue


# The field the canonical types travel in once a record leaves the store. It is not an
# E0005 field and is never written to a catalogue: E0005 is the vocabulary the brands
# and the frontend share, and the rule here has always been that nothing maps inside it.
# This is added on the way out, which is also what lets a correction to the book reach
# every brand at once instead of waiting for 41 rescrapes.
TYPE_FIELD = "archive_type"


def typed(records: list[dict], book: PhraseBook) -> list[dict]:
    """Copies of these records, each carrying what it answers to.

    Copies, not edits: the catalogue objects are cached in memory by the store, and a
    reader that wrote into them would have the archive quietly grow a field it never
    stored.
    """
    out = []
    for record in records:
        types = book.types_for(record)
        out.append({**record, TYPE_FIELD: ", ".join(types) if types else None})
    return out
