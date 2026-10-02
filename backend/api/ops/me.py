"""The signed-in person's own data: favourites and the brands they follow.

Six operations over two resources. Each query carries the session's user id, so
one person's rows are invisible to another by the database's own rule, not by a
check in a handler. The legacy /api/favourites routes call the same functions."""

from __future__ import annotations

from backend.api.ops import Context, OpError, Param, op
from backend.auth import db
from backend.userdata import favourites, following

KINDS = ("look", "show", "view")
FIELDS = ("list", "keys", "stats")


def _user(ctx: Context):
    if ctx.user is None:
        raise OpError("a signed-in person is needed for this", "NO_USER", 401)
    return ctx.user.id


def _fr():
    from backend.api import favorites_routes

    return favorites_routes


# --- favourites -----------------------------------------------------------------


def favourites_list(
    user_id, kind: str | None, limit: int | None, cursor: str | None, fields: str = "list"
) -> dict:
    with db.transaction() as conn:
        if fields == "keys":
            return {"keys": favourites.list_keys(conn, user_id=user_id)}
        if fields == "stats":
            return {"stats": favourites.stats(conn, user_id=user_id)}
        if limit is None and cursor is None:
            rows = favourites.list_all(conn, user_id=user_id, kind=kind)
            return {"favourites": rows, "total": len(rows), "hasMore": False, "nextCursor": None}
        try:
            page = favourites.list_page(
                conn,
                user_id=user_id,
                kind=kind,
                limit=favourites.DEFAULT_PAGE_LIMIT if limit is None else limit,
                cursor=cursor,
            )
        except favourites.BadCursor as e:
            raise OpError(str(e), "BAD_CURSOR") from e
        return {
            "favourites": page["rows"],
            "total": page["total"],
            "hasMore": page["hasMore"],
            "nextCursor": page["nextCursor"],
        }


def favourites_add(user_id, body: dict) -> dict:
    try:
        target = _fr().favourite_target(body)
    except favourites.UnknownKind as e:
        raise OpError(str(e), "BAD_KIND") from e
    with db.transaction() as conn:
        added = favourites.add(conn, user_id=user_id, **target)
    answer = (
        {"success": True, "message": "Added to favourites"}
        if added
        else {"success": False, "message": "Already in favourites"}
    )
    # A look's answer is the two keys it has always been. The other kinds say which
    # kind they were, and a view says what it ended up called.
    if target["kind"] != "look":
        answer["kind"] = target["kind"]
    if target["kind"] == "view":
        answer["view"] = {"name": target["view_name"], "filters": target["view_filters"]}
    return answer


def _key(body: dict) -> dict:
    fr = _fr()
    try:
        kind = fr._kind(body)
    except favourites.UnknownKind as e:
        raise OpError(str(e), "BAD_KIND") from e
    return dict(
        kind=kind,
        season_url=body.get("season_url") or "",
        collection_url=body.get("collection_url") or "",
        look_number=body.get("look_number") or 0,
        view_filters=fr._view_filters(body) if kind == "view" else None,
    )


def favourites_remove(user_id, body: dict) -> dict:
    key = _key(body)
    with db.transaction() as conn:
        removed = favourites.remove(conn, user_id=user_id, **key)
    if removed:
        return {"success": True, "message": "Removed from favourites"}
    return {"success": False, "message": "Not found in favourites"}


def favourites_exists(user_id, body: dict) -> bool:
    key = _key(body)
    with db.transaction() as conn:
        return favourites.exists(conn, user_id=user_id, **key)


# --- following ------------------------------------------------------------------


def following_list(user_id) -> dict:
    with db.transaction() as conn:
        brands = following.list_following(conn, user_id=user_id)
    return {"brands": brands, "count": len(brands)}


def following_set(user_id, brand: str, a: dict) -> dict:
    with db.transaction() as conn:
        created = following.follow(
            conn,
            user_id=user_id,
            brand_id=brand,
            brand_name=a.get("brand_name") or brand,
            notes=a.get("notes") or "",
        )
        if not created and a.get("notes") is not None:
            following.set_notes(conn, user_id=user_id, brand_id=brand, notes=a["notes"])
        if a.get("notify_new_products") is not None or a.get("notify_price_changes") is not None:
            following.set_notification_preferences(
                conn,
                user_id=user_id,
                brand_id=brand,
                notify_new_products=a.get("notify_new_products"),
                notify_price_changes=a.get("notify_price_changes"),
            )
    return {"success": True, "brand_id": brand, "created": created}


def following_remove(user_id, brand: str) -> dict:
    with db.transaction() as conn:
        removed = following.unfollow(conn, user_id=user_id, brand_id=brand)
    return {
        "success": removed,
        "brand_id": brand,
        "message": "Unfollowed" if removed else "Not following",
    }


# --- the operations -----------------------------------------------------------


@op(
    name="me_favourites",
    family="me",
    summary="What this person has saved: looks, shows and views, newest first.",
    method="GET",
    path="/api/me/favourites",
    reads=("favourites",),
    replaces=("get_favourites", "get_favourite_keys", "get_favourites_stats", "check_favourite"),
    params=(
        Param(
            "fields",
            "string",
            "list: the saves themselves. keys: only what identifies each save, "
            "complete and unpaged, for lighting stars. stats: counts by kind.",
            default="list",
            choices=FIELDS,
        ),
        Param("kind", "string", "Only one kind.", choices=KINDS),
        Param("limit", "integer", "Page size; omit it and cursor for the whole list."),
        Param("cursor", "string", "nextCursor from the previous page."),
    ),
)
def me_favourites(ctx: Context, a: dict) -> dict:
    """Paging is by cursor: this is the list a person unsaves from while paging
    through it, and an offset slides by one for every row taken out above it."""
    return favourites_list(_user(ctx), a["kind"], a["limit"], a["cursor"], a["fields"])


@op(
    name="me_favourite_add",
    family="me",
    summary="Save a look, a show or a view.",
    method="POST",
    path="/api/me/favourites",
    reads=("favourites",),
    writes=True,
    replaces=("add_favourite",),
    params=(
        Param("kind", "string", "What is being saved.", default="look", choices=KINDS),
        Param("season", "object", "The season: name, url (look, show)."),
        Param("collection", "object", "The collection: designer, url (look, show)."),
        Param("look", "object", "The look: number, total (look)."),
        Param("image_path", "string", "The picture shown for it."),
        Param("notes", "string", "A note to keep with it."),
        Param("filters", "object", "The view's filters (view)."),
        Param("name", "string", "What to call the view; derived from the filters when omitted."),
    ),
    example={
        "kind": "look",
        "season": {"name": "Fall 2024", "url": "https://…/f24"},
        "collection": {"designer": "Balenciaga", "url": "https://…/balenciaga-f24"},
        "look": {"number": 12, "total": 48},
        "image_path": "/api/images/…/look12.jpg",
    },
)
def me_favourite_add(ctx: Context, a: dict) -> dict:
    """Saving something already saved answers success: false rather than an error:
    the insert is ON CONFLICT DO NOTHING, so a double-click is reported, not aborted."""
    return favourites_add(_user(ctx), {k: v for k, v in a.items() if v is not None})


@op(
    name="me_favourite_remove",
    family="me",
    summary="Unsave one thing, by the key of its kind.",
    method="DELETE",
    path="/api/me/favourites",
    reads=("favourites",),
    writes=True,
    replaces=("remove_favourite",),
    params=(
        Param("kind", "string", "What is being unsaved.", default="look", choices=KINDS),
        Param("season_url", "string", "The season's url (look, show)."),
        Param("collection_url", "string", "The collection's url (look, show)."),
        Param("look_number", "integer", "The look's number (look)."),
        Param("filters", "object", "The view's filters (view)."),
    ),
)
def me_favourite_remove(ctx: Context, a: dict) -> dict:
    return favourites_remove(_user(ctx), {k: v for k, v in a.items() if v is not None})


@op(
    name="me_following",
    family="me",
    summary="The brands this person follows, with their notes and alert settings.",
    method="GET",
    path="/api/me/following",
    reads=("brand_following",),
    replaces=("get_following_brands", "check_following"),
)
def me_following(ctx: Context, a: dict) -> dict:
    return following_list(_user(ctx))


@op(
    name="me_follow",
    family="me",
    summary="Follow a brand, or change the notes and alerts on one already followed.",
    method="PUT",
    path="/api/me/following/{brand}",
    reads=("brand_following",),
    writes=True,
    replaces=("follow_brand", "update_brand_notes", "update_brand_notifications"),
    params=(
        Param("brand", "string", "The brand's id (its domain).", required=True),
        Param("brand_name", "string", "The brand's name, kept with the follow."),
        Param("notes", "string", "A note; omit to leave it as it is."),
        Param("notify_new_products", "boolean", "Alert on new products; omit to leave it."),
        Param("notify_price_changes", "boolean", "Alert on price changes; omit to leave it."),
    ),
    example={"brand": "huelleyrose.com", "notes": "the skirts", "notify_new_products": True},
)
def me_follow(ctx: Context, a: dict) -> dict:
    """One PUT does what three POSTs did: it creates the follow if there is none and
    applies whichever fields were sent. An omitted field is left alone, never reset."""
    return following_set(_user(ctx), a["brand"], a)


@op(
    name="me_unfollow",
    family="me",
    summary="Stop following a brand.",
    method="DELETE",
    path="/api/me/following/{brand}",
    reads=("brand_following",),
    writes=True,
    replaces=("unfollow_brand",),
    params=(Param("brand", "string", "The brand's id (its domain).", required=True),),
)
def me_unfollow(ctx: Context, a: dict) -> dict:
    return following_remove(_user(ctx), a["brand"])


OPS = [me_favourites, me_favourite_add, me_favourite_remove, me_following, me_follow, me_unfollow]
