from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import asyncpg

from .config import Settings
from .models import EventReminder, MemberAnalytics

logger = logging.getLogger(__name__)


def _normalize_username_ref(value: str) -> str:
    return value.strip().lstrip("@").lower()


def _russian_weekday(value: str) -> int | None:
    mapping = {
        "понедельник": 0,
        "вторник": 1,
        "среда": 2,
        "четверг": 3,
        "пятница": 4,
        "суббота": 5,
        "воскресенье": 6,
    }
    return mapping.get(value.strip().lower())


class Database:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.pool: asyncpg.Pool | None = None
        self.source_pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self.pool = await asyncpg.create_pool(
            self.settings.database_url,
            min_size=1,
            max_size=6,
            statement_cache_size=0,
        )
        if self.settings.effective_source_database_url == self.settings.database_url:
            self.source_pool = self.pool
        else:
            self.source_pool = await asyncpg.create_pool(
                self.settings.effective_source_database_url,
                min_size=1,
                max_size=4,
                statement_cache_size=0,
            )

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()
        if self.source_pool and self.source_pool is not self.pool:
            await self.source_pool.close()

    def _require_manager_pool(self) -> asyncpg.Pool:
        if not self.pool:
            raise RuntimeError("DB pool is not initialized")
        return self.pool

    def _require_source_pool(self) -> asyncpg.Pool:
        if not self.source_pool:
            raise RuntimeError("Source DB pool is not initialized")
        return self.source_pool

    async def init_schema(self) -> None:
        pool = self._require_manager_pool()
        schema = """
        create table if not exists manager_application_scores (
            id bigserial primary key,
            application_id bigint not null,
            user_id bigint not null,
            username text not null default '',
            score int not null,
            grade text not null,
            verdict text not null,
            reasons jsonb not null default '[]'::jsonb,
            risks jsonb not null default '[]'::jsonb,
            created_at timestamptz not null default now(),
            unique(application_id)
        );

        create table if not exists manager_event_state (
            event_id bigint primary key,
            last_reminded_at timestamptz,
            created_at timestamptz not null default now()
        );

        create table if not exists manager_user_strikes (
            user_id bigint primary key,
            warnings_count int not null default 0,
            muted_until timestamptz,
            is_banned bool not null default false,
            updated_at timestamptz not null default now()
        );

        create table if not exists manager_moderation_actions (
            id bigserial primary key,
            user_id bigint not null,
            actor_id bigint not null,
            action text not null,
            reason text not null,
            metadata jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default now()
        );

        create table if not exists manager_admins (
            user_id bigint primary key,
            username text not null default '',
            permissions jsonb not null default '[]'::jsonb,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now()
        );

        create table if not exists manager_chat_metrics_daily (
            day date not null,
            user_id bigint not null,
            username text not null default '',
            messages_count int not null default 0,
            helpful_answers int not null default 0,
            toxicity_flags int not null default 0,
            active_minutes int not null default 0,
            primary key (day, user_id)
        );

        create table if not exists manager_message_log (
            id bigserial primary key,
            source text not null default 'live',
            source_message_id bigint,
            chat_id bigint not null,
            user_id bigint not null,
            username text not null default '',
            text text not null default '',
            is_newbie bool not null default false,
            created_at timestamptz not null default now(),
            unique(source, source_message_id)
        );
        alter table manager_message_log add column if not exists source text not null default 'live';
        alter table manager_message_log add column if not exists source_message_id bigint;
        alter table manager_message_log add column if not exists is_newbie bool not null default false;
        create index if not exists idx_manager_message_log_created_at on manager_message_log(created_at);
        create index if not exists idx_manager_message_log_user_created_at on manager_message_log(user_id, created_at);
        create unique index if not exists idx_manager_message_log_source_message
            on manager_message_log(source, source_message_id);
        """
        async with pool.acquire() as conn:
            await conn.execute(schema)

    async def fetch_new_applications(self) -> list[dict[str, Any]]:
        manager_pool = self._require_manager_pool()
        source_pool = self._require_source_pool()

        if self.settings.source_applications_sql.strip():
            sql = self.settings.source_applications_sql
        else:
            sql = f"""
            with src as (
                select
                    a.*,
                    case
                        when coalesce(a.answers, '') = '' then '[]'::jsonb
                        else a.answers::jsonb
                    end as answers_json
                from {self.settings.source_applications_table} a
            )
            select
                src.id,
                coalesce(src.user_id, 0) as user_id,
                coalesce(src.username, '') as username,
                coalesce(src.answers_json->>4, '') as experience_text,
                coalesce(src.answers_json->>9, '') as activity_text,
                concat_ws(E'\\n',
                    'Имя и ник: ' || coalesce(src.answers_json->>0, ''),
                    'Возраст: ' || coalesce(src.answers_json->>1, ''),
                    'Город: ' || coalesce(src.answers_json->>3, ''),
                    'Игровой стаж: ' || coalesce(src.answers_json->>4, ''),
                    'Кланы ранее: ' || coalesce(src.answers_json->>5, ''),
                    'Помощь клану: ' || coalesce(src.answers_json->>6, ''),
                    'Участие в жизни: ' || coalesce(src.answers_json->>7, ''),
                    'Откуда узнал: ' || coalesce(src.answers_json->>8, ''),
                    'Актив в игре: ' || coalesce(src.answers_json->>9, '')
                ) as about_text,
                0 as warnings_count,
                coalesce(src.status, 'pending') as status,
                src.submitted_at as created_at
            from src
            where coalesce(src.status, 'pending') in ('pending', 'new')
            order by id asc
            limit 200
            """

        async with source_pool.acquire() as conn:
            rows = await conn.fetch(sql)
        if not rows:
            return []

        application_ids = [int(row["id"]) for row in rows]
        async with manager_pool.acquire() as conn:
            scored_rows = await conn.fetch(
                "select application_id from manager_application_scores where application_id = any($1::bigint[])",
                application_ids,
            )
        scored_ids = {int(row["application_id"]) for row in scored_rows}
        return [dict(row) for row in rows if int(row["id"]) not in scored_ids][:50]

    async def save_application_score(
        self,
        application_id: int,
        user_id: int,
        username: str,
        score: int,
        grade: str,
        verdict: str,
        reasons: list[str],
        risks: list[str],
    ) -> None:
        pool = self._require_manager_pool()
        sql = """
        insert into manager_application_scores (
            application_id, user_id, username, score, grade, verdict, reasons, risks
        ) values ($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb)
        on conflict (application_id) do update set
            score = excluded.score,
            grade = excluded.grade,
            verdict = excluded.verdict,
            reasons = excluded.reasons,
            risks = excluded.risks,
            created_at = now()
        """
        async with pool.acquire() as conn:
            await conn.execute(
                sql,
                application_id,
                user_id,
                username,
                score,
                grade,
                verdict,
                json.dumps(reasons, ensure_ascii=False),
                json.dumps(risks, ensure_ascii=False),
            )

    async def fetch_upcoming_events(self) -> list[EventReminder]:
        manager_pool = self._require_manager_pool()
        source_pool = self._require_source_pool()

        if self.settings.source_events_sql.strip():
            sql = self.settings.source_events_sql
        elif self.settings.source_events_table == "schedule":
            return await self._fetch_weekly_schedule_events()
        else:
            sql = f"""
            select
                e.id as event_id,
                coalesce(e.title, 'Event') as title,
                e.starts_at,
                coalesce(e.remind_before_min, 60) as remind_before_min,
                coalesce(e.description, '') as payload
            from {self.settings.source_events_table} e
            where e.starts_at >= now()
              and e.starts_at <= now() + interval '24 hours'
            order by e.starts_at asc
            limit 200
            """

        async with source_pool.acquire() as conn:
            rows = await conn.fetch(sql)

        event_ids = [int(row["event_id"]) for row in rows]
        reminded_by_event_id: dict[int, datetime] = {}
        if event_ids:
            async with manager_pool.acquire() as conn:
                reminded_rows = await conn.fetch(
                    """
                    select event_id, last_reminded_at
                    from manager_event_state
                    where event_id = any($1::bigint[])
                    """,
                    event_ids,
                )
            reminded_by_event_id = {
                int(row["event_id"]): row["last_reminded_at"]
                for row in reminded_rows
                if row["last_reminded_at"] is not None
            }

        reminders: list[EventReminder] = []
        now = datetime.now(timezone.utc)
        for row in rows:
            starts_at: datetime = row["starts_at"]
            event_id = int(row["event_id"])
            remind_before = int(row["remind_before_min"])
            remind_at = starts_at - timedelta(minutes=remind_before)
            last_reminded_at = reminded_by_event_id.get(event_id)
            if last_reminded_at and last_reminded_at >= remind_at:
                continue
            if now >= remind_at:
                reminders.append(
                    EventReminder(
                        event_id=event_id,
                        title=str(row["title"]),
                        starts_at=starts_at,
                        remind_before_min=remind_before,
                        payload=str(row["payload"]),
                    )
                )
        return reminders[:50]

    async def _fetch_weekly_schedule_events(self) -> list[EventReminder]:
        manager_pool = self._require_manager_pool()
        source_pool = self._require_source_pool()

        sql = f"""
        select id, day_name, time_str, description
        from {self.settings.source_events_table}
        order by id
        """
        async with source_pool.acquire() as conn:
            rows = await conn.fetch(sql)

        tz = ZoneInfo(self.settings.source_schedule_timezone)
        now_local = datetime.now(tz)
        now_utc = datetime.now(timezone.utc)
        reminders: list[EventReminder] = []

        for row in rows:
            time_match = re.search(r"(\d{1,2}):(\d{2})", str(row["time_str"] or ""))
            weekday = _russian_weekday(str(row["day_name"] or ""))
            if weekday is None or not time_match:
                continue

            hour = int(time_match.group(1))
            minute = int(time_match.group(2))
            days_ahead = (weekday - now_local.weekday()) % 7
            starts_local = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=days_ahead)
            if starts_local <= now_local:
                starts_local += timedelta(days=7)

            starts_at = starts_local.astimezone(timezone.utc)
            if not (now_utc <= starts_at <= now_utc + timedelta(hours=24)):
                continue

            reminder_id = int(starts_local.strftime("%Y%m%d")) * 1000 + int(row["id"])
            async with manager_pool.acquire() as conn:
                already = await conn.fetchval(
                    "select 1 from manager_event_state where event_id=$1 and last_reminded_at is not null",
                    reminder_id,
                )
            if already:
                continue

            reminders.append(
                EventReminder(
                    event_id=reminder_id,
                    title=f"{row['day_name']}: {row['time_str']}",
                    starts_at=starts_at,
                    remind_before_min=60,
                    payload=str(row["description"] or ""),
                )
            )

        return reminders

    async def mark_event_reminded(self, event_id: int) -> None:
        pool = self._require_manager_pool()
        sql = """
        insert into manager_event_state(event_id, last_reminded_at)
        values ($1, now())
        on conflict (event_id) do update set
          last_reminded_at = excluded.last_reminded_at
        """
        async with pool.acquire() as conn:
            await conn.execute(sql, event_id)

    async def log_message(
        self,
        chat_id: int,
        user_id: int,
        username: str,
        text: str,
        is_newbie: bool,
        created_at: datetime | None = None,
        source: str = "live",
        source_message_id: int | None = None,
    ) -> None:
        pool = self._require_manager_pool()
        message_created_at = created_at or datetime.now(timezone.utc)

        async with pool.acquire() as conn:
            inserted = await conn.fetchval(
                """
                insert into manager_message_log(source, source_message_id, chat_id, user_id, username, text, is_newbie, created_at)
                values ($1,$2,$3,$4,$5,$6,$7,$8)
                on conflict (source, source_message_id) do nothing
                returning id
                """,
                source,
                source_message_id,
                chat_id,
                user_id,
                username,
                text,
                is_newbie,
                message_created_at,
            )
            if inserted is None:
                return

            await conn.execute(
                """
                insert into manager_chat_metrics_daily(day, user_id, username, messages_count)
                values ($1, $2, $3, 1)
                on conflict (day, user_id)
                do update set
                    username = excluded.username,
                    messages_count = manager_chat_metrics_daily.messages_count + 1
                """,
                message_created_at.date(),
                user_id,
                username,
            )

    async def import_messages(self, messages: list[dict[str, Any]], batch_size: int = 500) -> int:
        pool = self._require_manager_pool()

        imported = 0
        async with pool.acquire() as conn:
            for start in range(0, len(messages), batch_size):
                batch = messages[start : start + batch_size]
                if not batch:
                    continue
                async with conn.transaction():
                    rows = await conn.fetch(
                        """
                        with incoming as (
                            select *
                            from unnest(
                                $1::text[],
                                $2::bigint[],
                                $3::bigint[],
                                $4::bigint[],
                                $5::text[],
                                $6::text[],
                                $7::bool[],
                                $8::timestamptz[]
                            ) as item(source, source_message_id, chat_id, user_id, username, text, is_newbie, created_at)
                        ), inserted as (
                            insert into manager_message_log(
                                source, source_message_id, chat_id, user_id, username, text, is_newbie, created_at
                            )
                            select source, source_message_id, chat_id, user_id, username, text, is_newbie, created_at
                            from incoming
                            on conflict (source, source_message_id) do nothing
                            returning user_id, username, created_at
                        ), metrics as (
                            select created_at::date as day, user_id, max(username) as username, count(*)::int as messages_count
                            from inserted
                            group by created_at::date, user_id
                        ), metric_upsert as (
                            insert into manager_chat_metrics_daily(day, user_id, username, messages_count)
                            select day, user_id, username, messages_count
                            from metrics
                            on conflict (day, user_id)
                            do update set
                                username = excluded.username,
                                messages_count = manager_chat_metrics_daily.messages_count + excluded.messages_count
                            returning 1
                        )
                        select user_id, username, created_at from inserted
                        """,
                        [item["source"] for item in batch],
                        [item["source_message_id"] for item in batch],
                        [item["chat_id"] for item in batch],
                        [item["user_id"] for item in batch],
                        [item["username"] for item in batch],
                        [item["text"] for item in batch],
                        [item["is_newbie"] for item in batch],
                        [item["created_at"] for item in batch],
                    )
                    imported += len(rows)
        return imported

    async def flag_helpful(self, user_id: int, username: str) -> None:
        pool = self._require_manager_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                insert into manager_chat_metrics_daily(day, user_id, username, helpful_answers)
                values (current_date, $1, $2, 1)
                on conflict (day, user_id)
                do update set
                    username = excluded.username,
                    helpful_answers = manager_chat_metrics_daily.helpful_answers + 1
                """,
                user_id,
                username,
            )

    async def flag_toxicity(self, user_id: int, username: str) -> None:
        pool = self._require_manager_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                insert into manager_chat_metrics_daily(day, user_id, username, toxicity_flags)
                values (current_date, $1, $2, 1)
                on conflict (day, user_id)
                do update set
                    username = excluded.username,
                    toxicity_flags = manager_chat_metrics_daily.toxicity_flags + 1
                """,
                user_id,
                username,
            )

    async def add_warning(self, user_id: int, reason: str, actor_id: int) -> int:
        pool = self._require_manager_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    insert into manager_user_strikes(user_id, warnings_count, updated_at)
                    values ($1, 1, now())
                    on conflict (user_id)
                    do update set warnings_count = manager_user_strikes.warnings_count + 1,
                                  updated_at = now()
                    returning warnings_count
                    """,
                    user_id,
                )
                await conn.execute(
                    """
                    insert into manager_moderation_actions(user_id, actor_id, action, reason)
                    values ($1,$2,'warn',$3)
                    """,
                    user_id,
                    actor_id,
                    reason,
                )
        return int(row["warnings_count"]) if row else 0

    async def set_mute(self, user_id: int, until_at: datetime, reason: str, actor_id: int) -> None:
        pool = self._require_manager_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    insert into manager_user_strikes(user_id, muted_until, updated_at)
                    values ($1, $2, now())
                    on conflict (user_id)
                    do update set muted_until = excluded.muted_until,
                                  updated_at = now()
                    """,
                    user_id,
                    until_at,
                )
                await conn.execute(
                    """
                    insert into manager_moderation_actions(user_id, actor_id, action, reason, metadata)
                    values ($1,$2,'mute',$3,$4::jsonb)
                    """,
                    user_id,
                    actor_id,
                    reason,
                    json.dumps({"until_at": until_at.isoformat()}),
                )

    async def set_ban(self, user_id: int, reason: str, actor_id: int, permanent: bool) -> None:
        if not self.pool:
            raise RuntimeError("DB pool is not initialized")
        action = "ban" if permanent else "kick"
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    insert into manager_user_strikes(user_id, is_banned, updated_at)
                    values ($1, $2, now())
                    on conflict (user_id)
                    do update set is_banned = excluded.is_banned,
                                  updated_at = now()
                    """,
                    user_id,
                    permanent,
                )
                await conn.execute(
                    """
                    insert into manager_moderation_actions(user_id, actor_id, action, reason)
                    values ($1,$2,$3,$4)
                    """,
                    user_id,
                    actor_id,
                    action,
                    reason,
                )

    async def remove_warning(self, user_id: int, reason: str, actor_id: int) -> int:
        pool = self._require_manager_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    insert into manager_user_strikes(user_id, warnings_count, updated_at)
                    values ($1, 0, now())
                    on conflict (user_id)
                    do update set warnings_count = greatest(manager_user_strikes.warnings_count - 1, 0),
                                  updated_at = now()
                    returning warnings_count
                    """,
                    user_id,
                )
                await conn.execute(
                    """
                    insert into manager_moderation_actions(user_id, actor_id, action, reason)
                    values ($1,$2,'unwarn',$3)
                    """,
                    user_id,
                    actor_id,
                    reason,
                )
        return int(row["warnings_count"]) if row else 0

    async def clear_mute(self, user_id: int, reason: str, actor_id: int) -> None:
        pool = self._require_manager_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    insert into manager_user_strikes(user_id, muted_until, updated_at)
                    values ($1, null, now())
                    on conflict (user_id)
                    do update set muted_until = null,
                                  updated_at = now()
                    """,
                    user_id,
                )
                await conn.execute(
                    """
                    insert into manager_moderation_actions(user_id, actor_id, action, reason)
                    values ($1,$2,'unmute',$3)
                    """,
                    user_id,
                    actor_id,
                    reason,
                )

    async def clear_ban(self, user_id: int, reason: str, actor_id: int) -> None:
        pool = self._require_manager_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    insert into manager_user_strikes(user_id, is_banned, updated_at)
                    values ($1, false, now())
                    on conflict (user_id)
                    do update set is_banned = false,
                                  updated_at = now()
                    """,
                    user_id,
                )
                await conn.execute(
                    """
                    insert into manager_moderation_actions(user_id, actor_id, action, reason)
                    values ($1,$2,'unban',$3)
                    """,
                    user_id,
                    actor_id,
                    reason,
                )

    async def fetch_member_analytics(self, days: int = 7) -> list[MemberAnalytics]:
        manager_pool = self._require_manager_pool()
        source_pool = self._require_source_pool()

        if self.settings.source_analytics_sql.strip():
            sql = self.settings.source_analytics_sql
            args: tuple[Any, ...] = ()
            async with source_pool.acquire() as conn:
                rows = await conn.fetch(sql, *args)
        else:
            async with manager_pool.acquire() as conn:
                manager_rows = await conn.fetch(
                    """
                    select
                        user_id,
                        max(username) as username,
                        sum(messages_count)::int as messages_count,
                        count(*)::int as active_days,
                        sum(helpful_answers)::int as helpful_answers,
                        sum(toxicity_flags)::int as toxicity_flags
                    from manager_chat_metrics_daily
                    where day >= current_date - ($1::int - 1)
                    group by user_id
                    """,
                    days,
                )
                warn_rows = await conn.fetch(
                    """
                    select user_id, coalesce(max(warnings_count), 0)::int as warnings_count
                    from manager_user_strikes
                    group by user_id
                    """
                )
            sql = f"""
            with old_bot_events as (
                select
                    user_id,
                    count(*)::int as messages_count,
                    count(distinct happened_at::date)::int as active_days
                from {self.settings.source_activity_table}
                where happened_at >= now() - make_interval(days => $1)
                group by user_id
            ), old_bot_users as (
                select
                    user_id,
                    max(username) as username,
                    count(*)::int as messages_count,
                    count(*)::int as active_days
                from users
                where last_active >= now() - make_interval(days => $1)
                  and blocked=0
                group by user_id
            )
            select
                coalesce(e.user_id, u.user_id) as user_id,
                coalesce(u.username, '') as username,
                (coalesce(e.messages_count, 0) + coalesce(u.messages_count, 0))::int as messages_count,
                greatest(coalesce(e.active_days, 0), coalesce(u.active_days, 0))::int as active_days,
                0::int as warnings_count,
                0::int as helpful_answers,
                0::int as toxicity_flags
            from old_bot_events e
            full outer join old_bot_users u using (user_id)
            order by 3 desc
            limit 200
            """
            args = (days,)
            async with source_pool.acquire() as conn:
                source_rows = await conn.fetch(sql, *args)

            merged: dict[int, dict[str, Any]] = {}
            for row in manager_rows:
                user_id = int(row["user_id"])
                merged[user_id] = {
                    "user_id": user_id,
                    "username": str(row["username"] or ""),
                    "messages_count": int(row["messages_count"] or 0),
                    "active_days": int(row["active_days"] or 0),
                    "warnings_count": 0,
                    "helpful_answers": int(row["helpful_answers"] or 0),
                    "toxicity_flags": int(row["toxicity_flags"] or 0),
                }
            for row in source_rows:
                user_id = int(row["user_id"])
                item = merged.setdefault(
                    user_id,
                    {
                        "user_id": user_id,
                        "username": "",
                        "messages_count": 0,
                        "active_days": 0,
                        "warnings_count": 0,
                        "helpful_answers": 0,
                        "toxicity_flags": 0,
                    },
                )
                if not item["username"]:
                    item["username"] = str(row["username"] or "")
                item["messages_count"] += int(row["messages_count"] or 0)
                item["active_days"] = max(item["active_days"], int(row["active_days"] or 0))
            for row in warn_rows:
                user_id = int(row["user_id"])
                item = merged.setdefault(
                    user_id,
                    {
                        "user_id": user_id,
                        "username": "",
                        "messages_count": 0,
                        "active_days": 0,
                        "warnings_count": 0,
                        "helpful_answers": 0,
                        "toxicity_flags": 0,
                    },
                )
                item["warnings_count"] = int(row["warnings_count"] or 0)
            rows = sorted(merged.values(), key=lambda item: item["messages_count"], reverse=True)[:100]

        result: list[MemberAnalytics] = []
        for row in rows:
            data = dict(row)
            result.append(
                MemberAnalytics(
                    user_id=int(data["user_id"]),
                    username=str(data["username"]),
                    messages_count=int(data["messages_count"]),
                    active_days=int(data["active_days"]),
                    warnings_count=int(data["warnings_count"]),
                    helpful_answers=int(data.get("helpful_answers", 0)),
                    toxicity_flags=int(data.get("toxicity_flags", 0)),
                )
            )
        return result

    async def fetch_newbie_templates_seed(self, days: int = 30) -> list[str]:
        pool = self._require_manager_pool()
        sql = """
        select text
        from manager_message_log
        where created_at >= now() - make_interval(days => $1)
          and is_newbie = true
          and length(text) > 5
        order by created_at desc
        limit 1000
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, days)
        return [str(r["text"]) for r in rows]

    async def top_scored_candidates(self, days: int = 7) -> list[dict[str, Any]]:
        pool = self._require_manager_pool()
        sql = """
        select application_id, user_id, username, score, grade, verdict, reasons, risks, created_at
        from manager_application_scores
        where created_at >= now() - make_interval(days => $1)
        order by score desc, created_at desc
        limit 20
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, days)
        return [dict(r) for r in rows]

    async def fetch_recent_messages(self, chat_id: int, limit: int = 25) -> list[dict[str, Any]]:
        pool = self._require_manager_pool()
        sql = """
        select user_id, username, text, created_at
        from manager_message_log
        where chat_id = $1
          and length(text) > 0
        order by created_at desc
        limit $2
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, chat_id, limit)
        return [dict(r) for r in rows]

    async def resolve_user_id_by_username(self, username: str) -> int | None:
        normalized = _normalize_username_ref(username)
        if not normalized:
            return None

        manager_pool = self._require_manager_pool()
        source_pool = self._require_source_pool()

        async with manager_pool.acquire() as conn:
            user_id = await conn.fetchval(
                """
                select user_id
                from manager_message_log
                where lower(username) = $1
                order by created_at desc
                limit 1
                """,
                normalized,
            )
        if user_id:
            return int(user_id)

        async with source_pool.acquire() as conn:
            users_table = await conn.fetchval(
                """
                select to_regclass($1)
                """,
                "users",
            )
            if users_table:
                user_id = await conn.fetchval(
                    """
                    select user_id
                    from users
                    where lower(username) = $1
                    order by last_active desc nulls last, user_id desc
                    limit 1
                    """,
                    normalized,
                )
                if user_id:
                    return int(user_id)

            applications_table = await conn.fetchval(
                """
                select to_regclass($1)
                """,
                self.settings.source_applications_table,
            )
            if applications_table:
                sql = f"""
                select user_id
                from {self.settings.source_applications_table}
                where lower(username) = $1
                order by submitted_at desc nulls last, id desc
                limit 1
                """
                user_id = await conn.fetchval(sql, normalized)
                if user_id:
                    return int(user_id)

        return None

    async def list_admins(self) -> list[dict[str, Any]]:
        pool = self._require_manager_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                select user_id, username, permissions, created_at, updated_at
                from manager_admins
                order by updated_at desc, user_id asc
                """
            )
        return [dict(row) for row in rows]

    async def get_admin_record(self, user_id: int) -> dict[str, Any] | None:
        pool = self._require_manager_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                select user_id, username, permissions, created_at, updated_at
                from manager_admins
                where user_id = $1
                """,
                user_id,
            )
        return dict(row) if row else None

    async def upsert_admin(self, user_id: int, username: str, permissions: list[str]) -> None:
        pool = self._require_manager_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                insert into manager_admins(user_id, username, permissions)
                values ($1, $2, $3::jsonb)
                on conflict (user_id)
                do update set
                    username = excluded.username,
                    permissions = excluded.permissions,
                    updated_at = now()
                """,
                user_id,
                username,
                json.dumps(sorted(set(permissions))),
            )

    async def delete_admin(self, user_id: int) -> None:
        pool = self._require_manager_pool()
        async with pool.acquire() as conn:
            await conn.execute("delete from manager_admins where user_id = $1", user_id)
