"""OpenID Connect-client (authorization code flow met PKCE).

De app controleert het ID-token zelf: handtekening (alleen RS256, sleutels
uit de JWKS van de provider), issuer, audience, verloopdatum en nonce.
"""

import secrets
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from authlib.integrations.httpx_client import OAuth2Client
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet

from app.settings import Settings, get_settings

ALLOWED_ALGORITHMS = ["RS256"]
_CACHE_SECONDS = 3600
_LEEWAY_SECONDS = 60


class OIDCError(Exception):
    """Inloggen via de identity provider is mislukt."""


class OIDCNotConfigured(OIDCError):
    """De OIDC-instellingen ontbreken."""


@dataclass
class LoginRequest:
    url: str
    state: str
    nonce: str
    code_verifier: str


@dataclass
class OIDCClient:
    settings: Settings
    # Alleen voor tests: een httpx.MockTransport in plaats van het netwerk.
    transport: httpx.BaseTransport | None = None
    _metadata: dict[str, Any] | None = field(default=None, repr=False)
    _metadata_at: float = 0.0
    _jwks: KeySet | None = field(default=None, repr=False)
    _jwks_at: float = 0.0

    def __post_init__(self) -> None:
        missing = self.settings.missing_auth_settings()
        if missing:
            raise OIDCNotConfigured(", ".join(missing))

    @property
    def redirect_uri(self) -> str:
        return f"{self.settings.base_url}/auth/callback"

    def _http(self) -> httpx.Client:
        return httpx.Client(transport=self.transport, timeout=10.0)

    def _oauth(self) -> OAuth2Client:
        secret = self.settings.oidc_client_secret
        return OAuth2Client(
            client_id=self.settings.oidc_client_id,
            client_secret=secret.get_secret_value() if secret else None,
            token_endpoint_auth_method="client_secret_basic",  # noqa: S106
            redirect_uri=self.redirect_uri,
            scope=self.settings.oidc_scopes,
            code_challenge_method="S256",
            transport=self.transport,
            timeout=10.0,
        )

    def metadata(self) -> dict[str, Any]:
        now = time.monotonic()
        if self._metadata is None or now - self._metadata_at > _CACHE_SECONDS:
            url = f"{self.settings.oidc_issuer}/.well-known/openid-configuration"
            try:
                with self._http() as http:
                    response = http.get(url)
                    response.raise_for_status()
                    data = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise OIDCError(f"discovery mislukt: {exc}") from exc
            if data.get("issuer") != self.settings.oidc_issuer:
                raise OIDCError("issuer in discovery wijkt af")
            self._metadata, self._metadata_at = data, now
        return self._metadata

    def _key_set(self, refresh: bool = False) -> KeySet:
        now = time.monotonic()
        if refresh or self._jwks is None or now - self._jwks_at > _CACHE_SECONDS:
            try:
                with self._http() as http:
                    response = http.get(self.metadata()["jwks_uri"])
                    response.raise_for_status()
                    self._jwks = KeySet.import_key_set(response.json())
            except (httpx.HTTPError, ValueError, KeyError, JoseError) as exc:
                raise OIDCError(f"JWKS ophalen mislukt: {exc}") from exc
            self._jwks_at = now
        return self._jwks

    def start_login(self) -> LoginRequest:
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(48)
        with self._oauth() as oauth:
            url, _ = oauth.create_authorization_url(
                self.metadata()["authorization_endpoint"],
                state=state,
                nonce=nonce,
                code_verifier=code_verifier,
            )
        return LoginRequest(url, state, nonce, code_verifier)

    def finish_login(self, code: str, code_verifier: str, nonce: str) -> dict:
        """Wisselt de code in en geeft de gecontroleerde ID-token-claims terug."""
        try:
            with self._oauth() as oauth:
                token = oauth.fetch_token(
                    self.metadata()["token_endpoint"],
                    grant_type="authorization_code",
                    code=code,
                    code_verifier=code_verifier,
                )
        except OIDCError:
            raise
        except Exception as exc:  # Authlib/httpx gooien uiteenlopende fouten
            raise OIDCError(f"code inwisselen mislukt: {exc}") from exc
        id_token = token.get("id_token")
        if not id_token:
            raise OIDCError("geen ID-token ontvangen")
        return self.validate_id_token(id_token, nonce)

    def validate_id_token(self, id_token: str, nonce: str) -> dict:
        try:
            try:
                decoded = jwt.decode(id_token, self._key_set(), ALLOWED_ALGORITHMS)
            except JoseError:
                # Mogelijk een nieuwe sleutel bij de provider: één keer verversen.
                decoded = jwt.decode(
                    id_token, self._key_set(refresh=True), ALLOWED_ALGORITHMS
                )
            registry = jwt.JWTClaimsRegistry(
                leeway=_LEEWAY_SECONDS,
                iss={"essential": True, "value": self.settings.oidc_issuer},
                aud={"essential": True, "value": self.settings.oidc_client_id},
                sub={"essential": True},
                exp={"essential": True},
                iat={"essential": True},
                nonce={"essential": True, "value": nonce},
            )
            registry.validate(decoded.claims)
        except JoseError as exc:
            raise OIDCError(f"ID-token ongeldig: {exc}") from exc
        claims = decoded.claims
        aud = claims["aud"]
        audiences = aud if isinstance(aud, list) else [aud]
        if len(audiences) > 1 and claims.get("azp") != self.settings.oidc_client_id:
            raise OIDCError("ID-token ongeldig: azp ontbreekt of wijkt af")
        return claims


_clients: dict[int, OIDCClient] = {}


def get_oidc_client() -> OIDCClient:
    """FastAPI-dependency; gooit OIDCNotConfigured als instellingen ontbreken.

    Eén client per Settings-object, zodat discovery en JWKS gecachet blijven.
    """
    settings = get_settings()
    client = _clients.get(id(settings))
    if client is None or client.settings is not settings:
        client = _clients[id(settings)] = OIDCClient(settings)
    return client
