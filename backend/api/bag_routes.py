"""The shopping bag, across every brand — HTTP endpoints.

    GET    /api/bag                 the bag, grouped by shop, checked against the catalogue
    POST   /api/bag/lines           {brand, itemurl, variant_id?, size?, qty?}  → the bag
    PATCH  /api/bag/lines/<id>      {qty}                                       → the bag
    DELETE /api/bag/lines/<id>                                                  → the bag
    DELETE /api/bag                                                             → the bag (empty)
    GET    /api/bag/checkout        per-shop totals and the links that take the money

Every handler is scoped to `current_user()`. A line is priced when it is added
and re-priced from the catalogue on every read, so the bag says `changed` and
`unavailable` rather than showing a number that is no longer true. The site
never charges anyone: /checkout returns the shops' own cart URLs (or, once a
buyer-of-record provider is configured, that provider's session).

The catalogue is asked through the storefront index — the same in-memory
tiles the product page reads — so a read costs no round trip to the store.
Before the index has built (~90 s after boot) the bag is served unchecked
rather than refused, and an add is refused with 503 because there is nothing
to price it against.
"""

from __future__ import annotations

from typing import Any

from flask import Flask, jsonify, request

from backend.api import archive_routes, checkout
from backend.auth import db
from backend.auth.middleware import current_user
from backend.userdata import bag


class Warming(RuntimeError):
    """The storefront index is not built yet."""


def _body() -> dict:
    return request.get_json(silent=True) or {}


def _tile_for(brand: str, itemurl: str) -> dict | None:
    """The catalogue's current view of one product, or None if the site does not
    show it (unknown brand, gated brand, no photograph, delisted)."""
    index = archive_routes._index()
    if index is None:
        raise Warming()
    return next((t for t in index.tiles if t["brand_id"] == brand and t["url"] == itemurl), None)


def _brand_name(brand: str) -> str:
    entry = archive_routes._entry(brand)
    return entry.name if entry else brand


# ---------------------------------------------------------------------------
# checking a line against the catalogue
# ---------------------------------------------------------------------------


def _offer_for(tile: dict, variant_id: str | None, size: str | None) -> dict | None:
    if variant_id:
        for o in tile.get("offers") or []:
            if str(o.get("variant_id")) == str(variant_id):
                return o
        return None
    if size:
        for s in tile.get("sizes") or []:
            if s.get("size") == size:
                return {"available": s.get("available"), "price": None}
    return None


def _check(line: dict, tile: dict | None) -> dict:
    """What the catalogue says about this line now, beside what it said at add time.

    `changed` is about price; `unavailable` about stock; `checked` is False when
    the catalogue had nothing to say (index warming, product no longer shown).
    """
    out = dict(line)
    out["brand_name"] = _brand_name(line["brand"])
    if tile is None:
        out.update(
            checked=False, current_price=None, available=None, changed=False, unavailable=False
        )
        return out
    offer = _offer_for(tile, line.get("variant_id"), line.get("size"))
    if line.get("variant_id") and offer is None:
        # The variant the person chose is no longer in the shop's feed.
        out.update(
            checked=True, current_price=None, available=False, changed=False, unavailable=True
        )
        return out
    current = (offer or {}).get("price")
    if current is None:
        current = tile.get("price")
    available = (offer or {}).get("available")
    if available is None:
        available = bool(tile.get("in_stock"))
    was = line.get("price")
    changed = current is not None and was is not None and abs(float(current) - float(was)) >= 0.005
    out.update(
        checked=True,
        current_price=current,
        available=bool(available),
        changed=bool(changed),
        unavailable=not available,
        currency=tile.get("currency") or line.get("currency"),
    )
    return out


def _grouped(lines: list[dict]) -> list[dict]:
    """Lines by shop, in the order the shops first appeared in the bag."""
    shops: dict[str, dict] = {}
    for ln in lines:
        shop = shops.setdefault(
            ln["brand"],
            {
                "brand": ln["brand"],
                "brand_name": ln["brand_name"],
                "platform": ln.get("platform"),
                "currency": ln.get("currency"),
                "lines": [],
            },
        )
        shop["lines"].append(ln)
        # A platform learned at add time is worth keeping; a later line from the
        # same shop that knows one when the first did not fills it in.
        shop["platform"] = shop["platform"] or ln.get("platform")
        shop["currency"] = shop["currency"] or ln.get("currency")
    return list(shops.values())


def _shop_bags(shops: list[dict]) -> list[checkout.ShopBag]:
    out = []
    for s in shops:
        out.append(
            checkout.ShopBag(
                brand=s["brand"],
                brand_name=s["brand_name"],
                platform=s["platform"],
                currency=s["currency"],
                lines=[
                    checkout.Line(
                        id=ln["id"],
                        brand=ln["brand"],
                        itemurl=ln["itemurl"],
                        variant_id=ln.get("variant_id"),
                        size=ln.get("size"),
                        qty=ln["qty"],
                        price=ln["current_price"] if ln["checked"] else ln.get("price"),
                        available=ln["available"] if ln["checked"] else None,
                    )
                    for ln in s["lines"]
                ],
            )
        )
    return out


def _bag_payload(lines: list[dict]) -> dict[str, Any]:
    try:
        checked = [_check(ln, _tile_for(ln["brand"], ln["itemurl"])) for ln in lines]
        warming = False
    except Warming:
        checked = [_check(ln, None) for ln in lines]
        warming = True
    shops = _grouped(checked)
    quotes = {q.brand: q.as_dict() for q in checkout.adapter().quote(_shop_bags(shops))}
    for s in shops:
        s["quote"] = quotes.get(s["brand"])
    return {
        "shops": shops,
        "line_count": len(lines),
        "item_count": sum(ln["qty"] for ln in lines),
        "checked": not warming,
        "max_lines": bag.MAX_LINES,
        "max_qty": bag.MAX_QTY,
    }


def _bag_response(status: int = 200):
    with db.transaction() as conn:
        lines = bag.list_lines(conn, user_id=current_user().id)
    return jsonify(_bag_payload(lines)), status


def _error(code: str, message: str, status: int):
    return jsonify({"success": False, "error": message, "code": code}), status


# ---------------------------------------------------------------------------
# handlers
# ---------------------------------------------------------------------------


def get_bag():
    """GET /api/bag"""
    return _bag_response()


def _qty(value: Any, default: int | None = 1) -> int | None:
    if value is None:
        return default
    try:
        qty = int(value)
    except (TypeError, ValueError):
        return None
    return qty if 1 <= qty <= bag.MAX_QTY else None


def add_line():
    """POST /api/bag/lines  {brand, itemurl, variant_id?, size?, qty?}

    The product must be one the site shows right now: the tile it is added from
    is the tile it is priced from. A size without a variant id is resolved to
    the id the tile knows for that size, so a size button needs to send only
    the size. A variant id the tile does not list is refused — it would build a
    cart link the shop rejects.
    """
    body = _body()
    brand = str(body.get("brand") or "").strip()
    itemurl = str(body.get("itemurl") or "").strip()
    if not brand or not itemurl:
        return _error("BAD_REQUEST", "brand and itemurl are required", 400)
    qty = _qty(body.get("qty"))
    if qty is None:
        return _error("BAD_QTY", f"qty must be an integer from 1 to {bag.MAX_QTY}", 400)
    variant_id = body.get("variant_id")
    variant_id = str(variant_id).strip() if variant_id not in (None, "") else None
    size = body.get("size")
    size = str(size).strip() if size not in (None, "") else None

    try:
        tile = _tile_for(brand, itemurl)
    except Warming:
        return _error("WARMING", "The shop front is still being built; try again shortly", 503)
    if tile is None:
        return _error("NOT_SHOWN", "This product is not in the shop front", 404)

    offers = tile.get("offers") or []
    if variant_id and offers and not any(str(o["variant_id"]) == variant_id for o in offers):
        return _error("UNKNOWN_VARIANT", "This variant is not one the shop lists", 400)
    if variant_id and not size:
        size = next((o.get("size") for o in offers if str(o["variant_id"]) == variant_id), None)
    if size and not variant_id:
        size_row = next((s for s in tile.get("sizes") or [] if s.get("size") == size), None)
        if size_row is None:
            return _error("UNKNOWN_SIZE", "This size is not one the shop lists", 400)
        variant_id = size_row.get("variant_id")
    if not variant_id and not size and len(offers) == 1 and offers[0].get("size") is None:
        variant_id = str(offers[0]["variant_id"])  # a one-variant product needs no choice

    offer = _offer_for(tile, variant_id, size) or {}
    price = offer.get("price") if offer.get("price") is not None else tile.get("price")

    with db.transaction() as conn:
        user_id = current_user().id
        if bag.count(conn, user_id=user_id) >= bag.MAX_LINES:
            return _error("BAG_FULL", f"A bag holds at most {bag.MAX_LINES} lines", 400)
        bag.add_line(
            conn,
            user_id=user_id,
            brand=brand,
            itemurl=itemurl,
            variant_id=variant_id,
            size=size,
            qty=qty,
            title=tile.get("title") or "",
            image=tile.get("image"),
            handle=tile.get("handle"),
            platform=tile.get("platform"),
            price=price,
            currency=tile.get("currency"),
        )
    return _bag_response(201)


def set_line_qty(line_id: int):
    """PATCH /api/bag/lines/<id>  {qty}"""
    qty = _qty(_body().get("qty"), default=None)
    if qty is None:
        return _error("BAD_QTY", f"qty must be an integer from 1 to {bag.MAX_QTY}", 400)
    with db.transaction() as conn:
        row = bag.set_qty(conn, user_id=current_user().id, line_id=line_id, qty=qty)
    if row is None:
        return _error("NOT_FOUND", "No such line in your bag", 404)
    return _bag_response()


def remove_line(line_id: int):
    """DELETE /api/bag/lines/<id>"""
    with db.transaction() as conn:
        removed = bag.remove_line(conn, user_id=current_user().id, line_id=line_id)
    if not removed:
        return _error("NOT_FOUND", "No such line in your bag", 404)
    return _bag_response()


def clear_bag():
    """DELETE /api/bag"""
    with db.transaction() as conn:
        bag.clear(conn, user_id=current_user().id)
    return _bag_response()


def get_checkout():
    """GET /api/bag/checkout — where to send the person, per shop, and for how much.

    The links are the shops' own carts; nothing is charged here. A shop whose
    platform has no cart URL, or a line with no variant id, gets its product
    page instead, and the note says so.
    """
    with db.transaction() as conn:
        lines = bag.list_lines(conn, user_id=current_user().id)
    if not lines:
        return _error("EMPTY", "The bag is empty", 400)
    payload = _bag_payload(lines)
    adapter = checkout.adapter()
    shop_bags = _shop_bags(payload["shops"])
    links = {c.brand: c.as_dict() for c in adapter.checkout(shop_bags)}
    shops = []
    for s in payload["shops"]:
        c = links.get(s["brand"]) or {}
        shops.append(
            {
                "brand": s["brand"],
                "brand_name": s["brand_name"],
                "platform": s["platform"],
                "currency": s["currency"],
                "quote": s["quote"],
                "kind": c.get("kind"),
                "links": c.get("links", []),
                "note": c.get("note"),
                "line_ids": [ln["id"] for ln in s["lines"]],
                "unavailable_line_ids": [ln["id"] for ln in s["lines"] if ln["unavailable"]],
            }
        )
    return jsonify(
        {
            "provider": adapter.name,
            "shops": shops,
            "checked": payload["checked"],
            "charged_by": "each shop, on its own checkout, in its own currency",
        }
    )


def register_bag_routes(app: Flask) -> None:
    """No decorators: `install_auth` protects every endpoint not named public."""
    app.add_url_rule("/api/bag", "bag_get", get_bag, methods=["GET"])
    app.add_url_rule("/api/bag", "bag_clear", clear_bag, methods=["DELETE"])
    app.add_url_rule("/api/bag/lines", "bag_add_line", add_line, methods=["POST"])
    app.add_url_rule("/api/bag/lines/<int:line_id>", "bag_set_qty", set_line_qty, methods=["PATCH"])
    app.add_url_rule(
        "/api/bag/lines/<int:line_id>", "bag_remove_line", remove_line, methods=["DELETE"]
    )
    app.add_url_rule("/api/bag/checkout", "bag_checkout", get_checkout, methods=["GET"])
    print("✅ Bag API routes registered (6 endpoints, all require auth)")
