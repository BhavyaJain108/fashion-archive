"""Saved looks, shows and views — HTTP endpoints.

Every handler is scoped to `current_user()`, and the user id is part of each
query rather than being used to pick a file path. That is the substantive
change from the SQLite generation: isolation is now enforced by the database on
every row, instead of by assembling a per-user directory name and trusting it.

A request says which of the three kinds it means with `kind`, defaulting to
`'look'` — so the look requests the frontend sends today are byte-for-byte the
requests it sent before views and shows existed, and get byte-for-byte the same
answers. A kind nothing recognises is a 400 rather than a row: the three
uniqueness indexes are partial, one per kind, so a row with a fourth kind is one
no index covers, no `DELETE` finds, and nothing ever cleans up.

The keying is deliberately not written here. `favourites.key_clause` owns which
columns identify which kind, and `remove` and `check` both go through it, so a
saved show and a saved look of the same collection cannot be confused for one
another by one endpoint and not the other.
"""

from __future__ import annotations

from flask import jsonify, request

from backend.api.ops import OpError, me
from backend.auth.middleware import current_user
from backend.userdata import favourites


def _body() -> dict:
    return request.get_json(silent=True) or {}


def _kind(source) -> str:
    """The kind this request means, validated before anything is opened.

    Absent is 'look': every request the frontend sent before this existed still
    means what it meant.
    """
    return favourites.check_kind(source.get("kind") or "look")


def _refuse(exc: favourites.UnknownKind):
    """A kind no index covers, answered before a transaction is opened."""
    return jsonify({"success": False, "error": str(exc)}), 400


def _legacy(fn):
    """The answer in this family's own error shape, which its callers still read."""
    try:
        return jsonify(fn())
    except OpError as e:
        return jsonify({"success": False, "error": e.message}), e.status


def _view_filters(body: dict) -> dict:
    """The filters as this server will store them, not as they arrived.

    Normalised here rather than in the handler bodies so `add`, `remove` and
    `check` cannot drift: the identity of a saved view is
    `md5(view_filters::text)`, and a client that saved through one rule and
    deleted through another would be unable to delete what it saved.
    """
    return favourites.normalise_filters(body.get("filters"))


def _view_name(body: dict, filters: dict) -> str:
    """What the library will list this view as.

    A display string, never an identity — two views with the same name and
    different filters are two rows, and the same filters under two names are
    still one.
    """
    supplied = body.get("name")
    supplied = supplied.strip() if isinstance(supplied, str) else ""
    return supplied or favourites.derive_view_name(filters)


def favourite_target(body: dict) -> dict:
    """One save body as the keyword arguments the data layer takes.

    Public, and the only place a request body becomes a favourite. The album
    add endpoint saves through this too — the spec's rule is that adding
    something unsaved to an album saves it first, so the two endpoints have to
    agree about what a body means down to the derived view name. Two readings
    of one body is how the same look becomes two rows.

    Raises `favourites.UnknownKind` for a kind no index covers; the caller
    turns that into the 400 `_refuse` writes.
    """
    kind = _kind(body)
    view_filters = _view_filters(body) if kind == "view" else None
    return {
        "kind": kind,
        "season": body.get("season", {}),
        "collection": body.get("collection", {}),
        "look": body.get("look", {}),
        "image_path": body.get("image_path", ""),
        "notes": body.get("notes", ""),
        "view_filters": view_filters,
        "view_name": _view_name(body, view_filters) if kind == "view" else None,
    }


def get_favourites():
    """GET /api/favourites — what the current user has saved.

    All three kinds interleaved by date, because the library lists them that
    way. `?kind=show` narrows it to one.

        ?limit=<n>&cursor=<c>   one page, newest first
        (neither)               the whole list, as this endpoint always answered

    The answer is the same object either way —

        {"favourites": [...], "total": n, "hasMore": bool, "nextCursor": str|None}

    — so a caller that sends no paging parameters gets the list it has always
    got under the key it has always read. Paging is by cursor rather than
    offset: see `favourites.list_page`.
    """
    wanted = request.args.get("kind")
    if wanted is not None:
        try:
            wanted = favourites.check_kind(wanted)
        except favourites.UnknownKind as exc:
            return _refuse(exc)
    # A `limit` that is not a number is no limit; a `cursor` that is not a cursor
    # is refused, loudly, inside — ignoring it hands back the page already shown.
    limit = request.args.get("limit")
    try:
        limit = int(limit) if limit is not None else None
    except ValueError:
        limit = None
    return _legacy(
        lambda: me.favourites_list(current_user().id, wanted, limit, request.args.get("cursor"))
    )


def get_favourite_keys():
    """GET /api/favourites/keys — the identity of every save, and nothing else.

    The list above can be paged because this one cannot be. A star is lit by
    asking whether the thing on screen is saved, of every thumbnail in a strip,
    so the answer must be local AND complete.
    """
    return jsonify(me.favourites_list(current_user().id, None, None, None, "keys"))


def add_favourite():
    """POST /api/favourites — save a look, a show, or a view.

        {"season": {...}, "collection": {...}, "look": {...}, "image_path": ...}
        {"kind": "show", "season": {...}, "collection": {...}, "image_path": ...}
        {"kind": "view", "filters": {...}, "name": "optional"}

    Saving something already saved is reported, not an error. A `collection_id`
    in the body is ignored: the column is derived from `collection.url` inside
    the INSERT and a CHECK constraint holds the two equal.
    """
    return _legacy(lambda: me.favourites_add(current_user().id, _body()))


def remove_favourite():
    """DELETE /api/favourites — unsave one thing.

        {"season_url": ..., "collection_url": ..., "look_number": 12}
        {"kind": "show", "season_url": ..., "collection_url": ...}
        {"kind": "view", "filters": {...}}

    The match is the key for the kind and nothing else.
    """
    return _legacy(lambda: me.favourites_remove(current_user().id, _body()))


def check_favourite():
    """POST /api/favourites/check — is this saved?

    Same body as the delete, and the same key, because a star that says saved
    and a delete that finds nothing is one bug reported twice.
    """
    return _legacy(lambda: {"is_favourite": me.favourites_exists(current_user().id, _body())})


def get_favourites_stats():
    """GET /api/favourites/stats — counts for the current user."""
    return jsonify(me.favourites_list(current_user().id, None, None, None, "stats"))


def register_favorites_routes(app):
    """Register the favourites endpoints.

    No decorators: `install_auth` protects every endpoint that is not in the
    public allowlist, and none of these are.

    /api/favourites/cleanup is deliberately gone. It deleted orphaned image
    files from a per-user directory, and favourites no longer copy images —
    they reference the central one — so there is nothing left to orphan.
    """
    app.add_url_rule("/api/favourites", "get_favourites", get_favourites, methods=["GET"])
    app.add_url_rule(
        "/api/favourites/keys",
        "get_favourite_keys",
        get_favourite_keys,
        methods=["GET"],
    )
    app.add_url_rule("/api/favourites", "add_favourite", add_favourite, methods=["POST"])
    app.add_url_rule("/api/favourites", "remove_favourite", remove_favourite, methods=["DELETE"])
    app.add_url_rule("/api/favourites/check", "check_favourite", check_favourite, methods=["POST"])
    app.add_url_rule(
        "/api/favourites/stats",
        "get_favourites_stats",
        get_favourites_stats,
        methods=["GET"],
    )

    print("✅ Favourites API routes registered (6 endpoints, all require auth)")
