import asyncio
from unittest.mock import AsyncMock

import pytest

import src.main as app_main
from src.config import Settings


class _FakeBot:
    instances = []

    def __init__(self, token: str) -> None:
        self.token = token
        self.session = AsyncMock()
        self.session.close = AsyncMock()
        self.__class__.instances.append(self)


def _settings(*, bot_token: str = "") -> Settings:
    return Settings(_env_file=None, BOT_TOKEN=bot_token)


async def test_main_runs_api_only_without_bot(monkeypatch):
    served = False

    async def serve_api():
        nonlocal served
        served = True

    monkeypatch.setattr(app_main, "get_settings", lambda: _settings())
    monkeypatch.setattr(app_main, "_serve_api", serve_api)

    await app_main.main()

    assert served is True


async def test_main_closes_bot_session_when_polling_fails(monkeypatch):
    async def serve_api():
        await asyncio.Event().wait()

    async def fail_polling(bot, settings):
        raise RuntimeError("polling failed")

    monkeypatch.setattr(app_main, "get_settings", lambda: _settings(bot_token="123:abc"))
    monkeypatch.setattr(app_main, "Bot", _FakeBot)
    monkeypatch.setattr(app_main, "_serve_api", serve_api)
    monkeypatch.setattr(app_main, "run_polling", fail_polling)
    _FakeBot.instances.clear()

    with pytest.raises(RuntimeError, match="polling failed"):
        await app_main.main()

    assert len(_FakeBot.instances) == 1
    _FakeBot.instances[0].session.close.assert_awaited_once()


async def test_main_cancels_api_when_polling_fails(monkeypatch):
    api_cancelled = False

    async def serve_api():
        nonlocal api_cancelled
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            api_cancelled = True
            raise

    async def fail_polling(bot, settings):
        raise RuntimeError("polling failed")

    monkeypatch.setattr(app_main, "get_settings", lambda: _settings(bot_token="123:abc"))
    monkeypatch.setattr(app_main, "Bot", _FakeBot)
    monkeypatch.setattr(app_main, "_serve_api", serve_api)
    monkeypatch.setattr(app_main, "run_polling", fail_polling)
    _FakeBot.instances.clear()

    with pytest.raises(RuntimeError, match="polling failed"):
        await app_main.main()

    assert api_cancelled is True


async def test_main_cancels_polling_when_api_stops(monkeypatch):
    polling_cancelled = False

    async def serve_api():
        return None

    async def run_forever(bot, settings):
        nonlocal polling_cancelled
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            polling_cancelled = True
            raise

    monkeypatch.setattr(app_main, "get_settings", lambda: _settings(bot_token="123:abc"))
    monkeypatch.setattr(app_main, "Bot", _FakeBot)
    monkeypatch.setattr(app_main, "_serve_api", serve_api)
    monkeypatch.setattr(app_main, "run_polling", run_forever)
    _FakeBot.instances.clear()

    await app_main.main()

    assert polling_cancelled is True
    _FakeBot.instances[0].session.close.assert_awaited_once()
