from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .config import Settings

TOXIC_PATTERNS = (
    "идиот",
    "дебил",
    "нахер",
    "fuck",
    "retard",
)

SPAM_PATTERNS = (
    "http://",
    "https://",
    "t.me/",
    "joinchat",
)


@dataclass(slots=True)
class AutoAction:
    action: str
    reason: str
    until_at: datetime | None = None


class ModerationPolicy:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def detect_flags(self, text: str) -> tuple[bool, bool]:
        lowered = text.lower()
        toxic = any(token in lowered for token in TOXIC_PATTERNS)
        spam = any(token in lowered for token in SPAM_PATTERNS)
        repeated = len(lowered) > 60 and lowered.count("!") >= 6
        return toxic, spam or repeated

    def decide_escalation(self, warnings_count: int) -> AutoAction | None:
        if warnings_count >= self.settings.warns_for_auto_ban:
            return AutoAction(action="ban", reason="Автобан: превышен лимит предупреждений")

        if warnings_count >= self.settings.warns_for_kick:
            return AutoAction(action="kick", reason="Автокик: превышен лимит предупреждений")

        if warnings_count >= self.settings.warns_for_day_mute:
            until_at = datetime.now(timezone.utc) + timedelta(hours=self.settings.day_mute_hours)
            return AutoAction(
                action="mute",
                reason=f"Автомут на {self.settings.day_mute_hours}ч: превышен лимит предупреждений",
                until_at=until_at,
            )

        if warnings_count >= self.settings.warns_for_short_mute:
            until_at = datetime.now(timezone.utc) + timedelta(minutes=self.settings.short_mute_minutes)
            return AutoAction(
                action="mute",
                reason=f"Автомут на {self.settings.short_mute_minutes}м: предупреждения",
                until_at=until_at,
            )

        return None

