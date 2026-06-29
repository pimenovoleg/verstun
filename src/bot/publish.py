import structlog
from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from aiogram.types import (
    CallbackQuery,
    InaccessibleMessage,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputRichMessage,
    Message,
)

from src.bot import common, texts
from src.bot.storage import BotStateError, ConnectedChannel
from src.config import Settings

log = structlog.get_logger()


async def handle_publish_callback(callback: CallbackQuery, bot: Bot, settings: Settings) -> None:
    post_message_id, channel_id = _parse_publish_callback(callback.data or "")
    if post_message_id is None or channel_id is None:
        await callback.answer(texts.POST_BUTTON_STALE, show_alert=True)
        return
    if callback.message is None or isinstance(callback.message, InaccessibleMessage):
        await callback.answer(texts.POST_BUTTON_STALE, show_alert=True)
        return
    if not common._is_private_chat(callback.message):
        await callback.answer(texts.PUBLISH_PRIVATE_REQUIRED, show_alert=True)
        return

    try:
        store = common._store(settings)
        html = store.get_post(callback.message.chat.id, post_message_id)
        channel = store.get_channel(channel_id)
    except BotStateError:
        await _show_publish_result(callback.message, texts.STATE_READ_ERROR, post_message_id)
        return
    if html is None or channel is None:
        await callback.answer(texts.POST_BUTTON_STALE, show_alert=True)
        return
    try:
        can_publish = common._can_publish_to_channel(
            settings, common._actor_id(callback), channel_id
        )
    except BotStateError:
        await _show_publish_result(callback.message, texts.STATE_READ_ERROR, post_message_id)
        return
    if not can_publish:
        await callback.answer(texts.PUBLISH_NO_ACCESS, show_alert=True)
        return

    try:
        publish_started = store.begin_publish(
            private_chat_id=callback.message.chat.id,
            post_message_id=post_message_id,
            channel_id=channel_id,
        )
    except BotStateError:
        await _show_publish_result(callback.message, texts.STATE_READ_ERROR, post_message_id)
        return
    if not publish_started:
        await callback.answer(texts.PUBLISH_ALREADY_SENT, show_alert=True)
        return

    await callback.answer(texts.PUBLISHING, show_alert=False)
    published, result = await _publish_html(bot, channel, html)
    if not published:
        try:
            store.clear_publish(
                private_chat_id=callback.message.chat.id,
                post_message_id=post_message_id,
                channel_id=channel_id,
            )
        except BotStateError:
            log.warning("publish_marker_clear_failed", channel_id=channel_id)
    await _show_publish_result(callback.message, result, post_message_id)


async def _bot_can_post_to_channel(bot: Bot, channel_id: int) -> bool:
    try:
        # bot.me() caches get_me() for the bot's lifetime, so checking N channels
        # in a row issues one getMe call instead of one per channel.
        me = await bot.me()
        member = await bot.get_chat_member(chat_id=channel_id, user_id=me.id)
    except TelegramAPIError as exc:
        log.warning("channel_rights_check_failed", channel_id=channel_id, exc_info=exc)
        return False

    if member.status == ChatMemberStatus.CREATOR:
        return True
    return member.status == ChatMemberStatus.ADMINISTRATOR and bool(
        getattr(member, "can_post_messages", False)
    )


async def _publish_html(
    bot: Bot,
    channel: ConnectedChannel,
    html: str,
) -> tuple[bool, str]:
    try:
        if not await _bot_can_post_to_channel(bot, channel.chat_id):
            return False, texts.PUBLISH_RIGHTS_MISSING

        await bot.send_rich_message(
            chat_id=channel.chat_id,
            rich_message=InputRichMessage(html=html),
        )
    except TelegramAPIError as exc:
        log.warning("channel_publish_failed", channel_id=channel.chat_id, exc_info=exc)
        return False, texts.PUBLISH_SEND_ERROR
    return True, texts.publish_success(channel.title)


def _parse_publish_callback(data: str) -> tuple[int | None, int | None]:
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "pub":
        return None, None
    try:
        return int(parts[1]), int(parts[2])
    except ValueError:
        return None, None


async def _send_publish_controls(
    message: Message,
    bot: Bot,
    settings: Settings,
    post_message_id: int,
) -> None:
    try:
        channels = common._visible_channels(settings, common._actor_id(message))
    except BotStateError:
        await common._answer_state_error(message)
        return
    channels_with_rights = [
        channel for channel in channels if await _bot_can_post_to_channel(bot, channel.chat_id)
    ]

    if not channels_with_rights:
        if common._is_owner(settings, common._actor_id(message)):
            text = texts.OWNER_NO_PUBLISHABLE_CHANNELS
        else:
            text = texts.USER_NO_PUBLISHABLE_CHANNELS
        await message.answer(text, reply_to_message_id=post_message_id)
        return

    buttons = [
        [
            InlineKeyboardButton(
                text=texts.publish_channel_button(channel.title),
                callback_data=f"pub:{post_message_id}:{channel.chat_id}",
            )
        ]
        for channel in channels_with_rights
    ]
    try:
        sent = await message.answer(
            _publish_controls_text(),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            reply_to_message_id=post_message_id,
        )
    except TelegramAPIError as exc:
        log.warning("publish_controls_send_failed", post_message_id=post_message_id, exc_info=exc)
        await _send_reply_message(
            message,
            texts.PUBLISH_CONTROLS_SEND_ERROR,
            reply_to_message_id=post_message_id,
        )
        return
    private_chat_id = getattr(getattr(message, "chat", None), "id", None)
    controls_message_id = getattr(sent, "message_id", None)
    if isinstance(private_chat_id, int) and isinstance(controls_message_id, int):
        try:
            common._store(settings).save_active_controls(
                private_chat_id=private_chat_id,
                post_message_id=post_message_id,
                controls_message_id=controls_message_id,
            )
        except BotStateError:
            log.warning("active_controls_save_failed", message_id=controls_message_id)


def _publish_controls_text(result: str | None = None) -> str:
    text = texts.PUBLISH_CONTROLS_PROMPT
    if result:
        text = f"{text}\n\n{result}"
    return text


async def _show_publish_result(
    message: Message,
    result: str,
    post_message_id: int | None,
) -> None:
    reply_to_message_id = post_message_id or _reply_to_message_id(message)
    await _send_reply_message(message, result, reply_to_message_id=reply_to_message_id)


async def _send_reply_message(
    message: Message,
    text: str,
    reply_to_message_id: int | None,
) -> None:
    try:
        if reply_to_message_id is None:
            await message.answer(text)
        else:
            await message.answer(text, reply_to_message_id=reply_to_message_id)
    except TelegramAPIError:
        log.warning("reply_message_send_failed")
        try:
            await message.answer(text)
        except TelegramAPIError:
            log.warning("reply_message_fallback_failed")


def _reply_to_message_id(message: Message) -> int | None:
    reply_to_message = getattr(message, "reply_to_message", None)
    message_id = getattr(reply_to_message, "message_id", None)
    return message_id if isinstance(message_id, int) else None


async def _deactivate_previous_controls(
    bot: Bot,
    settings: Settings,
    private_chat_id: int,
) -> None:
    try:
        active = common._store(settings).pop_active_controls(private_chat_id)
    except BotStateError:
        return
    if active is None:
        return
    _, controls_message_id = active
    try:
        await bot.edit_message_reply_markup(
            chat_id=private_chat_id,
            message_id=controls_message_id,
            reply_markup=None,
        )
    except TelegramAPIError:
        log.warning("active_controls_deactivate_failed", message_id=controls_message_id)
