from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    base_url: str = "http://localhost:8000"
    database_url: str = "sqlite+aiosqlite:///./flight_notifier.db"
    redis_url: str = "redis://localhost:6379/0"

    telegram_bot_token: str = ""
    telegram_webhook_secret: str = "development-webhook-secret"
    telegram_init_data_max_age_seconds: int = 3600
    session_secret: str = "development-session-secret"
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    admin_telegram_ids: list[int] = Field(default_factory=list)

    scraping_enabled: bool = False
    scraper_headless: bool = True
    scraper_timeout_seconds: int = 45
    scraper_min_delay_seconds: float = 2.0

    normal_poll_minutes: int = 15
    urgent_poll_minutes: int = 5
    urgent_window_hours: int = 24
    max_active_alerts_per_user: int = 5
    max_alerts_per_day: int = 30

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("admin_telegram_ids", mode="before")
    @classmethod
    def parse_admins(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(part.strip()) for part in value.split(",") if part.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()

