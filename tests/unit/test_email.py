"""Unit tests for outbound email construction.

No network. These check the parts that are easy to get wrong and expensive to
discover in production: a verification link pointing at the wrong host, or a
reset token leaking into a subject line that shows in a notification preview.
"""

from __future__ import annotations

import pytest
from auth.email import (
    ConsoleSender,
    RecordingSender,
    build_account_exists_email,
    build_reset_email,
    build_verification_email,
)

pytestmark = pytest.mark.unit

API = "https://api.example.studio"
APP = "https://example.studio"


class TestVerificationEmail:
    def test_link_points_at_the_api_not_the_frontend(self):
        """Verification needs no user input, so the link hits the API directly
        and the API redirects onward. A frontend link would need a page whose
        only job is to forward the token."""
        message = build_verification_email(api_base_url=API, token="tok123")
        assert f"{API}/api/auth/verify?token=tok123" in message.html
        assert f"{API}/api/auth/verify?token=tok123" in message.text

    def test_token_is_not_in_the_subject(self):
        """Subjects show in lock-screen previews and get logged by mail relays."""
        assert "tok123" not in build_verification_email(api_base_url=API, token="tok123").subject

    def test_has_both_html_and_plaintext(self):
        """A text/plain alternative keeps this out of spam filters that
        penalise HTML-only mail."""
        message = build_verification_email(api_base_url=API, token="tok123")
        assert message.html.strip() and message.text.strip()


class TestResetEmail:
    def test_link_points_at_the_frontend_not_the_api(self):
        """Reset needs the user to type a new password, so it must land on a
        page, not an API endpoint."""
        message = build_reset_email(app_base_url=APP, token="tok456")
        assert f"{APP}/reset-password?token=tok456" in message.html

    def test_token_is_not_in_the_subject(self):
        assert "tok456" not in build_reset_email(app_base_url=APP, token="tok456").subject

    def test_states_the_expiry(self):
        """Users who wait get a clear reason rather than a dead link."""
        assert "hour" in build_reset_email(app_base_url=APP, token="tok456").text.lower()


class TestAccountExistsEmail:
    def test_offers_a_reset_link(self):
        """Sent when someone registers an address that already has an account.
        Registration cannot say so in the response without disclosing who has an
        account, so this mail is the only feedback that reaches the real owner."""
        message = build_account_exists_email(app_base_url=APP)
        assert f"{APP}/reset-password" in message.html

    def test_does_not_contain_a_token(self):
        """Nobody proved they control this address by registering it, so the
        mail links to the reset form rather than carrying a live token."""
        message = build_account_exists_email(app_base_url=APP)
        assert "token=" not in message.html


class TestRecordingSender:
    def test_captures_messages_instead_of_sending(self):
        sender = RecordingSender()
        message = build_verification_email(api_base_url=API, token="tok123")
        sender.send(to="someone@example.com", message=message)

        assert len(sender.sent) == 1
        assert sender.sent[0].to == "someone@example.com"
        assert "tok123" in sender.sent[0].message.text

    def test_last_is_a_convenience_for_the_most_recent(self):
        sender = RecordingSender()
        sender.send(
            to="a@example.com", message=build_verification_email(api_base_url=API, token="1")
        )
        sender.send(
            to="b@example.com", message=build_verification_email(api_base_url=API, token="2")
        )
        assert sender.last.to == "b@example.com"

    def test_last_is_none_when_nothing_sent(self):
        assert RecordingSender().last is None


class TestConsoleSender:
    def test_prints_rather_than_sending(self, capsys):
        """Local development without a Resend key: the link goes to stdout."""
        sender = ConsoleSender()
        sender.send(
            to="dev@example.com",
            message=build_verification_email(api_base_url=API, token="tok123"),
        )
        printed = capsys.readouterr().out
        assert "dev@example.com" in printed
        assert "tok123" in printed
