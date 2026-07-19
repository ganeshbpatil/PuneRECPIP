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

    # Crawling (Module 4).
    crawl_user_agent: str = (
        "PuneRECPIPBot/0.1 (+https://github.com/ganeshbpatil/PuneRECPIP; "
        "real estate company website crawler; respects robots.txt)"
    )
    # None lets Playwright resolve its own managed browser; set to override
    # (this repo's sandbox pins a specific pre-installed Chromium binary whose
    # revision doesn't match what a freshly `pip install`-ed playwright expects
    # — see docs/modules/04-crawling.md).
    chromium_executable_path: str | None = None
    crawl_page_timeout_seconds: float = 20.0
    crawl_max_concurrent_pages: int = 3
    crawl_max_pages_per_company: int = 6
    crawl_default_requests_per_second: float = 0.5
    crawl_max_retries: int = 2

    # Object storage for crawl artifacts (HTML/markdown/screenshots).
    object_storage_backend: str = "local"  # "local" | "s3"
    object_storage_local_dir: str = "./.data/object-storage"
    object_storage_bucket: str = "punerecpip-artifacts"
    object_storage_endpoint_url: str | None = None
    object_storage_region: str = "us-east-1"
    object_storage_access_key: str | None = None
    object_storage_secret_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
