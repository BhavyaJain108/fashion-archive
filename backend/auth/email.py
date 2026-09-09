"""Outbound email.

Sending is behind a small interface with three implementations: Resend in
production, a console printer for local development, and a recorder for tests.
That is why the test suite never needs a Resend API key and never sends real
mail — and why swapping Resend for Postmark or SES later is one new class.

Message bodies are plain functions returning a Message, so a link or a subject
can be asserted without a network call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import requests

RESEND_ENDPOINT = "https://api.resend.com/emails"
REQUEST_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class Message:
    subject: str
    html: str
    text: str


@dataclass(frozen=True)
class SentMessage:
    to: str
    message: Message


class EmailSender(Protocol):
    def send(self, *, to: str, message: Message) -> None: ...


class EmailDeliveryError(RuntimeError):
    """Raised when the provider rejects a message.

    Callers must let this propagate during registration so the surrounding
    transaction rolls back: an account created without a delivered verification
    link is unusable and its address is permanently taken.
    """


# --------------------------------------------------------------------------
# Senders
# --------------------------------------------------------------------------


class ResendSender:
    """Production sender. Uses the HTTP API directly — it is one POST, which is
    less to keep working than an extra dependency."""

    def __init__(self, api_key: str, mail_from: str):
        self._api_key = api_key
        self._mail_from = mail_from

    def send(self, *, to: str, message: Message) -> None:
        response = requests.post(
            RESEND_ENDPOINT,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "from": self._mail_from,
                "to": [to],
                "subject": message.subject,
                "html": message.html,
                "text": message.text,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code >= 400:
            # The body can echo the recipient address; the status and Resend's
            # own error id are enough to diagnose without logging the address.
            raise EmailDeliveryError(
                f"Resend rejected the message: HTTP {response.status_code}"
            )


class ConsoleSender:
    """Development sender: prints the message instead of delivering it.

    Lets the whole signup flow be exercised locally without a Resend key or a
    verified domain — copy the link out of the terminal.
    """

    def send(self, *, to: str, message: Message) -> None:
        print(f"\n--- email to {to} ---\n{message.subject}\n\n{message.text}\n---\n")


@dataclass
class RecordingSender:
    """Test sender: captures messages so assertions can read them."""

    sent: list[SentMessage] = field(default_factory=list)

    def send(self, *, to: str, message: Message) -> None:
        self.sent.append(SentMessage(to=to, message=message))

    @property
    def last(self) -> SentMessage | None:
        return self.sent[-1] if self.sent else None


# --------------------------------------------------------------------------
# Message bodies
# --------------------------------------------------------------------------

_SIGNATURE = "Premium Propoganda Fashion"


def _wrap(body_html: str) -> str:
    return (
        '<div style="font-family:system-ui,sans-serif;font-size:15px;line-height:1.5">'
        f"{body_html}"
        f'<p style="color:#888;font-size:13px">{_SIGNATURE}</p>'
        "</div>"
    )


def build_verification_email(*, api_base_url: str, token: str) -> Message:
    """Confirm a new signup.

    The link targets the API rather than the site: verification needs no input
    from the user, so the endpoint can consume the token and redirect. Tokens
    stay out of the subject, which appears in notification previews and relay logs.
    """
    link = f"{api_base_url}/api/auth/verify?token={token}"
    return Message(
        subject="Confirm your email",
        html=_wrap(
            "<p>Confirm your email address to finish setting up your archive.</p>"
            f'<p><a href="{link}">Confirm email</a></p>'
            "<p>This link expires in 24 hours. If you didn't sign up, ignore this.</p>"
        ),
        text=(
            "Confirm your email address to finish setting up your archive.\n\n"
            f"{link}\n\n"
            "This link expires in 24 hours. If you didn't sign up, ignore this.\n\n"
            f"{_SIGNATURE}"
        ),
    )


def build_reset_email(*, app_base_url: str, token: str) -> Message:
    """Password reset. Links to the site, because the user has to type a new
    password — an API endpoint has nowhere to put a form."""
    link = f"{app_base_url}/reset-password?token={token}"
    return Message(
        subject="Reset your password",
        html=_wrap(
            "<p>Use the link below to choose a new password.</p>"
            f'<p><a href="{link}">Reset password</a></p>'
            "<p>This link expires in 1 hour and can be used once. If you didn't "
            "ask for this, ignore it — your password will not change.</p>"
        ),
        text=(
            "Use the link below to choose a new password.\n\n"
            f"{link}\n\n"
            "This link expires in 1 hour and can be used once. If you didn't ask "
            "for this, ignore it - your password will not change.\n\n"
            f"{_SIGNATURE}"
        ),
    )


def build_account_exists_email(*, app_base_url: str) -> Message:
    """Sent when someone tries to register an address that already has an account.

    Registration cannot report this in its response without disclosing which
    addresses are registered, so this mail is the only feedback the real owner
    gets. It carries no token: whoever triggered it has not proven they control
    the address, so it links to the reset form rather than granting access.
    """
    link = f"{app_base_url}/reset-password"
    return Message(
        subject="You already have an account",
        html=_wrap(
            "<p>Someone tried to create an account with this email address, but "
            "one already exists.</p>"
            f'<p>If that was you and you\'ve forgotten your password, <a href="{link}">'
            "reset it here</a>. Otherwise nothing has changed and you can ignore "
            "this message.</p>"
        ),
        text=(
            "Someone tried to create an account with this email address, but one "
            "already exists.\n\n"
            f"If that was you and you've forgotten your password, reset it here:\n{link}\n\n"
            "Otherwise nothing has changed and you can ignore this message.\n\n"
            f"{_SIGNATURE}"
        ),
    )
