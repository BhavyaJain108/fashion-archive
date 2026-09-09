"""Tests for the auth service — the flows a user actually experiences.

The repository tests cover storage. These cover decisions: who is allowed in,
what an attacker can learn from a response, and what a password reset must
invalidate.
"""

from __future__ import annotations

import pytest
from auth import repository as repo
from auth import service as svc
from auth.email import RecordingSender

pytestmark = pytest.mark.db

PASSWORD = "a-good-password"
EMAIL = "archivist@example.com"


@pytest.fixture
def sender():
    return RecordingSender()


@pytest.fixture
def auth(sender):
    return svc.AuthService(
        sender=sender,
        api_base_url="https://api.example.studio",
        app_base_url="https://example.studio",
    )


def token_from(sender):
    """Pull the token out of the most recent email, the way a user would by
    clicking the link."""
    text = sender.last.message.text
    return text.split("token=")[1].split()[0].strip()


def register_and_verify(auth, conn, sender, email=EMAIL, password=PASSWORD):
    auth.register(conn, email=email, password=password, display_name="Archivist")
    auth.verify_email(conn, token_from(sender))


class TestRegister:
    def test_creates_an_unverified_account(self, auth, conn):
        auth.register(conn, email=EMAIL, password=PASSWORD, display_name="Archivist")
        user = repo.get_user_by_email(conn, EMAIL)
        assert user is not None and user.email_verified_at is None

    def test_sends_a_verification_email(self, auth, conn, sender):
        auth.register(conn, email=EMAIL, password=PASSWORD, display_name="Archivist")
        assert sender.last.to == EMAIL
        assert "verify" in sender.last.message.text.lower()

    def test_password_is_not_stored_in_plaintext(self, auth, conn):
        auth.register(conn, email=EMAIL, password=PASSWORD, display_name="Archivist")
        stored = repo.get_user_by_email(conn, EMAIL).password_hash
        assert PASSWORD not in stored
        assert stored.startswith("$argon2id$")

    @pytest.mark.parametrize("bad", ["", "short", "1234567"])
    def test_rejects_passwords_under_eight_characters(self, auth, conn, bad):
        with pytest.raises(svc.WeakPassword):
            auth.register(conn, email=EMAIL, password=bad, display_name="A")

    @pytest.mark.parametrize("bad", ["", "not-an-email", "@example.com", "a@", "a b@c.com"])
    def test_rejects_malformed_emails(self, auth, conn, bad):
        with pytest.raises(svc.InvalidEmail):
            auth.register(conn, email=bad, password=PASSWORD, display_name="A")

    def test_rejects_absurdly_long_passwords(self, auth, conn):
        """argon2 will hash any length; an unbounded input is a cheap way to
        make the server do expensive work."""
        with pytest.raises(svc.WeakPassword):
            auth.register(conn, email=EMAIL, password="x" * 200, display_name="A")


class TestRegisterWithExistingEmail:
    def test_does_not_raise(self, auth, conn, sender):
        """Raising would let an attacker enumerate registered addresses by
        watching which registrations fail."""
        register_and_verify(auth, conn, sender)
        auth.register(conn, email=EMAIL, password=PASSWORD, display_name="Archivist")

    def test_does_not_create_a_second_account(self, auth, conn, sender):
        auth.register(conn, email=EMAIL, password=PASSWORD, display_name="First")
        auth.register(conn, email=EMAIL, password="another-password", display_name="Second")
        count = conn.execute("SELECT count(*) FROM users WHERE email = %s", (EMAIL,)).fetchone()[0]
        assert count == 1

    def test_does_not_change_the_existing_password(self, auth, conn, sender):
        """Otherwise anyone could overwrite an account's password by
        re-registering its address."""
        auth.register(conn, email=EMAIL, password=PASSWORD, display_name="First")
        auth.verify_email(conn, token_from(sender))
        auth.register(conn, email=EMAIL, password="attacker-chosen", display_name="Second")

        assert auth.login(conn, email=EMAIL, password=PASSWORD)
        with pytest.raises(svc.InvalidCredentials):
            auth.login(conn, email=EMAIL, password="attacker-chosen")

    def test_emails_the_real_owner_that_an_account_exists(self, auth, conn, sender):
        auth.register(conn, email=EMAIL, password=PASSWORD, display_name="First")
        auth.register(conn, email=EMAIL, password=PASSWORD, display_name="Second")
        assert sender.last.to == EMAIL
        assert "already" in sender.last.message.text.lower()


class TestVerifyEmail:
    def test_marks_the_account_verified(self, auth, conn, sender):
        auth.register(conn, email=EMAIL, password=PASSWORD, display_name="Archivist")
        auth.verify_email(conn, token_from(sender))
        assert repo.get_user_by_email(conn, EMAIL).is_verified

    def test_token_cannot_be_reused(self, auth, conn, sender):
        auth.register(conn, email=EMAIL, password=PASSWORD, display_name="Archivist")
        token = token_from(sender)
        auth.verify_email(conn, token)
        with pytest.raises(svc.InvalidToken):
            auth.verify_email(conn, token)

    def test_unknown_token_is_rejected(self, auth, conn):
        with pytest.raises(svc.InvalidToken):
            auth.verify_email(conn, "not-a-real-token")


class TestLogin:
    def test_returns_a_session_token(self, auth, conn, sender):
        register_and_verify(auth, conn, sender)
        token = auth.login(conn, email=EMAIL, password=PASSWORD)
        assert repo.get_session_user(conn, token).email == EMAIL

    def test_is_refused_before_verification(self, auth, conn):
        """The whole point of verification: an unverified address may belong to
        someone else."""
        auth.register(conn, email=EMAIL, password=PASSWORD, display_name="Archivist")
        with pytest.raises(svc.EmailNotVerified):
            auth.login(conn, email=EMAIL, password=PASSWORD)

    def test_wrong_password_is_refused(self, auth, conn, sender):
        register_and_verify(auth, conn, sender)
        with pytest.raises(svc.InvalidCredentials):
            auth.login(conn, email=EMAIL, password="wrong-password")

    def test_unknown_email_gives_the_same_error_as_a_wrong_password(self, auth, conn):
        """Distinct errors would let an attacker enumerate registered users."""
        with pytest.raises(svc.InvalidCredentials):
            auth.login(conn, email="nobody@example.com", password=PASSWORD)

    def test_unknown_email_still_performs_a_hash(self, auth, conn, monkeypatch):
        """Skipping the hash for unknown users makes the response measurably
        faster, which enumerates accounts by timing alone."""
        calls = []
        real = svc.passwords.verify_password
        monkeypatch.setattr(
            svc.passwords,
            "verify_password",
            lambda p, h: (calls.append(1), real(p, h))[1],
        )
        with pytest.raises(svc.InvalidCredentials):
            auth.login(conn, email="nobody@example.com", password=PASSWORD)
        assert calls, "no password hash performed for an unknown email"

    def test_email_is_case_insensitive(self, auth, conn, sender):
        register_and_verify(auth, conn, sender, email="Archivist@Example.com")
        assert auth.login(conn, email="ARCHIVIST@EXAMPLE.COM", password=PASSWORD)

    def test_records_last_login(self, auth, conn, sender):
        register_and_verify(auth, conn, sender)
        auth.login(conn, email=EMAIL, password=PASSWORD)
        assert repo.get_user_by_email(conn, EMAIL).last_login_at is not None

    def test_upgrades_a_stale_password_hash(self, auth, conn, sender):
        """Lets argon2 cost be raised later without forcing a password reset."""
        register_and_verify(auth, conn, sender)
        weak = "$argon2id$v=19$m=8,t=1,p=1$c29tZXNhbHQ$aGFzaGhhc2hoYXNoaGFzaGhhc2g"
        repo.set_password_hash(conn, repo.get_user_by_email(conn, EMAIL).id, weak)

        # A stale hash the user can still satisfy gets rewritten on login.
        import auth.passwords as pw

        monkey = pw.PasswordHasher(memory_cost=8, time_cost=1, parallelism=1)
        repo.set_password_hash(conn, repo.get_user_by_email(conn, EMAIL).id, monkey.hash(PASSWORD))

        auth.login(conn, email=EMAIL, password=PASSWORD)
        assert not pw.needs_rehash(repo.get_user_by_email(conn, EMAIL).password_hash)


class TestLogout:
    def test_revokes_the_session(self, auth, conn, sender):
        register_and_verify(auth, conn, sender)
        token = auth.login(conn, email=EMAIL, password=PASSWORD)
        auth.logout(conn, token)
        assert repo.get_session_user(conn, token) is None

    def test_unknown_token_is_not_an_error(self, auth, conn):
        """Logging out twice, or with an already-expired cookie, should succeed
        quietly rather than showing the user an error on the way out."""
        auth.logout(conn, "not-a-real-token")


class TestPasswordReset:
    def test_request_sends_a_reset_email(self, auth, conn, sender):
        register_and_verify(auth, conn, sender)
        auth.request_password_reset(conn, email=EMAIL)
        assert sender.last.to == EMAIL
        assert "reset" in sender.last.message.text.lower()

    def test_request_for_unknown_email_does_not_raise(self, auth, conn, sender):
        """Same reason as registration: a distinct response enumerates users."""
        auth.request_password_reset(conn, email="nobody@example.com")

    def test_request_for_unknown_email_sends_nothing(self, auth, conn, sender):
        auth.request_password_reset(conn, email="nobody@example.com")
        assert sender.last is None

    def test_reset_sets_the_new_password(self, auth, conn, sender):
        register_and_verify(auth, conn, sender)
        auth.request_password_reset(conn, email=EMAIL)
        auth.reset_password(conn, token=token_from(sender), new_password="brand-new-password")

        assert auth.login(conn, email=EMAIL, password="brand-new-password")

    def test_reset_invalidates_the_old_password(self, auth, conn, sender):
        register_and_verify(auth, conn, sender)
        auth.request_password_reset(conn, email=EMAIL)
        auth.reset_password(conn, token=token_from(sender), new_password="brand-new-password")

        with pytest.raises(svc.InvalidCredentials):
            auth.login(conn, email=EMAIL, password=PASSWORD)

    def test_reset_revokes_every_existing_session(self, auth, conn, sender):
        """If the account was compromised, resetting the password must evict the
        attacker — not leave their 30-day session alive."""
        register_and_verify(auth, conn, sender)
        attacker_session = auth.login(conn, email=EMAIL, password=PASSWORD)

        auth.request_password_reset(conn, email=EMAIL)
        auth.reset_password(conn, token=token_from(sender), new_password="brand-new-password")

        assert repo.get_session_user(conn, attacker_session) is None

    def test_reset_token_is_single_use(self, auth, conn, sender):
        register_and_verify(auth, conn, sender)
        auth.request_password_reset(conn, email=EMAIL)
        token = token_from(sender)
        auth.reset_password(conn, token=token, new_password="brand-new-password")

        with pytest.raises(svc.InvalidToken):
            auth.reset_password(conn, token=token, new_password="another-password")

    def test_reset_rejects_a_weak_new_password(self, auth, conn, sender):
        register_and_verify(auth, conn, sender)
        auth.request_password_reset(conn, email=EMAIL)
        with pytest.raises(svc.WeakPassword):
            auth.reset_password(conn, token=token_from(sender), new_password="short")

    def test_verification_token_cannot_reset_a_password(self, auth, conn, sender):
        """Otherwise a signup link doubles as a password-change link."""
        auth.register(conn, email=EMAIL, password=PASSWORD, display_name="Archivist")
        with pytest.raises(svc.InvalidToken):
            auth.reset_password(conn, token=token_from(sender), new_password="brand-new-password")


class TestResendVerification:
    def test_sends_a_fresh_token(self, auth, conn, sender):
        auth.register(conn, email=EMAIL, password=PASSWORD, display_name="Archivist")
        first = token_from(sender)
        auth.resend_verification(conn, email=EMAIL)
        assert token_from(sender) != first

    def test_the_fresh_token_works(self, auth, conn, sender):
        auth.register(conn, email=EMAIL, password=PASSWORD, display_name="Archivist")
        auth.resend_verification(conn, email=EMAIL)
        auth.verify_email(conn, token_from(sender))
        assert repo.get_user_by_email(conn, EMAIL).is_verified

    def test_unknown_email_sends_nothing_and_does_not_raise(self, auth, conn, sender):
        auth.resend_verification(conn, email="nobody@example.com")
        assert sender.last is None

    def test_already_verified_sends_nothing(self, auth, conn, sender):
        """No point mailing a verification link to someone already verified, and
        it would let anyone spam a known address with mail from your domain."""
        register_and_verify(auth, conn, sender)
        sender.sent.clear()
        auth.resend_verification(conn, email=EMAIL)
        assert sender.last is None
