import pytest
from pydantic import ValidationError

from clan_manager_bot.config import Settings


def make_settings(**overrides: object) -> Settings:
    data = {
        "BOT_TOKEN": "x",
        "ADMIN_CHAT_ID": -1001,
        "PUBLIC_CHAT_ID": -1002,
        "ADMIN_IDS": "1,2",
        "DATABASE_URL": "postgresql://u:p@localhost:5432/db",
    }
    data.update(overrides)
    return Settings(**data)


def test_validates_table_names() -> None:
    settings = make_settings(SOURCE_APPLICATIONS_TABLE="public.applications")
    assert settings.source_applications_table == "public.applications"

    with pytest.raises(ValidationError):
        make_settings(SOURCE_APPLICATIONS_TABLE="applications; drop table users")


def test_validates_admin_ids_and_scheduler_values() -> None:
    with pytest.raises(ValidationError):
        make_settings(ADMIN_IDS="1,abc")

    with pytest.raises(ValidationError):
        make_settings(APPLICATION_SCAN_INTERVAL_MIN=0)

    with pytest.raises(ValidationError):
        make_settings(ANALYTICS_REPORT_HOUR_UTC=24)


def test_accepts_numeric_and_list_admin_ids() -> None:
    assert make_settings(ADMIN_IDS=123).admin_id_list == [123]
    assert make_settings(ADMIN_IDS=[1, 2]).admin_id_list == [1, 2]


def test_source_database_defaults_to_main_database() -> None:
    settings = make_settings()
    assert settings.effective_source_database_url == "postgresql://u:p@localhost:5432/db"

    override = make_settings(SOURCE_DATABASE_URL="postgresql://u:p@remote:5432/old_db")
    assert override.effective_source_database_url == "postgresql://u:p@remote:5432/old_db"
