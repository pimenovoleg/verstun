import os
from base64 import b64encode
from importlib import resources

import structlog
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InaccessibleMessage,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputRichMessage,
    KeyboardButton,
    KeyboardButtonRequestUsers,
    Message,
    MessageOriginChannel,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from src.bot import texts
from src.bot.storage import BotStateError, BotStateStore, ConnectedChannel, ManagedUser
from src.config import Settings
from src.middleware import AccessMiddleware
from src.post import MediaStore, markdown_to_rich_html

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

log = structlog.get_logger()

dp = Dispatcher()
dp.message.outer_middleware(AccessMiddleware())
dp.callback_query.outer_middleware(AccessMiddleware())


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


@dp.message(CommandStart())
async def start(message: Message) -> None:
    await message.answer(texts.START_TEXT)


@dp.message(Command("demo"))
async def handle_demo(message: Message, settings: Settings) -> None:
    media_store = MediaStore(
        media_dir=settings.media_dir,
        media_base_url=settings.media_base_url,
        media_max_bytes=settings.media_max_bytes,
        max_image_bytes=_MAX_IMAGE_B64_BYTES,
        max_images_per_message=_MAX_IMAGES_PER_MESSAGE,
    )
    demo_image_url = _save_demo_image(media_store)
    demo_image_block = ""
    if demo_image_url:
        demo_image_block = f'<p><img src="{demo_image_url}"></p>'
    html = texts.DEMO_HTML.format(demo_image=demo_image_block)
    await message.answer_rich(InputRichMessage(html=html))


def _save_demo_image(media_store: MediaStore) -> str | None:
    image = resources.files("src.bot").joinpath("assets/demo-image.jpg").read_bytes()
    return media_store.save(b64encode(image).decode("ascii"))


@dp.message(Command("users"))
async def handle_users_command(message: Message, settings: Settings) -> None:
    if not _is_owner(settings, _actor_id(message)):
        return
    if not _is_private_chat(message):
        await _answer_private_chat_required(message)
        return
    try:
        store = _store(settings)
        _drop_managed_owner(store, settings)
        text, markup = _users_list_view(store, page=0)
    except BotStateError:
        await _answer_state_error(message)
        return
    await message.answer(text, reply_markup=markup)


@dp.message(F.users_shared)
async def handle_user_picker_shared(message: Message, settings: Settings) -> None:
    if not _is_owner(settings, _actor_id(message)):
        return
    if not _is_private_chat(message):
        await _answer_private_chat_required(message)
        return

    shared = message.users_shared
    if shared is None or shared.request_id != USER_PICKER_REQUEST_ID or not shared.users:
        return

    user = shared.users[0]
    if _is_owner(settings, user.user_id):
        try:
            _drop_managed_owner(_store(settings), settings)
        except BotStateError:
            await _answer_state_error(message)
            return
        await message.answer(
            texts.USER_IS_OWNER,
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    name_parts = [part for part in (user.first_name, user.last_name) if part]
    name = " ".join(name_parts) or user.username or str(user.user_id)

    try:
        store = _store(settings)
        existing = store.get_user(user.user_id)
        store.save_user(telegram_id=user.user_id, name=name, username=user.username)
        text, markup = _user_card_view(store, telegram_id=user.user_id, user_page=0, channel_page=0)
    except BotStateError:
        await _answer_state_error(message)
        return

    status_text = texts.USER_ALREADY_ADDED if existing else texts.USER_ADDED
    await message.answer(status_text, reply_markup=ReplyKeyboardRemove())
    await message.answer(text, reply_markup=markup)


@dp.message(Command("channels"))
async def handle_channels(message: Message, settings: Settings) -> None:
    if not _is_private_chat(message):
        await _answer_private_chat_required(message)
        return
    try:
        channels = _visible_channels(settings, _actor_id(message))
    except BotStateError:
        await _answer_state_error(message)
        return
    if not channels:
        if _is_owner(settings, _actor_id(message)):
            await message.answer(texts.CHANNELS_EMPTY, reply_markup=_channels_owner_markup(False))
        else:
            await message.answer(texts.NO_GRANTED_CHANNELS)
        return

    reply_markup = _channels_owner_markup(True) if _is_owner(settings, _actor_id(message)) else None
    if reply_markup is None:
        await message.answer(_channels_overview_text(channels))
    else:
        await message.answer(_channels_overview_text(channels), reply_markup=reply_markup)


@dp.message(F.forward_origin)
async def handle_forwarded_channel(message: Message, bot: Bot, settings: Settings) -> None:
    if not _is_owner(settings, _actor_id(message)):
        return
    if not _is_private_chat(message):
        await _answer_private_chat_required(message)
        return
    store = _store(settings)
    try:
        is_pending = store.is_connect_pending()
    except BotStateError:
        await _answer_state_error(message)
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
        await _answer_state_error(message)
        return
    await message.answer(texts.channel_connected(title))


@dp.callback_query(F.data.startswith("pub:"))
async def handle_publish_callback(callback: CallbackQuery, bot: Bot, settings: Settings) -> None:
    post_message_id, channel_id = _parse_publish_callback(callback.data or "")
    if post_message_id is None or channel_id is None:
        await callback.answer(texts.POST_BUTTON_STALE, show_alert=True)
        return
    if callback.message is None or isinstance(callback.message, InaccessibleMessage):
        await callback.answer(texts.POST_BUTTON_STALE, show_alert=True)
        return
    if not _is_private_chat(callback.message):
        await callback.answer(texts.PUBLISH_PRIVATE_REQUIRED, show_alert=True)
        return

    try:
        store = _store(settings)
        html = store.get_post(callback.message.chat.id, post_message_id)
        channel = store.get_channel(channel_id)
    except BotStateError:
        await _show_publish_result(callback.message, texts.STATE_READ_ERROR, post_message_id)
        return
    if html is None or channel is None:
        await callback.answer(texts.POST_BUTTON_STALE, show_alert=True)
        return
    try:
        can_publish = _can_publish_to_channel(settings, _actor_id(callback), channel_id)
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


@dp.callback_query(F.data.startswith("usr:"))
async def handle_users_callback(callback: CallbackQuery, settings: Settings) -> None:
    if not _is_owner(settings, _actor_id(callback)):
        return
    if callback.message is None or isinstance(callback.message, InaccessibleMessage):
        await callback.answer(texts.USERS_MENU_STALE, show_alert=True)
        return
    if not _is_private_chat(callback.message):
        await callback.answer(texts.USERS_PRIVATE_REQUIRED, show_alert=True)
        return

    try:
        store = _store(settings)
        _drop_managed_owner(store, settings)
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
                                request_id=USER_PICKER_REQUEST_ID,
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


@dp.callback_query(F.data.startswith("chan:"))
async def handle_channel_callback(callback: CallbackQuery, settings: Settings) -> None:
    if not _is_owner(settings, _actor_id(callback)):
        return
    if callback.message is None or isinstance(callback.message, InaccessibleMessage):
        await callback.answer(texts.CHANNELS_MENU_STALE, show_alert=True)
        return
    if not _is_private_chat(callback.message):
        await callback.answer(texts.CHANNELS_PRIVATE_REQUIRED, show_alert=True)
        return
    data = callback.data or ""
    if data == "chan:connect":
        await _start_connect_from_callback(callback, settings)
        return

    try:
        text, markup = _handle_channel_action(_store(settings), data)
    except BotStateError:
        await callback.message.edit_text(texts.STATE_READ_ERROR)
        return

    if text is None or markup is None:
        await callback.answer(texts.CHANNELS_MENU_STALE, show_alert=True)
        return

    await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer()


@dp.message(F.document)
async def handle_document(message: Message, bot: Bot, settings: Settings) -> None:
    if not _is_private_chat(message):
        await message.answer(texts.DOCUMENT_PRIVATE_REQUIRED)
        return

    document = message.document

    file_name = (document.file_name or "").lower()
    mime_type = document.mime_type or ""
    is_md = file_name.endswith(".md") or mime_type in ("text/markdown", "text/x-markdown")
    if not is_md:
        await message.answer(texts.DOCUMENT_MD_REQUIRED)
        return

    if document.file_size is not None and document.file_size > _MAX_UPLOAD_BYTES:
        await message.answer(texts.DOCUMENT_TOO_LARGE)
        return

    try:
        buffer = await bot.download(document)
    except TelegramAPIError as exc:
        log.warning("document_download_failed", exc_info=exc)
        await message.answer(texts.DOCUMENT_DOWNLOAD_ERROR)
        return
    raw = buffer.read() if buffer is not None else b""

    # Defense-in-depth: re-check the actual downloaded size against the same cap.
    # file_size may be absent or understated, so the pre-download check alone
    # cannot bound what we hold in memory.
    if len(raw) > _MAX_UPLOAD_BYTES:
        await message.answer(texts.DOCUMENT_TOO_LARGE)
        return

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        await message.answer(texts.DOCUMENT_READ_ERROR)
        return

    if not text.strip():
        await message.answer(texts.DOCUMENT_EMPTY)
        return

    media_store = MediaStore(
        media_dir=settings.media_dir,
        media_base_url=settings.media_base_url,
        media_max_bytes=settings.media_max_bytes,
        max_image_bytes=_MAX_IMAGE_B64_BYTES,
        max_images_per_message=_MAX_IMAGES_PER_MESSAGE,
    )
    html, failed_media_indices = markdown_to_rich_html(text, media_store)

    # Cap the post body itself, before appending the failed-media notice — the
    # notice must never push a borderline post over the limit and silence it.
    if len(html) > _MAX_HTML_CHARS:
        await message.answer(texts.POST_TOO_LONG)
        return

    failed_media_text = (
        texts.failed_media_notice(failed_media_indices) if failed_media_indices else None
    )

    private_chat_id = getattr(getattr(message, "chat", None), "id", None)
    if isinstance(private_chat_id, int):
        await _deactivate_previous_controls(bot, settings, private_chat_id)

    try:
        sent = await message.answer_rich(InputRichMessage(html=html))
    except TelegramAPIError as exc:
        log.warning("rich_message_send_failed", exc_info=exc)
        await message.answer(texts.POST_SEND_ERROR)
        return
    sent_message_id = getattr(sent, "message_id", None)
    if failed_media_text and isinstance(sent_message_id, int):
        await _send_reply_message(message, failed_media_text, reply_to_message_id=sent_message_id)
    saved = False
    if isinstance(sent_message_id, int) and isinstance(private_chat_id, int):
        try:
            _store(settings).save_post(
                private_chat_id=private_chat_id,
                message_id=sent_message_id,
                html=html,
            )
            saved = True
        except BotStateError:
            log.warning("sent_post_cache_save_failed", message_id=sent_message_id)
    if saved:
        await _send_publish_controls(message, bot, settings, sent_message_id)


async def _bot_can_post_to_channel(bot: Bot, channel_id: int) -> bool:
    try:
        me = await bot.get_me()
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
        channels = _visible_channels(settings, _actor_id(message))
    except BotStateError:
        await _answer_state_error(message)
        return
    channels_with_rights = [
        channel for channel in channels if await _bot_can_post_to_channel(bot, channel.chat_id)
    ]

    if not channels_with_rights:
        if _is_owner(settings, _actor_id(message)):
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
            _store(settings).save_active_controls(
                private_chat_id=private_chat_id,
                post_message_id=post_message_id,
                controls_message_id=controls_message_id,
            )
        except BotStateError:
            log.warning("active_controls_save_failed", message_id=controls_message_id)


def build_dispatcher() -> Dispatcher:
    return dp


async def _start_connect_from_callback(callback: CallbackQuery, settings: Settings) -> None:
    try:
        _store(settings).set_connect_pending(True)
    except BotStateError:
        await callback.message.answer(texts.STATE_READ_ERROR)
        await callback.answer(texts.STATE_READ_ERROR, show_alert=True)
        return
    await callback.message.answer(texts.CONNECT_TEXT)
    await callback.answer()


def _channels_overview_text(channels: list[ConnectedChannel]) -> str:
    return texts.channels_overview([channel.title for channel in channels])


def _channels_owner_markup(has_channels: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=texts.BUTTON_CONNECT_CHANNEL, callback_data="chan:connect")]]
    if has_channels:
        rows.append(
            [
                InlineKeyboardButton(
                    text=texts.BUTTON_DISCONNECT_CHANNEL, callback_data="chan:list:0"
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _handle_channel_action(
    store: BotStateStore,
    data: str,
) -> tuple[str | None, InlineKeyboardMarkup | None]:
    parts = data.split(":")
    if len(parts) == 3 and parts[:2] == ["chan", "list"]:
        return _channel_delete_list_view(store, _int_or_zero(parts[2]))
    if len(parts) == 4 and parts[:2] == ["chan", "drop"]:
        channel_id = _int_or_none(parts[2])
        if channel_id is None:
            return None, None
        channel = store.get_channel(channel_id)
        if channel is None:
            return _channel_delete_list_view(store, _int_or_zero(parts[3]))
        store.delete_channel(channel_id)
        text, markup = _channel_delete_list_view(store, _int_or_zero(parts[3]))
        return f"{texts.channel_disconnected(channel.title)}\n\n{text}", markup
    if len(parts) == 2 and parts == ["chan", "back"]:
        channels = store.list_channels()
        if not channels:
            return texts.CHANNELS_EMPTY, _channels_owner_markup(False)
        return _channels_overview_text(channels), _channels_owner_markup(True)
    if len(parts) == 2 and parts == ["chan", "noop"]:
        return None, None
    return None, None


def _channel_delete_list_view(
    store: BotStateStore,
    page: int,
) -> tuple[str, InlineKeyboardMarkup]:
    channels = store.list_channels()
    page_items, page, pages = _paginate(channels, page, _CHANNELS_PAGE_SIZE)
    if not channels:
        return texts.CHANNELS_EMPTY, _channels_owner_markup(False)

    rows = []
    for row in _button_rows(
        [
            InlineKeyboardButton(
                text=texts.channel_delete_button(channel.title),
                callback_data=f"chan:drop:{channel.chat_id}:{page}",
            )
            for channel in page_items
        ]
    ):
        rows.append(row)
    rows.extend(_nav_rows(prefix="chan:list", page=page, pages=pages))
    rows.append([InlineKeyboardButton(text=texts.BUTTON_BACK, callback_data="chan:back")])
    return texts.CHANNEL_DELETE_PROMPT, InlineKeyboardMarkup(inline_keyboard=rows)


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


async def _deactivate_previous_controls(
    bot: Bot,
    settings: Settings,
    private_chat_id: int,
) -> None:
    try:
        active = _store(settings).pop_active_controls(private_chat_id)
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


def _handle_users_action(
    store: BotStateStore,
    data: str,
) -> tuple[str | None, InlineKeyboardMarkup | None]:
    parts = data.split(":")
    if parts == ["usr", "add"]:
        return "add", InlineKeyboardMarkup(inline_keyboard=[])
    if len(parts) == 3 and parts[:2] == ["usr", "list"]:
        return _users_list_view(store, _int_or_zero(parts[2]))
    if len(parts) == 5 and parts[:2] == ["usr", "view"]:
        user_id = _int_or_none(parts[2])
        if user_id is None:
            return None, None
        return _user_card_view(store, user_id, _int_or_zero(parts[3]), _int_or_zero(parts[4]))
    if len(parts) == 4 and parts[:2] == ["usr", "del"]:
        user_id = _int_or_none(parts[2])
        if user_id is None:
            return None, None
        store.delete_user(user_id)
        return _users_list_view(store, _int_or_zero(parts[3]))
    if len(parts) == 6 and parts[:2] == ["usr", "toggle"]:
        user_id = _int_or_none(parts[2])
        channel_id = _int_or_none(parts[3])
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
        return _user_card_view(store, user_id, _int_or_zero(parts[5]), _int_or_zero(parts[4]))
    if len(parts) == 2 and parts == ["usr", "noop"]:
        return None, None
    return None, None


def _users_list_view(store: BotStateStore, page: int) -> tuple[str, InlineKeyboardMarkup]:
    users = store.list_users()
    page_items, page, pages = _paginate(users, page, _USERS_PAGE_SIZE)
    rows = [[InlineKeyboardButton(text=texts.BUTTON_ADD_USER, callback_data="usr:add")]]
    for row in _button_rows(
        [
            InlineKeyboardButton(
                text=_user_button_label(user),
                callback_data=f"usr:view:{user.telegram_id}:{page}:0",
            )
            for user in page_items
        ]
    ):
        rows.append(row)
    rows.extend(_nav_rows(prefix="usr:list", page=page, pages=pages))
    return texts.users_list_text(has_users=bool(users)), InlineKeyboardMarkup(inline_keyboard=rows)


def _user_card_view(
    store: BotStateStore,
    telegram_id: int,
    user_page: int,
    channel_page: int,
) -> tuple[str | None, InlineKeyboardMarkup | None]:
    user = store.get_user(telegram_id)
    if user is None:
        return None, None
    channels = store.list_channels()
    page_items, channel_page, pages = _paginate(channels, channel_page, _CHANNELS_PAGE_SIZE)
    rows = []
    for row in _button_rows(
        [
            InlineKeyboardButton(
                text=texts.user_channel_access_button(
                    title=channel.title,
                    allowed=channel.chat_id in user.channel_ids,
                ),
                callback_data=(
                    f"usr:toggle:{user.telegram_id}:{channel.chat_id}:{channel_page}:{user_page}"
                ),
            )
            for channel in page_items
        ]
    ):
        rows.append(row)
    rows.extend(
        _nav_rows(
            prefix=f"usr:view:{user.telegram_id}:{user_page}",
            page=channel_page,
            pages=pages,
        )
    )
    rows.append(
        [
            InlineKeyboardButton(
                text=texts.BUTTON_DELETE_USER, callback_data=f"usr:del:{telegram_id}:{user_page}"
            )
        ]
    )
    rows.append(
        [InlineKeyboardButton(text=texts.BUTTON_BACK, callback_data=f"usr:list:{user_page}")]
    )
    text = texts.user_card_text(
        name=user.name,
        telegram_id=user.telegram_id,
        username=user.username,
        has_channels=bool(channels),
    )
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def _button_rows(buttons: list[InlineKeyboardButton]) -> list[list[InlineKeyboardButton]]:
    return [buttons[index : index + 3] for index in range(0, len(buttons), 3)]


def _nav_rows(prefix: str, page: int, pages: int) -> list[list[InlineKeyboardButton]]:
    if pages <= 1:
        return []
    row = []
    if page > 0:
        row.append(InlineKeyboardButton(text="<", callback_data=f"{prefix}:{page - 1}"))
    noop_prefix = prefix.split(":", 1)[0]
    row.append(
        InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data=f"{noop_prefix}:noop")
    )
    if page < pages - 1:
        row.append(InlineKeyboardButton(text=">", callback_data=f"{prefix}:{page + 1}"))
    return [row]


def _paginate[T](items: list[T], page: int, page_size: int) -> tuple[list[T], int, int]:
    pages = max(1, (len(items) + page_size - 1) // page_size)
    page = min(max(page, 0), pages - 1)
    start = page * page_size
    return items[start : start + page_size], page, pages


def _user_button_label(user: ManagedUser) -> str:
    suffix = f" (@{user.username})" if user.username else ""
    return f"{user.name}{suffix}"


def _int_or_none(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def _int_or_zero(value: str) -> int:
    parsed = _int_or_none(value)
    return parsed if parsed is not None else 0


async def run_polling(bot: Bot, settings: Settings) -> None:
    os.makedirs(settings.data_dir, exist_ok=True)
    os.makedirs(settings.media_dir, exist_ok=True)
    await _register_bot_commands(bot)
    await dp.start_polling(bot, settings=settings)


async def _register_bot_commands(bot: Bot) -> None:
    await bot.set_my_commands(texts.BOT_COMMANDS)
