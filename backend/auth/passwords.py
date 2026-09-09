"""Password hashing.

argon2id, replacing unsalted SHA-256. SHA-256 is fast by design, which is the
opposite of what a password hash needs: a consumer GPU tries billions of
candidates per second against it, and without a salt one precomputed table
cracks every user at once. argon2id is deliberately slow and memory-hard, and
salts each hash automatically.

Parameters are argon2-cffi's defaults, which track the current OWASP guidance.
Raising them later is safe: `needs_rehash` reports existing hashes as stale and
they are upgraded transparently on the user's next successful login.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, InvalidHashError

_hasher = PasswordHasher()

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128


def hash_password(password: str) -> str:
    """Hash a password for storage. Returns a self-describing argon2id string."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """True if the password matches.

    A malformed or corrupt stored hash returns False rather than raising, so a
    damaged row fails one login instead of returning 500 from the endpoint.
    """
    try:
        return _hasher.verify(password_hash, password)
    except (Argon2Error, InvalidHashError, TypeError, ValueError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True if the hash was made with weaker parameters than we now use."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except (Argon2Error, InvalidHashError, TypeError, ValueError):
        return True
