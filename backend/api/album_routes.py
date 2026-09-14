"""Albums — HTTP endpoints.

A second routes module rather than more handlers in `favorites_routes.py`.
Favourites are one flat collection addressed by their content: every request
carries the thing itself and no URL has an id in it. An album is addressed by
id, which brings a different set of answers with it — a 404 for an album that
is not yours, a 409 for a name you already used — and a different failure to
worry about. Mixing the two would put two error vocabularies in one file and
bury the rule that matters here under the rule that matters there.

What matters here is that an album id is a number a stranger can type. Every
handler below looks the album up as `current_user()`'s before it does anything
else, and answers **404** when that lookup comes back empty — for an album that
does not exist and for one that belongs to somebody else, identically. A 403
would be the honest answer to the second case and is the wrong one: it confirms
the row exists, which is a fact about another person's library.

`album_items` carries no `user_id` of its own — it is bounded by `albums` and
`favourites`, both of which do — so nothing in the schema stops a query that
forgets to join. The data layer's queries all join; these handlers check
ownership first anyway, because that is what turns "the query matched nothing"
into the right status code instead of a misleading `success: false`.

One rule is a spec rule rather than a data-layer one, and so it lives here:
**adding something not yet saved saves it first.** An album holds favourites, so
there is nothing to put in one until the thing is saved. The add endpoint
therefore takes the same body the favourites endpoint takes — through
`favourite_target`, so the two cannot read it differently — and does both halves
in one transaction. Either the favourite and the membership row both land or
neither does; a membership row naming a favourite that was never written is a
tile for something that does not exist, and a favourite written for an add that
then failed is a save the user never asked for.
"""

from __future__ import annotations

from flask import jsonify, request

from backend.api.favorites_routes import favourite_target
from backend.auth import db
from backend.auth.middleware import current_user
from backend.userdata import albums, favourites


def _body() -> dict:
    return request.get_json(silent=True) or {}


def _no_such_album():
    """The answer for an album id that is not this user's — whether it does not
    exist or belongs to somebody else.

    One answer for both, deliberately. See the module docstring.
    """
    return jsonify({"success": False, "error": "no such album"}), 404


def _bad_request(message: str):
    return jsonify({"success": False, "error": message}), 400


def _mine(conn, album_id: int):
    """This user's album with that id, or None."""
    return albums.get(conn, user_id=current_user().id, album_id=album_id)


def list_albums():
    """GET /api/albums — this user's albums, newest first.

    Each carries `item_count` and `cover_image_path`, so the picker and the
    shelf render from one request rather than one per album. The cover is the
    first item in the album's own order that has an image; an album holding
    nothing but saved views has none, and gets null rather than a broken tile.
    """
    with db.transaction() as conn:
        rows = albums.list_albums(conn, user_id=current_user().id)
    return jsonify({"albums": rows, "count": len(rows)})


def create_album():
    """POST /api/albums — make an album.

        {"name": "Resort", "layout_mode": "grid", "sort_by": "added"}

    409 for a name this user already has, case-insensitively: one name per user
    is what makes the name a handle rather than a label. 400 for a blank name
    or an option the table's CHECK constraints do not allow.
    """
    body = _body()
    with db.transaction() as conn:
        try:
            album = albums.create(
                conn,
                user_id=current_user().id,
                name=body.get("name"),
                layout_mode=body.get("layout_mode", "grid"),
                sort_by=body.get("sort_by", "added"),
            )
        except albums.DuplicateName as exc:
            # Reported rather than raised out of the transaction: `create`
            # inserts with ON CONFLICT DO NOTHING precisely so this case leaves
            # the transaction usable instead of aborting it.
            return jsonify({"success": False, "error": str(exc)}), 409
        except (albums.BlankName, albums.UnknownOption) as exc:
            return _bad_request(str(exc))

    return jsonify({"success": True, "album": album}), 201


def get_album(album_id: int):
    """GET /api/albums/<id> — one album and what is in it.

    `?sort_by=` renders it in another order for this request without storing
    the choice; absent means the album's own stored order.
    """
    sort_by = request.args.get("sort_by")
    with db.transaction() as conn:
        album = _mine(conn, album_id)
        if album is None:
            return _no_such_album()
        try:
            items = albums.list_items(
                conn, user_id=current_user().id, album_id=album_id, sort_by=sort_by
            )
        except albums.UnknownOption as exc:
            return _bad_request(str(exc))
    return jsonify({"album": album, "items": items})


def update_album(album_id: int):
    """PATCH /api/albums/<id> — rename it, or change how it is laid out.

        {"name": "Resort 2025"}
        {"layout_mode": "canvas", "sort_by": "designer"}

    Only what is sent is written. A client changing the sort must not reset the
    layout to its default on the way past.
    """
    body = _body()
    user_id = current_user().id

    with db.transaction() as conn:
        if _mine(conn, album_id) is None:
            return _no_such_album()

        try:
            if "name" in body:
                albums.rename(conn, user_id=user_id, album_id=album_id, name=body.get("name"))
            if "layout_mode" in body or "sort_by" in body:
                albums.set_options(
                    conn,
                    user_id=user_id,
                    album_id=album_id,
                    layout_mode=body.get("layout_mode"),
                    sort_by=body.get("sort_by"),
                )
        except albums.DuplicateName as exc:
            return jsonify({"success": False, "error": str(exc)}), 409
        except (albums.BlankName, albums.UnknownOption) as exc:
            return _bad_request(str(exc))

        album = _mine(conn, album_id)

    return jsonify({"success": True, "album": album})


def delete_album(album_id: int):
    """DELETE /api/albums/<id> — delete the album, keep the favourites.

    `album_items` cascades and nothing else does. An album is an arrangement of
    things the user kept, not the keeping of them, and the opposite mistake
    loses saved work with no way back.
    """
    with db.transaction() as conn:
        if _mine(conn, album_id) is None:
            return _no_such_album()
        albums.delete(conn, user_id=current_user().id, album_id=album_id)
    return jsonify({"success": True, "message": "Album deleted"})


def add_album_item(album_id: int):
    """POST /api/albums/<id>/items — put something in an album.

    Two bodies, one endpoint:

        {"favourite_id": 41}
        {"season": {...}, "collection": {...}, "look": {...}, "image_path": ...}
        {"kind": "show", "season": {...}, "collection": {...}}
        {"kind": "view", "filters": {...}, "name": "optional"}

    The second form is the spec's rule: an album holds favourites, so something
    not yet saved is saved first and then added. The body is read by
    `favourite_target` — the favourites endpoint's own reading of it — so the
    look that lands in an album is the same row a plain save would have made,
    and starring it afterwards finds it rather than writing a second copy.

    **One transaction for both halves.** `db.transaction` commits on the way out
    and rolls back on any exception, and both statements run inside it, so a
    membership insert that fails takes the favourite with it and there is no
    half-add to clean up. The ownership check comes first for the same reason:
    a 404 must not be preceded by a save.

    The answer says which halves actually happened:

        {"success": true, "favourite_id": 41, "saved": false, "added": true}

    `saved` is whether this request created the favourite, `added` whether it
    created the membership row. Both false is a thing already saved and already
    in the album — reported, not an error, because a double-click is not a
    failure.
    """
    body = _body()
    user_id = current_user().id

    with db.transaction() as conn:
        if _mine(conn, album_id) is None:
            return _no_such_album()

        supplied = body.get("favourite_id")
        if supplied is not None:
            # An id is a number a stranger can type, so it is checked against
            # this user before it is used, and somebody else's is the same 404
            # somebody else's album is. `add_item`'s JOIN would refuse it too,
            # but as `false` — indistinguishable from "already in the album".
            if isinstance(supplied, bool) or not isinstance(supplied, int):
                return _bad_request("favourite_id must be an integer")
            if not favourites.owns(conn, user_id=user_id, favourite_id=supplied):
                return jsonify({"success": False, "error": "no such favourite"}), 404
            favourite_id, saved = supplied, False
        else:
            try:
                target = favourite_target(body)
            except favourites.UnknownKind as exc:
                return _bad_request(str(exc))
            favourite_id, saved = favourites.add_returning_id(conn, user_id=user_id, **target)
            if favourite_id is None:
                # Nothing to point a membership row at. Unreachable unless the
                # insert and the lookup disagree about this kind's key, which is
                # why both go through `favourites.key_clause`. Raised rather
                # than returned: a 400 here would leave the transaction to
                # commit, and the favourite `add` may just have written would
                # be a save the user never asked for. This is a server bug, and
                # the rollback is the point.
                raise RuntimeError(
                    f"saved a favourite and could not find it again; kind={target['kind']!r}"
                )

        added = albums.add_item(conn, user_id=user_id, album_id=album_id, favourite_id=favourite_id)

    return jsonify(
        {
            "success": True,
            "favourite_id": favourite_id,
            "saved": saved,
            "added": added,
            "message": "Added to album" if added else "Already in album",
        }
    )


def remove_album_item(album_id: int, favourite_id: int):
    """DELETE /api/albums/<id>/items/<favourite_id> — take it out of the album.

    It stays saved. This and un-saving are the two destructive acts the UI has
    to keep apart, and this is the reversible one.
    """
    with db.transaction() as conn:
        if _mine(conn, album_id) is None:
            return _no_such_album()
        removed = albums.remove_item(
            conn, user_id=current_user().id, album_id=album_id, favourite_id=favourite_id
        )

    if removed:
        return jsonify({"success": True, "message": "Removed from album"})
    return jsonify({"success": False, "message": "Not in that album"})


def reorder_album(album_id: int):
    """PUT /api/albums/<id>/order — the whole arrangement, in one request.

        {"favourite_ids": [7, 3, 12]}

    One request rather than one per item: a drag that rewrites N positions over
    N requests is N chances to arrive out of order, and the order that lands is
    then whichever one finished last. The list is the album's order from first
    to last, and `set_order` writes it in a single statement whatever N is.

    Anything in the album but missing from the list keeps the index it had, so
    a partial list is a partial reorder rather than a silent deletion; the
    count of rows actually moved comes back so a client can notice.
    """
    ids = _body().get("favourite_ids")
    if not isinstance(ids, list):
        return _bad_request("favourite_ids must be a list")
    if any(isinstance(i, bool) or not isinstance(i, int) for i in ids):
        return _bad_request("favourite_ids must be a list of integers")

    with db.transaction() as conn:
        if _mine(conn, album_id) is None:
            return _no_such_album()
        moved = albums.set_order(
            conn, user_id=current_user().id, album_id=album_id, favourite_ids=ids
        )

    return jsonify({"success": True, "reordered": moved})


def register_album_routes(app):
    """Register the album endpoints.

    No decorators: `install_auth` protects every endpoint that is not in the
    public allowlist, and none of these are. `tests/api/test_route_protection.py`
    walks the real url_map and fails if one of them answers an anonymous
    request, so this is checked rather than asserted.
    """
    app.add_url_rule("/api/albums", "list_albums", list_albums, methods=["GET"])
    app.add_url_rule("/api/albums", "create_album", create_album, methods=["POST"])
    app.add_url_rule("/api/albums/<int:album_id>", "get_album", get_album, methods=["GET"])
    app.add_url_rule("/api/albums/<int:album_id>", "update_album", update_album, methods=["PATCH"])
    app.add_url_rule("/api/albums/<int:album_id>", "delete_album", delete_album, methods=["DELETE"])
    app.add_url_rule(
        "/api/albums/<int:album_id>/items",
        "add_album_item",
        add_album_item,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/albums/<int:album_id>/items/<int:favourite_id>",
        "remove_album_item",
        remove_album_item,
        methods=["DELETE"],
    )
    app.add_url_rule(
        "/api/albums/<int:album_id>/order",
        "reorder_album",
        reorder_album,
        methods=["PUT"],
    )

    print("✅ Albums API routes registered (8 endpoints, all require auth)")
