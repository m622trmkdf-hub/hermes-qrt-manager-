# Clan AI Manager Bot (Telegram)

Готовый отдельный бот-менеджер для клана. Он **не ломает старый бот**, а анализирует его данные через БД/логи и выполняет управление в Telegram.

## Что умеет

- Оценка анкет из старого бота в процентах (`0-100`) + вердикт в админ-чат.
- Авто-напоминания о событиях/расписании в общий чат.
- Аналитика активности участников и рекомендации по кандидатам в админы.
- Авто-модерация: варны, муты, кик, бан, автобан по лимиту предупреждений.
- Генерация шаблонов ответов новичкам на базе чата.
- Интеграция с Hermes Agent для умной оценки анкет и объяснений.

## Почему выбран обычный Telegram Bot API

Для твоего кейса это лучший базовый режим:

- Безопаснее и стабильнее для продакшена.
- Нативная поддержка прав администратора (mute/kick/ban).
- Проще разворачивать на Railway.

`Userbot` оставляем как дополнительный источник данных (через БД/логи), а не как ядро модерации.

## Hermes Agent

Hermes Agent подключается как основной AI-слой через OpenAI-compatible API.

Как это работает:

- Новый бот читает анкету из Supabase.
- Анкеты, `/report`, ежедневные отчеты и `/templates` отправляются в Hermes Agent.
- Hermes возвращает оценку, выводы, риски, рекомендации и шаблоны.
- Локальные формулы используются только как аварийный черновик, если Hermes недоступен.
- В production держи `HERMES_REQUIRED=true`, чтобы было видно, что аналитика не должна работать "тихо" без Hermes.

Переменные:

```env
HERMES_API_BASE_URL=https://your-hermes-service.up.railway.app/v1
HERMES_API_KEY=
HERMES_MODEL=hermes-agent
HERMES_MAX_TOKENS=1200
HERMES_TIMEOUT_SECONDS=45
HERMES_REQUIRED=true
```

Для Railway используй две службы: `hermes-agent` и `clan-manager-bot`. Подробно: [deploy/railway/README.md](/Users/zx/Documents/Codex/2026-04-25/hermes-agent/deploy/railway/README.md).

## Быстрый старт локально

### 1. Установка

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Конфигурация

```bash
cp .env.example .env
```

Заполни минимум:

- `BOT_TOKEN`
- `ADMIN_CHAT_ID`
- `PUBLIC_CHAT_ID`
- `ADMIN_IDS`
- `DATABASE_URL`
- `SOURCE_DATABASE_URL` if the old bot lives in another database

### 3. Запуск

```bash
PYTHONPATH=src python -m clan_manager_bot.main
```

## Интеграция со старым ботом

Есть два режима:

- `DATABASE_URL` -> новая БД бота, где хранятся только таблицы `manager_*`
- `SOURCE_DATABASE_URL` -> старая БД, которую новый бот читает в онлайне

Если `SOURCE_DATABASE_URL` пустой, бот использует `DATABASE_URL` и для source-таблиц тоже.

По умолчанию в source-БД ожидаются таблицы:

- `applications`
- `schedule`
- `chat_messages`
- `user_events`

Для архива старого QRT-бота заявки берутся из `applications.answers` (JSON-список из 10 ответов), расписание из `schedule`, а активность из `users` и `user_events`.

Если у тебя другие имена/структура, задай свои SQL в `.env`:

- `SOURCE_APPLICATIONS_SQL`
- `SOURCE_EVENTS_SQL`
- `SOURCE_ANALYTICS_SQL`

Так ты можешь подключить хоть обычный бот, хоть userbot, хоть бизнес-бот через единый слой БД.

## Команды админов

- `/report` — рейтинг кандидатов в админы + аналитика чата.
- `/templates` — актуальные шаблоны ответов новичкам.
- `/warn <user_id> [reason]` — предупреждение.
- `/mute <user_id> [minutes]` — мут.
- `/kick <user_id>` — кик (с возможностью вернуться по ссылке).
- `/ban <user_id>` — перманентный бан.

Также `/warn`/`/mute`/`/kick`/`/ban` можно использовать ответом на сообщение.

## Автоматические процессы

- Скан анкет: каждые `APPLICATION_SCAN_INTERVAL_MIN`.
- Скан событий/напоминаний: каждые `EVENT_SCAN_INTERVAL_MIN`.
- Daily отчеты: каждый день в `ANALYTICS_REPORT_HOUR_UTC` (UTC).

## Права бота в Telegram

Боту нужны права администратора в целевом чате:

- Delete messages (опционально)
- Restrict members
- Ban users

И отключи privacy mode в BotFather, если нужен полный анализ сообщений группы.

## Railway

Основной вариант для тебя: Railway + Supabase.

Коротко:

1. `hermes-agent` сервис из репозитория `NousResearch/hermes-agent`.
2. `clan-manager-bot` сервис из этой папки.
3. `DATABASE_URL` берется из Supabase.
4. `SOURCE_DATABASE_URL` указывает на старую БД, если старый бот живет отдельно.
5. `HERMES_API_BASE_URL` в боте указывает на public domain сервиса Hermes.

Полная инструкция: [deploy/railway/README.md](/Users/zx/Documents/Codex/2026-04-25/hermes-agent/deploy/railway/README.md).

Минимум файлов для деплоя:

- `src/`
- `requirements.txt`
- `Procfile`
- `runtime.txt`
- `pyproject.toml`

Старт-команда в `Procfile`:

```text
worker: PYTHONPATH=src python -m clan_manager_bot.main
```

Для Railway добавь эти переменные в `Variables`:

- `BOT_TOKEN`
- `ADMIN_CHAT_ID`
- `PUBLIC_CHAT_ID`
- `ADMIN_IDS`
- `DATABASE_URL`
- `SOURCE_DATABASE_URL`
- `HERMES_API_BASE_URL`
- `HERMES_API_KEY` (если API Hermes защищен)
- `HERMES_MODEL`
- `HERMES_REQUIRED=true`

## Проверки перед продом

```bash
PYTHONPATH=src python -m py_compile src/clan_manager_bot/*.py
PYTHONPATH=src pytest -q
```

## Импорт Истории Чата

Если есть Telegram export `result.json`, его можно загрузить в аналитику:

```bash
PYTHONPATH=src python scripts/import_telegram_export.py "/path/to/result.json" --database-url "YOUR_SUPABASE_DATABASE_URL"
```

Скрипт пишет старые сообщения в `manager_message_log` и обновляет `manager_chat_metrics_daily`. Повторный запуск безопасен: сообщения не дублируются.

## Ограничения

- Модерация админов выше по правам невозможна (ограничение Telegram).
- Качество AI-скоринга зависит от полноты анкет и истории данных.
- Для глубоких AI-объяснений подключается Hermes Agent через `HERMES_API_BASE_URL`.
