"""Authentication HTTP endpoints.

A thin translation layer: parse the request, call `AuthService`, turn the
result or an `AuthError` into a response. No SQL, no policy. Anything resembling
a decision belongs in the service, where it can be tested without a request.

Each handler runs inside one `db.transaction()`, so a flow that writes several
rows — creating an account and its verification token — either lands completely
or not at all. If the email provider raises, the transaction rolls back and no
half-built account is left holding the address.
"""

from __future__ import annotations

from flask import current_app, jsonify, redirect, request

from backend.auth import db
from backend.auth import service as svc
from backend.auth.middleware import (
    clear_session_cookie,
    current_user,
    set_session_cookie,
)

# Endpoints reachable without a session. Everything not named here requires one
# — see `install_auth`. Note that resend-verification and the reset endpoints
# must be public: the users who need them are by definition unable to log in.
PUBLIC_AUTH_ENDPOINTS = {
    "auth_register",
    "auth_login",
    "auth_logout",
    "auth_verify",
    "auth_resend_verification",
    "auth_request_reset",
    "auth_reset_password",
}


def _body() -> dict:
    return request.get_json(silent=True) or {}


def _error(exc: svc.AuthError):
    return jsonify({"success": False, "error": str(exc), "code": exc.code}), exc.status


def _user_json(user) -> dict:
    """The public shape of a user. Deliberately excludes password_hash."""
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "email_verified": user.is_verified,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def _service() -> svc.AuthService:
    return current_app.extensions["auth_service"]


# --------------------------------------------------------------------------
# Handlers
# --------------------------------------------------------------------------


def auth_register():
    """POST /api/auth/register

    Always 202 on a well-formed request, whether or not the address was already
    registered. Reporting the difference here would let anyone test which
    addresses have accounts; the distinction is delivered by email instead.
    """
    body = _body()
    try:
        with db.transaction() as conn:
            _service().register(
                conn,
                email=body.get("email", ""),
                password=body.get("password", ""),
                display_name=body.get("display_name", ""),
            )
    except svc.AuthError as exc:
        return _error(exc)

    return jsonify(
        {
            "success": True,
            "message": "Check your email for a confirmation link.",
        }
    ), 202


def auth_verify():
    """GET /api/auth/verify?token=...

    Redirects rather than returning JSON: this URL is opened by clicking a link
    in an email, so the response lands in a browser window and the user needs to
    end up looking at the site.
    """
    app_base = current_app.config["APP_BASE_URL"]
    token = request.args.get("token", "")

    try:
        with db.transaction() as conn:
            _service().verify_email(conn, token)
    except svc.AuthError as exc:
        return redirect(f"{app_base}/login?error={exc.code}")

    return redirect(f"{app_base}/login?verified=1")


def auth_resend_verification():
    """POST /api/auth/resend-verification — always 202, never says whether the
    address exists or was already verified."""
    try:
        with db.transaction() as conn:
            _service().resend_verification(conn, email=_body().get("email", ""))
    except svc.AuthError as exc:
        return _error(exc)
    return jsonify(
        {"success": True, "message": "If that account needs confirming, a new link is on its way."}
    ), 202


def auth_login():
    """POST /api/auth/login — sets the session cookie."""
    body = _body()
    try:
        with db.transaction() as conn:
            token = _service().login(
                conn, email=body.get("email", ""), password=body.get("password", "")
            )
            user = _service_user(conn, token)
    except svc.AuthError as exc:
        return _error(exc)

    response = jsonify({"success": True, "user": _user_json(user)})
    return set_session_cookie(response, token, config=current_app.config["APP_CONFIG"])


def _service_user(conn, token):
    from backend.auth import repository as repo

    return repo.get_session_user(conn, token)


def auth_logout():
    """POST /api/auth/logout — always succeeds, so an expired cookie does not
    show the user an error on their way out."""
    from backend.auth.middleware import SESSION_COOKIE_NAME

    token = request.cookies.get(SESSION_COOKIE_NAME)
    with db.transaction() as conn:
        _service().logout(conn, token)

    response = jsonify({"success": True})
    return clear_session_cookie(response, config=current_app.config["APP_CONFIG"])


def auth_me():
    """GET /api/auth/me — the current user. Requires a session.

    This is what the frontend calls on load; a 200 here is what "remembered the
    user" looks like from the browser's side.
    """
    return jsonify({"success": True, "user": _user_json(current_user())})


def auth_request_reset():
    """POST /api/auth/request-reset — always 202, even for unknown addresses."""
    try:
        with db.transaction() as conn:
            _service().request_password_reset(conn, email=_body().get("email", ""))
    except svc.AuthError as exc:
        return _error(exc)
    return jsonify(
        {"success": True, "message": "If that account exists, a reset link is on its way."}
    ), 202


def auth_reset_password():
    """POST /api/auth/reset — sets a new password and signs out every device."""
    body = _body()
    try:
        with db.transaction() as conn:
            _service().reset_password(
                conn,
                token=body.get("token", ""),
                new_password=body.get("password", ""),
            )
    except svc.AuthError as exc:
        return _error(exc)

    response = jsonify({"success": True, "message": "Password updated. Please sign in."})
    return clear_session_cookie(response, config=current_app.config["APP_CONFIG"])


def register_auth_routes(app):
    """Register the authentication endpoints."""
    app.add_url_rule("/api/auth/register", "auth_register", auth_register, methods=["POST"])
    app.add_url_rule("/api/auth/login", "auth_login", auth_login, methods=["POST"])
    app.add_url_rule("/api/auth/logout", "auth_logout", auth_logout, methods=["POST"])
    app.add_url_rule("/api/auth/me", "auth_me", auth_me, methods=["GET"])
    app.add_url_rule("/api/auth/verify", "auth_verify", auth_verify, methods=["GET"])
    app.add_url_rule(
        "/api/auth/resend-verification",
        "auth_resend_verification",
        auth_resend_verification,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/auth/request-reset", "auth_request_reset", auth_request_reset, methods=["POST"]
    )
    app.add_url_rule(
        "/api/auth/reset", "auth_reset_password", auth_reset_password, methods=["POST"]
    )
