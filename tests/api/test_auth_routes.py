"""Signing in with a provider, over HTTP.

The provider itself is stubbed: these tests never leave the machine. What they
check is everything on our side of the round trip — that a callback without a
valid state is refused, that a verified email links to an account that already
exists, that the session cookie comes back with the flags a browser needs, and
that failures land the user back on the site instead of on a blank API page.
"""

from __future__ import annotations

import pytest

from backend.auth import oauth

from .conftest import sign_in

pytestmark = pytest.mark.db

APP = "http://localhost:3000"


class StubProvider(oauth.Provider):
    """Answers like Google without a network call."""

    name = "google"
    authorize_endpoint = "https://accounts.example.test/authorize"
    token_endpoint = "https://oauth.example.test/token"
    jwks_uri = "https://oauth.example.test/certs"
    issuers = ("https://accounts.example.test",)
    scope = "openid email profile"

    def __init__(
        self,
        *,
        sub="google-sub-1",
        email="signup@example.test",
        email_verified=True,
        name="Signup Person",
    ):
        self.client_id = "client-id"
        self.claims = {"sub": sub, "email": email, "email_verified": email_verified, "name": name}
        self.exchanged = []
        # Deliberately skips Provider.__init__: no JWKS client is needed.

    def client_secret(self):
        return "secret"

    def exchange_code(self, *, code, redirect_uri, code_verifier):
        self.exchanged.append(
            {"code": code, "redirect_uri": redirect_uri, "code_verifier": code_verifier}
        )
        return "stub-id-token"

    def verify_id_token(self, id_token, *, nonce):
        return dict(self.claims)


@pytest.fixture
def provider(flask_app):
    stub = StubProvider()
    flask_app.extensions["oauth_providers"] = {"google": stub}
    yield stub
    flask_app.extensions["oauth_providers"] = {}


def start(client):
    """Begin a sign-in and return the state the provider would send back."""
    from urllib.parse import parse_qs, urlparse

    response = client.get("/api/auth/oauth/google/start")
    assert response.status_code == 302
    return parse_qs(urlparse(response.headers["Location"]).query)["state"][0]


def callback(client, state, **extra):
    return client.get(
        "/api/auth/oauth/google/callback",
        query_string={"state": state, "code": "auth-code", **extra},
    )


def bind(client, state):
    """Put the binding cookie back, as the browser that began the attempt would.

    The callback clears it on every finished attempt, so a test that wants to
    reach the database's single-use check has to present it again.
    """
    from backend.auth.middleware import OAUTH_STATE_COOKIE_NAME

    client.set_cookie(OAUTH_STATE_COOKIE_NAME, state, path="/api/auth")


def session_cookie(response):
    for header in response.headers.getlist("Set-Cookie"):
        if header.startswith("fa_session="):
            return header
    return None


class TestProviders:
    def test_lists_only_configured_providers(self, client, provider):
        assert client.get("/api/auth/providers").get_json()["providers"] == ["google"]

    def test_empty_when_none_configured(self, client, flask_app):
        flask_app.extensions["oauth_providers"] = {}
        assert client.get("/api/auth/providers").get_json()["providers"] == []

    def test_is_public(self, client, provider):
        assert client.get("/api/auth/providers").status_code == 200


class TestStart:
    def test_redirects_to_the_provider(self, client, provider):
        response = client.get("/api/auth/oauth/google/start")
        assert response.status_code == 302
        assert response.headers["Location"].startswith(provider.authorize_endpoint)

    def test_unknown_provider_goes_back_to_the_site(self, client, provider):
        """Not a JSON 404: the browser is mid-navigation and needs somewhere to land."""
        response = client.get("/api/auth/oauth/nope/start")
        assert response.status_code == 302
        assert "auth_error=PROVIDER_UNAVAILABLE" in response.headers["Location"]


class TestCallback:
    def test_signs_in_and_sets_the_cookie(self, client, provider):
        response = callback(client, start(client))
        assert response.status_code == 302
        assert response.headers["Location"] == f"{APP}/"

        cookie = session_cookie(response)
        assert cookie and "HttpOnly" in cookie and "SameSite=Lax" in cookie
        assert client.get("/api/auth/me").get_json()["user"]["email"] == "signup@example.test"

    def test_creates_a_verified_account(self, client, provider):
        callback(client, start(client))
        user = client.get("/api/auth/me").get_json()["user"]
        assert user["email_verified"] is True
        assert user["display_name"] == "Signup Person"

    def test_second_sign_in_reuses_the_same_account(self, client, provider):
        callback(client, start(client))
        first = client.get("/api/auth/me").get_json()["user"]["id"]
        callback(client, start(client))
        assert client.get("/api/auth/me").get_json()["user"]["id"] == first

    def test_links_to_an_account_that_already_existed(self, client, provider):
        """Someone who signed up by email before keeps their archive."""
        existing = sign_in(client, "signup@example.test")
        client.post("/api/auth/logout")

        callback(client, start(client))
        assert client.get("/api/auth/me").get_json()["user"]["id"] == str(existing.id)

    def test_a_state_cannot_be_replayed(self, client, provider):
        state = start(client)
        assert callback(client, state).headers["Location"] == f"{APP}/"

        # Even from the browser that started it: the row is gone after one use.
        bind(client, state)
        replayed = callback(client, state)
        assert "auth_error=INVALID_STATE" in replayed.headers["Location"]
        assert session_cookie(replayed) is None

    def test_a_forged_state_is_refused(self, client, provider):
        """A state we never issued, presented as though we had."""
        bind(client, "state-we-never-issued")
        response = callback(client, "state-we-never-issued")
        assert "auth_error=INVALID_STATE" in response.headers["Location"]
        assert session_cookie(response) is None

    def test_an_attempt_this_browser_did_not_start_is_refused(self, client, provider):
        """Login CSRF. Someone else begins a sign-in and has this browser finish
        it; without the binding cookie the browser would be handed a session for
        *their* account."""
        state = start(client)
        client.delete_cookie("fa_oauth_state", path="/api/auth")

        response = callback(client, state)
        assert "auth_error=STATE_NOT_BOUND" in response.headers["Location"]
        assert session_cookie(response) is None

    def test_a_binding_cookie_for_another_attempt_is_refused(self, client, provider):
        state = start(client)
        bind(client, "some-other-attempt")

        response = callback(client, state)
        assert "auth_error=STATE_NOT_BOUND" in response.headers["Location"]
        assert session_cookie(response) is None

    def test_the_binding_cookie_is_dropped_once_the_attempt_is_over(self, client, provider):
        response = callback(client, start(client))
        cleared = [
            h for h in response.headers.getlist("Set-Cookie") if h.startswith("fa_oauth_state=")
        ]
        assert cleared and ("Expires=Thu, 01 Jan 1970" in cleared[0] or "Max-Age=0" in cleared[0])

    def test_a_cancelled_sign_in_says_so(self, client, provider):
        response = callback(client, start(client), error="access_denied")
        assert "auth_error=CANCELLED" in response.headers["Location"]

    def test_an_unverified_email_is_refused(self, client, flask_app):
        """Linking on an unverified address would let anyone claim it."""
        flask_app.extensions["oauth_providers"] = {"google": StubProvider(email_verified=False)}
        response = callback(client, start(client))
        assert "auth_error=EMAIL_NOT_VERIFIED" in response.headers["Location"]
        assert session_cookie(response) is None


class TestSession:
    def test_me_needs_a_session(self, client):
        assert client.get("/api/auth/me").status_code == 401

    def test_logout_ends_it(self, client):
        sign_in(client)
        assert client.get("/api/auth/me").status_code == 200
        assert client.post("/api/auth/logout").status_code == 200
        assert client.get("/api/auth/me").status_code == 401

    def test_logout_without_a_session_still_succeeds(self, client):
        assert client.post("/api/auth/logout").status_code == 200


class TestLogoutOrigin:
    """Logout is the one state-changing endpoint without a session in front of it."""

    def test_our_own_page_can_sign_out(self, client):
        response = client.post("/api/auth/logout", headers={"Origin": APP})
        assert response.status_code == 200
        assert response.get_json()["success"] is True

    def test_another_site_cannot_sign_you_out(self, client):
        response = client.post("/api/auth/logout", headers={"Origin": "https://evil.example"})
        assert response.status_code == 403
        assert response.get_json()["code"] == "BAD_ORIGIN"
        assert session_cookie(response) is None

    def test_a_request_with_no_origin_still_works(self, client):
        # curl, a health check, a same-origin form: a browser always sends Origin
        # cross-origin, so its absence is not the case being defended against.
        assert client.post("/api/auth/logout").status_code == 200

    def test_signing_out_really_ends_the_session(self, client, provider):
        callback(client, start(client))
        assert client.get("/api/auth/me").status_code == 200
        client.post("/api/auth/logout", headers={"Origin": APP})
        assert client.get("/api/auth/me").status_code == 401
