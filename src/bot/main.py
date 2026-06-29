import os

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart

from src.bot import texts
from src.bot.basic import _save_demo_image, handle_demo, start
from src.bot.channels import (
    _handle_channel_action,
    _start_connect_from_callback,
    handle_channel_callback,
    handle_channels,
    handle_forwarded_channel,
)
from src.bot.common import (
    _BLANK_SPACERS_CALLBACK,
    _CHANNELS_PAGE_SIZE,
    _MAX_HTML_CHARS,
    _MAX_IMAGE_B64_BYTES,
    _MAX_IMAGES_PER_MESSAGE,
    _MAX_UPLOAD_BYTES,
    _USERS_PAGE_SIZE,
    USER_PICKER_REQUEST_ID,
    _actor_id,
    _answer_private_chat_required,
    _answer_state_error,
    _can_publish_to_channel,
    _drop_managed_owner,
    _int_or_none,
    _int_or_zero,
    _is_owner,
    _is_private_chat,
    _paginate,
    _store,
    _visible_channels,
)
from src.bot.document import handle_document, markdown_to_rich_html
from src.bot.keyboards import (
    _button_rows,
    _channel_delete_list_view,
    _channels_overview_text,
    _channels_owner_markup,
    _nav_rows,
    _settings_markup,
    _user_button_label,
    _user_card_view,
    _users_list_view,
)
from src.bot.publish import (
    _bot_can_post_to_channel,
    _deactivate_previous_controls,
    _parse_publish_callback,
    _publish_controls_text,
    _publish_html,
    _reply_to_message_id,
    _send_publish_controls,
    _send_reply_message,
    _show_publish_result,
    handle_publish_callback,
)
from src.bot.settings import handle_settings_callback, handle_settings_command
from src.bot.users import (
    _handle_users_action,
    handle_user_picker_shared,
    handle_users_callback,
    handle_users_command,
)
from src.config import Settings
from src.middleware import AccessMiddleware

__all__ = [
    "USER_PICKER_REQUEST_ID",
    "_BLANK_SPACERS_CALLBACK",
    "_CHANNELS_PAGE_SIZE",
    "_MAX_HTML_CHARS",
    "_MAX_IMAGE_B64_BYTES",
    "_MAX_IMAGES_PER_MESSAGE",
    "_MAX_UPLOAD_BYTES",
    "_USERS_PAGE_SIZE",
    "_actor_id",
    "_answer_private_chat_required",
    "_answer_state_error",
    "_bot_can_post_to_channel",
    "_button_rows",
    "_can_publish_to_channel",
    "_channel_delete_list_view",
    "_channels_overview_text",
    "_channels_owner_markup",
    "_deactivate_previous_controls",
    "_drop_managed_owner",
    "_handle_channel_action",
    "_handle_users_action",
    "_int_or_none",
    "_int_or_zero",
    "_is_owner",
    "_is_private_chat",
    "_nav_rows",
    "_paginate",
    "_parse_publish_callback",
    "_publish_controls_text",
    "_publish_html",
    "_register_bot_commands",
    "_reply_to_message_id",
    "_save_demo_image",
    "_send_publish_controls",
    "_send_reply_message",
    "_settings_markup",
    "_show_publish_result",
    "_start_connect_from_callback",
    "_store",
    "_user_button_label",
    "_user_card_view",
    "_users_list_view",
    "_visible_channels",
    "build_dispatcher",
    "dp",
    "handle_channel_callback",
    "handle_channels",
    "handle_demo",
    "handle_document",
    "handle_forwarded_channel",
    "handle_publish_callback",
    "handle_settings_callback",
    "handle_settings_command",
    "handle_user_picker_shared",
    "handle_users_callback",
    "handle_users_command",
    "markdown_to_rich_html",
    "run_polling",
    "start",
]

dp = Dispatcher()
dp.message.outer_middleware(AccessMiddleware())
dp.callback_query.outer_middleware(AccessMiddleware())

dp.message(CommandStart())(start)
dp.message(Command("demo"))(handle_demo)
dp.message(Command("users"))(handle_users_command)
dp.message(F.users_shared)(handle_user_picker_shared)
dp.message(Command("channels"))(handle_channels)
dp.message(Command("settings"))(handle_settings_command)
dp.message(F.forward_origin)(handle_forwarded_channel)
dp.message(F.document)(handle_document)

dp.callback_query(F.data.startswith("pub:"))(handle_publish_callback)
dp.callback_query(F.data.startswith("usr:"))(handle_users_callback)
dp.callback_query(F.data.startswith("chan:"))(handle_channel_callback)
dp.callback_query(F.data.startswith("set:"))(handle_settings_callback)


def build_dispatcher() -> Dispatcher:
    return dp


async def run_polling(bot: Bot, settings: Settings) -> None:
    os.makedirs(settings.data_dir, exist_ok=True)
    os.makedirs(settings.media_dir, exist_ok=True)
    await _register_bot_commands(bot)
    await dp.start_polling(bot, settings=settings)


async def _register_bot_commands(bot: Bot) -> None:
    await bot.set_my_commands(texts.BOT_COMMANDS)
