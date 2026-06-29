import asyncio
from collections.abc import Awaitable

import structlog
import uvicorn
from aiogram import Bot

from src.api.app import app
from src.bot.main import run_polling
from src.config import get_settings

log = structlog.get_logger()

_SHUTDOWN_TIMEOUT_SECONDS = 10.0


async def _serve_api() -> None:
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_config=None)
    await uvicorn.Server(config).serve()


async def _run_until_stopped(tasks: list[asyncio.Task[object]]) -> None:
    pending = set(tasks)
    try:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            exc = task.exception()
            if exc is not None:
                raise exc
    finally:
        await _cancel_pending(pending)


async def _cancel_pending(tasks: set[asyncio.Task[object]]) -> None:
    if not tasks:
        return
    for task in tasks:
        task.cancel()
    done, pending = await asyncio.wait(tasks, timeout=_SHUTDOWN_TIMEOUT_SECONDS)
    if pending:
        log.warning("shutdown_tasks_timeout", count=len(pending))
    for task in done:
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            log.warning("shutdown_task_failed", exc_info=True)


def _create_task(coro: Awaitable[object], name: str) -> asyncio.Task[object]:
    return asyncio.create_task(coro, name=name)


async def main() -> None:
    settings = get_settings()
    log.info("starting", environment=settings.environment)

    tasks = [_create_task(_serve_api(), "api")]
    bot = None
    if settings.bot_token:
        bot = Bot(token=settings.bot_token)
        tasks.append(_create_task(run_polling(bot, settings), "bot-polling"))
    else:
        log.warning("BOT_TOKEN not set — running API only")

    try:
        await _run_until_stopped(tasks)
    finally:
        if bot is not None:
            await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
