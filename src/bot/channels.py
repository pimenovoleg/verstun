from aiogram import Bot
from aiogram.types import CallbackQuery, InaccessibleMessage, Message, MessageOriginChannel

from src.bot import common, texts
from src.bot.keyboards import (
    _channel_delete_list_view,
    _channels_overview_text,
    _channels_owner_markup,
)
from src.bot.publish import _bot_can_post_to_channel
from src.bot.storage import BotStateError, BotStateStore
from src.config import Settings


async def handle_channels(message: Message, settings: Settings) -> None:
    if not common._is_private_chat(message):
        await common._answer_private_chat_required(message)
        return
    try:
        channels = common._visible_channels(settings, common._actor_id(message))
    except BotStateError:
        await common._answer_state_error(message)
        return
    if not channels:
        if common._is_owner(settings, common._actor_id(message)):
            await message.answer(texts.CHANNELS_EMPTY, reply_markup=_channels_owner_markup(False))
        else:
            await message.answer(texts.NO_GRANTED_CHANNELS)
        return

    reply_markup = (
        _channels_owner_markup(True)
        if common._is_owner(settings, common._actor_id(message))
        else None
    )
    if reply_markup is None:
        await message.answer(_channels_overview_text(channels))
    else:
        await message.answer(_channels_overview_text(channels), reply_markup=reply_markup)


async def handle_forwarded_channel(message: Message, bot: Bot, settings: Settings) -> None:
    if not common._is_owner(settings, common._actor_id(message)):
        return
    if not common._is_private_chat(message):
        await common._answer_private_chat_required(message)
        return
    store = common._store(settings)
    try:
        is_pending = store.is_connect_pending()
    except BotStateError:
        await common._answer_state_error(message)
        return
    if not is_pending:
        return

    origin = message.forward_origin
    if not isinstance(origin, MessageOriginChannel):
        await message.answer(texts.CHANNEL_FORWARD_REQUIRED)
        return

    if not await _bot_can_post_to_channel(bot, origin.chat.id):
        await message.answer(texts.CHANNEL_POSTING_RIGHTS_MISSING)
        return

    title = origin.chat.title or str(origin.chat.id)
    try:
        store.save_channel(chat_id=origin.chat.id, title=title, username=origin.chat.username)
        store.set_connect_pending(False)
    except BotStateError:
        await common._answer_state_error(message)
        return
    await message.answer(texts.channel_connected(title))


async def handle_channel_callback(callback: CallbackQuery, settings: Settings) -> None:
    if not common._is_owner(settings, common._actor_id(callback)):
        return
    if callback.message is None or isinstance(callback.message, InaccessibleMessage):
        await callback.answer(texts.CHANNELS_MENU_STALE, show_alert=True)
        return
    if not common._is_private_chat(callback.message):
        await callback.answer(texts.CHANNELS_PRIVATE_REQUIRED, show_alert=True)
        return
    data = callback.data or ""
    if data == "chan:connect":
        await _start_connect_from_callback(callback, settings)
        return

    try:
        text, markup = _handle_channel_action(common._store(settings), data)
    except BotStateError:
        await callback.message.edit_text(texts.STATE_READ_ERROR)
        return

    if text is None or markup is None:
        await callback.answer(texts.CHANNELS_MENU_STALE, show_alert=True)
        return

    await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer()


async def _start_connect_from_callback(callback: CallbackQuery, settings: Settings) -> None:
    try:
        common._store(settings).set_connect_pending(True)
    except BotStateError:
        await callback.message.answer(texts.STATE_READ_ERROR)
        await callback.answer(texts.STATE_READ_ERROR, show_alert=True)
        return
    await callback.message.answer(texts.CONNECT_TEXT)
    await callback.answer()


def _handle_channel_action(
    store: BotStateStore,
    data: str,
):
    parts = data.split(":")
    if len(parts) == 3 and parts[:2] == ["chan", "list"]:
        return _channel_delete_list_view(store, common._int_or_zero(parts[2]))
    if len(parts) == 4 and parts[:2] == ["chan", "drop"]:
        channel_id = common._int_or_none(parts[2])
        if channel_id is None:
            return None, None
        channel = store.get_channel(channel_id)
        if channel is None:
            return _channel_delete_list_view(store, common._int_or_zero(parts[3]))
        store.delete_channel(channel_id)
        text, markup = _channel_delete_list_view(store, common._int_or_zero(parts[3]))
        return f"{texts.channel_disconnected(channel.title)}\n\n{text}", markup
    if len(parts) == 2 and parts == ["chan", "back"]:
        channels = store.list_channels()
        if not channels:
            return texts.CHANNELS_EMPTY, _channels_owner_markup(False)
        return _channels_overview_text(channels), _channels_owner_markup(True)
    if len(parts) == 2 and parts == ["chan", "noop"]:
        return None, None
    return None, None
