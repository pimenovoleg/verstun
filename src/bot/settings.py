from aiogram.types import CallbackQuery, InaccessibleMessage, Message

from src.bot import common, texts
from src.bot.keyboards import _settings_markup
from src.bot.storage import BotStateError
from src.config import Settings


async def handle_settings_command(message: Message, settings: Settings) -> None:
    if not common._is_owner(settings, common._actor_id(message)):
        return
    if not common._is_private_chat(message):
        await common._answer_private_chat_required(message)
        return
    try:
        add_blank_spacers = common._store(settings).get_add_blank_spacers()
    except BotStateError:
        await common._answer_state_error(message)
        return
    await message.answer(
        texts.settings_text(add_blank_spacers),
        reply_markup=_settings_markup(add_blank_spacers),
    )


async def handle_settings_callback(callback: CallbackQuery, settings: Settings) -> None:
    if not common._is_owner(settings, common._actor_id(callback)):
        return
    if callback.message is None or isinstance(callback.message, InaccessibleMessage):
        await callback.answer(texts.SETTINGS_MENU_STALE, show_alert=True)
        return
    if not common._is_private_chat(callback.message):
        await callback.answer(texts.SETTINGS_PRIVATE_REQUIRED, show_alert=True)
        return
    if (callback.data or "") != common._BLANK_SPACERS_CALLBACK:
        await callback.answer(texts.SETTINGS_MENU_STALE, show_alert=True)
        return

    try:
        store = common._store(settings)
        add_blank_spacers = not store.get_add_blank_spacers()
        store.set_add_blank_spacers(add_blank_spacers)
    except BotStateError:
        await callback.message.edit_text(texts.STATE_READ_ERROR)
        return

    await callback.message.edit_text(
        texts.settings_text(add_blank_spacers),
        reply_markup=_settings_markup(add_blank_spacers),
    )
    await callback.answer()
