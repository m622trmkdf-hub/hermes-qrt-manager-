from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from .config import Settings
from .models import CandidateScore, MemberAnalytics
from .scoring import ScoringInputs

logger = logging.getLogger(__name__)


class HermesUnavailableError(RuntimeError):
    """Raised when Hermes is required but not configured or unavailable."""


class HermesClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def score_candidate(self, data: ScoringInputs, fallback: CandidateScore) -> CandidateScore:
        if not self.settings.hermes_enabled:
            if self.settings.hermes_required:
                raise HermesUnavailableError("HERMES_API_BASE_URL is required for candidate scoring")
            return fallback

        try:
            payload = self._build_payload(data, fallback)
            headers = {"Content-Type": "application/json"}
            if self.settings.hermes_api_key:
                headers["Authorization"] = f"Bearer {self.settings.hermes_api_key}"

            base_url = self.settings.hermes_api_base_url.rstrip("/")
            async with httpx.AsyncClient(timeout=self.settings.hermes_timeout_seconds) as client:
                response = await client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
                response.raise_for_status()
                body = response.json()

            content = body["choices"][0]["message"]["content"]
            parsed = parse_hermes_candidate_json(content)
            return merge_hermes_candidate_score(data, fallback, parsed)
        except Exception:
            logger.exception("Hermes Agent candidate scoring failed; using local fallback")
            if self.settings.hermes_required:
                raise HermesUnavailableError("Hermes Agent candidate scoring failed")
            return fallback

    async def build_clan_report(self, items: list[MemberAnalytics], fallback: str) -> str:
        if not self.settings.hermes_enabled:
            if self.settings.hermes_required:
                return self._missing_hermes_text()
            return self._fallback_text(fallback)

        try:
            payload = self._build_clan_report_payload(items)
            content = await self._chat_completion(payload)
            return _clean_report_text(content)
        except Exception:
            logger.exception("Hermes Agent clan report failed; using local fallback")
            if self.settings.hermes_required:
                return self._hermes_failed_text()
            return self._fallback_text(fallback)

    async def build_newbie_templates(self, messages: list[str], fallback: list[str]) -> list[str]:
        if not self.settings.hermes_enabled:
            if self.settings.hermes_required:
                return [self._missing_hermes_text()]
            return fallback

        try:
            payload = self._build_templates_payload(messages)
            content = await self._chat_completion(payload)
            parsed = parse_hermes_candidate_json(content)
            templates = _clean_text_list(parsed.get("templates"))
            return templates[:8] or fallback
        except Exception:
            logger.exception("Hermes Agent templates generation failed; using local fallback")
            if self.settings.hermes_required:
                return [self._hermes_failed_text()]
            return [self._fallback_text("\n".join(fallback))]

    async def _chat_completion(self, payload: dict[str, Any]) -> str:
        headers = {"Content-Type": "application/json"}
        if self.settings.hermes_api_key:
            headers["Authorization"] = f"Bearer {self.settings.hermes_api_key}"

        base_url = self.settings.hermes_api_base_url.rstrip("/")
        async with httpx.AsyncClient(timeout=self.settings.hermes_timeout_seconds) as client:
            response = await client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()
        return str(body["choices"][0]["message"]["content"])

    def _missing_hermes_text(self) -> str:
        return "Hermes Agent не настроен. Заполни HERMES_API_BASE_URL и HERMES_API_KEY в Railway Variables."

    def _hermes_failed_text(self) -> str:
        return "Hermes Agent недоступен или вернул ошибку. Проверь Railway service Hermes, API_SERVER_KEY и URL."

    def _fallback_text(self, fallback: str) -> str:
        return f"Hermes Agent недоступен. Локальный черновик:\n{fallback}"

    def _build_payload(self, data: ScoringInputs, fallback: CandidateScore) -> dict[str, Any]:
        return {
            "model": self.settings.hermes_model,
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Ты AI-офицер клана Car Parking Multiplayer 2. "
                        "Оцени анкету кандидата строго и коротко. "
                        "Ответь только JSON без markdown."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task": "candidate_application_score",
                            "scale": "0-100",
                            "local_fallback_score": fallback.score,
                            "candidate": {
                                "application_id": data.application_id,
                                "user_id": data.user_id,
                                "username": data.username,
                                "experience_text": data.experience_text,
                                "activity_text": data.activity_text,
                                "about_text": data.about_text,
                                "warnings_count": data.warnings_count,
                            },
                            "required_json": {
                                "score": "integer 0..100",
                                "verdict": "Рекомендован | Условно рекомендован | Не рекомендован",
                                "reasons": ["3-5 short reasons"],
                                "risks": ["1-4 short risks"],
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        }

    def _build_clan_report_payload(self, items: list[MemberAnalytics]) -> dict[str, Any]:
        return {
            "model": self.settings.hermes_model,
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Ты AI-аналитик клана Car Parking Multiplayer 2. "
                        "Дай понятный отчет для админов: активность, дисциплина, "
                        "кандидаты в админы, риски и конкретные действия. "
                        "Пиши по-русски, коротко, без markdown-таблиц."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task": "weekly_clan_chat_analytics",
                            "members": [member_analytics_to_dict(item) for item in items[:100]],
                            "required_sections": [
                                "summary",
                                "top_admin_candidates",
                                "activity_risks",
                                "discipline_risks",
                                "recommended_actions",
                            ],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        }

    def _build_templates_payload(self, messages: list[str]) -> dict[str, Any]:
        return {
            "model": self.settings.hermes_model,
            "temperature": 0.3,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Ты помощник админов клана Car Parking Multiplayer 2. "
                        "На основе вопросов новичков сделай готовые шаблоны ответов. "
                        "Ответь только JSON без markdown."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task": "newbie_reply_templates",
                            "messages": messages[:200],
                            "required_json": {"templates": ["4-8 short ready-to-send replies"]},
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        }


def parse_hermes_candidate_json(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def member_analytics_to_dict(item: MemberAnalytics) -> dict[str, Any]:
    return {
        "user_id": item.user_id,
        "username": item.username,
        "messages_count": item.messages_count,
        "active_days": item.active_days,
        "warnings_count": item.warnings_count,
        "helpful_answers": item.helpful_answers,
        "toxicity_flags": item.toxicity_flags,
    }


def merge_hermes_candidate_score(
    data: ScoringInputs,
    fallback: CandidateScore,
    parsed: dict[str, Any],
) -> CandidateScore:
    score = _clamp_int(parsed.get("score"), fallback.score)
    verdict = str(parsed.get("verdict") or fallback.verdict)
    if verdict not in {"Рекомендован", "Условно рекомендован", "Не рекомендован"}:
        verdict = fallback.verdict

    if score >= 85:
        grade = "A"
    elif score >= 70:
        grade = "B"
    else:
        grade = "C"

    reasons = _clean_text_list(parsed.get("reasons")) or fallback.reasons
    risks = _clean_text_list(parsed.get("risks")) or fallback.risks
    reasons = ["Hermes Agent: оценка по анкете и правилам клана", *reasons[:5]]

    return CandidateScore(
        application_id=data.application_id,
        user_id=data.user_id,
        username=data.username,
        score=score,
        grade=grade,
        verdict=verdict,
        reasons=reasons[:6],
        risks=risks[:4],
    )


def _clamp_int(value: object, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(0, min(100, number))


def _clean_text_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            result.append(text[:180])
    return result


def _clean_report_text(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:text|markdown)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    if len(text) > 3900:
        text = text[:3890].rstrip() + "\n..."
    return f"Hermes Agent analytics\n{text}"
