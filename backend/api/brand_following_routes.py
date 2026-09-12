"""Brand following — HTTP endpoints.

Scoped to `current_user()`; the user id is a column in every query rather than
a directory name. Brand data itself remains central and shared — only the
follow list is per user.
"""

from __future__ import annotations

from flask import jsonify, request

from backend.auth import db
from backend.auth.middleware import current_user
from backend.userdata import following


def _body() -> dict:
    return request.get_json(silent=True) or {}


def follow_brand():
    """POST /api/brands/follow"""
    body = _body()
    brand_id = body.get("brand_id", "")
    if not brand_id:
        return jsonify({"success": False, "error": "brand_id is required"}), 400

    with db.transaction() as conn:
        followed = following.follow(
            conn,
            user_id=current_user().id,
            brand_id=brand_id,
            brand_name=body.get("brand_name", brand_id),
            notes=body.get("notes", ""),
        )

    if followed:
        return jsonify({"success": True, "message": "Now following"})
    return jsonify({"success": False, "message": "Already following"})


def unfollow_brand():
    """POST /api/brands/unfollow"""
    brand_id = _body().get("brand_id", "")
    if not brand_id:
        return jsonify({"success": False, "error": "brand_id is required"}), 400

    with db.transaction() as conn:
        removed = following.unfollow(conn, user_id=current_user().id, brand_id=brand_id)

    if removed:
        return jsonify({"success": True, "message": "Unfollowed"})
    return jsonify({"success": False, "message": "Not following"})


def check_following():
    """POST /api/brands/check-following"""
    with db.transaction() as conn:
        result = following.is_following(
            conn, user_id=current_user().id, brand_id=_body().get("brand_id", "")
        )
    return jsonify({"is_following": result})


def get_following_brands():
    """GET /api/brands/following"""
    with db.transaction() as conn:
        brands = following.list_following(conn, user_id=current_user().id)
    return jsonify({"brands": brands, "count": len(brands)})


def update_brand_notifications():
    """POST /api/brands/notifications

    Omitted flags are left as they are rather than reset to their defaults, so
    a client that sends only one does not silently clobber the other.
    """
    body = _body()
    brand_id = body.get("brand_id", "")
    if not brand_id:
        return jsonify({"success": False, "error": "brand_id is required"}), 400

    with db.transaction() as conn:
        updated = following.set_notification_preferences(
            conn,
            user_id=current_user().id,
            brand_id=brand_id,
            notify_new_products=body.get("notify_new_products"),
            notify_price_changes=body.get("notify_price_changes"),
        )

    if updated:
        return jsonify({"success": True, "message": "Preferences updated"})
    return jsonify({"success": False, "message": "Not following that brand"}), 404


def update_brand_notes():
    """POST /api/brands/notes"""
    body = _body()
    brand_id = body.get("brand_id", "")
    if not brand_id:
        return jsonify({"success": False, "error": "brand_id is required"}), 400

    with db.transaction() as conn:
        updated = following.set_notes(
            conn,
            user_id=current_user().id,
            brand_id=brand_id,
            notes=body.get("notes", ""),
        )

    if updated:
        return jsonify({"success": True, "message": "Notes updated"})
    return jsonify({"success": False, "message": "Not following that brand"}), 404


def register_brand_following_routes(app):
    """Register the brand-following endpoints.

    No decorators: `install_auth` covers every endpoint outside the public
    allowlist, and none of these are in it.
    """
    app.add_url_rule("/api/brands/follow", "follow_brand", follow_brand, methods=["POST"])
    app.add_url_rule(
        "/api/brands/unfollow", "unfollow_brand", unfollow_brand, methods=["POST"]
    )
    app.add_url_rule(
        "/api/brands/check-following", "check_following", check_following, methods=["POST"]
    )
    app.add_url_rule(
        "/api/brands/following", "get_following_brands", get_following_brands, methods=["GET"]
    )
    app.add_url_rule(
        "/api/brands/notifications",
        "update_brand_notifications",
        update_brand_notifications,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/brands/notes", "update_brand_notes", update_brand_notes, methods=["POST"]
    )

    print("✅ Brand Following API routes registered (6 endpoints, all require auth)")
