# Railway deploy

Use one Railway project with two services:

1. `hermes-agent` service.
2. `clan-manager-bot` service.

Supabase stays outside Railway.

Recommended production layout:

1. `DATABASE_URL` -> new manager database with `manager_*` tables.
2. `SOURCE_DATABASE_URL` -> old bot database for live read-only access.

## 1. Supabase

1. Open Supabase.
2. Go to `SQL Editor`.
3. Run `sql/schema.sql`.
4. Copy the pooler connection string.
5. Use it as `DATABASE_URL` with `?sslmode=require`.
6. If the old bot is in another database, copy that second connection string too and use it as `SOURCE_DATABASE_URL`.

## 2. Hermes Agent service

1. Open `https://github.com/NousResearch/hermes-agent`.
2. Press `Fork` in GitHub.
3. In Railway, create a new service from GitHub.
4. Select your fork of `hermes-agent`.
5. Add these variables from `.env.railway.hermes.example`:

```env
API_SERVER_ENABLED=true
API_SERVER_HOST=0.0.0.0
API_SERVER_KEY=replace_with_long_random_secret
API_SERVER_MODEL_NAME=hermes-agent
HERMES_INFERENCE_PROVIDER=openrouter
HERMES_MODEL=google/gemini-2.5-flash
OPENROUTER_API_KEY=your_key
```

6. Open `Settings`.
7. Find `Start Command`.
8. Paste this value into that field:

```text
sh -lc 'API_SERVER_PORT=$PORT hermes gateway'
```

9. Open `Networking`.
10. Generate a public domain for this service.
11. Check `Deployments` -> latest deployment -> `Logs`.
12. The logs must show that the API server is listening. If it does not, fix this service before deploying the bot.

## 3. Clan manager bot service

1. Create another Railway service from your `clan-manager-bot` GitHub repository.
2. Add variables from `.env.railway.bot.example`.
3. Set:

```env
HERMES_API_BASE_URL=https://YOUR-HERMES.up.railway.app/v1
HERMES_API_KEY=same_value_as_API_SERVER_KEY
HERMES_MODEL=hermes-agent
HERMES_REQUIRED=true
```

If the old bot lives in another database, also set:

```env
SOURCE_DATABASE_URL=postgresql://...old_bot_db...?sslmode=require
```

For the old QRT bot archive, also keep these source settings:

```env
SOURCE_APPLICATIONS_TABLE=applications
SOURCE_EVENTS_TABLE=schedule
SOURCE_MESSAGES_TABLE=chat_messages
SOURCE_ACTIVITY_TABLE=user_events
SOURCE_SCHEDULE_TIMEZONE=Europe/Moscow
```

4. Deploy the service.

The bot service does not need a public domain because it uses Telegram polling.

## 4. Telegram check

In BotFather:

1. Turn off `Group Privacy`.
2. Add bot to the clan chat as admin.
3. Give rights: restrict members, ban users, delete messages.
4. Add bot to the admin chat.

Send:

```text
/start
/report
/templates
```

If Hermes is missing or broken, the bot will say that Hermes is unavailable instead of silently using local analytics.

## 5. Import Telegram chat export

Railway has no interactive command line. Import Telegram `result.json` from your MacBook into Supabase before or after Railway deploy.

1. Open Terminal on MacBook.
2. Go to the bot project folder.
3. Run the importer with your Supabase `DATABASE_URL`.

```text
PYTHONPATH=src python3 scripts/import_telegram_export.py "/path/to/result.json" --database-url "YOUR_SUPABASE_DATABASE_URL"
```

Expected output:

```text
prepared=...
imported=...
```

Run this only on your MacBook, not inside Railway.
