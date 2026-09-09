"""Auth flows: register, verify, login, logout, reset.

This layer holds the decisions — who gets in, what a response is allowed to
reveal, what a reset invalidates. It calls the repository for storage and a
sender for email, and knows nothing about HTTP; `auth_routes.py` translates the
exceptions below into status codes.

A theme worth stating once: several methods deliberately succeed when you might
expect them to fail. Registering an existing address, resetting an unknown
address, and logging out an expired token all return quietly. Each distinct
failure response is a way for an attacker to learn which email addresses have
accounts, so the difference is delivered by email to the address itself, where
only its real owner sees it.

Methods take a connection and never commit. The caller wraps a whole flow in one
transaction, so an account is never created without its verification token.
"""

from __future__ import annotations

import re
from datetime import timedelta
from uuid import UUID

from . import email as email_mod
from . import passwords
from . import repository as repo
from .tokens import new_token

SESSION_TTL = timedelta(days=30)
SESSION_REFRESH_AFTER = timedelta(days=1)
VERIFY_TOKEN_TTL = timedelta(hours=24)
RESET_TOKEN_TTL = timedelta(hours=1)

# Deliberately permissive. Strict RFC 5322 matching rejects addresses that work,
# and the verification email is the real proof that an address exists.
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")

# A hash to check against when no user exists, so an unknown email costs the
# same time as a wrong password. Computed once at import.
_DUMMY_HASH = passwords.hash_password("dummy-password-for-constant-time-login")


class AuthError(Exception):
    """Base for expected auth failures. `code` is what the API returns."""

    code = "AUTH_ERROR"
    status = 400


class InvalidEmail(AuthError):
    code = "INVALID_EMAIL"
    status = 400


class WeakPassword(AuthError):
    code = "WEAK_PASSWORD"
    status = 400


class InvalidCredentials(AuthError):
    code = "INVALID_CREDENTIALS"
    status = 401


class EmailNotVerified(AuthError):
    code = "EMAIL_NOT_VERIFIED"
    status = 403


class InvalidToken(AuthError):
    code = "INVALID_TOKEN"
    status = 400


def _validate_email(address: str) -> str:
    address = (address or "").strip()
    if not _EMAIL_PATTERN.match(address):
        raise InvalidEmail("that does not look like an email address")
    return address


def _validate_password(password: str) -> str:
    if len(password or "") < passwords.MIN_PASSWORD_LENGTH:
        raise WeakPassword(
            f"password must be at least {passwords.MIN_PASSWORD_LENGTH} characters"
        )
    if len(password) > passwords.MAX_PASSWORD_LENGTH:
        # Unbounded input is a cheap way to make the server do expensive work.
        raise WeakPassword(
            f"password must be at most {passwords.MAX_PASSWORD_LENGTH} characters"
        )
    return password


class AuthService:
    def __init__(
        self,
        *,
        sender: email_mod.EmailSender,
        api_base_url: str,
        app_base_url: str,
        session_ttl: timedelta = SESSION_TTL,
    ):
        self._sender = sender
        self._api_base_url = api_base_url.rstrip("/")
        self._app_base_url = app_base_url.rstrip("/")
        self._session_ttl = session_ttl

    # ----------------------------------------------------------------------
    # Registration and verification
    # ----------------------------------------------------------------------

    def register(self, conn, *, email: str, password: str, display_name: str) -> None:
        """Create an unverified account and email a verification link.

        Succeeds whether or not the address is already registered — see the
        module docstring. An address that already exists gets a different email,
        not a different response, and its stored password is left untouched so
        re-registering cannot overwrite someone's credentials.
        """
        email = _validate_email(email)
        _validate_password(password)

        try:
            user = repo.create_user(
                conn,
                email=email,
                password_hash=passwords.hash_password(password),
                display_name=(display_name or "").strip() or email.split("@")[0],
            )
        except repo.EmailAlreadyExists:
            self._sender.send(
                to=email,
                message=email_mod.build_account_exists_email(
                    app_base_url=self._app_base_url
                ),
            )
            return

        self._send_verification(conn, user_id=user.id, email=user.email)

    def resend_verification(self, conn, *, email: str) -> None:
        """Issue a fresh verification link.

        Silent for unknown addresses and for already-verified accounts: mailing
        either would turn this endpoint into a way to send mail from your domain
        to any address an attacker chooses.
        """
        user = repo.get_user_by_email(conn, email)
        if user is None or user.is_verified:
            return
        self._send_verification(conn, user_id=user.id, email=user.email)

    def _send_verification(self, conn, *, user_id: UUID, email: str) -> None:
        token = new_token()
        repo.create_email_token(
            conn, user_id=user_id, token=token, purpose="verify", ttl=VERIFY_TOKEN_TTL
        )
        self._sender.send(
            to=email,
            message=email_mod.build_verification_email(
                api_base_url=self._api_base_url, token=token
            ),
        )

    def verify_email(self, conn, token: str) -> UUID:
        """Redeem a verification token. Returns the verified user's id."""
        user_id = repo.consume_email_token(conn, token, purpose="verify")
        if user_id is None:
            raise InvalidToken("this verification link is invalid or has expired")
        repo.mark_email_verified(conn, user_id)
        return user_id

    # ----------------------------------------------------------------------
    # Sessions
    # ----------------------------------------------------------------------

    def login(self, conn, *, email: str, password: str) -> str:
        """Authenticate and return a new session token.

        An unknown address and a wrong password produce the same error, and both
        pay the cost of an argon2 verification — otherwise the faster response
        for an unknown address enumerates accounts by timing alone.
        """
        user = repo.get_user_by_email(conn, (email or "").strip())

        if user is None:
            passwords.verify_password(password, _DUMMY_HASH)
            raise InvalidCredentials("email or password is incorrect")

        if not passwords.verify_password(password, user.password_hash):
            raise InvalidCredentials("email or password is incorrect")

        if not user.is_verified:
            raise EmailNotVerified("confirm your email address before signing in")

        # Now that the password is known correct, transparently upgrade a hash
        # made with older parameters.
        if passwords.needs_rehash(user.password_hash):
            repo.set_password_hash(conn, user.id, passwords.hash_password(password))

        token = new_token()
        repo.create_session(conn, user_id=user.id, token=token, ttl=self._session_ttl)
        repo.update_last_login(conn, user.id)
        return token

    def logout(self, conn, token: str) -> None:
        """Revoke a session. Unknown tokens succeed quietly — an already-expired
        cookie should not show the user an error on their way out."""
        if token:
            repo.delete_session(conn, token)

    # ----------------------------------------------------------------------
    # Password reset
    # ----------------------------------------------------------------------

    def request_password_reset(self, conn, *, email: str) -> None:
        """Email a reset link. Silent for unknown addresses."""
        user = repo.get_user_by_email(conn, (email or "").strip())
        if user is None:
            return

        token = new_token()
        repo.create_email_token(
            conn, user_id=user.id, token=token, purpose="reset", ttl=RESET_TOKEN_TTL
        )
        self._sender.send(
            to=user.email,
            message=email_mod.build_reset_email(
                app_base_url=self._app_base_url, token=token
            ),
        )

    def reset_password(self, conn, *, token: str, new_password: str) -> UUID:
        """Set a new password and sign out every device.

        Revoking sessions is the point of a reset when an account is already
        compromised: leaving the attacker's 30-day session alive would make the
        new password irrelevant to them.

        The password is validated before the token is consumed, so a rejected
        password does not burn a single-use link.
        """
        _validate_password(new_password)

        user_id = repo.consume_email_token(conn, token, purpose="reset")
        if user_id is None:
            raise InvalidToken("this reset link is invalid, used, or has expired")

        repo.set_password_hash(conn, user_id, passwords.hash_password(new_password))
        repo.delete_all_sessions(conn, user_id)
        return user_id
