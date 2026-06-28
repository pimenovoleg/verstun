from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from aiogram.methods import SendRichMessage
from aiogram.types import (
    Chat,
    ChatMemberAdministrator,
    InaccessibleMessage,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputRichMessage,
    KeyboardButton,
    MessageOriginChannel,
    MessageOriginUser,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    SharedUser,
    User,
    UsersShared,
)

from src.bot import texts
from src.bot.main import (
    USER_PICKER_REQUEST_ID,
    _register_bot_commands,
    handle_channel_callback,
    handle_channels,
    handle_demo,
    handle_document,
    handle_forwarded_channel,
    handle_publish_callback,
    handle_user_picker_shared,
    handle_users_callback,
    handle_users_command,
    start,
)
from src.bot.storage import BotStateError, BotStateStore
from src.config import Settings


def _settings(tmp_path, **overrides) -> Settings:
    base = {
        "OWNER_TELEGRAM_ID": 42,
        "DATA_DIR": str(tmp_path / "data"),
        "MEDIA_DIR": str(tmp_path / "media"),
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


def _message(chat_id: int = 42):
    message = AsyncMock()
    message.chat = MagicMock()
    message.chat.id = chat_id
    message.chat.type = "private"
    message.from_user = MagicMock()
    message.from_user.id = 42
    return message


def _callback(data: str, user_id: int = 42, chat_id: int = 42):
    callback = AsyncMock()
    callback.data = data
    callback.from_user = MagicMock()
    callback.from_user.id = user_id
    callback.message = AsyncMock()
    callback.message.chat = MagicMock()
    callback.message.chat.id = chat_id
    callback.message.chat.type = "private"
    callback.message.reply_markup = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Опубликовать", callback_data=data)]]
    )
    return callback


def _admin_member(can_post_messages: bool = True) -> ChatMemberAdministrator:
    return ChatMemberAdministrator(
        status=ChatMemberStatus.ADMINISTRATOR,
        user=User(id=999, is_bot=True, first_name="verstun"),
        can_be_edited=False,
        is_anonymous=False,
        can_manage_chat=True,
        can_delete_messages=False,
        can_manage_video_chats=False,
        can_restrict_members=False,
        can_promote_members=False,
        can_change_info=False,
        can_invite_users=False,
        can_post_stories=False,
        can_edit_stories=False,
        can_delete_stories=False,
        can_post_messages=can_post_messages,
    )


def _bot_with_member(member: ChatMemberAdministrator) -> AsyncMock:
    bot = AsyncMock()
    bot.get_me = AsyncMock(return_value=User(id=999, is_bot=True, first_name="verstun"))
    bot.get_chat_member = AsyncMock(return_value=member)
    return bot


def _telegram_error() -> TelegramAPIError:
    return TelegramAPIError(
        method=SendRichMessage(
            chat_id=-100123,
            rich_message=InputRichMessage(html="<h1>Hello</h1>"),
        ),
        message="bad request",
    )


async def test_start_explains_main_workflow():
    message = _message()

    await start(message)

    message.answer.assert_awaited_once_with(texts.START_TEXT)
    assert "5. Выбери канал" in texts.START_TEXT
    assert "/connect" not in texts.START_TEXT


async def test_register_bot_commands_sets_command_menu():
    bot = AsyncMock()

    await _register_bot_commands(bot)

    bot.set_my_commands.assert_awaited_once_with(texts.BOT_COMMANDS)
    commands = [command.command for command in texts.BOT_COMMANDS]
    assert commands == ["start", "demo", "channels", "users"]


async def test_demo_sends_rich_message_with_demo_image(tmp_path):
    settings = _settings(tmp_path, MEDIA_BASE_URL="https://example.test/media")
    message = _message()

    await handle_demo(message, settings)

    message.answer_rich.assert_awaited_once()
    rich = message.answer_rich.await_args.args[0]
    assert isinstance(rich, InputRichMessage)
    assert "<h1>Демонстрация Verstun</h1>" in rich.html
    for tag in ("h2", "h3", "h4", "h5", "h6"):
        assert f"<{tag}>" in rich.html
    for fragment in (
        "<ul>",
        "<ol>",
        "<blockquote>",
        "<details>",
        "<summary>",
        "<table>",
        "<pre><code>",
        "<hr>",
        "<tg-spoiler>",
    ):
        assert fragment in rich.html
    assert "<h2>Сноски</h2>" in rich.html
    assert '<a name="footnote-ref-1"></a><sup><a href="#footnote-1">1</a></sup>' in rich.html
    assert '<a name="footnote-1"></a><footer>1. Так выглядят сноски' in rich.html
    assert '<a href="#footnote-ref-1">↩</a></footer>' in rich.html
    assert "<tg-math>E = mc^2</tg-math>" in rich.html
    assert r"<tg-math-block>x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}</tg-math-block>" in rich.html
    assert '<a href="https://telegram.org/blog/watch-apps-and-more">' in rich.html
    assert '<img src="https://example.test/media/' in rich.html
    assert (
        '<video src="https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4">'
        in rich.html
    )
    assert '<audio src="https://www.w3schools.com/html/horse.mp3">' in rich.html


async def test_users_command_lists_users_with_add_button(tmp_path):
    settings = _settings(tmp_path)
    store = BotStateStore(settings.data_dir)
    store.save_user(telegram_id=100, name="B User", username="b")
    store.save_user(telegram_id=99, name="A User", username="a")
    message = _message()

    await handle_users_command(message, settings)

    message.answer.assert_awaited_once()
    text = message.answer.await_args.args[0]
    assert "Пользователи" in text
    markup = message.answer.await_args.kwargs["reply_markup"]
    rows = markup.inline_keyboard
    assert rows[0][0].text == "➕ Добавить пользователя"
    assert rows[0][0].callback_data == "usr:add"
    buttons = {button.text: button.callback_data for row in rows[1:] for button in row}
    assert buttons["A User (@a)"] == "usr:view:99:0:0"
    assert buttons["B User (@b)"] == "usr:view:100:0:0"


async def test_users_command_reports_state_error(tmp_path):
    settings = _settings(tmp_path)
    store = MagicMock()
    store.delete_user.side_effect = BotStateError("state")
    message = _message()

    with patch("src.bot.main._store", return_value=store):
        await handle_users_command(message, settings)

    message.answer.assert_awaited_once_with(texts.STATE_READ_ERROR)


async def test_users_command_ignores_non_owner_user(tmp_path):
    settings = _settings(tmp_path)
    BotStateStore(settings.data_dir).save_user(telegram_id=7, name="User", username=None)
    message = _message(chat_id=7)
    message.from_user.id = 7

    await handle_users_command(message, settings)

    message.answer.assert_not_awaited()


async def test_users_command_rejects_group_chat(tmp_path):
    settings = _settings(tmp_path)
    message = _message(chat_id=-2001)
    message.chat.type = "group"

    await handle_users_command(message, settings)

    message.answer.assert_awaited_once_with(texts.PRIVATE_CHAT_REQUIRED)


async def test_channels_command_owner_sees_all_channels(tmp_path):
    settings = _settings(tmp_path)
    store = BotStateStore(settings.data_dir)
    store.save_channel(chat_id=-1001, title="Первый", username=None)
    store.save_channel(chat_id=-1002, title="Второй", username=None)
    message = _message()

    await handle_channels(message, settings)

    message.answer.assert_awaited_once()
    text = message.answer.await_args.args[0]
    assert "Первый" in text
    assert "Второй" in text
    markup = message.answer.await_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[0][0].text == "➕ Подключить новый канал"
    assert markup.inline_keyboard[0][0].callback_data == "chan:connect"
    assert markup.inline_keyboard[1][0].text == "🗑 Отключить канал"
    assert markup.inline_keyboard[1][0].callback_data == "chan:list:0"


async def test_channels_command_reports_state_error(tmp_path):
    settings = _settings(tmp_path)
    message = _message()

    with patch("src.bot.main._visible_channels", side_effect=BotStateError("state")):
        await handle_channels(message, settings)

    message.answer.assert_awaited_once_with(texts.STATE_READ_ERROR)


async def test_channels_command_added_user_sees_only_granted_channels(tmp_path):
    settings = _settings(tmp_path)
    store = BotStateStore(settings.data_dir)
    store.save_channel(chat_id=-1001, title="Первый", username=None)
    store.save_channel(chat_id=-1002, title="Второй", username=None)
    store.save_user(telegram_id=7, name="User", username=None)
    store.set_user_channel_access(telegram_id=7, channel_id=-1002, allowed=True)
    message = _message(chat_id=7)
    message.from_user.id = 7

    await handle_channels(message, settings)

    message.answer.assert_awaited_once()
    text = message.answer.await_args.args[0]
    assert "Первый" not in text
    assert "Второй" in text
    assert "reply_markup" not in message.answer.await_args.kwargs


async def test_channels_command_added_user_without_grants_gets_empty_hint(tmp_path):
    settings = _settings(tmp_path)
    store = BotStateStore(settings.data_dir)
    store.save_channel(chat_id=-1001, title="Первый", username=None)
    store.save_user(telegram_id=7, name="User", username=None)
    message = _message(chat_id=7)
    message.from_user.id = 7

    await handle_channels(message, settings)

    message.answer.assert_awaited_once_with(texts.NO_GRANTED_CHANNELS)


async def test_channels_command_owner_without_channels_gets_connect_button(tmp_path):
    settings = _settings(tmp_path)
    message = _message()

    await handle_channels(message, settings)

    message.answer.assert_awaited_once()
    assert message.answer.await_args.args[0] == texts.CHANNELS_EMPTY
    markup = message.answer.await_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[0][0].text == "➕ Подключить новый канал"
    assert markup.inline_keyboard[0][0].callback_data == "chan:connect"


async def test_channels_command_rejects_group_chat(tmp_path):
    settings = _settings(tmp_path)
    message = _message(chat_id=-2001)
    message.chat.type = "group"

    await handle_channels(message, settings)

    message.answer.assert_awaited_once_with(texts.PRIVATE_CHAT_REQUIRED)


async def test_connect_button_sets_pending_state(tmp_path):
    settings = _settings(tmp_path)
    callback = _callback("chan:connect")

    await handle_channel_callback(callback, settings)

    assert BotStateStore(settings.data_dir).is_connect_pending() is True
    callback.message.answer.assert_awaited_once_with(texts.CONNECT_TEXT)
    callback.answer.assert_awaited_once()


async def test_channel_callback_reports_state_error(tmp_path):
    settings = _settings(tmp_path)
    callback = _callback("chan:list:0")

    with patch("src.bot.main._store", side_effect=BotStateError("state")):
        await handle_channel_callback(callback, settings)

    callback.message.edit_text.assert_awaited_once_with(texts.STATE_READ_ERROR)
    callback.answer.assert_not_awaited()


async def test_channels_disconnect_button_opens_channel_delete_list(tmp_path):
    settings = _settings(tmp_path)
    store = BotStateStore(settings.data_dir)
    store.save_channel(chat_id=-1001, title="Первый", username=None)
    store.save_channel(chat_id=-1002, title="Второй", username=None)
    callback = _callback("chan:list:0")

    await handle_channel_callback(callback, settings)

    callback.message.edit_text.assert_awaited_once()
    assert callback.message.edit_text.await_args.args[0] == texts.CHANNEL_DELETE_PROMPT
    markup = callback.message.edit_text.await_args.kwargs["reply_markup"]
    buttons = {
        button.text: button.callback_data for row in markup.inline_keyboard for button in row
    }
    assert buttons["🗑 Первый"] == "chan:drop:-1001:0"
    assert buttons["🗑 Второй"] == "chan:drop:-1002:0"
    assert buttons["↩️ Назад"] == "chan:back"


async def test_channel_drop_removes_channel_and_user_grants(tmp_path):
    settings = _settings(tmp_path)
    store = BotStateStore(settings.data_dir)
    store.save_channel(chat_id=-1001, title="Первый", username=None)
    store.save_channel(chat_id=-1002, title="Второй", username=None)
    store.save_user(telegram_id=7, name="User", username=None)
    store.set_user_channel_access(telegram_id=7, channel_id=-1001, allowed=True)
    store.set_user_channel_access(telegram_id=7, channel_id=-1002, allowed=True)
    callback = _callback("chan:drop:-1001:0")

    await handle_channel_callback(callback, settings)

    assert store.get_channel(-1001) is None
    assert [channel.chat_id for channel in store.list_channels()] == [-1002]
    assert store.user_can_publish_to(telegram_id=7, channel_id=-1001) is False
    assert store.user_can_publish_to(telegram_id=7, channel_id=-1002) is True
    callback.message.edit_text.assert_awaited_once()
    assert callback.message.edit_text.await_args.args[0].startswith(
        texts.channel_disconnected("Первый")
    )


async def test_users_add_button_sends_native_user_picker(tmp_path):
    settings = _settings(tmp_path)
    callback = _callback("usr:add")

    await handle_users_callback(callback, settings)

    callback.message.answer.assert_awaited_once()
    kwargs = callback.message.answer.await_args.kwargs
    markup = kwargs["reply_markup"]
    assert isinstance(markup, ReplyKeyboardMarkup)
    button = markup.keyboard[0][0]
    assert isinstance(button, KeyboardButton)
    assert button.request_users is not None
    assert button.request_users.request_id == USER_PICKER_REQUEST_ID
    assert button.request_users.max_quantity == 1
    callback.answer.assert_awaited_once()


async def test_users_callback_reports_state_error(tmp_path):
    settings = _settings(tmp_path)
    callback = _callback("usr:list:0")

    with patch("src.bot.main._store", side_effect=BotStateError("state")):
        await handle_users_callback(callback, settings)

    callback.message.edit_text.assert_awaited_once_with(texts.STATE_READ_ERROR)
    callback.answer.assert_not_awaited()


async def test_users_callback_rejects_group_chat(tmp_path):
    settings = _settings(tmp_path)
    callback = _callback("usr:list:0", chat_id=-2001)
    callback.message.chat.type = "group"

    await handle_users_callback(callback, settings)

    callback.answer.assert_awaited_once_with(texts.USERS_PRIVATE_REQUIRED, show_alert=True)
    callback.message.edit_text.assert_not_awaited()


async def test_user_picker_shared_saves_user_and_opens_card(tmp_path):
    settings = _settings(tmp_path)
    store = BotStateStore(settings.data_dir)
    store.save_channel(chat_id=-1001, title="Main", username=None)
    message = _message()
    message.users_shared = UsersShared(
        request_id=USER_PICKER_REQUEST_ID,
        users=[SharedUser(user_id=7, first_name="Lena", last_name="SMM", username="lena")],
    )

    await handle_user_picker_shared(message, settings)

    user = store.get_user(7)
    assert user is not None
    assert user.name == "Lena SMM"
    assert user.username == "lena"
    assert message.answer.await_count == 2
    assert isinstance(message.answer.await_args_list[0].kwargs["reply_markup"], ReplyKeyboardRemove)
    card_text = message.answer.await_args_list[1].args[0]
    assert "Lena SMM" in card_text
    assert "ID: 7" in card_text
    markup = message.answer.await_args_list[1].kwargs["reply_markup"]
    buttons = {
        button.text: button.callback_data for row in markup.inline_keyboard for button in row
    }
    assert buttons["❌ Main"] == "usr:toggle:7:-1001:0:0"
    assert buttons["🗑 Удалить пользователя"] == "usr:del:7:0"
    assert buttons["↩️ Назад"] == "usr:list:0"


async def test_user_picker_shared_reports_existing_user_without_duplicate(tmp_path):
    settings = _settings(tmp_path)
    store = BotStateStore(settings.data_dir)
    store.save_user(telegram_id=7, name="Lena", username=None)
    store.save_channel(chat_id=-1001, title="Main", username=None)
    message = _message()
    message.users_shared = UsersShared(
        request_id=USER_PICKER_REQUEST_ID,
        users=[SharedUser(user_id=7, first_name="Lena", last_name="SMM", username="lena")],
    )

    await handle_user_picker_shared(message, settings)

    assert len([user for user in store.list_users() if user.telegram_id == 7]) == 1
    assert message.answer.await_args_list[0].args[0] == texts.USER_ALREADY_ADDED


async def test_user_picker_shared_does_not_add_owner_as_managed_user(tmp_path):
    settings = _settings(tmp_path)
    store = BotStateStore(settings.data_dir)
    store.save_user(telegram_id=42, name="Owner", username="owner")
    message = _message()
    message.users_shared = UsersShared(
        request_id=USER_PICKER_REQUEST_ID,
        users=[SharedUser(user_id=42, first_name="Owner", last_name=None, username="owner")],
    )

    await handle_user_picker_shared(message, settings)

    assert store.get_user(42) is None
    message.answer.assert_awaited_once_with(
        texts.USER_IS_OWNER,
        reply_markup=ReplyKeyboardRemove(),
    )


async def test_users_command_removes_legacy_owner_from_managed_users(tmp_path):
    settings = _settings(tmp_path)
    store = BotStateStore(settings.data_dir)
    store.save_user(telegram_id=42, name="Owner", username="owner")
    store.save_user(telegram_id=7, name="User", username=None)
    message = _message()

    await handle_users_command(message, settings)

    assert store.get_user(42) is None
    markup = message.answer.await_args.kwargs["reply_markup"]
    buttons = {button.text for row in markup.inline_keyboard for button in row}
    assert "Owner (@owner)" not in buttons
    assert "User" in buttons


async def test_user_card_toggle_channel_access_in_place(tmp_path):
    settings = _settings(tmp_path)
    store = BotStateStore(settings.data_dir)
    store.save_user(telegram_id=7, name="Lena", username=None)
    store.save_channel(chat_id=-1001, title="Main", username=None)
    callback = _callback("usr:toggle:7:-1001:0:0")

    await handle_users_callback(callback, settings)

    assert store.user_can_publish_to(telegram_id=7, channel_id=-1001) is True
    callback.message.edit_text.assert_awaited_once()
    markup = callback.message.edit_text.await_args.kwargs["reply_markup"]
    buttons = {
        button.text: button.callback_data for row in markup.inline_keyboard for button in row
    }
    assert "✅ Main" in buttons
    callback.answer.assert_awaited_once()


async def test_user_delete_removes_user(tmp_path):
    settings = _settings(tmp_path)
    store = BotStateStore(settings.data_dir)
    store.save_user(telegram_id=7, name="Lena", username=None)
    callback = _callback("usr:del:7:0")

    await handle_users_callback(callback, settings)

    assert store.get_user(7) is None
    callback.message.edit_text.assert_awaited_once()
    assert "Пользователи" in callback.message.edit_text.await_args.args[0]


async def test_forwarded_channel_connects_when_bot_can_post(tmp_path):
    settings = _settings(tmp_path)
    store = BotStateStore(settings.data_dir)
    store.set_connect_pending(True)
    message = _message()
    message.forward_origin = MessageOriginChannel(
        date=datetime.now(UTC),
        chat=Chat(id=-100123, type="channel", title="Тестовый канал", username=None),
        message_id=10,
    )
    bot = _bot_with_member(_admin_member(can_post_messages=True))

    await handle_forwarded_channel(message, bot, settings)

    channels = BotStateStore(settings.data_dir).list_channels()
    assert [(c.chat_id, c.title) for c in channels] == [(-100123, "Тестовый канал")]
    assert BotStateStore(settings.data_dir).is_connect_pending() is False
    message.answer.assert_awaited_once_with(texts.channel_connected("Тестовый канал"))


async def test_forwarded_channel_reports_state_error_when_pending_read_fails(tmp_path):
    settings = _settings(tmp_path)
    store = MagicMock()
    store.is_connect_pending.side_effect = BotStateError("state")
    message = _message()
    message.forward_origin = MessageOriginChannel(
        date=datetime.now(UTC),
        chat=Chat(id=-100123, type="channel", title="Тестовый канал", username=None),
        message_id=10,
    )
    bot = AsyncMock()

    with patch("src.bot.main._store", return_value=store):
        await handle_forwarded_channel(message, bot, settings)

    message.answer.assert_awaited_once_with(texts.STATE_READ_ERROR)
    bot.get_chat_member.assert_not_called()


async def test_forwarded_channel_rejected_without_posting_rights(tmp_path):
    settings = _settings(tmp_path)
    BotStateStore(settings.data_dir).set_connect_pending(True)
    message = _message()
    message.forward_origin = MessageOriginChannel(
        date=datetime.now(UTC),
        chat=Chat(id=-100123, type="channel", title="Тестовый канал"),
        message_id=10,
    )
    bot = _bot_with_member(_admin_member(can_post_messages=False))

    await handle_forwarded_channel(message, bot, settings)

    assert BotStateStore(settings.data_dir).list_channels() == []
    assert BotStateStore(settings.data_dir).is_connect_pending() is True
    message.answer.assert_awaited_once_with(texts.CHANNEL_POSTING_RIGHTS_MISSING)


async def test_forwarded_non_channel_is_rejected_while_connect_pending(tmp_path):
    settings = _settings(tmp_path)
    BotStateStore(settings.data_dir).set_connect_pending(True)
    message = _message()
    message.forward_origin = MessageOriginUser(
        date=datetime.now(UTC),
        sender_user=User(id=7, is_bot=False, first_name="User"),
    )
    bot = AsyncMock()

    await handle_forwarded_channel(message, bot, settings)

    assert BotStateStore(settings.data_dir).list_channels() == []
    assert BotStateStore(settings.data_dir).is_connect_pending() is True
    bot.get_chat_member.assert_not_called()
    message.answer.assert_awaited_once_with(texts.CHANNEL_FORWARD_REQUIRED)


async def test_forwarded_channel_rejects_group_chat(tmp_path):
    settings = _settings(tmp_path)
    BotStateStore(settings.data_dir).set_connect_pending(True)
    message = _message(chat_id=-2001)
    message.chat.type = "group"
    message.forward_origin = MessageOriginChannel(
        date=datetime.now(UTC),
        chat=Chat(id=-100123, type="channel", title="Тестовый канал", username=None),
        message_id=10,
    )
    bot = AsyncMock()

    await handle_forwarded_channel(message, bot, settings)

    message.answer.assert_awaited_once_with(texts.PRIVATE_CHAT_REQUIRED)
    bot.get_chat_member.assert_not_called()


async def test_channel_callback_rejects_group_chat(tmp_path):
    settings = _settings(tmp_path)
    callback = _callback("chan:list:0", chat_id=-2001)
    callback.message.chat.type = "group"

    await handle_channel_callback(callback, settings)

    callback.answer.assert_awaited_once_with(texts.CHANNELS_PRIVATE_REQUIRED, show_alert=True)
    callback.message.edit_text.assert_not_awaited()


async def test_document_handler_replies_with_publish_buttons_when_channels_exist(tmp_path):
    settings = _settings(tmp_path)
    store = BotStateStore(settings.data_dir)
    store.save_channel(chat_id=-1001, title="Первый", username=None)
    store.save_channel(chat_id=-1002, title="Второй", username=None)
    message = _message()
    message.document = MagicMock()
    message.document.file_name = "post.md"
    message.document.mime_type = "text/markdown"
    message.document.file_size = 100
    sent = MagicMock()
    sent.message_id = 777
    message.answer_rich = AsyncMock(return_value=sent)
    controls = MagicMock()
    controls.message_id = 778
    message.answer = AsyncMock(return_value=controls)
    bot = _bot_with_member(_admin_member(can_post_messages=True))
    bot.download = AsyncMock(return_value=MagicMock(read=MagicMock(return_value=b"# Hello")))

    with patch("src.bot.main.markdown_to_rich_html", return_value=("<h1>Hello</h1>", [])):
        await handle_document(message, bot, settings)

    assert BotStateStore(settings.data_dir).get_post(private_chat_id=42, message_id=777) == (
        "<h1>Hello</h1>"
    )
    message.answer.assert_awaited_once()
    assert message.answer.await_args.kwargs["reply_to_message_id"] == 777
    assert texts.PUBLISH_CONTROLS_PROMPT in message.answer.await_args.args[0]
    markup = message.answer.await_args.kwargs["reply_markup"]
    buttons = {button.text: button.callback_data for [button] in markup.inline_keyboard}
    assert buttons == {
        texts.publish_channel_button("Первый"): "pub:777:-1001",
        texts.publish_channel_button("Второй"): "pub:777:-1002",
    }
    assert BotStateStore(settings.data_dir).pop_active_controls(private_chat_id=42) == (777, 778)


async def test_document_handler_reports_publish_controls_send_error(tmp_path):
    settings = _settings(tmp_path)
    BotStateStore(settings.data_dir).save_channel(chat_id=-1001, title="Первый", username=None)
    message = _message()
    message.document = MagicMock()
    message.document.file_name = "post.md"
    message.document.mime_type = "text/markdown"
    message.document.file_size = 100
    sent = MagicMock()
    sent.message_id = 777
    message.answer_rich = AsyncMock(return_value=sent)
    message.answer = AsyncMock(side_effect=[_telegram_error(), None])
    bot = _bot_with_member(_admin_member(can_post_messages=True))
    bot.download = AsyncMock(return_value=MagicMock(read=MagicMock(return_value=b"# Hello")))

    with patch("src.bot.main.markdown_to_rich_html", return_value=("<h1>Hello</h1>", [])):
        await handle_document(message, bot, settings)

    assert message.answer.await_args_list[0].args[0] == texts.PUBLISH_CONTROLS_PROMPT
    assert message.answer.await_args_list[1].args[0] == texts.PUBLISH_CONTROLS_SEND_ERROR
    assert message.answer.await_args_list[1].kwargs["reply_to_message_id"] == 777


async def test_document_handler_rejects_group_chat_without_saving_post(tmp_path):
    settings = _settings(tmp_path)
    store = BotStateStore(settings.data_dir)
    store.save_channel(chat_id=-1001, title="Первый", username=None)
    message = _message(chat_id=-2001)
    message.chat.type = "group"
    message.document = MagicMock()
    message.document.file_name = "post.md"
    message.document.mime_type = "text/markdown"
    message.document.file_size = 100
    bot = _bot_with_member(_admin_member(can_post_messages=True))
    bot.download = AsyncMock(return_value=MagicMock(read=MagicMock(return_value=b"# Hello")))

    await handle_document(message, bot, settings)

    message.answer.assert_awaited_once_with(texts.DOCUMENT_PRIVATE_REQUIRED)
    message.answer_rich.assert_not_awaited()
    bot.download.assert_not_awaited()
    assert store.get_post(private_chat_id=-2001, message_id=777) is None


async def test_document_handler_filters_publish_buttons_for_user_acl(tmp_path):
    settings = _settings(tmp_path)
    store = BotStateStore(settings.data_dir)
    store.save_channel(chat_id=-1001, title="Первый", username=None)
    store.save_channel(chat_id=-1002, title="Второй", username=None)
    store.save_user(telegram_id=7, name="User", username=None)
    store.set_user_channel_access(telegram_id=7, channel_id=-1002, allowed=True)
    message = _message(chat_id=7)
    message.from_user.id = 7
    message.document = MagicMock()
    message.document.file_name = "post.md"
    message.document.mime_type = "text/markdown"
    message.document.file_size = 100
    sent = MagicMock()
    sent.message_id = 777
    message.answer_rich = AsyncMock(return_value=sent)
    controls = MagicMock()
    controls.message_id = 778
    message.answer = AsyncMock(return_value=controls)
    bot = _bot_with_member(_admin_member(can_post_messages=True))
    bot.download = AsyncMock(return_value=MagicMock(read=MagicMock(return_value=b"# Hello")))

    with patch("src.bot.main.markdown_to_rich_html", return_value=("<h1>Hello</h1>", [])):
        await handle_document(message, bot, settings)

    markup = message.answer.await_args.kwargs["reply_markup"]
    buttons = {button.text: button.callback_data for [button] in markup.inline_keyboard}
    assert buttons == {texts.publish_channel_button("Второй"): "pub:777:-1002"}


async def test_document_handler_hides_channels_without_current_bot_rights(tmp_path):
    settings = _settings(tmp_path)
    store = BotStateStore(settings.data_dir)
    store.save_channel(chat_id=-1001, title="Без прав", username=None)
    store.save_channel(chat_id=-1002, title="С правами", username=None)
    message = _message()
    message.document = MagicMock()
    message.document.file_name = "post.md"
    message.document.mime_type = "text/markdown"
    message.document.file_size = 100
    sent = MagicMock()
    sent.message_id = 777
    message.answer_rich = AsyncMock(return_value=sent)
    controls = MagicMock()
    controls.message_id = 778
    message.answer = AsyncMock(return_value=controls)
    bot = _bot_with_member(_admin_member(can_post_messages=True))
    bot.get_chat_member.side_effect = [
        _admin_member(can_post_messages=False),
        _admin_member(can_post_messages=True),
    ]
    bot.download = AsyncMock(return_value=MagicMock(read=MagicMock(return_value=b"# Hello")))

    with patch("src.bot.main.markdown_to_rich_html", return_value=("<h1>Hello</h1>", [])):
        await handle_document(message, bot, settings)

    markup = message.answer.await_args.kwargs["reply_markup"]
    buttons = {button.text: button.callback_data for [button] in markup.inline_keyboard}
    assert buttons == {texts.publish_channel_button("С правами"): "pub:777:-1002"}


async def test_document_handler_deactivates_previous_publish_controls(tmp_path):
    settings = _settings(tmp_path)
    store = BotStateStore(settings.data_dir)
    store.save_channel(chat_id=-1001, title="Первый", username=None)
    store.save_active_controls(private_chat_id=42, post_message_id=100, controls_message_id=101)
    store.save_post(private_chat_id=42, message_id=100, html="old")
    message = _message()
    message.document = MagicMock()
    message.document.file_name = "post.md"
    message.document.mime_type = "text/markdown"
    message.document.file_size = 100
    sent = MagicMock()
    sent.message_id = 777
    message.answer_rich = AsyncMock(return_value=sent)
    controls = MagicMock()
    controls.message_id = 778
    message.answer = AsyncMock(return_value=controls)
    bot = _bot_with_member(_admin_member(can_post_messages=True))
    bot.download = AsyncMock(return_value=MagicMock(read=MagicMock(return_value=b"# Hello")))

    with patch("src.bot.main.markdown_to_rich_html", return_value=("<h1>Hello</h1>", [])):
        await handle_document(message, bot, settings)

    bot.edit_message_reply_markup.assert_awaited_once_with(
        chat_id=42,
        message_id=101,
        reply_markup=None,
    )
    assert store.get_post(private_chat_id=42, message_id=100) is None
    assert store.get_post(private_chat_id=42, message_id=777) == "<h1>Hello</h1>"


async def test_document_handler_replies_with_connect_hint_when_no_channels(tmp_path):
    settings = _settings(tmp_path)
    message = _message()
    message.document = MagicMock()
    message.document.file_name = "post.md"
    message.document.mime_type = "text/markdown"
    message.document.file_size = 100
    sent = MagicMock()
    sent.message_id = 777
    message.answer_rich = AsyncMock(return_value=sent)
    bot = AsyncMock()
    bot.download = AsyncMock(return_value=MagicMock(read=MagicMock(return_value=b"# Hello")))

    with patch("src.bot.main.markdown_to_rich_html", return_value=("<h1>Hello</h1>", [])):
        await handle_document(message, bot, settings)

    message.answer.assert_awaited_once_with(
        texts.OWNER_NO_PUBLISHABLE_CHANNELS,
        reply_to_message_id=777,
    )


async def test_publish_callback_sends_saved_html_to_selected_channel(tmp_path):
    settings = _settings(tmp_path)
    store = BotStateStore(settings.data_dir)
    store.save_channel(chat_id=-100123, title="Канал", username=None)
    store.save_post(private_chat_id=42, message_id=777, html="<h1>Hello</h1>")
    store.save_active_controls(private_chat_id=42, post_message_id=777, controls_message_id=778)
    callback = _callback("pub:777:-100123")
    callback.message.reply_to_message = MagicMock()
    callback.message.reply_to_message.message_id = 777
    bot = _bot_with_member(_admin_member(can_post_messages=True))

    await handle_publish_callback(callback, bot, settings)
    await handle_publish_callback(callback, bot, settings)

    assert callback.answer.await_count == 2
    callback.answer.assert_any_await(texts.PUBLISHING, show_alert=False)
    callback.answer.assert_any_await(texts.PUBLISH_ALREADY_SENT, show_alert=True)
    assert bot.send_rich_message.await_count == 1
    assert bot.send_rich_message.await_args.kwargs["chat_id"] == -100123
    callback.message.edit_text.assert_not_awaited()
    callback.message.answer.assert_awaited_once_with(
        texts.publish_success("Канал"),
        reply_to_message_id=777,
    )
    bot.edit_message_reply_markup.assert_not_awaited()
    assert store.pop_active_controls(private_chat_id=42) == (777, 778)


async def test_publish_callback_rejects_missing_cached_post(tmp_path):
    settings = _settings(tmp_path)
    BotStateStore(settings.data_dir).save_channel(chat_id=-100123, title="Канал", username=None)
    callback = _callback("pub:777:-100123")
    bot = _bot_with_member(_admin_member(can_post_messages=True))

    await handle_publish_callback(callback, bot, settings)

    callback.answer.assert_awaited_once_with(texts.POST_BUTTON_STALE, show_alert=True)
    bot.send_rich_message.assert_not_awaited()


async def test_publish_callback_rejects_deleted_channel(tmp_path):
    settings = _settings(tmp_path)
    BotStateStore(settings.data_dir).save_post(
        private_chat_id=42, message_id=777, html="<h1>Hello</h1>"
    )
    callback = _callback("pub:777:-100123")
    bot = _bot_with_member(_admin_member(can_post_messages=True))

    await handle_publish_callback(callback, bot, settings)

    callback.answer.assert_awaited_once_with(texts.POST_BUTTON_STALE, show_alert=True)
    bot.send_rich_message.assert_not_awaited()


async def test_publish_callback_state_error_keeps_controls_message(tmp_path):
    settings = _settings(tmp_path)
    callback = _callback("pub:777:-100123")
    callback.message.reply_to_message = MagicMock()
    callback.message.reply_to_message.message_id = 777
    bot = _bot_with_member(_admin_member(can_post_messages=True))

    with patch("src.bot.main._store", side_effect=BotStateError("state")):
        await handle_publish_callback(callback, bot, settings)

    bot.send_rich_message.assert_not_awaited()
    callback.message.edit_text.assert_not_awaited()
    callback.message.answer.assert_awaited_once_with(
        texts.STATE_READ_ERROR,
        reply_to_message_id=777,
    )


async def test_publish_callback_acl_state_error_keeps_controls_message(tmp_path):
    settings = _settings(tmp_path)
    store = BotStateStore(settings.data_dir)
    store.save_channel(chat_id=-100123, title="Канал", username=None)
    store.save_user(telegram_id=7, name="User", username=None)
    store.save_post(private_chat_id=7, message_id=777, html="<h1>Hello</h1>")
    callback = _callback("pub:777:-100123", user_id=7, chat_id=7)
    callback.message.reply_to_message = MagicMock()
    callback.message.reply_to_message.message_id = 777
    bot = _bot_with_member(_admin_member(can_post_messages=True))

    with patch("src.bot.main._can_publish_to_channel", side_effect=BotStateError("state")):
        await handle_publish_callback(callback, bot, settings)

    bot.send_rich_message.assert_not_awaited()
    callback.message.edit_text.assert_not_awaited()
    callback.message.answer.assert_awaited_once_with(
        texts.STATE_READ_ERROR,
        reply_to_message_id=777,
    )


async def test_publish_callback_rejects_user_without_channel_access(tmp_path):
    settings = _settings(tmp_path)
    store = BotStateStore(settings.data_dir)
    store.save_channel(chat_id=-100123, title="Канал", username=None)
    store.save_user(telegram_id=7, name="User", username=None)
    store.save_post(private_chat_id=7, message_id=777, html="<h1>Hello</h1>")
    callback = _callback("pub:777:-100123", user_id=7, chat_id=7)
    bot = _bot_with_member(_admin_member(can_post_messages=True))

    await handle_publish_callback(callback, bot, settings)

    bot.send_rich_message.assert_not_awaited()
    callback.answer.assert_awaited_once_with(texts.PUBLISH_NO_ACCESS, show_alert=True)
    callback.message.edit_text.assert_not_awaited()


async def test_publish_callback_rejects_group_chat(tmp_path):
    settings = _settings(tmp_path)
    store = BotStateStore(settings.data_dir)
    store.save_channel(chat_id=-100123, title="Канал", username=None)
    store.save_post(private_chat_id=-2001, message_id=777, html="<h1>Hello</h1>")
    callback = _callback("pub:777:-100123", chat_id=-2001)
    callback.message.chat.type = "group"
    bot = _bot_with_member(_admin_member(can_post_messages=True))

    await handle_publish_callback(callback, bot, settings)

    callback.answer.assert_awaited_once_with(texts.PUBLISH_PRIVATE_REQUIRED, show_alert=True)
    bot.send_rich_message.assert_not_awaited()
    callback.message.edit_text.assert_not_awaited()


async def test_publish_callback_reports_missing_current_rights(tmp_path):
    settings = _settings(tmp_path)
    store = BotStateStore(settings.data_dir)
    store.save_channel(chat_id=-100123, title="Канал", username=None)
    store.save_post(private_chat_id=42, message_id=777, html="<h1>Hello</h1>")
    store.save_active_controls(private_chat_id=42, post_message_id=777, controls_message_id=778)
    callback = _callback("pub:777:-100123")
    bot = _bot_with_member(_admin_member(can_post_messages=False))

    await handle_publish_callback(callback, bot, settings)

    bot.send_rich_message.assert_not_awaited()
    callback.answer.assert_awaited_once_with(texts.PUBLISHING, show_alert=False)
    callback.message.edit_text.assert_not_awaited()
    callback.message.answer.assert_awaited_once_with(
        texts.PUBLISH_RIGHTS_MISSING,
        reply_to_message_id=777,
    )
    bot.edit_message_reply_markup.assert_not_awaited()
    assert store.pop_active_controls(private_chat_id=42) == (777, 778)


async def test_publish_callback_reports_telegram_send_error(tmp_path):
    settings = _settings(tmp_path)
    store = BotStateStore(settings.data_dir)
    store.save_channel(chat_id=-100123, title="Канал", username=None)
    store.save_post(private_chat_id=42, message_id=777, html="<h1>Hello</h1>")
    store.save_active_controls(private_chat_id=42, post_message_id=777, controls_message_id=778)
    callback = _callback("pub:777:-100123")
    bot = _bot_with_member(_admin_member(can_post_messages=True))
    bot.send_rich_message.side_effect = _telegram_error()

    await handle_publish_callback(callback, bot, settings)

    callback.answer.assert_awaited_once_with(texts.PUBLISHING, show_alert=False)
    callback.message.edit_text.assert_not_awaited()
    callback.message.answer.assert_awaited_once_with(
        texts.PUBLISH_SEND_ERROR,
        reply_to_message_id=777,
    )
    bot.edit_message_reply_markup.assert_not_awaited()
    assert store.pop_active_controls(private_chat_id=42) == (777, 778)


async def test_publish_callback_rejects_inaccessible_message(tmp_path):
    settings = _settings(tmp_path)
    callback = AsyncMock()
    callback.data = "pub:777:-100123"
    callback.message = InaccessibleMessage(
        chat=Chat(id=42, type="private"),
        message_id=1,
        date=0,
    )
    bot = AsyncMock()

    await handle_publish_callback(callback, bot, settings)

    callback.answer.assert_awaited_once_with(texts.POST_BUTTON_STALE, show_alert=True)
    bot.send_rich_message.assert_not_awaited()


async def test_document_handler_saves_sent_rich_html(tmp_path):
    from src.bot.main import handle_document

    settings = _settings(tmp_path)
    message = _message()
    message.document = MagicMock()
    message.document.file_name = "post.md"
    message.document.mime_type = "text/markdown"
    message.document.file_size = 100
    sent = MagicMock()
    sent.message_id = 777
    message.answer_rich = AsyncMock(return_value=sent)
    bot = AsyncMock()
    bot.download = AsyncMock(return_value=MagicMock(read=MagicMock(return_value=b"# Hello")))

    with patch("src.bot.main.markdown_to_rich_html", return_value=("<h1>Hello</h1>", [])):
        await handle_document(message, bot, settings)

    assert BotStateStore(settings.data_dir).get_post(private_chat_id=42, message_id=777) == (
        "<h1>Hello</h1>"
    )
