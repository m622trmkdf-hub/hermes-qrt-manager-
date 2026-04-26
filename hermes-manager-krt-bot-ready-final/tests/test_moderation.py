from clan_manager_bot.config import Settings
from clan_manager_bot.moderation import ModerationPolicy


def make_settings() -> Settings:
    return Settings(
        BOT_TOKEN="x",
        ADMIN_CHAT_ID=-1001,
        PUBLIC_CHAT_ID=-1002,
        ADMIN_IDS="1,2",
        DATABASE_URL="postgresql://u:p@localhost:5432/db",
    )


def test_detect_toxic_and_spam() -> None:
    policy = ModerationPolicy(make_settings())
    toxic, spam = policy.detect_flags("Ты идиот")
    assert toxic is True
    assert spam is False

    toxic2, spam2 = policy.detect_flags("Смотри https://spam.example")
    assert toxic2 is False
    assert spam2 is True


def test_escalation_order() -> None:
    s = make_settings()
    policy = ModerationPolicy(s)

    assert policy.decide_escalation(1) is None
    assert policy.decide_escalation(s.warns_for_short_mute).action == "mute"
    assert policy.decide_escalation(s.warns_for_day_mute).action == "mute"
    assert policy.decide_escalation(s.warns_for_kick).action == "kick"
    assert policy.decide_escalation(s.warns_for_auto_ban).action == "ban"
