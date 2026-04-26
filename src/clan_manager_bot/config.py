from __future__ import annotations

from functools import lru_cache
import re
from typing import Optional
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = Field(alias="BOT_TOKEN")
    admin_chat_id: int = Field(alias="ADMIN_CHAT_ID")
    public_chat_id: int = Field(alias="PUBLIC_CHAT_ID")
    admin_ids: str = Field(alias="ADMIN_IDS")

    database_url: str = Field(alias="DATABASE_URL")
    source_database_url: Optional[str] = Field(default=None, alias="SOURCE_DATABASE_URL")

    source_applications_table: str = Field(default="applications", alias="SOURCE_APPLICATIONS_TABLE")
    source_events_table: str = Field(default="schedule", alias="SOURCE_EVENTS_TABLE")
    source_messages_table: str = Field(default="chat_messages", alias="SOURCE_MESSAGES_TABLE")
    source_activity_table: str = Field(default="user_events", alias="SOURCE_ACTIVITY_TABLE")

    source_applications_sql: str = Field(default="", alias="SOURCE_APPLICATIONS_SQL")
    source_events_sql: str = Field(default="", alias="SOURCE_EVENTS_SQL")
    source_analytics_sql: str = Field(default="", alias="SOURCE_ANALYTICS_SQL")
    source_schedule_timezone: str = Field(default="Europe/Moscow", alias="SOURCE_SCHEDULE_TIMEZONE")

    warns_for_auto_ban: int = Field(default=5, alias="WARNS_FOR_AUTO_BAN")
    warns_for_kick: int = Field(default=4, alias="WARNS_FOR_KICK")
    warns_for_day_mute: int = Field(default=3, alias="WARNS_FOR_DAY_MUTE")
    warns_for_short_mute: int = Field(default=2, alias="WARNS_FOR_SHORT_MUTE")
    short_mute_minutes: int = Field(default=60, alias="SHORT_MUTE_MINUTES")
    day_mute_hours: int = Field(default=24, alias="DAY_MUTE_HOURS")

    application_scan_interval_min: int = Field(default=10, alias="APPLICATION_SCAN_INTERVAL_MIN")
    event_scan_interval_min: int = Field(default=5, alias="EVENT_SCAN_INTERVAL_MIN")
    analytics_report_hour_utc: int = Field(default=18, alias="ANALYTICS_REPORT_HOUR_UTC")

    ai_provider: str = Field(default="local", alias="AI_PROVIDER")
    agent_api_base_url: Optional[str] = Field(default=None, alias="AGENT_API_BASE_URL")
    agent_api_key: Optional[str] = Field(default=None, alias="AGENT_API_KEY")
    agent_timeout_seconds: int = Field(default=45, alias="AGENT_TIMEOUT_SECONDS")

    hermes_api_base_url: Optional[str] = Field(default=None, alias="HERMES_API_BASE_URL")
    hermes_api_key: Optional[str] = Field(default=None, alias="HERMES_API_KEY")
    hermes_model: str = Field(default="hermes-agent", alias="HERMES_MODEL")
    hermes_max_tokens: int = Field(default=1200, alias="HERMES_MAX_TOKENS")
    hermes_timeout_seconds: int = Field(default=45, alias="HERMES_TIMEOUT_SECONDS")
    hermes_required: bool = Field(default=True, alias="HERMES_REQUIRED")

    @field_validator("admin_ids", mode="before")
    @classmethod
    def normalize_admin_ids(cls, value: object) -> str:
        if isinstance(value, int):
            return str(value)
        if isinstance(value, (list, tuple, set)):
            return ",".join(str(item) for item in value)
        return str(value)

    @field_validator("admin_ids")
    @classmethod
    def validate_admin_ids(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("ADMIN_IDS cannot be empty")
        for chunk in value.replace(" ", "").split(","):
            if chunk and not chunk.isdigit():
                raise ValueError("ADMIN_IDS must contain Telegram numeric IDs separated by commas")
        return value

    @field_validator(
        "source_applications_table",
        "source_events_table",
        "source_messages_table",
        "source_activity_table",
    )
    @classmethod
    def validate_table_name(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?", value):
            raise ValueError("Table names must be simple SQL identifiers, for example applications or public.applications")
        return value

    @field_validator("application_scan_interval_min", "event_scan_interval_min")
    @classmethod
    def validate_positive_interval(cls, value: int) -> int:
        if value < 1:
            raise ValueError("Scheduler intervals must be at least 1 minute")
        return value

    @field_validator("analytics_report_hour_utc")
    @classmethod
    def validate_report_hour(cls, value: int) -> int:
        if not 0 <= value <= 23:
            raise ValueError("ANALYTICS_REPORT_HOUR_UTC must be between 0 and 23")
        return value

    @field_validator("source_schedule_timezone")
    @classmethod
    def validate_schedule_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value

    @field_validator("hermes_max_tokens")
    @classmethod
    def validate_hermes_max_tokens(cls, value: int) -> int:
        if value < 128:
            raise ValueError("HERMES_MAX_TOKENS must be at least 128")
        return value

    @field_validator("hermes_timeout_seconds")
    @classmethod
    def validate_hermes_timeout(cls, value: int) -> int:
        if value < 5:
            raise ValueError("HERMES_TIMEOUT_SECONDS must be at least 5")
        return value

    @field_validator("agent_timeout_seconds")
    @classmethod
    def validate_agent_timeout(cls, value: int) -> int:
        if value < 5:
            raise ValueError("AGENT_TIMEOUT_SECONDS must be at least 5")
        return value

    @field_validator("ai_provider")
    @classmethod
    def validate_ai_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"local", "hermes", "agent_api"}:
            raise ValueError("AI_PROVIDER must be one of: local, hermes, agent_api")
        return normalized

    @property
    def hermes_enabled(self) -> bool:
        return self.ai_provider == "hermes" and bool(self.hermes_api_base_url)

    @property
    def agent_api_enabled(self) -> bool:
        return self.ai_provider == "agent_api" and bool(self.agent_api_base_url)

    @property
    def effective_source_database_url(self) -> str:
        return self.source_database_url or self.database_url

    @property
    def admin_id_list(self) -> list[int]:
        result: list[int] = []
        for chunk in self.admin_ids.replace(" ", "").split(","):
            if not chunk:
                continue
            result.append(int(chunk))
        return result


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
