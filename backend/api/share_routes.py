"""Share links.

Minting, listing and revoking need a session. Resolving does not — it is the
one deliberately public read in the application, so it is rate-limited by IP
and it answers for exactly one target per token, never for a list.
"""

from __future__ import annotations

from flask import jsonify, request

from backend.auth import db
from backend.auth.middleware import current_user
from backend.auth.ratelimit import limited
from backend.high_fashion import collection_cache
from backend.userdata import albums, share

# The public endpoint names, for the auth allowlist in app.py.
PUBLIC_SHARE_ENDPOINTS = {"share_resolve"}


def _body():
    return request.get_json(silent=True) or {}


def _public_item(row: dict) -> dict:
    """A favourite as a stranger may see it: no notes, no internal ids."""
    return {
        "kind": row["kind"],
        "season": {"name": row["season"]["name"]},
        "collection": {"designer": row["collection"]["designer"], "id": row["collection"]["id"]},
        "look": row["look"],
        "view": row["view"],
        "image_path": row.get("image_path"),
    }


def create_share():
    """POST /api/share — mint a link. Body: {kind, target}."""
    body = _body()
    kind = body.get("kind")
    target = body.get("target") or {}
    if kind not in share.KINDS or not isinstance(target, dict):
        return jsonify({"success": False, "error": "kind must be look, show or album"}), 400

    user_id = current_user().id
    with db.transaction() as conn:
        if kind == "album":
            if albums.get(conn, user_id=user_id, album_id=int(target.get("album_id", 0))) is None:
                return jsonify({"success": False, "error": "no such album"}), 404
            stored = {"album_id": int(target["album_id"])}
        elif kind == "show":
            if not target.get("collection_id"):
                return jsonify({"success": False, "error": "collection_id required"}), 400
            stored = {
                k: target.get(k) for k in ("collection_id", "designer", "subtitle", "season_name")
            }
        else:
            for k in ("image_path", "look_number"):
                if not target.get(k):
                    return jsonify({"success": False, "error": f"{k} required"}), 400
            stored = {
                k: target.get(k)
                for k in ("image_path", "look_number", "designer", "season_name", "collection_id")
            }
        token = share.mint(conn, user_id=user_id, kind=kind, target=stored)
    return jsonify({"success": True, "token": token})


def list_shares():
    with db.transaction() as conn:
        rows = share.list_mine(conn, user_id=current_user().id)
    return jsonify({"success": True, "shares": rows})


def revoke_share(token: str):
    with db.transaction() as conn:
        ok = share.revoke(conn, user_id=current_user().id, token=token)
    if not ok:
        return jsonify({"success": False, "error": "no such share"}), 404
    return jsonify({"success": True})


@limited(limit=60, window_seconds=60)
def share_resolve(token: str):
    """GET /api/s/<token> — public. One target, read-only, or 404."""
    with db.transaction() as conn:
        hit = share.resolve(conn, token=token)
        if hit is None:
            return jsonify({"success": False, "error": "not found"}), 404
        kind, target, owner = hit["kind"], hit["target"], hit["user_id"]

        if kind == "album":
            album = albums.get(conn, user_id=owner, album_id=target["album_id"])
            if album is None:
                return jsonify({"success": False, "error": "not found"}), 404
            items = albums.list_items(conn, user_id=owner, album_id=target["album_id"])
            return jsonify(
                {
                    "success": True,
                    "kind": "album",
                    "album": {"name": album["name"], "sort_by": album.get("sort_by")},
                    "items": [_public_item(i) for i in items],
                }
            )

        if kind == "show":
            cid = str(target["collection_id"])
            images = None
            for quality in ("full", "large", "medium", "thumb", "low"):
                cached = collection_cache.get(conn, collection_id=cid, quality=quality)
                if cached:
                    images = cached["images"]
                    break
            return jsonify(
                {
                    "success": True,
                    "kind": "show",
                    "show": {k: target.get(k) for k in ("designer", "subtitle", "season_name")},
                    # Served from the cache only. A share link is not a way to make
                    # this server crawl firstVIEW for a stranger.
                    "images": images or [],
                    "available": images is not None,
                }
            )

        return jsonify({"success": True, "kind": "look", "look": target})


def register_share_routes(app):
    app.add_url_rule("/api/share", "share_create", create_share, methods=["POST"])
    app.add_url_rule("/api/share", "share_list", list_shares, methods=["GET"])
    app.add_url_rule("/api/share/<token>", "share_revoke", revoke_share, methods=["DELETE"])
    app.add_url_rule("/api/s/<token>", "share_resolve", share_resolve, methods=["GET"])
    print("✅ Share API routes registered (4 endpoints, 1 public)")
