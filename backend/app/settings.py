from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cache_version: int = 62
    request_timeout_seconds: float = 15.0
    source_timeout_seconds: float = 45.0
    enrich_timeout_seconds: float = 12.0
    max_concurrent_sources: int = 2
    max_enrich_events_per_source: int = 120
    minimum_refresh_ratio: float = 0.7
    cache_ttl_seconds: int = 300
    cache_file: Path = BASE_DIR / "data" / "events_cache.json"
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
    )
    sources_file: Path = BASE_DIR / "config" / "sources.json"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    admin_token: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
