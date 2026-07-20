from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Loaded from environment variables / .env. See .env.example at repo root
    for the full list this will grow into as later modules land."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str = "postgresql+asyncpg://punerecpip:change_me@localhost:5432/punerecpip"


@lru_cache
def get_settings() -> Settings:
    return Settings()
