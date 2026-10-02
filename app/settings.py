from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Instellingen uit omgevingsvariabelen.

    Geheimen krijgen nooit een standaardwaarde.
    """

    app_env: Literal["dev", "test", "prod"] = "prod"
    database_url: str = "sqlite:////data/huishoud.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()
