# app/core/crypto.py
"""
Application-layer encryption for sensitive PII — specifically BVN, NIN, and
CAC numbers collected during merchant onboarding verification.

Why app-layer and not just "trust the DB disk encryption": if the database
itself is ever dumped, leaked, or queried by anyone who shouldn't see raw
BVN/NIN values (a support engineer debugging a row, a compromised DB
credential, a misconfigured backup bucket), those columns should still be
unreadable without APP_ENCRYPTION_KEY, which lives only in the app's own
environment.

Only these three columns are encrypted, not the whole row — full-row
encryption would block normal admin search/filter on everything else
(business_name, email, status, etc.) for no benefit, since those fields
aren't the sensitive ones.

Uses Fernet (symmetric, authenticated encryption) from the `cryptography`
package, which is already a transitive dependency in requirements.txt.
"""
import logging
import os

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.types import String, TypeDecorator

logger = logging.getLogger(__name__)

_fernet = None


def _get_fernet():
    global _fernet
    if _fernet is not None:
        return _fernet

    key = os.getenv("APP_ENCRYPTION_KEY", "")
    if not key:
        # Fail loudly rather than silently storing plaintext BVN/NIN/CAC.
        # Generate a real key once with:
        #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
        # and set it as APP_ENCRYPTION_KEY in your environment (Railway vars).
        # NEVER rotate/lose this key without a migration plan — existing
        # encrypted rows become unreadable if it changes.
        raise RuntimeError(
            "APP_ENCRYPTION_KEY is not set. Required to store BVN/NIN/CAC "
            "numbers. Generate one with Fernet.generate_key() and set it "
            "as an environment variable before accepting verification data."
        )
    try:
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as exc:
        raise RuntimeError(
            "APP_ENCRYPTION_KEY is set but isn't a valid Fernet key "
            "(must be 32 url-safe base64-encoded bytes)."
        ) from exc
    return _fernet


def encrypt_value(value):
    """Encrypt a plaintext string, returning a url-safe base64 ciphertext string."""
    if value is None:
        return None
    token = _get_fernet().encrypt(value.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_value(token):
    """Decrypt a ciphertext string back to plaintext. Returns None if token is None."""
    if token is None:
        return None
    try:
        return _get_fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        logger.error("Failed to decrypt value — invalid token or wrong APP_ENCRYPTION_KEY")
        raise


class EncryptedString(TypeDecorator):
    """
    SQLAlchemy column type that transparently encrypts on write and decrypts
    on read. Use exactly like String() on a model column:

        bvn = Column(EncryptedString(500), nullable=True)

    The model code never sees ciphertext — set/get plaintext as normal,
    encryption happens at the DB boundary.
    """
    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None or value == "":
            return None
        return encrypt_value(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return decrypt_value(value)
