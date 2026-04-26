from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clan_manager_bot.config import get_settings
from clan_manager_bot.config import Settings
from clan_manager_bot.db import Database


NEWBIE_MARKERS = ("как вступ", "нович", "анкет", "правила", "заявк", "распис", "когда сбор")


def normalize_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text", "")))
        return "".join(parts).strip()
    return ""


def parse_user_id(value: object) -> int:
    match = re.search(r"(\d+)", str(value or ""))
    return int(match.group(1)) if match else 0


def parse_export_date(value: object) -> datetime:
    raw = str(value or "")
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def export_messages_to_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    chat_id = int(payload.get("id") or 0)
    rows: list[dict[str, Any]] = []
    for message in payload.get("messages", []):
        if message.get("type") != "message":
            continue

        text = normalize_text(message.get("text"))
        if not text:
            continue

        user_id = parse_user_id(message.get("from_id"))
        if user_id == 0:
            continue

        lowered = text.lower()
        rows.append(
            {
                "source": "telegram_export",
                "source_message_id": int(message["id"]),
                "chat_id": chat_id,
                "user_id": user_id,
                "username": str(message.get("from") or user_id),
                "text": text[:4000],
                "is_newbie": any(marker in lowered for marker in NEWBIE_MARKERS),
                "created_at": parse_export_date(message.get("date")),
            }
        )
    return rows


def settings_for_import(database_url: str | None) -> Settings:
    if not database_url:
        return get_settings()
    return Settings(
        BOT_TOKEN="import-only",
        ADMIN_CHAT_ID=0,
        PUBLIC_CHAT_ID=0,
        ADMIN_IDS="0",
        DATABASE_URL=database_url,
    )


async def run(path: Path, database_url: str | None = None) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = export_messages_to_rows(data)
    settings = settings_for_import(database_url)
    db = Database(settings)
    await db.connect()
    try:
        await db.init_schema()
        imported = await db.import_messages(rows)
    finally:
        await db.close()
    print(f"prepared={len(rows)}")
    print(f"imported={imported}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Telegram JSON export into manager analytics tables")
    parser.add_argument("path", type=Path, help="Path to Telegram result.json")
    parser.add_argument("--database-url", help="Supabase/Postgres URL. If omitted, DATABASE_URL is read from .env")
    args = parser.parse_args()
    asyncio.run(run(args.path, args.database_url))


if __name__ == "__main__":
    main()
