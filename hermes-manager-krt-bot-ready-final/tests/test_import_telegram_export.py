from datetime import timezone

from scripts.import_telegram_export import export_messages_to_rows, normalize_text, parse_user_id, settings_for_import


def test_normalize_text_handles_telegram_rich_text() -> None:
    assert normalize_text(["hello ", {"type": "bold", "text": "world"}]) == "hello world"
    assert normalize_text(" plain ") == "plain"


def test_parse_user_id() -> None:
    assert parse_user_id("user7677385267") == 7677385267
    assert parse_user_id(None) == 0


def test_export_messages_to_rows_skips_service_and_empty_messages() -> None:
    payload = {
        "id": 123,
        "messages": [
            {
                "id": 1,
                "type": "message",
                "date": "2025-09-24T00:32:32",
                "from": "Player",
                "from_id": "user111",
                "text": ["как вступить ", {"type": "bold", "text": "в клан"}],
            },
            {"id": 2, "type": "service", "date": "2025-09-24T00:32:32", "text": ""},
            {"id": 3, "type": "message", "date": "2025-09-24T00:32:32", "from_id": "user222", "text": ""},
        ],
    }

    rows = export_messages_to_rows(payload)
    assert len(rows) == 1
    assert rows[0]["chat_id"] == 123
    assert rows[0]["user_id"] == 111
    assert rows[0]["is_newbie"] is True
    assert rows[0]["created_at"].tzinfo is timezone.utc


def test_settings_for_import_only_needs_database_url() -> None:
    settings = settings_for_import("postgresql://u:p@localhost:5432/db")
    assert settings.database_url == "postgresql://u:p@localhost:5432/db"
    assert settings.bot_token == "import-only"
