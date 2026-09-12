"""Favourite looks — HTTP endpoints.

Every handler is scoped to `current_user()`, and the user id is part of each
query rather than being used to pick a file path. That is the substantive
change: isolation is now enforced by the database on every row, instead of by
assembling a per-user directory name and trusting it.

The JSON contract is unchanged, so the frontend does not need to know that
storage moved.
"""

from __future__ import annotations

from flask import jsonify, request

from backend.auth import db
from backend.auth.middleware import current_user
from backend.userdata import favourites


def _body() -> dict:
    return request.get_json(silent=True) or {}


def get_favourites():
    """GET /api/favourites — every favourite for the current user."""
    with db.transaction() as conn:
        return jsonify({"favourites": favourites.list_all(conn, user_id=current_user().id)})


def add_favourite():
    """POST /api/favourites — favourite a look."""
    body = _body()
    with db.transaction() as conn:
        added = favourites.add(
            conn,
            user_id=current_user().id,
            season=body.get("season", {}),
            collection=body.get("collection", {}),
            look=body.get("look", {}),
            image_path=body.get("image_path", ""),
            notes=body.get("notes", ""),
        )

    if added:
        return jsonify({"success": True, "message": "Added to favourites"})
    return jsonify({"success": False, "message": "Already in favourites"})


def remove_favourite():
    """DELETE /api/favourites — unfavourite a look."""
    body = _body()
    with db.transaction() as conn:
        removed = favourites.remove(
            conn,
            user_id=current_user().id,
            season_url=body.get("season_url", ""),
            collection_url=body.get("collection_url", ""),
            look_number=body.get("look_number", 0),
        )

    if removed:
        return jsonify({"success": True, "message": "Removed from favourites"})
    return jsonify({"success": False, "message": "Not found in favourites"})


def check_favourite():
    """POST /api/favourites/check — is this look favourited?"""
    body = _body()
    with db.transaction() as conn:
        is_fav = favourites.exists(
            conn,
            user_id=current_user().id,
            season_url=body.get("season_url", ""),
            collection_url=body.get("collection_url", ""),
            look_number=body.get("look_number", 0),
        )
    return jsonify({"is_favourite": is_fav})


def get_favourites_stats():
    """GET /api/favourites/stats — counts for the current user."""
    with db.transaction() as conn:
        return jsonify({"stats": favourites.stats(conn, user_id=current_user().id)})


def register_favorites_routes(app):
    """Register the favourites endpoints.

    No decorators: `install_auth` protects every endpoint that is not in the
    public allowlist, and none of these are.

    /api/favourites/cleanup is deliberately gone. It deleted orphaned image
    files from a per-user directory, and favourites no longer copy images —
    they reference the central one — so there is nothing left to orphan.
    """
    app.add_url_rule("/api/favourites", "get_favourites", get_favourites, methods=["GET"])
    app.add_url_rule("/api/favourites", "add_favourite", add_favourite, methods=["POST"])
    app.add_url_rule("/api/favourites", "remove_favourite", remove_favourite, methods=["DELETE"])
    app.add_url_rule("/api/favourites/check", "check_favourite", check_favourite, methods=["POST"])
    app.add_url_rule(
        "/api/favourites/stats",
        "get_favourites_stats",
        get_favourites_stats,
        methods=["GET"],
    )

    print("✅ Favourites API routes registered (5 endpoints, all require auth)")
