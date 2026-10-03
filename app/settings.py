from functools import lru_cache
from typing import Literal

from pydantic import Field
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
