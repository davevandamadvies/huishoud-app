"""Hulpjes voor tests met Web Push."""

import json

import http_ece
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app import push
from app.settings import get_settings


class Browser:
    """Simuleert de sleutels die een browser bij een abonnement maakt."""

    def __init__(self) -> None:
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.auth = b"0123456789abcdef"

    @property
    def p256dh(self) -> str:
        raw = self.key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        return push.b64url_encode(raw)

    @property
    def auth_b64(self) -> str:
        return push.b64url_encode(self.auth)

    def decrypt(self, body: bytes) -> dict:
        plain = http_ece.decrypt(
            body, private_key=self.key, auth_secret=self.auth, version="aes128gcm"
        )
        return json.loads(plain)


@pytest.fixture
def vapid(monkeypatch: pytest.MonkeyPatch, db_url: str) -> tuple[str, str]:
    public, private = push.generate_keys()
    monkeypatch.setenv("VAPID_PUBLIC_KEY", public)
    monkeypatch.setenv("VAPID_PRIVATE_KEY", private)
    monkeypatch.setenv("VAPID_SUBJECT", "mailto:test@example.com")
    get_settings.cache_clear()
    return public, private
