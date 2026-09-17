"""ID-token verification, and the two providers' differences.

Keys are generated here, so nothing is fetched and nothing is trusted that this
file did not sign. The checks below are the ones standing between a real
sign-in and a forged one: signature, audience, issuer, and the nonce that ties
a token to the attempt this browser started.
"""

from __future__ import annotations

import time
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from backend.auth.oauth import AppleProvider, GoogleProvider, OAuthError

pytestmark = pytest.mark.unit

CLIENT_ID = "client-id.apps.googleusercontent.com"
ISSUER = "https://accounts.google.com"


@pytest.fixture(scope="module")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def ec_key():
    return ec.generate_private_key(ec.SECP256R1())


class FakeJwks:
    """Stands in for PyJWKClient, handing back the key we signed with."""

    def __init__(self, key):
        self._key = key

    def get_signing_key_from_jwt(self, _token):
        return type("Key", (), {"key": self._key.public_key()})()


@pytest.fixture
def google(rsa_key):
    return GoogleProvider(CLIENT_ID, "client-secret", jwk_client=FakeJwks(rsa_key))


def make_token(rsa_key, **overrides):
    now = int(time.time())
    claims = {
        "iss": ISSUER, "aud": CLIENT_ID, "sub": "1234567890",
        "email": "person@example.test", "email_verified": True,
        "name": "A Person", "nonce": "the-nonce",
        "iat": now, "exp": now + 600,
    }
    claims.update(overrides)
    return jwt.encode(claims, rsa_key, algorithm="RS256")


class TestVerifyIdToken:
    def test_accepts_a_good_token(self, google, rsa_key):
        claims = google.verify_id_token(make_token(rsa_key), nonce="the-nonce")
        assert claims["sub"] == "1234567890"

    def test_rejects_a_different_nonce(self, google, rsa_key):
        """Without this a token obtained elsewhere could be posted to our callback."""
        with pytest.raises(OAuthError) as exc:
            google.verify_id_token(make_token(rsa_key), nonce="a-different-nonce")
        assert exc.value.code == "INVALID_ID_TOKEN"

    def test_rejects_a_token_for_another_client(self, google, rsa_key):
        with pytest.raises(OAuthError):
            google.verify_id_token(make_token(rsa_key, aud="someone-else"), nonce="the-nonce")

    def test_rejects_a_foreign_issuer(self, google, rsa_key):
        with pytest.raises(OAuthError):
            google.verify_id_token(
                make_token(rsa_key, iss="https://evil.example.test"), nonce="the-nonce"
            )

    def test_rejects_an_expired_token(self, google, rsa_key):
        now = int(time.time())
        with pytest.raises(OAuthError):
            google.verify_id_token(
                make_token(rsa_key, iat=now - 7200, exp=now - 3600), nonce="the-nonce"
            )

    def test_rejects_a_token_signed_by_another_key(self, google):
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        with pytest.raises(OAuthError):
            google.verify_id_token(make_token(other), nonce="the-nonce")

    def test_rejects_an_unsigned_token(self, google, rsa_key):
        """alg=none is the oldest trick against a JWT verifier."""
        forged = jwt.encode({"iss": ISSUER, "aud": CLIENT_ID, "sub": "1",
                             "nonce": "the-nonce", "exp": int(time.time()) + 600},
                            key="", algorithm="none")
        with pytest.raises(OAuthError):
            google.verify_id_token(forged, nonce="the-nonce")


class TestIdentity:
    def test_reads_the_claims(self, google, rsa_key):
        claims = google.verify_id_token(make_token(rsa_key), nonce="the-nonce")
        identity = google.identity(claims)
        assert (identity.provider, identity.subject) == ("google", "1234567890")
        assert identity.email == "person@example.test"
        assert identity.email_verified is True

    def test_accepts_apples_string_boolean(self, google, rsa_key):
        """Apple sends email_verified as the string "true", Google as a boolean."""
        claims = google.verify_id_token(
            make_token(rsa_key, email_verified="true"), nonce="the-nonce"
        )
        assert google.identity(claims).email_verified is True

    def test_treats_anything_else_as_unverified(self, google, rsa_key):
        claims = google.verify_id_token(
            make_token(rsa_key, email_verified=False), nonce="the-nonce"
        )
        assert google.identity(claims).email_verified is False


class TestAuthorizeUrl:
    def test_google_sends_a_pkce_challenge(self, google):
        url = google.authorize_url(redirect_uri="https://api.example.test/cb",
                                   state="st", nonce="no", code_verifier="verifier")
        q = parse_qs(urlparse(url).query)
        assert q["code_challenge_method"] == ["S256"]
        assert "verifier" not in url  # the challenge is a hash, never the verifier
        assert q["state"] == ["st"] and q["nonce"] == ["no"]

    def test_apple_asks_for_a_form_post(self, ec_key):
        """Apple only returns the person's name and email by form_post."""
        apple = AppleProvider("studio.example.web", "TEAMID", "KEYID",
                              _pem(ec_key), jwk_client=FakeJwks(ec_key))
        q = parse_qs(urlparse(apple.authorize_url(
            redirect_uri="https://api.example.test/cb", state="st", nonce="no",
            code_verifier=None)).query)
        assert q["response_mode"] == ["form_post"]
        assert q["scope"] == ["name email"]
        assert "code_challenge" not in q


class TestAppleClientSecret:
    def test_is_a_jwt_apple_can_check(self, ec_key):
        apple = AppleProvider("studio.example.web", "TEAMID", "KEYID", _pem(ec_key))
        secret = apple.client_secret()

        assert jwt.get_unverified_header(secret)["kid"] == "KEYID"
        claims = jwt.decode(secret, ec_key.public_key(), algorithms=["ES256"],
                            audience="https://appleid.apple.com")
        assert claims["iss"] == "TEAMID"
        assert claims["sub"] == "studio.example.web"
        assert claims["exp"] > time.time()

    def test_accepts_a_key_whose_newlines_were_flattened(self, ec_key):
        """Render stores multi-line values with literal \\n in them."""
        apple = AppleProvider("studio.example.web", "TEAMID", "KEYID",
                              _pem(ec_key).replace("\n", "\\n"))
        assert apple.client_secret()


def _pem(key) -> str:
    from cryptography.hazmat.primitives import serialization

    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
