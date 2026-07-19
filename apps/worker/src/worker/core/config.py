from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Loaded from environment variables / .env. See .env.example at repo root."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str = "postgresql+asyncpg://punerecpip:change_me@localhost:5432/punerecpip"
    redis_url: str = "redis://localhost:6379/0"

    # Discovery HTTP defaults — overridable per SiteProfile.
    discovery_user_agent: str = (
        "PuneRECPIPBot/0.1 (+https://github.com/ganeshbpatil/PuneRECPIP; "
        "real estate company discovery; respects robots.txt)"
    )
    discovery_request_timeout_seconds: float = 15.0
    discovery_max_retries: int = 3
    discovery_default_requests_per_second: float = 0.5


@lru_cache
def get_settings() -> Settings:
    return Settings()
