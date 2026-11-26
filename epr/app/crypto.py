"""Field-level encryption (AES-256-GCM) and blind indexes.

Clinical free text and national identifiers are encrypted before they reach the
database, so a database dump or backup alone does not reveal them. Disk-level
encryption (LUKS) on the host is still required; this is a second layer.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.types import Text, TypeDecorator

from .config import settings

_PREFIX = "v1:"


def encrypt(plaintext: str | None) -> str | None:
    if plaintext is None:
        return None
    nonce = os.urandom(12)
    ct = AESGCM(settings.data_key()).encrypt(nonce, plaintext.encode("utf-8"), None)
    return _PREFIX + base64.b64encode(nonce + ct).decode("ascii")


def decrypt(token: str | None) -> str | None:
    if token is None:
        return None
    if not token.startswith(_PREFIX):
        raise ValueError("Unknown ciphertext format")
    raw = base64.b64decode(token[len(_PREFIX):])
    return AESGCM(settings.data_key()).decrypt(raw[:12], raw[12:], None).decode("utf-8")


def blind_index(value: str | None) -> str | None:
    """Keyed hash used to look up an encrypted identifier by exact value."""
    if not value:
        return None
    norm = "".join(value.split()).upper()
    return hmac.new(settings.index_key(), norm.encode(), hashlib.sha256).hexdigest()


class EncryptedText(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt(value)

    def process_result_value(self, value, dialect):
        return decrypt(value)
