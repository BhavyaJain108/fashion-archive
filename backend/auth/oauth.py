"""Sign in with Google or Apple.

Both are OpenID Connect: send the browser to the provider, get a one-time code
back on our callback, trade it for an ID token, and check that token's
signature against the provider's published keys. The token names a stable
subject id plus an email the provider has already verified — which is why there
is no password, verification email or reset flow any more.

Accounts are found by (provider, subject) first. A first-time identity with a
verified email that matches an existing account is linked to it, so people who
signed up with email and password keep their archive when they switch.

The `state` row and its nonce live in Postgres; the caller also puts the state in
a short-lived cookie, and the callback requires both. The row proves the provider
sent the browser to us, and the cookie proves it is the browser that started —
without the second, an attacker can finish their own sign-in inside someone
else's browser and hand them a session for the attacker's account. Apple replies
with a cross-site POST, which a Lax cookie is not sent on, so that cookie is
issued SameSite=None for Apple and Lax for Google.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlencode

import jwt
import requests

from . import repository as repo
from .tokens import new_token

STATE_TTL = timedelta(minutes=10)
HTTP_TIMEOUT = 10


class OAuthError(Exception):
    """The provider round trip failed. `code` goes back to the site in the URL."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code


@dataclass(frozen=True)
class Identity:
    provider: str
    subject: str
    email: str | None
    email_verified: bool
    name: str | None


class Provider:
    name: str
    client_id: str
    authorize_endpoint: str
    token_endpoint: str
    jwks_uri: str
    issuers: tuple[str, ...]
    scope: str
    use_pkce: bool = True
    response_mode: str | None = None

    def __init__(self, jwk_client=None):
        # Injected in tests so no key fetch leaves the machine.
        self._jwks = jwk_client or jwt.PyJWKClient(self.jwks_uri, cache_keys=True)

    def client_secret(self) -> str:
        raise NotImplementedError

    def authorize_url(
        self, *, redirect_uri: str, state: str, nonce: str, code_verifier: str | None
    ) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": self.scope,
            "state": state,
            "nonce": nonce,
        }
        if self.response_mode:
            params["response_mode"] = self.response_mode
        if self.use_pkce and code_verifier:
            digest = hashlib.sha256(code_verifier.encode()).digest()
            params["code_challenge"] = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
            params["code_challenge_method"] = "S256"
        return f"{self.authorize_endpoint}?{urlencode(params)}"

    def exchange_code(self, *, code: str, redirect_uri: str, code_verifier: str | None) -> str:
        """Trade the one-time code for an ID token."""
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": self.client_id,
            "client_secret": self.client_secret(),
        }
        if self.use_pkce and code_verifier:
            data["code_verifier"] = code_verifier
        resp = requests.post(self.token_endpoint, data=data, timeout=HTTP_TIMEOUT)
        if resp.status_code != 200:
            raise OAuthError("TOKEN_EXCHANGE_FAILED", f"{self.name}: HTTP {resp.status_code}")
        id_token = resp.json().get("id_token")
        if not id_token:
            raise OAuthError("TOKEN_EXCHANGE_FAILED", f"{self.name}: no id_token")
        return id_token

    def verify_id_token(self, id_token: str, *, nonce: str) -> dict:
        try:
            key = self._jwks.get_signing_key_from_jwt(id_token).key
            claims = jwt.decode(
                id_token,
                key,
                algorithms=["RS256", "ES256"],
                audience=self.client_id,
                leeway=60,
                options={"require": ["iss", "aud", "exp", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise OAuthError("INVALID_ID_TOKEN", str(exc)) from exc
        if claims.get("iss") not in self.issuers:
            raise OAuthError("INVALID_ID_TOKEN", "wrong issuer")
        # The nonce ties this token to the sign-in this browser started, so a
        # token lifted from somewhere else cannot be replayed into our callback.
        if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
            raise OAuthError("INVALID_ID_TOKEN", "nonce mismatch")
        return claims

    def identity(self, claims: dict, extra_name: str | None = None) -> Identity:
        verified = claims.get("email_verified")
        return Identity(
            provider=self.name,
            subject=str(claims["sub"]),
            email=claims.get("email"),
            email_verified=verified is True or str(verified).lower() == "true",
            name=claims.get("name") or extra_name,
        )


class GoogleProvider(Provider):
    name = "google"
    authorize_endpoint = "https://accounts.google.com/o/oauth2/v2/auth"
    token_endpoint = "https://oauth2.googleapis.com/token"
    jwks_uri = "https://www.googleapis.com/oauth2/v3/certs"
    issuers = ("https://accounts.google.com", "accounts.google.com")
    scope = "openid email profile"

    def __init__(self, client_id: str, client_secret: str, jwk_client=None):
        self.client_id = client_id
        self._secret = client_secret
        super().__init__(jwk_client)

    def client_secret(self) -> str:
        return self._secret


class AppleProvider(Provider):
    name = "apple"
    authorize_endpoint = "https://appleid.apple.com/auth/authorize"
    token_endpoint = "https://appleid.apple.com/auth/token"
    jwks_uri = "https://appleid.apple.com/auth/keys"
    issuers = ("https://appleid.apple.com",)
    scope = "name email"
    # Apple only returns name and email via form_post, and does not document
    # PKCE — the signed client secret below stands in for it.
    use_pkce = False
    response_mode = "form_post"

    def __init__(
        self, client_id: str, team_id: str, key_id: str, private_key: str, jwk_client=None
    ):
        self.client_id = client_id  # the Services ID, not the App ID
        self._team_id = team_id
        self._key_id = key_id
        # Render env vars flatten newlines; accept the .p8 either way.
        self._private_key = private_key.replace("\\n", "\n")
        super().__init__(jwk_client)

    def client_secret(self) -> str:
        """Apple has no static secret: it is a JWT we sign with the .p8 key."""
        now = int(time.time())
        return jwt.encode(
            {
                "iss": self._team_id,
                "iat": now,
                "exp": now + 300,
                "aud": "https://appleid.apple.com",
                "sub": self.client_id,
            },
            self._private_key,
            algorithm="ES256",
            headers={"kid": self._key_id},
        )


def providers_from_config(config) -> dict[str, Provider]:
    """Only providers whose credentials are all present are offered."""
    found: dict[str, Provider] = {}
    if config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET:
        found["google"] = GoogleProvider(config.GOOGLE_CLIENT_ID, config.GOOGLE_CLIENT_SECRET)
    if all(
        (
            config.APPLE_CLIENT_ID,
            config.APPLE_TEAM_ID,
            config.APPLE_KEY_ID,
            config.APPLE_PRIVATE_KEY,
        )
    ):
        found["apple"] = AppleProvider(
            config.APPLE_CLIENT_ID,
            config.APPLE_TEAM_ID,
            config.APPLE_KEY_ID,
            config.APPLE_PRIVATE_KEY,
        )
    return found


def redirect_uri(api_base_url: str, provider: str) -> str:
    return f"{api_base_url.rstrip('/')}/api/auth/oauth/{provider}/callback"


def begin(conn, provider: Provider, *, api_base_url: str) -> tuple[str, str]:
    """Record this attempt. Returns (provider URL, state).

    The state is handed back so the caller can also put it in a cookie: the row
    below proves the provider sent the browser to us, and the cookie proves it is
    the browser that started.
    """
    state = new_token()
    nonce = new_token()
    verifier = new_token() if provider.use_pkce else None
    repo.create_oauth_state(
        conn,
        state=state,
        provider=provider.name,
        nonce=nonce,
        code_verifier=verifier,
        ttl=STATE_TTL,
    )
    url = provider.authorize_url(
        redirect_uri=redirect_uri(api_base_url, provider.name),
        state=state,
        nonce=nonce,
        code_verifier=verifier,
    )
    return url, state


def complete(
    conn,
    provider: Provider,
    *,
    state: str,
    code: str,
    api_base_url: str,
    apple_name: str | None = None,
) -> Identity:
    """Check state, redeem the code, verify the token. Returns who signed in."""
    saved = repo.consume_oauth_state(conn, state, provider=provider.name)
    if saved is None:
        raise OAuthError("INVALID_STATE", "unknown, used or expired state")
    id_token = provider.exchange_code(
        code=code,
        redirect_uri=redirect_uri(api_base_url, provider.name),
        code_verifier=saved["code_verifier"],
    )
    claims = provider.verify_id_token(id_token, nonce=saved["nonce"])
    return provider.identity(claims, extra_name=apple_name)


def sign_in(conn, identity: Identity) -> repo.User:
    """Find, link or create the account behind an identity."""
    user = repo.get_user_by_identity(conn, identity.provider, identity.subject)
    if user is None:
        if not identity.email or not identity.email_verified:
            raise OAuthError("EMAIL_NOT_VERIFIED", "provider gave no verified email")
        user = repo.get_user_by_email(conn, identity.email)
        if user is None:
            try:
                user = repo.create_user(
                    conn,
                    email=identity.email,
                    display_name=(identity.name or identity.email.split("@")[0]).strip(),
                )
            except repo.EmailAlreadyExists as exc:
                # Exists but deactivated: do not hand the address to someone new.
                raise OAuthError("ACCOUNT_DISABLED") from exc
        repo.link_identity(
            conn,
            user_id=user.id,
            provider=identity.provider,
            subject=identity.subject,
            email=identity.email,
        )
        if not user.is_verified:
            repo.mark_email_verified(conn, user.id)
    repo.update_last_login(conn, user.id)
    return repo.get_user_by_id(conn, user.id)
