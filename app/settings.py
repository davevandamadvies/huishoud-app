from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Instellingen uit omgevingsvariabelen.

    Geheimen krijgen nooit een standaardwaarde.
    """

    app_env: Literal["dev", "test", "prod"] = "prod"
    database_url: str = "sqlite:////data/huishoud.db"

    # Eerste beheerder: de `sub` van het Authelia-account. Wordt alleen
    # gebruikt zolang er nog geen beheerder in de database staat.
    initial_admin_sub: str | None = None
    initial_admin_name: str = Field(default="Beheerder", max_length=50)

    # Levensduur van een sessie; schuift mee bij gebruik.
    session_max_age_days: int = Field(default=90, ge=1, le=400)

    # Publieke URL van de app (bron voor de redirect-URI en de Origin-check),
    # bijv. https://huishoud.example.com
    base_url: str | None = None

    # Inloggen via OpenID Connect (Authelia). Geen standaardwaarden.
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: SecretStr | None = None
    oidc_scopes: str = "openid profile"

    # Back-up van de database (alleen SQLite): elke nacht een kopie hierin.
    backup_dir: str = "/data/backups"
    backup_keep: int = Field(default=14, ge=1, le=365)

    # Web Push (VAPID). Zonder sleutels staan meldingen uit.
    vapid_public_key: str | None = None
    vapid_private_key: SecretStr | None = None
    vapid_subject: str | None = None

    @property
    def push_enabled(self) -> bool:
        return bool(
            self.vapid_public_key and self.vapid_private_key and self.vapid_subject
        )

    @field_validator("base_url", "oidc_issuer")
    @classmethod
    def _strip_trailing_slash(cls, value: str | None) -> str | None:
        return value.rstrip("/") if value else value

    def missing_auth_settings(self) -> list[str]:
        """Namen van ontbrekende instellingen die nodig zijn voor inloggen."""
        required = {
            "BASE_URL": self.base_url,
            "OIDC_ISSUER": self.oidc_issuer,
            "OIDC_CLIENT_ID": self.oidc_client_id,
            "OIDC_CLIENT_SECRET": self.oidc_client_secret,
        }
        return [name for name, value in required.items() if not value]


@lru_cache
def get_settings() -> Settings:
    return Settings()
