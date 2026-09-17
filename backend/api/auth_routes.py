"""Authentication HTTP endpoints: sign in with Google or Apple, who am I, sign out.

The flow is two redirects. The site links to `/oauth/<provider>/start`, which
records a state and sends the browser to the provider. The provider sends it
back to `/oauth/<provider>/callback`, which verifies everything, sets the
session cookie and redirects to the site. Failures redirect too, with a short
`?auth_error=` code, because the browser is mid-navigation and a JSON error
would strand the user on a blank API page.
"""

from __future__ import annotations

import json

from flask import current_app, jsonify, redirect, request

from backend.auth import db, oauth
from backend.auth import repository as repo
from backend.auth.middleware import (
    SESSION_COOKIE_NAME,
    SESSION_TTL,
    clear_session_cookie,
    current_user,
    set_session_cookie,
)
from backend.auth.ratelimit import limited
from backend.auth.tokens import new_token

# Endpoints reachable without a session. Everything not named here requires one
# — see `install_auth`.
PUBLIC_AUTH_ENDPOINTS = {
    "auth_providers",
    "auth_oauth_start",
    "auth_oauth_callback",
    "auth_logout",
}

# What the provider sends when the person closes the consent screen. Not an
# error worth alarming anyone about — they changed their mind.
_CANCELLED = {"access_denied", "user_cancelled_authorize"}


def _user_json(user) -> dict:
    """The public shape of a user."""
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "email_verified": user.is_verified,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def _providers() -> dict:
    return current_app.extensions["oauth_providers"]


def _back_to_site(code: str | None = None):
    app_base = current_app.config["APP_BASE_URL"].rstrip("/")
    return redirect(f"{app_base}/?auth_error={code}" if code else f"{app_base}/")


def auth_providers():
    """GET /api/auth/providers — which sign-in buttons the site should show."""
    return jsonify({"success": True, "providers": sorted(_providers())})


@limited(limit=30, window_seconds=60)
def auth_oauth_start(provider):
    """GET /api/auth/oauth/<provider>/start"""
    p = _providers().get(provider)
    if p is None:
        return _back_to_site("PROVIDER_UNAVAILABLE")
    with db.transaction() as conn:
        url = oauth.begin(conn, p, api_base_url=current_app.config["API_BASE_URL"])
    return redirect(url)


@limited(limit=30, window_seconds=60)
def auth_oauth_callback(provider):
    """GET (Google) or POST (Apple) /api/auth/oauth/<provider>/callback"""
    p = _providers().get(provider)
    if p is None:
        return _back_to_site("PROVIDER_UNAVAILABLE")

    args = request.form if request.method == "POST" else request.args
    if args.get("error"):
        return _back_to_site("CANCELLED" if args["error"] in _CANCELLED else "PROVIDER_ERROR")

    # Apple sends the person's name once, on their very first sign-in, as a
    # form field beside the code — never inside the ID token.
    apple_name = None
    if args.get("user"):
        try:
            n = json.loads(args["user"]).get("name") or {}
            apple_name = " ".join(x for x in (n.get("firstName"), n.get("lastName")) if x) or None
        except (ValueError, AttributeError):
            apple_name = None

    try:
        with db.transaction() as conn:
            identity = oauth.complete(
                conn, p, state=args.get("state", ""), code=args.get("code", ""),
                api_base_url=current_app.config["API_BASE_URL"], apple_name=apple_name,
            )
            user = oauth.sign_in(conn, identity)
            token = new_token()
            repo.create_session(conn, user_id=user.id, token=token, ttl=SESSION_TTL)
    except oauth.OAuthError as exc:
        current_app.logger.warning("sign-in with %s failed: %s", provider, exc)
        return _back_to_site(exc.code)

    return set_session_cookie(_back_to_site(), token, config=current_app.config["APP_CONFIG"])


def auth_logout():
    """POST /api/auth/logout — always succeeds, so an expired cookie does not
    show the user an error on their way out."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        with db.transaction() as conn:
            repo.delete_session(conn, token)
    return clear_session_cookie(jsonify({"success": True}),
                                config=current_app.config["APP_CONFIG"])


def auth_me():
    """GET /api/auth/me — the current user. A 200 on load means already signed in."""
    return jsonify({"success": True, "user": _user_json(current_user())})


def register_auth_routes(app):
    """Register the authentication endpoints."""
    app.add_url_rule("/api/auth/providers", "auth_providers", auth_providers, methods=["GET"])
    app.add_url_rule("/api/auth/oauth/<provider>/start", "auth_oauth_start",
                     auth_oauth_start, methods=["GET"])
    app.add_url_rule("/api/auth/oauth/<provider>/callback", "auth_oauth_callback",
                     auth_oauth_callback, methods=["GET", "POST"])
    app.add_url_rule("/api/auth/logout", "auth_logout", auth_logout, methods=["POST"])
    app.add_url_rule("/api/auth/me", "auth_me", auth_me, methods=["GET"])
