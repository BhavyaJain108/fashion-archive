"""Opaque token generation and hashing.

Session and email tokens are 32 bytes from `secrets` — 256 bits of entropy.
Guessing one is infeasible, so unlike passwords they need no slow hash; SHA-256
is used purely so the database stores something non-replayable. A slow KDF here
would cost a hash on every authenticated request and buy nothing.
"""

from __future__ import annotations

import hashlib
import secrets

TOKEN_BYTES = 32


def new_token() -> str:
    """A fresh URL-safe token. Give this to the user; store only its hash."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> bytes:
    """The 32-byte digest stored in `sessions.token_hash` / `email_tokens.token_hash`."""
    return hashlib.sha256(token.encode("utf-8")).digest()
