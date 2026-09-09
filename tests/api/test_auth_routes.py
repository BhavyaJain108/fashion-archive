"""HTTP behaviour of the auth endpoints.

The service tests cover the rules; these cover the wire: status codes, the
cookie's flags, and the redirect a user lands on after clicking an email link.
Those are the parts a browser cares about and a service test cannot see.
"""

from __future__ import annotations

import pytest

from .conftest import token_from

pytestmark = pytest.mark.db

EMAIL = "archivist@example.com"
PASSWORD = "a-good-password"


def register(client, email=EMAIL, password=PASSWORD):
    return client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "display_name": "Archivist"},
    )


def verify(client, sender):
    return client.get(f"/api/auth/verify?token={token_from(sender)}")


def login(client, email=EMAIL, password=PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def session_cookie(response):
    """The Set-Cookie header for the session, if the response sets one."""
    for header in response.headers.getlist("Set-Cookie"):
        if header.startswith("fa_session="):
            return header
    return None


class TestRegister:
    def test_accepted(self, client, sender):
        assert register(client).status_code == 202

    def test_sends_verification_email(self, client, sender):
        register(client)
        assert sender.last.to == EMAIL

    def test_existing_email_returns_the_identical_response(self, client, sender):
        """Byte-identical, not merely the same status — a different message
        would still disclose which addresses are registered."""
        first = register(client)
        second = register(client)
        assert first.status_code == second.status_code == 202
        assert first.get_json() == second.get_json()

    def test_malformed_email_is_rejected(self, client, sender):
        response = register(client, email="not-an-email")
        assert response.status_code == 400
        assert response.get_json()["code"] == "INVALID_EMAIL"

    def test_short_password_is_rejected(self, client, sender):
        response = register(client, password="short")
        assert response.status_code == 400
        assert response.get_json()["code"] == "WEAK_PASSWORD"

    def test_empty_body_is_rejected_not_crashed(self, client, sender):
        assert client.post("/api/auth/register", json={}).status_code == 400

    def test_no_body_at_all_is_rejected_not_crashed(self, client, sender):
        assert client.post("/api/auth/register").status_code == 400


class TestVerify:
    def test_redirects_to_the_site_on_success(self, client, sender):
        register(client)
        response = verify(client, sender)
        assert response.status_code == 302
        assert response.headers["Location"] == "http://localhost:3000/login?verified=1"

    def test_redirects_with_an_error_on_a_bad_token(self, client, sender):
        response = client.get("/api/auth/verify?token=garbage")
        assert response.status_code == 302
        assert "error=INVALID_TOKEN" in response.headers["Location"]

    def test_missing_token_does_not_crash(self, client, sender):
        assert client.get("/api/auth/verify").status_code == 302


class TestLogin:
    def test_refused_before_verification(self, client, sender):
        register(client)
        response = login(client)
        assert response.status_code == 403
        assert response.get_json()["code"] == "EMAIL_NOT_VERIFIED"

    def test_succeeds_after_verification(self, client, sender):
        register(client)
        verify(client, sender)
        response = login(client)
        assert response.status_code == 200
        assert response.get_json()["user"]["email"] == EMAIL

    def test_sets_an_httponly_session_cookie(self, client, sender):
        """HttpOnly is what stops an XSS bug from reading the session token."""
        register(client)
        verify(client, sender)
        cookie = session_cookie(login(client))
        assert cookie is not None
        assert "HttpOnly" in cookie

    def test_cookie_is_samesite_lax(self, client, sender):
        register(client)
        verify(client, sender)
        assert "SameSite=Lax" in session_cookie(login(client))

    def test_wrong_password_is_401_with_no_cookie(self, client, sender):
        register(client)
        verify(client, sender)
        response = login(client, password="wrong-password")
        assert response.status_code == 401
        assert session_cookie(response) is None

    def test_unknown_email_gives_the_same_code_as_a_wrong_password(self, client, sender):
        response = login(client, email="nobody@example.com")
        assert response.status_code == 401
        assert response.get_json()["code"] == "INVALID_CREDENTIALS"

    def test_response_never_contains_the_password_hash(self, client, sender):
        register(client)
        verify(client, sender)
        assert "password" not in str(login(client).get_json()["user"])


class TestSessionLifecycle:
    def test_me_returns_the_user_once_logged_in(self, client, sender):
        register(client)
        verify(client, sender)
        login(client)

        response = client.get("/api/auth/me")
        assert response.status_code == 200
        assert response.get_json()["user"]["email"] == EMAIL

    def test_me_reports_verified_status(self, client, sender):
        register(client)
        verify(client, sender)
        login(client)
        assert client.get("/api/auth/me").get_json()["user"]["email_verified"] is True

    def test_the_session_survives_across_requests(self, client, sender):
        """This is 'remember me' — no re-login between calls."""
        register(client)
        verify(client, sender)
        login(client)
        for _ in range(3):
            assert client.get("/api/auth/me").status_code == 200

    def test_a_session_unlocks_the_other_protected_endpoints(self, client, sender):
        """Auth is global, so logging in must open more than /auth/me."""
        register(client)
        verify(client, sender)
        login(client)
        assert client.get("/api/brands").status_code != 401

    def test_logout_ends_the_session(self, client, sender):
        register(client)
        verify(client, sender)
        login(client)
        assert client.post("/api/auth/logout").status_code == 200
        assert client.get("/api/auth/me").status_code == 401

    def test_logout_without_a_session_still_succeeds(self, client, sender):
        """An expired cookie should not show an error on the way out."""
        assert client.post("/api/auth/logout").status_code == 200


class TestPasswordResetOverHttp:
    def test_request_is_accepted_for_a_real_address(self, client, sender):
        register(client)
        verify(client, sender)
        response = client.post("/api/auth/request-reset", json={"email": EMAIL})
        assert response.status_code == 202

    def test_request_for_unknown_address_looks_identical(self, client, sender):
        real = client.post("/api/auth/request-reset", json={"email": EMAIL})
        unknown = client.post("/api/auth/request-reset", json={"email": "nobody@example.com"})
        assert real.status_code == unknown.status_code == 202
        assert real.get_json() == unknown.get_json()

    def test_full_reset_flow(self, client, sender):
        register(client)
        verify(client, sender)
        client.post("/api/auth/request-reset", json={"email": EMAIL})

        response = client.post(
            "/api/auth/reset",
            json={"token": token_from(sender), "password": "a-brand-new-password"},
        )
        assert response.status_code == 200
        assert login(client, password="a-brand-new-password").status_code == 200
        assert login(client, password=PASSWORD).status_code == 401

    def test_reset_signs_out_existing_sessions(self, client, sender):
        register(client)
        verify(client, sender)
        login(client)
        assert client.get("/api/auth/me").status_code == 200

        client.post("/api/auth/request-reset", json={"email": EMAIL})
        client.post(
            "/api/auth/reset",
            json={"token": token_from(sender), "password": "a-brand-new-password"},
        )
        assert client.get("/api/auth/me").status_code == 401


class TestResendVerification:
    def test_accepted_for_an_unverified_account(self, client, sender):
        register(client)
        assert (
            client.post("/api/auth/resend-verification", json={"email": EMAIL}).status_code == 202
        )

    def test_the_resent_link_works(self, client, sender):
        register(client)
        client.post("/api/auth/resend-verification", json={"email": EMAIL})
        verify(client, sender)
        assert login(client).status_code == 200

    def test_unknown_address_looks_identical(self, client, sender):
        known = client.post("/api/auth/resend-verification", json={"email": EMAIL})
        unknown = client.post("/api/auth/resend-verification", json={"email": "no@example.com"})
        assert known.get_json() == unknown.get_json()
