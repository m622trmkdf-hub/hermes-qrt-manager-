from __future__ import annotations

from clan_manager_bot.config import get_settings


def main() -> None:
    settings = get_settings()
    print("config_ok")
    print(f"admin_chat_id={settings.admin_chat_id}")
    print(f"public_chat_id={settings.public_chat_id}")
    print(f"admin_ids={','.join(str(x) for x in settings.admin_id_list)}")
    print(f"database_url_set={bool(settings.database_url)}")
    print(f"hermes_enabled={settings.hermes_enabled}")
    if settings.hermes_enabled:
        print(f"hermes_api_base_url={settings.hermes_api_base_url}")
        print(f"hermes_model={settings.hermes_model}")
        print(f"hermes_required={settings.hermes_required}")


if __name__ == "__main__":
    main()
