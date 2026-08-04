from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent


class BotSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bot_token: str
    api_base_url: str = "http://localhost:8000"
    admin_token: str = ""
    admin_telegram_ids: str = ""
    poll_interval_seconds: int = 900
    digest_hour_utc: int = 6
    reminder_check_interval_seconds: int = 3600
    request_timeout_seconds: float = 15.0
    subscriptions_file: Path = BASE_DIR / "data" / "subscriptions.json"
    favorite_events_file: Path = BASE_DIR / "data" / "favorite_events.json"
    event_tokens_file: Path = BASE_DIR / "data" / "event_tokens.json"

    @property
    def admin_ids(self) -> set[int]:
        return {
            int(part.strip())
            for part in self.admin_telegram_ids.split(",")
            if part.strip().isdigit()
        }


settings = BotSettings()
