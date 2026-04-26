from __future__ import annotations

import asyncio
import logging
import os
import signal

from telegram.ext import Application

from .config import get_settings
from .db import Database
from .handlers import BotRuntime


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def run() -> None:
    settings = get_settings()
    db = Database(settings)
    await db.connect()
    await db.init_schema()

    runtime = BotRuntime(settings=settings, db=db)

    app = Application.builder().token(settings.bot_token).build()
    runtime.register_handlers(app)
    runtime.register_jobs(app)

    logger.info("Starting clan manager bot")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    stop_event = asyncio.Event()

    def _stop(*_: object) -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            pass

    try:
        await stop_event.wait()
    finally:
        logger.info("Shutting down bot")
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        await db.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
