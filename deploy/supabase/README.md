# Supabase setup

1. Open Supabase project.
2. Go to `SQL Editor`.
3. Run `sql/schema.sql`.
4. Open `Project Settings` -> `Database`.
5. Copy the connection string. Prefer the pooler URL on port `6543`.
6. Put it into `.env` as `DATABASE_URL` and keep `?sslmode=require`.
7. If the old bot uses another database, keep that second connection string separately as `SOURCE_DATABASE_URL`.

Example:

```env
DATABASE_URL=postgresql://postgres.project_ref:password@aws-0-region.pooler.supabase.com:6543/postgres?sslmode=require
```

The bot uses `statement_cache_size=0`, which is compatible with Supabase pooler mode.

## Two-database mode

Use this mode if the old bot must stay on its current database and the new bot should read it online:

```env
DATABASE_URL=postgresql://...new_manager_db...?sslmode=require
SOURCE_DATABASE_URL=postgresql://...old_bot_db...?sslmode=require
```

`DATABASE_URL` stores only `manager_*` tables.

`SOURCE_DATABASE_URL` is used only for reading old bot tables and analytics.

## Old bot tables

The manager reads old bot data from these defaults:

```env
SOURCE_APPLICATIONS_TABLE=applications
SOURCE_EVENTS_TABLE=schedule
SOURCE_MESSAGES_TABLE=chat_messages
SOURCE_ACTIVITY_TABLE=user_events
SOURCE_SCHEDULE_TIMEZONE=Europe/Moscow
```

If the old bot has another schema, keep the tables untouched and set custom SQL:

```env
SOURCE_APPLICATIONS_SQL=select id, user_id, username, experience_text, activity_text, about_text, warnings_count, status, created_at from your_table where ...
SOURCE_EVENTS_SQL=select id as event_id, title, starts_at, remind_before_min, description as payload from your_events where ...
SOURCE_ANALYTICS_SQL=select user_id, username, messages_count, active_days, warnings_count, helpful_answers, toxicity_flags from your_view
```

Required output columns:

`SOURCE_APPLICATIONS_SQL`: `id`, `user_id`, `username`, `experience_text`, `activity_text`, `about_text`, `warnings_count`, `status`, `created_at`.

`SOURCE_EVENTS_SQL`: `event_id`, `title`, `starts_at`, `remind_before_min`, `payload`.

`SOURCE_ANALYTICS_SQL`: `user_id`, `username`, `messages_count`, `active_days`, `warnings_count`, `helpful_answers`, `toxicity_flags`.
