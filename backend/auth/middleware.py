"""Request authentication.

Auth is enforced by a `before_request` hook with an explicit allowlist of public
endpoints, not by a decorator on each view. The difference matters: a decorator
protects the routes someone remembered to decorate, so a new endpoint is public
until noticed. A hook plus an allowlist inverts that — a new endpoint is
protected until someone deliberately lists it. The old system had 29 endpoints
that were public by omission, which is exactly the failure this prevents.

Sessions travel in an HttpOnly cookie. The previous implementation also accepted
`?session_token=` in the query string, which writes credentials into access
logs, browser history and `Referer` headers; only the cookie is read here.
"""

from __future__ import annotations

from datetime import timedelta

from flask import Response, g, jsonify, request

from . import db
from . import repository as repo

SESSION_COOKIE_NAME = "fa_session"

# How long a session lasts, and how stale it must get before a request extends
# it. Refreshing on every request would write to the database on every
# authenticated call for no benefit.
SESSION_TTL = timedelta(days=30)
SESSION_REFRESH_AFTER = timedelta(days=1)


def _unauthorized(code: str, message: str):
    return jsonify({"success": False, "error": message, "code": code}), 401


def install_auth(app, *, public_endpoints: set[str]) -> None:
    """Require a valid session on every endpoint outside `public_endpoints`."""

    app.config["PUBLIC_ENDPOINTS"] = set(public_endpoints)

    @app.before_request
    def _authenticate():
        # Preflight carries no cookies by design; rejecting it would break CORS
        # before the real request is ever sent.
        if request.method == "OPTIONS":
            return None

        # No endpoint means no route matched. Let Flask return its 404 rather
        # than implying the path exists but needs a login.
        if request.endpoint is None:
            return None

        if request.endpoint in app.config["PUBLIC_ENDPOINTS"]:
            return None

        token = request.cookies.get(SESSION_COOKIE_NAME)
        if not token:
            return _unauthorized("NO_SESSION", "authentication required")

        with db.transaction() as conn:
            user = repo.get_session_user(conn, token)
            if user is None:
                return _unauthorized("INVALID_SESSION", "session expired or invalid")
            repo.refresh_session_if_stale(
                conn, token, ttl=SESSION_TTL, refresh_after=SESSION_REFRESH_AFTER
            )

        g.current_user = user
        return None


def current_user():
    """The authenticated user for this request, or None on a public endpoint."""
    return getattr(g, "current_user", None)


# --------------------------------------------------------------------------
# Cookie handling
# --------------------------------------------------------------------------


def set_session_cookie(response: Response, token: str, *, config) -> Response:
    """Attach the session cookie.

    HttpOnly keeps the token unreadable from JavaScript, so an XSS bug cannot
    exfiltrate it. SameSite=Lax is sufficient because the site and the API are
    subdomains of one registrable domain — Lax restricts cross-*site* requests,
    and these are same-site. Secure is configurable only so local development
    works over plain http; it is always on in production.
    """
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite="Lax",
        domain=config.COOKIE_DOMAIN or None,
        path="/",
    )
    return response


# One sign-in attempt, named in the browser that started it. The database row
# holds the nonce and the code verifier; this holds nothing but proof that the
# browser finishing the flow is the browser that began it.
OAUTH_STATE_COOKIE_NAME = "fa_oauth_state"
OAUTH_STATE_COOKIE_TTL = 600


def set_oauth_state_cookie(response: Response, state: str, *, config, cross_site: bool) -> Response:
    """Bind a pending sign-in to this browser.

    Without this, `state` lives only in the database, so any browser can finish
    any pending sign-in: an attacker starts a flow and has the victim's browser
    load the callback, and the victim is handed a session for the attacker's
    account. Requiring the cookie to come back makes the attempt browser-bound.

    Apple replies with a cross-site POST, and Lax cookies are not sent on those,
    so Apple needs SameSite=None — which browsers only honour on Secure cookies.
    In local development over plain http that combination is dropped entirely,
    so there we fall back to Lax and Apple's callback is unbound; production is
    https and gets the real thing.
    """
    same_site = "None" if (cross_site and config.COOKIE_SECURE) else "Lax"
    response.set_cookie(
        OAUTH_STATE_COOKIE_NAME,
        state,
        max_age=OAUTH_STATE_COOKIE_TTL,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite=same_site,
        domain=config.COOKIE_DOMAIN or None,
        path="/api/auth",
    )
    return response


def clear_oauth_state_cookie(response: Response, *, config) -> Response:
    """Drop the binding cookie. Called on every finished attempt, good or bad, so
    a failed sign-in does not leave a usable one behind."""
    response.set_cookie(
        OAUTH_STATE_COOKIE_NAME,
        "",
        expires=0,
        httponly=True,
        secure=config.COOKIE_SECURE,
        domain=config.COOKIE_DOMAIN or None,
        path="/api/auth",
    )
    return response


def clear_session_cookie(response: Response, *, config) -> Response:
    """Remove the session cookie.

    The flags must match those used when setting it, or the browser treats this
    as a different cookie and leaves the original in place.
    """
    response.set_cookie(
        SESSION_COOKIE_NAME,
        "",
        expires=0,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite="Lax",
        domain=config.COOKIE_DOMAIN or None,
        path="/",
    )
    return response
