from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime configuration for the Telegram bot."""

    bot_token: str = ""
    telegram_proxy: str | None = None

    api_base_url: str = "http://localhost:8000"
    request_timeout_seconds: float = 30
    api_cache_ttl_seconds: int = 90
    filter_cache_ttl_seconds: int = 3600

    admin_token: str = ""
    admin_telegram_ids: str = ""

    # Delivery
    poll_interval_seconds: int = 900
    digest_hour_utc: int = 6
    reminder_check_interval_seconds: int = 3600
    max_notifications_per_tick: int = 4
    # Quiet hours are in Moscow time. Outside this window the bot sends
    # nothing proactively: no new-event digests and no reminders.
    quiet_hours_start: int = 22
    quiet_hours_end: int = 9
    drop_pending_updates: bool = False

    # Growth / monetization
    public_base_url: str = ""
    partner_contact: str = "@fronteno"
    partner_impression_per_user_day: int = 1
    partner_config_file: str = str(BASE_DIR / "app" / "config" / "partners.json")

    # Local data
    database_file: str = str(BASE_DIR / "app" / "data" / "sporly.db")
    webapp_url: str = "https://sporly.ru"
    season_override: str = ""

    redirect_host: str = "0.0.0.0"
    redirect_port: int = 8081

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def admin_ids(self) -> set[int]:
        result: set[int] = set()
        for part in self.admin_telegram_ids.split(","):
            part = part.strip()
            if part.isdigit():
                result.add(int(part))
        return result

    @property
    def database_path(self) -> Path:
        return Path(self.database_file).expanduser().resolve()

    @property
    def partner_config_path(self) -> Path:
        path = Path(self.partner_config_file).expanduser()
        if not path.is_absolute():
            path = BASE_DIR / path
        return path.resolve()


settings = Settings()
