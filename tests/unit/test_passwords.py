"""Unit tests for password hashing.

These replace unsalted SHA-256 (`user_system/models.py:174`), which was
reversible via rainbow tables and computable at GPU speed. The properties
below are what make that class of attack impractical, so each one is a
regression guard on a real weakness, not a formality.
"""

from __future__ import annotations

import pytest
from auth.passwords import hash_password, needs_rehash, verify_password


@pytest.mark.unit
class TestHashPassword:
    def test_hash_is_not_the_password(self):
        assert hash_password("correct horse battery") != "correct horse battery"

    def test_same_password_hashes_differently_each_time(self):
        """Random salt per hash. Without this, identical passwords produce
        identical hashes and one cracked hash exposes every user sharing it."""
        first = hash_password("hunter2hunter2")
        second = hash_password("hunter2hunter2")
        assert first != second

    def test_uses_argon2id(self):
        assert hash_password("hunter2hunter2").startswith("$argon2id$")

    def test_accepts_unicode_and_long_passwords(self):
        for password in ("ünïcødé-påsswørd", "x" * 128, "🔐🔐🔐🔐🔐🔐🔐🔐"):
            assert verify_password(password, hash_password(password))


@pytest.mark.unit
class TestVerifyPassword:
    def test_accepts_correct_password(self):
        assert verify_password("hunter2hunter2", hash_password("hunter2hunter2"))

    def test_rejects_wrong_password(self):
        assert not verify_password("wrong-password", hash_password("hunter2hunter2"))

    def test_rejects_empty_password(self):
        assert not verify_password("", hash_password("hunter2hunter2"))

    def test_is_case_sensitive(self):
        assert not verify_password("HUNTER2HUNTER2", hash_password("hunter2hunter2"))

    @pytest.mark.parametrize(
        "bad_hash",
        ["", "not-a-hash", "$argon2id$truncated", "$2b$12$bcryptstyleinstead"],
    )
    def test_malformed_hash_returns_false_rather_than_raising(self, bad_hash):
        """A corrupt stored hash must fail the login, not 500 the endpoint."""
        assert verify_password("hunter2hunter2", bad_hash) is False


@pytest.mark.unit
class TestNeedsRehash:
    def test_current_parameters_do_not_need_rehash(self):
        assert needs_rehash(hash_password("hunter2hunter2")) is False

    def test_weaker_parameters_need_rehash(self):
        """Lets us raise argon2 cost later and upgrade hashes on next login."""
        weak = "$argon2id$v=19$m=8,t=1,p=1$c29tZXNhbHQ$aGFzaGhhc2hoYXNoaGFzaGhhc2g"
        assert needs_rehash(weak) is True

    def test_malformed_hash_needs_rehash(self):
        assert needs_rehash("not-a-hash") is True
