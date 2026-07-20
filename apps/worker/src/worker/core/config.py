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

    # AI Enrichment (Module 5).
    enrichment_provider: str = "claude"  # "claude" | "openai"
    enrichment_claude_model: str = "claude-sonnet-5"
    enrichment_openai_model: str = "gpt-4o-mini"
    enrichment_embedding_model: str = "text-embedding-3-small"
    # SDK-level retry (both AsyncAnthropic/AsyncOpenAI retry transient
    # 429/5xx/connection errors internally) rather than a hand-rolled retry
    # loop in EnrichmentService — see docs/modules/05-ai-enrichment.md.
    enrichment_max_retries: int = 3
    # Combined crawled-markdown budget handed to the AI provider, roughly
    # 4 chars/token — keeps a multi-page crawl within a reasonable request
    # size/cost regardless of how much content Module 4 collected.
    enrichment_max_content_chars: int = 24000
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None

    # Public RERA registry enrichment (Module 7). Reuses the discovery-style
    # rate-limit/robots/retry plumbing since it's the same "polite public-web
    # HTTP client" shape.
    rera_user_agent: str = (
        "PuneRECPIPBot/0.1 (+https://github.com/ganeshbpatil/PuneRECPIP; "
        "public RERA registry lookup; respects robots.txt)"
    )
    rera_request_timeout_seconds: float = 15.0
    rera_max_retries: int = 3
    rera_default_requests_per_second: float = 0.5

    # Geographic Intelligence (Module 9). Nominatim's usage policy requires a
    # descriptive User-Agent and caps the shared public instance at 1 req/s —
    # see worker/geo/nominatim.py. base_url is overridable to point at a
    # self-hosted Nominatim instance or another provider for real volume.
    geo_nominatim_base_url: str = "https://nominatim.openstreetmap.org/search"
    geo_user_agent: str = (
        "PuneRECPIPBot/0.1 (+https://github.com/ganeshbpatil/PuneRECPIP; "
        "geocoding via Nominatim, respects usage policy)"
    )
    geo_request_timeout_seconds: float = 15.0
    geo_max_retries: int = 3
    geo_requests_per_second: float = 1.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
