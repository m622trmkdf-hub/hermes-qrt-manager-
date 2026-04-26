from __future__ import annotations

import re
from dataclasses import dataclass

from .models import CandidateScore

TOXIC_WORDS = {
    "идиот",
    "дебил",
    "тупой",
    "лох",
    "ненавижу",
    "shit",
    "fuck",
}

POSITIVE_WORDS = {
    "помогу",
    "ответственный",
    "дисциплина",
    "команда",
    "уважение",
    "готов",
    "help",
    "responsible",
}


@dataclass(slots=True)
class ScoringInputs:
    application_id: int
    user_id: int
    username: str
    experience_text: str
    activity_text: str
    about_text: str
    warnings_count: int


class CandidateScorer:
    """Heuristic AI-like scorer with transparent weights.

    Score formula:
    0.30*A + 0.25*Q + 0.20*R + 0.15*D + 0.10*L - P
    """

    def score(self, data: ScoringInputs) -> CandidateScore:
        exp = data.experience_text.lower()
        activity = data.activity_text.lower()
        about = data.about_text.lower()
        full = f"{exp} {activity} {about}"

        a = self._activity_score(activity)
        q = self._quality_score(full)
        r = self._reputation_score(full, data.warnings_count)
        d = self._discipline_score(data.warnings_count)
        l = self._leadership_score(full)
        p = self._penalty_score(full, data.warnings_count)

        score = round(0.30 * a + 0.25 * q + 0.20 * r + 0.15 * d + 0.10 * l - p)
        score = max(0, min(100, score))

        if score >= 85:
            grade, verdict = "A", "Рекомендован"
        elif score >= 70:
            grade, verdict = "B", "Условно рекомендован"
        else:
            grade, verdict = "C", "Не рекомендован"

        reasons = [
            f"Активность: {a}/100",
            f"Качество общения: {q}/100",
            f"Репутация: {r}/100",
            f"Дисциплина: {d}/100",
            f"Лидерский потенциал: {l}/100",
        ]

        risks: list[str] = []
        if data.warnings_count > 0:
            risks.append(f"Есть предупреждения: {data.warnings_count}")
        if self._contains_toxic(full):
            risks.append("В анкете есть токсичные/агрессивные формулировки")
        if len(full.strip()) < 60:
            risks.append("Анкета слишком короткая, данных мало")
        if not risks:
            risks.append("Критичных рисков не выявлено")

        return CandidateScore(
            application_id=data.application_id,
            user_id=data.user_id,
            username=data.username,
            score=score,
            grade=grade,
            verdict=verdict,
            reasons=reasons,
            risks=risks,
        )

    def _activity_score(self, text: str) -> int:
        hours = re.findall(r"(\d{1,2})\s*(?:ч|час|hours?)", text)
        days = re.findall(r"(\d)\s*(?:дн|days?)", text)
        base = 45
        if hours:
            h = max(int(x) for x in hours)
            base += min(40, h * 3)
        if days:
            d = max(int(x) for x in days)
            base += min(15, d * 2)
        if "ежеднев" in text or "daily" in text:
            base += 10
        return min(100, base)

    def _quality_score(self, text: str) -> int:
        size = len(text.split())
        base = 35 + min(35, size)
        positives = sum(1 for w in POSITIVE_WORDS if w in text)
        base += min(20, positives * 5)
        if self._contains_toxic(text):
            base -= 25
        return max(0, min(100, base))

    def _reputation_score(self, text: str, warnings_count: int) -> int:
        base = 70
        if "конфликт" in text or "toxic" in text:
            base -= 20
        base -= warnings_count * 8
        return max(0, min(100, base))

    def _discipline_score(self, warnings_count: int) -> int:
        return max(0, 100 - warnings_count * 22)

    def _leadership_score(self, text: str) -> int:
        base = 40
        leadership_tokens = ["организ", "помога", "веду", "лидер", "mentor", "support"]
        bonus = sum(10 for token in leadership_tokens if token in text)
        return min(100, base + bonus)

    def _penalty_score(self, text: str, warnings_count: int) -> int:
        penalty = warnings_count * 3
        if self._contains_toxic(text):
            penalty += 10
        if len(text.split()) < 12:
            penalty += 5
        return min(30, penalty)

    def _contains_toxic(self, text: str) -> bool:
        return any(word in text for word in TOXIC_WORDS)

