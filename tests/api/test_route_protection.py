"""Every endpoint requires a session unless it is explicitly public.

This is the test that keeps the fix from decaying. The old system had 29
endpoints that were unauthenticated by omission — nobody decided they should be
public, they just never got a decorator. Here, a route added tomorrow with no
thought given to auth fails this test until someone either protects it or names
it in the allowlist. The decision becomes mandatory rather than remembered.

It walks the real `app.url_map` and sends real requests, so it cannot be
satisfied by a hook that exists but is never reached.
"""

from __future__ import annotations

import re

import pytest

pytestmark = pytest.mark.db

# Flask's own static handler, not ours.
IGNORED_ENDPOINTS = {"static"}


def concrete_path(rule) -> str:
    """Fill in path parameters so the URL actually matches."""
    return re.sub(r"<[^>]+>", "1", str(rule))


def methods_to_check(rule) -> set[str]:
    # HEAD is derived from GET; OPTIONS is CORS preflight and must stay open.
    return set(rule.methods or set()) - {"HEAD", "OPTIONS"}


def all_rules(flask_app):
    return [r for r in flask_app.url_map.iter_rules() if r.endpoint not in IGNORED_ENDPOINTS]


def protected_rules(flask_app):
    public = flask_app.config["PUBLIC_ENDPOINTS"]
    return [r for r in all_rules(flask_app) if r.endpoint not in public]


class TestEveryProtectedEndpointRejectsAnonymous:
    def test_there_are_protected_routes_to_check(self, flask_app):
        """Guards against this whole file silently passing because the app
        failed to register anything."""
        assert len(protected_rules(flask_app)) > 20

    def test_no_protected_endpoint_serves_an_anonymous_request(self, flask_app, client):
        offenders = []
        for rule in protected_rules(flask_app):
            for method in methods_to_check(rule):
                response = client.open(concrete_path(rule), method=method)
                if response.status_code != 401:
                    offenders.append(
                        f"{method} {rule} -> {response.status_code} "
                        f"(endpoint {rule.endpoint})"
                    )

        assert not offenders, "endpoints reachable without a session:\n" + "\n".join(offenders)

    def test_rejection_names_a_machine_readable_code(self, flask_app, client):
        """The frontend routes on the code, not the prose."""
        rule = protected_rules(flask_app)[0]
        method = sorted(methods_to_check(rule))[0]
        body = client.open(concrete_path(rule), method=method).get_json()
        assert body["code"] == "NO_SESSION"
        assert body["success"] is False


class TestPublicEndpoints:
    def test_health_check_is_reachable(self, client):
        assert client.get("/api/health").status_code == 200

    def test_the_allowlist_contains_only_auth_and_health(self, flask_app):
        """A public endpoint should be a deliberate, reviewable choice. If this
        fails, someone widened the allowlist — check that they meant to."""
        assert flask_app.config["PUBLIC_ENDPOINTS"] == {
            "health_check",
            "auth_register",
            "auth_login",
            "auth_logout",
            "auth_verify",
            "auth_resend_verification",
            "auth_request_reset",
            "auth_reset_password",
        }

    def test_auth_me_is_not_public(self, flask_app):
        """It reports who you are; it must require being someone."""
        assert "auth_me" not in flask_app.config["PUBLIC_ENDPOINTS"]

    def test_scraper_endpoints_are_not_public(self, flask_app):
        """An open endpoint that launches Chromium against an arbitrary URL is
        an unmetered bill and an abuse vector."""
        public = flask_app.config["PUBLIC_ENDPOINTS"]
        assert not [e for e in public if not e.startswith("auth_") and e != "health_check"]


class TestSessionRejection:
    def test_a_garbage_cookie_is_rejected(self, flask_app, client):
        client.set_cookie("fa_session", "not-a-real-token", domain="localhost")
        response = client.get("/api/auth/me")
        assert response.status_code == 401
        assert response.get_json()["code"] == "INVALID_SESSION"

    def test_missing_cookie_is_rejected(self, client):
        assert client.get("/api/auth/me").status_code == 401
