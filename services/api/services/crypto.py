"""Symmetric encryption for secrets persisted in the database.

Used to keep Instagram long-lived access tokens encrypted at rest so a
database dump does not leak publish-capable credentials.

Key rotation: bumping IG_TOKEN_ENC_KEY invalidates every stored token;
users have to re-connect Instagram. That's intentional — we never want
to silently decrypt with an old key after rotation.
"""
from __future__ import annotations

import base64
import logging
import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


class TokenDecryptionError(RuntimeError):
    """Raised when a stored ciphertext can't be decrypted.

    Callers should treat this as "the user must reconnect Instagram" —
    it typically means the encryption key rotated or the row was copied
    from a different environment.
    """


@lru_cache(maxsize=1)
def _get_cipher() -> Fernet:
    key = os.getenv("IG_TOKEN_ENC_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "IG_TOKEN_ENC_KEY is not set. Generate one with: "
            "python -c 'from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())'"
        )
    # Fernet expects a 32-byte urlsafe base64 key. Validate shape early
    # so a malformed env var fails at startup, not on first OAuth call.
    try:
        raw = base64.urlsafe_b64decode(key.encode())
    except Exception as exc:
        raise RuntimeError(f"IG_TOKEN_ENC_KEY is not valid urlsafe base64: {exc}")
    if len(raw) != 32:
        raise RuntimeError(
            f"IG_TOKEN_ENC_KEY must decode to 32 bytes, got {len(raw)}"
        )
    return Fernet(key.encode())


def encrypt_token(plaintext: str) -> str:
    """Encrypt a raw token. Output is urlsafe base64 text, DB-safe."""
    if not plaintext:
        raise ValueError("encrypt_token: plaintext must be non-empty")
    return _get_cipher().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    """Decrypt a previously-encrypted token."""
    if not ciphertext:
        raise ValueError("decrypt_token: ciphertext must be non-empty")
    try:
        return _get_cipher().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise TokenDecryptionError(
            "Stored IG token is not decryptable with the current "
            "IG_TOKEN_ENC_KEY — the user must reconnect Instagram."
        ) from exc


def redact_token(token: str | None) -> str:
    """Safe log-line representation — first 6 + last 4 chars only."""
    if not token:
        return "<none>"
    if len(token) < 16:
        return "<redacted>"
    return f"{token[:6]}...{token[-4:]}"
