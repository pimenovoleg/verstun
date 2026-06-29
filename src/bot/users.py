from aiogram.types import (
    CallbackQuery,
    InaccessibleMessage,
    InlineKeyboardMarkup,
    KeyboardButton,
    KeyboardButtonRequestUsers,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from src.bot import common, texts
from src.bot.keyboards import _user_card_view, _users_list_view
from src.bot.storage import BotStateError, BotStateStore
from src.config import Settings


async def handle_users_command(message: Message, settings: Settings) -> None:
    if not common._is_owner(settings, common._actor_id(message)):
        return
    if not common._is_private_chat(message):
        await common._answer_private_chat_required(message)
        return
    try:
        store = common._store(settings)
        common._drop_managed_owner(store, settings)
        text, markup = _users_list_view(store, page=0)
    except BotStateError:
        await common._answer_state_error(message)
        return
    await message.answer(text, reply_markup=markup)


async def handle_user_picker_shared(message: Message, settings: Settings) -> None:
    if not common._is_owner(settings, common._actor_id(message)):
        return
    if not common._is_private_chat(message):
        await common._answer_private_chat_required(message)
        return

    shared = message.users_shared
    if shared is None or shared.request_id != common.USER_PICKER_REQUEST_ID or not shared.users:
        return

    user = shared.users[0]
    if common._is_owner(settings, user.user_id):
        try:
            common._drop_managed_owner(common._store(settings), settings)
        except BotStateError:
            await common._answer_state_error(message)
            return
        await message.answer(
            texts.USER_IS_OWNER,
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    name_parts = [part for part in (user.first_name, user.last_name) if part]
    name = " ".join(name_parts) or user.username or str(user.user_id)

    try:
        store = common._store(settings)
        existing = store.get_user(user.user_id)
        store.save_user(telegram_id=user.user_id, name=name, username=user.username)
        text, markup = _user_card_view(store, telegram_id=user.user_id, user_page=0, channel_page=0)
    except BotStateError:
        await common._answer_state_error(message)
        return

    status_text = texts.USER_ALREADY_ADDED if existing else texts.USER_ADDED
    await message.answer(status_text, reply_markup=ReplyKeyboardRemove())
    await message.answer(text, reply_markup=markup)


async def handle_users_callback(callback: CallbackQuery, settings: Settings) -> None:
    if not common._is_owner(settings, common._actor_id(callback)):
        return
    if callback.message is None or isinstance(callback.message, InaccessibleMessage):
        await callback.answer(texts.USERS_MENU_STALE, show_alert=True)
        return
    if not common._is_private_chat(callback.message):
        await callback.answer(texts.USERS_PRIVATE_REQUIRED, show_alert=True)
        return

    try:
        store = common._store(settings)
        common._drop_managed_owner(store, settings)
        text, markup = _handle_users_action(store, callback.data or "")
    except BotStateError:
        await callback.message.edit_text(texts.STATE_READ_ERROR)
        return

    if text is None or markup is None:
        await callback.answer(texts.USERS_MENU_STALE, show_alert=True)
        return

    if (callback.data or "") == "usr:add":
        await callback.message.answer(
            texts.USER_PICKER_PROMPT,
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[
                    [
                        KeyboardButton(
                            text=texts.USER_PICKER_BUTTON,
                            request_users=KeyboardButtonRequestUsers(
                                request_id=common.USER_PICKER_REQUEST_ID,
                                user_is_bot=False,
                                max_quantity=1,
                                request_name=True,
                                request_username=True,
                            ),
                        )
                    ]
                ],
                resize_keyboard=True,
                one_time_keyboard=True,
                is_persistent=False,
            ),
        )
        await callback.answer()
        return

    await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer()


def _handle_users_action(
    store: BotStateStore,
    data: str,
) -> tuple[str | None, InlineKeyboardMarkup | None]:
    parts = data.split(":")
    if parts == ["usr", "add"]:
        return "add", InlineKeyboardMarkup(inline_keyboard=[])
    if len(parts) == 3 and parts[:2] == ["usr", "list"]:
        return _users_list_view(store, common._int_or_zero(parts[2]))
    if len(parts) == 5 and parts[:2] == ["usr", "view"]:
        user_id = common._int_or_none(parts[2])
        if user_id is None:
            return None, None
        return _user_card_view(
            store, user_id, common._int_or_zero(parts[3]), common._int_or_zero(parts[4])
        )
    if len(parts) == 4 and parts[:2] == ["usr", "del"]:
        user_id = common._int_or_none(parts[2])
        if user_id is None:
            return None, None
        store.delete_user(user_id)
        return _users_list_view(store, common._int_or_zero(parts[3]))
    if len(parts) == 6 and parts[:2] == ["usr", "toggle"]:
        user_id = common._int_or_none(parts[2])
        channel_id = common._int_or_none(parts[3])
        if user_id is None or channel_id is None:
            return None, None
        user = store.get_user(user_id)
        if user is None:
            return None, None
        store.set_user_channel_access(
            telegram_id=user_id,
            channel_id=channel_id,
            allowed=channel_id not in user.channel_ids,
        )
        return _user_card_view(
            store, user_id, common._int_or_zero(parts[5]), common._int_or_zero(parts[4])
        )
    if len(parts) == 2 and parts == ["usr", "noop"]:
        return None, None
    return None, None
