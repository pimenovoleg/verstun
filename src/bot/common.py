from aiogram.types import CallbackQuery, Message

from src.bot import texts
from src.bot.storage import BotStateStore, ConnectedChannel
from src.config import Settings

# Telegram's sendRichMessage HTML source cap (tech-spec Decision 7).
_MAX_HTML_CHARS = 32768

# Per-upload .md size cap, checked on Document.file_size before any download so an
# oversized blob is never fetched. Well under Telegram's 20 MB get_file ceiling.
_MAX_UPLOAD_BYTES = 5 * 1024 * 1024

# MediaStore per-message limits (not config-driven). The base64 string cap is the
# ~4/3 inflation of a generous per-image decoded budget; the count cap bounds how
# many distinct images one post may host.
_MAX_IMAGE_B64_BYTES = 14 * 1024 * 1024
_MAX_IMAGES_PER_MESSAGE = 50

USER_PICKER_REQUEST_ID = 26062801
_USERS_PAGE_SIZE = 6
_CHANNELS_PAGE_SIZE = 6
_BLANK_SPACERS_CALLBACK = "set:blank_spacers:toggle"


def _store(settings: Settings) -> BotStateStore:
    return BotStateStore(settings.data_dir)


def _is_owner(settings: Settings, user_id: int | None) -> bool:
    return user_id is not None and user_id == settings.owner_telegram_id


def _actor_id(event: Message | CallbackQuery) -> int | None:
    user = getattr(event, "from_user", None)
    return getattr(user, "id", None)


def _is_private_chat(message: Message) -> bool:
    chat = getattr(message, "chat", None)
    return getattr(chat, "type", None) == "private"


def _drop_managed_owner(store: BotStateStore, settings: Settings) -> None:
    if settings.owner_telegram_id is not None:
        store.delete_user(settings.owner_telegram_id)


async def _answer_state_error(message: Message) -> None:
    await message.answer(texts.STATE_READ_ERROR)


async def _answer_private_chat_required(message: Message) -> None:
    await message.answer(texts.PRIVATE_CHAT_REQUIRED)


def _visible_channels(settings: Settings, user_id: int | None) -> list[ConnectedChannel]:
    store = _store(settings)
    if _is_owner(settings, user_id):
        return store.list_channels()
    if user_id is None:
        return []
    return store.list_channels_for_user(user_id)


def _can_publish_to_channel(settings: Settings, user_id: int | None, channel_id: int) -> bool:
    if _is_owner(settings, user_id):
        return True
    if user_id is None:
        return False
    return _store(settings).user_can_publish_to(user_id, channel_id)


def _paginate[T](items: list[T], page: int, page_size: int) -> tuple[list[T], int, int]:
    pages = max(1, (len(items) + page_size - 1) // page_size)
    page = min(max(page, 0), pages - 1)
    start = page * page_size
    return items[start : start + page_size], page, pages


def _int_or_none(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def _int_or_zero(value: str) -> int:
    parsed = _int_or_none(value)
    return parsed if parsed is not None else 0
