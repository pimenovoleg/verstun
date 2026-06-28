import asyncio

import structlog
import uvicorn
from aiogram import Bot

from src.api.app import app
from src.bot.main import run_polling
from src.config import get_settings

log = structlog.get_logger()


async def _serve_api() -> None:
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_config=None)
    await uvicorn.Server(config).serve()


async def main() -> None:
    settings = get_settings()
    log.info("starting", environment=settings.environment)

    tasks = [asyncio.create_task(_serve_api())]
    if settings.bot_token:
        bot = Bot(token=settings.bot_token)
        tasks.append(asyncio.create_task(run_polling(bot, settings)))
    else:
        log.warning("BOT_TOKEN not set — running API only")

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
