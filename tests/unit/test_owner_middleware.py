from unittest.mock import AsyncMock

from src.bot.main import build_dispatcher
from src.bot.storage import BotStateStore
from src.config import Settings
from src.middleware import AccessMiddleware


def _event(user_id: int | None):
    event = AsyncMock()
    if user_id is None:
        event.from_user = None
    else:
        event.from_user = AsyncMock()
        event.from_user.id = user_id
    return event


async def test_owner_update_passes():
    settings = Settings(_env_file=None, OWNER_TELEGRAM_ID=42)
    middleware = AccessMiddleware()
    handler = AsyncMock(return_value="handled")
    event = _event(42)

    result = await middleware(handler, event, {"settings": settings})

    handler.assert_awaited_once_with(event, {"settings": settings})
    assert result == "handled"


async def test_non_owner_update_dropped():
    settings = Settings(_env_file=None, OWNER_TELEGRAM_ID=42)
    middleware = AccessMiddleware()
    handler = AsyncMock()
    event = _event(7)

    result = await middleware(handler, event, {"settings": settings})

    handler.assert_not_awaited()
    assert result is None
    event.answer.assert_not_called()


async def test_unset_owner_id_drops_all():
    settings = Settings(_env_file=None)
    assert settings.owner_telegram_id is None
    middleware = AccessMiddleware()
    handler = AsyncMock()
    event = _event(42)

    result = await middleware(handler, event, {"settings": settings})

    handler.assert_not_awaited()
    assert result is None


async def test_no_from_user_dropped():
    settings = Settings(_env_file=None, OWNER_TELEGRAM_ID=42)
    middleware = AccessMiddleware()
    handler = AsyncMock()
    event = _event(None)

    result = await middleware(handler, event, {"settings": settings})

    handler.assert_not_awaited()
    assert result is None


async def test_saved_user_update_passes(tmp_path):
    settings = Settings(
        _env_file=None,
        OWNER_TELEGRAM_ID=42,
        DATA_DIR=str(tmp_path),
    )
    BotStateStore(settings.data_dir).save_user(telegram_id=7, name="Lena", username=None)
    middleware = AccessMiddleware()
    handler = AsyncMock(return_value="handled")
    event = _event(7)

    result = await middleware(handler, event, {"settings": settings})

    handler.assert_awaited_once_with(event, {"settings": settings})
    assert result == "handled"


async def test_deleted_user_update_dropped(tmp_path):
    settings = Settings(
        _env_file=None,
        OWNER_TELEGRAM_ID=42,
        DATA_DIR=str(tmp_path),
    )
    store = BotStateStore(settings.data_dir)
    store.save_user(telegram_id=7, name="Lena", username=None)
    store.delete_user(7)
    middleware = AccessMiddleware()
    handler = AsyncMock()
    event = _event(7)

    result = await middleware(handler, event, {"settings": settings})

    handler.assert_not_awaited()
    assert result is None


def test_dispatcher_has_access_middleware_on_messages_and_callbacks():
    dispatcher = build_dispatcher()

    message_middlewares = dispatcher.message.outer_middleware._middlewares
    callback_middlewares = dispatcher.callback_query.outer_middleware._middlewares

    assert any(isinstance(middleware, AccessMiddleware) for middleware in message_middlewares)
    assert any(isinstance(middleware, AccessMiddleware) for middleware in callback_middlewares)
