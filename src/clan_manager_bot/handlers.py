from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from telegram import ChatPermissions, Update
from telegram.ext import Application, CallbackContext, CommandHandler, ContextTypes, MessageHandler, filters

from .analytics import build_admin_potential_report, build_chat_health_report, build_newbie_templates
from .config import Settings
from .db import Database
from .hermes_client import HermesClient, HermesUnavailableError
from .moderation import ModerationPolicy
from .scoring import CandidateScorer, ScoringInputs

logger = logging.getLogger(__name__)


def _short(text: str, limit: int = 220) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _as_int(value: object, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_text(value: object, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _looks_like_username_ref(value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return False
    if text.startswith("@"):
        text = text[1:]
    return text.replace("_", "").isalnum()


class BotRuntime:
    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db
        self.scorer = CandidateScorer()
        self.hermes = HermesClient(settings)
        self.moderation = ModerationPolicy(settings)

    def is_admin(self, user_id: int | None) -> bool:
        return bool(user_id and user_id in self.settings.admin_id_list)

    async def admin_guard(self, update: Update) -> bool:
        user_id = update.effective_user.id if update.effective_user else None
        if self.is_admin(user_id):
            return True
        if update.effective_message:
            await update.effective_message.reply_text("Недостаточно прав.")
        return False

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.admin_guard(update):
            return
        await update.effective_message.reply_text(
            "Умный менеджер клана активен. Команды: /report, /templates, /warn, /mute, /kick, /ban"
        )

    async def cmd_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.admin_guard(update):
            return
        items = await self.db.fetch_member_analytics(days=7)
        admin_report = build_admin_potential_report(items)
        chat_report = build_chat_health_report(items)
        text = await self.hermes.build_clan_report(items, f"{admin_report}\n\n{chat_report}")
        await update.effective_message.reply_text(text)

    async def cmd_templates(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.admin_guard(update):
            return
        seeds = await self.db.fetch_newbie_templates_seed(days=30)
        templates = await self.hermes.build_newbie_templates(seeds, build_newbie_templates(seeds))
        lines = ["🧩 Шаблоны для новичков:"]
        for i, template in enumerate(templates, start=1):
            lines.append(f"{i}. {template}")
        await update.effective_message.reply_text("\n".join(lines))

    async def _extract_target_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
        msg = update.effective_message
        if msg and msg.reply_to_message and msg.reply_to_message.from_user:
            return msg.reply_to_message.from_user.id
        if context.args:
            try:
                return int(context.args[0])
            except ValueError:
                if _looks_like_username_ref(context.args[0]):
                    return await self.db.resolve_user_id_by_username(context.args[0])
                return None
        return None

    async def cmd_warn(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.admin_guard(update):
            return

        user_id = await self._extract_target_user(update, context)
        if not user_id:
            await update.effective_message.reply_text("Использование: /warn <user_id|@username> <причина> или ответом на сообщение")
            return

        reason = " ".join(context.args[1:]).strip() if len(context.args) > 1 else "Нарушение правил"
        count = await self.db.add_warning(user_id=user_id, reason=reason, actor_id=update.effective_user.id)
        await update.effective_message.reply_text(f"⚠️ Warn выдан. User={user_id}, count={count}")

        action = self.moderation.decide_escalation(count)
        if action:
            await self._apply_auto_action(update, user_id, action.action, action.reason, action.until_at)

    async def cmd_mute(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.admin_guard(update):
            return

        user_id = await self._extract_target_user(update, context)
        if not user_id:
            await update.effective_message.reply_text("Использование: /mute <user_id|@username> <минуты>")
            return

        minutes = self.settings.short_mute_minutes
        if len(context.args) > 1:
            try:
                minutes = max(1, int(context.args[1]))
            except ValueError:
                await update.effective_message.reply_text("Минуты должны быть числом.")
                return

        until_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        await self._mute_user(update, user_id, until_at, f"Ручной мут на {minutes}м")

    async def cmd_kick(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.admin_guard(update):
            return

        user_id = await self._extract_target_user(update, context)
        if not user_id:
            await update.effective_message.reply_text("Использование: /kick <user_id|@username>")
            return

        await self._kick_user(update, user_id, "Ручной кик")

    async def cmd_ban(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.admin_guard(update):
            return

        user_id = await self._extract_target_user(update, context)
        if not user_id:
            await update.effective_message.reply_text("Использование: /ban <user_id|@username>")
            return

        await self._ban_user(update, user_id, "Ручной перманентный бан")

    async def _apply_auto_action(
        self,
        update: Update,
        user_id: int,
        action: str,
        reason: str,
        until_at: datetime | None,
    ) -> None:
        if action == "mute" and until_at:
            await self._mute_user(update, user_id, until_at, reason)
        elif action == "kick":
            await self._kick_user(update, user_id, reason)
        elif action == "ban":
            await self._ban_user(update, user_id, reason)

    async def _mute_user(self, update: Update, user_id: int, until_at: datetime, reason: str) -> None:
        chat_id = update.effective_chat.id if update.effective_chat else self.settings.public_chat_id
        await update.get_bot().restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until_at,
        )
        actor_id = update.effective_user.id if update.effective_user else 0
        await self.db.set_mute(user_id, until_at, reason, actor_id)
        await update.effective_message.reply_text(f"🔇 Мут выдан: {user_id} до {until_at.isoformat()}")

    async def _kick_user(self, update: Update, user_id: int, reason: str) -> None:
        chat_id = update.effective_chat.id if update.effective_chat else self.settings.public_chat_id
        await update.get_bot().ban_chat_member(chat_id=chat_id, user_id=user_id, until_date=int((datetime.now(timezone.utc) + timedelta(seconds=31)).timestamp()))
        await update.get_bot().unban_chat_member(chat_id=chat_id, user_id=user_id, only_if_banned=True)
        actor_id = update.effective_user.id if update.effective_user else 0
        await self.db.set_ban(user_id, reason, actor_id, permanent=False)
        await update.effective_message.reply_text(f"👢 Пользователь кикнут: {user_id}")

    async def _ban_user(self, update: Update, user_id: int, reason: str) -> None:
        chat_id = update.effective_chat.id if update.effective_chat else self.settings.public_chat_id
        await update.get_bot().ban_chat_member(chat_id=chat_id, user_id=user_id)
        actor_id = update.effective_user.id if update.effective_user else 0
        await self.db.set_ban(user_id, reason, actor_id, permanent=True)
        await update.effective_message.reply_text(f"⛔ Пользователь забанен: {user_id}")

    async def on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        if not msg or not msg.from_user or not msg.text:
            return

        user_id = msg.from_user.id
        username = msg.from_user.username or msg.from_user.full_name or str(user_id)
        text = msg.text

        is_newbie = any(token in text.lower() for token in ("как вступ", "нович", "анкет", "правила"))
        await self.db.log_message(
            chat_id=msg.chat.id,
            user_id=user_id,
            username=username,
            text=text,
            is_newbie=is_newbie,
        )

        lower = text.lower()
        if any(token in lower for token in ("спасибо", "благодар", "thanks")) and msg.reply_to_message and msg.reply_to_message.from_user:
            helper = msg.reply_to_message.from_user
            helper_name = helper.username or helper.full_name or str(helper.id)
            await self.db.flag_helpful(helper.id, helper_name)

        toxic, spam = self.moderation.detect_flags(text)
        if toxic:
            await self.db.flag_toxicity(user_id, username)

        if toxic or spam:
            reason = "Автофлаг: токсичность" if toxic else "Автофлаг: спам"
            count = await self.db.add_warning(user_id=user_id, reason=reason, actor_id=0)
            await context.bot.send_message(
                chat_id=self.settings.admin_chat_id,
                text=f"🚨 Авто-модерация: user={user_id} @{username}\nПричина: {reason}\nWarnings: {count}\nТекст: {_short(text)}",
            )
            action = self.moderation.decide_escalation(count)
            if action and update.effective_chat:
                try:
                    if action.action == "mute" and action.until_at:
                        await context.bot.restrict_chat_member(
                            chat_id=update.effective_chat.id,
                            user_id=user_id,
                            permissions=ChatPermissions(can_send_messages=False),
                            until_date=action.until_at,
                        )
                        await self.db.set_mute(user_id, action.until_at, action.reason, actor_id=0)
                    elif action.action == "kick":
                        now = datetime.now(timezone.utc)
                        await context.bot.ban_chat_member(
                            chat_id=update.effective_chat.id,
                            user_id=user_id,
                            until_date=int((now + timedelta(seconds=31)).timestamp()),
                        )
                        await context.bot.unban_chat_member(update.effective_chat.id, user_id, only_if_banned=True)
                        await self.db.set_ban(user_id, action.reason, actor_id=0, permanent=False)
                    elif action.action == "ban":
                        await context.bot.ban_chat_member(chat_id=update.effective_chat.id, user_id=user_id)
                        await self.db.set_ban(user_id, action.reason, actor_id=0, permanent=True)
                except Exception:
                    logger.exception("Failed to apply automatic moderation action")
                    await context.bot.send_message(
                        chat_id=self.settings.admin_chat_id,
                        text=f"Ошибка авто-модерации для user={user_id}. Проверь права бота в чате.",
                    )

    async def process_applications_job(self, context: CallbackContext) -> None:
        bot = context.bot
        records = await self.db.fetch_new_applications()
        for row in records:
            payload = ScoringInputs(
                application_id=_as_int(row.get("id")),
                user_id=_as_int(row.get("user_id")),
                username=_as_text(row.get("username")),
                experience_text=_as_text(row.get("experience_text")),
                activity_text=_as_text(row.get("activity_text")),
                about_text=_as_text(row.get("about_text")),
                warnings_count=_as_int(row.get("warnings_count")),
            )
            local_result = self.scorer.score(payload)
            try:
                result = await self.hermes.score_candidate(payload, local_result)
            except HermesUnavailableError as exc:
                await bot.send_message(
                    chat_id=self.settings.admin_chat_id,
                    text=f"Анкета @{payload.username or payload.user_id} не оценена: {exc}",
                )
                continue
            await self.db.save_application_score(
                application_id=result.application_id,
                user_id=result.user_id,
                username=result.username,
                score=result.score,
                grade=result.grade,
                verdict=result.verdict,
                reasons=result.reasons,
                risks=result.risks,
            )

            text = (
                f"🧾 Новая анкета: @{result.username or result.user_id}\n"
                f"Score: {result.score}% ({result.grade})\n"
                f"Вердикт: {result.verdict}\n"
                f"Причины:\n- " + "\n- ".join(result.reasons[:4]) + "\n"
                f"Риски:\n- " + "\n- ".join(result.risks[:3])
            )
            await bot.send_message(chat_id=self.settings.admin_chat_id, text=text)

    async def process_events_job(self, context: CallbackContext) -> None:
        bot = context.bot
        reminders = await self.db.fetch_upcoming_events()
        for event in reminders:
            text = (
                f"📣 Напоминание клана\n"
                f"{event.title}\n"
                f"Старт: {event.starts_at.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
                f"До старта: {event.remind_before_min} мин\n"
                f"{event.payload}"
            )
            await bot.send_message(chat_id=self.settings.public_chat_id, text=text)
            await self.db.mark_event_reminded(event.event_id)

    async def process_daily_report_job(self, context: CallbackContext) -> None:
        bot = context.bot
        items = await self.db.fetch_member_analytics(days=7)
        admin_report = build_admin_potential_report(items)
        chat_report = build_chat_health_report(items)
        hermes_report = await self.hermes.build_clan_report(items, f"{admin_report}\n\n{chat_report}")

        seeds = await self.db.fetch_newbie_templates_seed(days=30)
        templates = await self.hermes.build_newbie_templates(seeds, build_newbie_templates(seeds))
        templates_block = "\n".join(f"- {x}" for x in templates[:4])

        await bot.send_message(chat_id=self.settings.admin_chat_id, text=hermes_report)
        await bot.send_message(chat_id=self.settings.admin_chat_id, text=f"🧩 Шаблоны ответов новичкам:\n{templates_block}")

    async def on_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.exception("Unhandled telegram bot error", exc_info=context.error)
        try:
            await context.bot.send_message(
                chat_id=self.settings.admin_chat_id,
                text=f"Ошибка в боте-менеджере:\n{_short(str(context.error), 800)}",
            )
        except Exception:
            logger.exception("Failed to notify admin chat about bot error")

    def register_handlers(self, app: Application) -> None:
        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(CommandHandler("report", self.cmd_report))
        app.add_handler(CommandHandler("templates", self.cmd_templates))

        app.add_handler(CommandHandler("warn", self.cmd_warn))
        app.add_handler(CommandHandler("mute", self.cmd_mute))
        app.add_handler(CommandHandler("kick", self.cmd_kick))
        app.add_handler(CommandHandler("ban", self.cmd_ban))

        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_message))
        app.add_error_handler(self.on_error)

    def register_jobs(self, app: Application) -> None:
        jq = app.job_queue
        if not jq:
            return

        jq.run_repeating(self.process_applications_job, interval=self.settings.application_scan_interval_min * 60, first=15)
        jq.run_repeating(self.process_events_job, interval=self.settings.event_scan_interval_min * 60, first=20)

        now = datetime.now(timezone.utc)
        report_time = now.replace(
            hour=self.settings.analytics_report_hour_utc,
            minute=0,
            second=0,
            microsecond=0,
        )
        if report_time <= now:
            report_time += timedelta(days=1)
        first_in = int((report_time - now).total_seconds())
        jq.run_repeating(self.process_daily_report_job, interval=24 * 60 * 60, first=max(30, first_in))
