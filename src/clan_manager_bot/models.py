from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class CandidateScore:
    application_id: int
    user_id: int
    username: str
    score: int
    grade: str
    verdict: str
    reasons: list[str]
    risks: list[str]


@dataclass(slots=True)
class ModerationThresholds:
    short_mute_at: int
    day_mute_at: int
    kick_at: int
    ban_at: int


@dataclass(slots=True)
class EventReminder:
    event_id: int
    title: str
    starts_at: datetime
    remind_before_min: int
    payload: str


@dataclass(slots=True)
class MemberAnalytics:
    user_id: int
    username: str
    messages_count: int
    active_days: int
    warnings_count: int
    helpful_answers: int
    toxicity_flags: int
