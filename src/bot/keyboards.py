from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot import texts
from src.bot.common import _CHANNELS_PAGE_SIZE, _USERS_PAGE_SIZE, _paginate
from src.bot.storage import BotStateStore, ConnectedChannel, ManagedUser


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


def _settings_markup(add_blank_spacers: bool) -> InlineKeyboardMarkup:
    button_text = (
        texts.BUTTON_DISABLE_BLANK_SPACERS
        if add_blank_spacers
        else texts.BUTTON_ENABLE_BLANK_SPACERS
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=button_text, callback_data="set:blank_spacers:toggle")]
        ]
    )


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


def _user_button_label(user: ManagedUser) -> str:
    suffix = f" (@{user.username})" if user.username else ""
    return f"{user.name}{suffix}"
