from __future__ import annotations

from collections import Counter

from .models import MemberAnalytics


def admin_potential_score(item: MemberAnalytics) -> tuple[int, str, list[str], list[str]]:
    # A: activity, Q: quality, R: reputation, D: discipline, L: leadership, P: penalties
    activity = min(100, item.active_days * 12 + min(40, item.messages_count // 5))
    quality = min(100, 30 + item.helpful_answers * 6 + min(30, item.messages_count // 10))
    reputation = max(0, 85 - item.toxicity_flags * 12 - item.warnings_count * 10)
    discipline = max(0, 100 - item.warnings_count * 22)
    leadership = min(100, 20 + item.helpful_answers * 8)

    penalty = min(30, item.toxicity_flags * 4 + max(0, item.warnings_count - 1) * 3)

    score = round(0.30 * activity + 0.25 * quality + 0.20 * reputation + 0.15 * discipline + 0.10 * leadership - penalty)
    score = max(0, min(100, score))

    if score >= 85:
        grade = "A"
    elif score >= 70:
        grade = "B"
    else:
        grade = "C"

    reasons = [
        f"Активность: {activity}",
        f"Качество: {quality}",
        f"Репутация: {reputation}",
    ]
    risks = []
    if item.warnings_count > 0:
        risks.append(f"Предупреждения: {item.warnings_count}")
    if item.toxicity_flags > 0:
        risks.append(f"Токсичность/конфликты: {item.toxicity_flags}")
    if not risks:
        risks.append("Явных рисков не выявлено")

    return score, grade, reasons, risks


def build_admin_potential_report(items: list[MemberAnalytics]) -> str:
    if not items:
        return "📊 Отчет по кандидатам: пока недостаточно данных."

    scored: list[tuple[int, str, MemberAnalytics, list[str], list[str]]] = []
    for item in items:
        score, grade, reasons, risks = admin_potential_score(item)
        scored.append((score, grade, item, reasons, risks))

    scored.sort(key=lambda x: x[0], reverse=True)

    lines = ["📊 Кандидаты в админы (7 дней)", ""]
    for idx, (score, grade, item, reasons, risks) in enumerate(scored[:10], start=1):
        lines.append(f"{idx}. @{item.username or item.user_id} — {score} ({grade})")
        lines.append(f"   Причины: {', '.join(reasons[:3])}")
        lines.append(f"   Риски: {', '.join(risks[:2])}")

    promote = [f"@{i.username}" for s, g, i, _, _ in scored if g == "A"][:3]
    reserve = [f"@{i.username}" for s, g, i, _, _ in scored if g == "B"][:3]

    lines.append("")
    lines.append(f"✅ На повышение: {', '.join(promote) if promote else 'нет'}")
    lines.append(f"⚠️ В резерв: {', '.join(reserve) if reserve else 'нет'}")
    return "\n".join(lines)


def build_chat_health_report(items: list[MemberAnalytics]) -> str:
    if not items:
        return "📈 Аналитика чата: данных пока нет."

    total_messages = sum(i.messages_count for i in items)
    total_warnings = sum(i.warnings_count for i in items)
    total_toxic = sum(i.toxicity_flags for i in items)
    top_active = sorted(items, key=lambda x: x.messages_count, reverse=True)[:5]

    lines = [
        "📈 Недельная аналитика чата",
        f"Сообщений: {total_messages}",
        f"Предупреждений: {total_warnings}",
        f"Конфликтных флагов: {total_toxic}",
        "",
        "Топ активности:",
    ]

    for i, member in enumerate(top_active, start=1):
        lines.append(f"{i}. @{member.username or member.user_id} — {member.messages_count} сообщений")

    return "\n".join(lines)


def build_newbie_templates(messages: list[str]) -> list[str]:
    if not messages:
        return [
            "Привет! Добро пожаловать в клан. Напиши свой ник в игре и часовой пояс.",
            "Спасибо за заявку. Проверь, пожалуйста: активность, опыт и готовность к клановым событиям.",
            "Напоминание: уважительное общение обязательно, за токсичность выдаются предупреждения.",
        ]

    intents = Counter()
    for msg in messages:
        low = msg.lower()
        if "как вступ" in low or "заявк" in low:
            intents["join"] += 1
        if "распис" in low or "когда сбор" in low:
            intents["schedule"] += 1
        if "правил" in low or "можно ли" in low:
            intents["rules"] += 1
        if "роль" in low or "админ" in low:
            intents["roles"] += 1

    templates: list[str] = []
    if intents["join"]:
        templates.append("Чтобы вступить: отправь анкету (опыт, онлайн, возраст, ник). Ответ придет в течение суток.")
    if intents["schedule"]:
        templates.append("Расписание клана публикуется в закрепе и бот присылает авто-напоминания перед событиями.")
    if intents["rules"]:
        templates.append("Базовые правила: без спама и оскорблений. За нарушения: варн -> мут -> кик/бан.")
    if intents["roles"]:
        templates.append("Админ-права выдаются по активности, дисциплине и помощи участникам по итогам недельной аналитики.")

    if not templates:
        templates.append("Спасибо за сообщение. Если нужна помощь, опиши вопрос подробнее, и админ подскажет.")

    return templates[:6]

