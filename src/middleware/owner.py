from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from src.bot.storage import BotStateError, BotStateStore


class AccessMiddleware(BaseMiddleware):
    """Outer middleware that drops updates from users without bot access.

    The owner passes always. Other users pass only after the owner adds them
    through the JSON-backed user list. Unknown users are ignored silently.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        owner_id = data["settings"].owner_telegram_id
        if owner_id is None:
            return None
        user = getattr(event, "from_user", None)
        if user is None:
            return None
        if user.id == owner_id:
            return await handler(event, data)
        try:
            is_allowed = BotStateStore(data["settings"].data_dir).is_allowed_user(user.id)
        except BotStateError:
            return None
        if not is_allowed:
            return None
        return await handler(event, data)


OwnerOnlyMiddleware = AccessMiddleware
