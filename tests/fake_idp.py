"""Nep-identity provider voor tests: discovery, JWKS, token-endpoint."""

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs

import httpx
from joserfc import jwt
from joserfc.jwk import RSAKey

ISSUER = "https://idp.test"
CLIENT_ID = "huishoud-test"
CLIENT_SECRET = "test-secret"  # noqa: S105 - alleen in tests


@dataclass
class FakeIdP:
    key: RSAKey = field(
        default_factory=lambda: RSAKey.generate_key(2048, {"kid": "k1"})
    )
    # code -> (code_challenge, claims)
    codes: dict[str, tuple[str, dict[str, Any]]] = field(default_factory=dict)
    token_overrides: dict[str, Any] = field(default_factory=dict)
    sign_key: RSAKey | None = None
    header: dict[str, Any] = field(default_factory=dict)
    jwks_requests: int = 0

    def issue_code(self, code_challenge: str, **claims: Any) -> str:
        code = secrets.token_urlsafe(16)
        self.codes[code] = (code_challenge, claims)
        return code

    def id_token(self, claims: dict[str, Any]) -> str:
        now = int(time.time())
        payload = {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "iat": now,
            "exp": now + 300,
            **claims,
            **self.token_overrides,
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        key = self.sign_key or self.key
        header = {"alg": "RS256", "kid": key.kid, **self.header}
        return jwt.encode(header, payload, key)

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/.well-known/openid-configuration":
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": f"{ISSUER}/authorize",
                    "token_endpoint": f"{ISSUER}/token",
                    "jwks_uri": f"{ISSUER}/jwks",
                },
            )
        if path == "/jwks":
            self.jwks_requests += 1
            return httpx.Response(200, json={"keys": [self.key.as_dict(private=False)]})
        if path == "/token" and request.method == "POST":
            return self._token(request)
        return httpx.Response(404)

    def _token(self, request: httpx.Request) -> httpx.Response:
        expected = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
        if request.headers.get("authorization") != f"Basic {expected}":
            return httpx.Response(401, json={"error": "invalid_client"})
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        entry = self.codes.pop(form.get("code", ""), None)
        if entry is None:
            return httpx.Response(400, json={"error": "invalid_grant"})
        challenge, claims = entry
        verifier = form.get("code_verifier", "")
        digest = hashlib.sha256(verifier.encode()).digest()
        computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        if computed != challenge:
            return httpx.Response(400, json={"error": "invalid_grant", "pkce": True})
        body = {
            "access_token": "at",
            "token_type": "Bearer",
            "expires_in": 300,
            "id_token": self.id_token(claims),
        }
        return httpx.Response(200, content=json.dumps(body))

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)
