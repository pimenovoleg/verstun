import io
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.exceptions import TelegramAPIError
from aiogram.methods import SendRichMessage
from aiogram.types import InputRichMessage

from src.bot import texts
from src.bot.main import _MAX_UPLOAD_BYTES, handle_document
from src.config import Settings


def _settings(media_dir, **overrides) -> Settings:
    base = {
        "OWNER_TELEGRAM_ID": 42,
        "DATA_DIR": str(media_dir / "data"),
        "MEDIA_MAX_BYTES": 1_073_741_824,
        "MEDIA_DIR": str(media_dir),
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


def _message(file_name="post.md", mime_type="text/markdown", file_size=100):
    message = AsyncMock()
    message.chat = MagicMock()
    message.chat.id = 42
    message.chat.type = "private"
    message.document = MagicMock()
    message.document.file_name = file_name
    message.document.mime_type = mime_type
    message.document.file_size = file_size
    return message


def _bot_returning(content: bytes) -> AsyncMock:
    bot = AsyncMock()
    bot.download = AsyncMock(return_value=io.BytesIO(content))
    return bot


def _rich_arg(message: AsyncMock) -> InputRichMessage:
    call = message.answer_rich.await_args
    if call.args:
        return call.args[0]
    return call.kwargs["rich_message"]


def _telegram_error() -> TelegramAPIError:
    return TelegramAPIError(
        method=SendRichMessage(
            chat_id=42,
            rich_message=InputRichMessage(html="<h1>Hello</h1>"),
        ),
        message="bad request",
    )


async def test_happy_path_answers_rich_once(tmp_path):
    message = _message()
    bot = _bot_returning(b"# Hello\n")

    with patch("src.bot.document.markdown_to_rich_html", return_value=("<b>Hello</b>", [])) as conv:
        await handle_document(message, bot, _settings(tmp_path))

    conv.assert_called_once()
    bot.download.assert_awaited_once()
    message.answer_rich.assert_awaited_once()
    rich = _rich_arg(message)
    assert isinstance(rich, InputRichMessage)
    assert rich.html == "<b>Hello</b>"


async def test_non_md_file_rejected(tmp_path):
    message = _message(file_name="post.txt", mime_type="text/plain")
    bot = AsyncMock()

    await handle_document(message, bot, _settings(tmp_path))

    message.answer.assert_awaited_once_with(texts.DOCUMENT_MD_REQUIRED)
    message.answer_rich.assert_not_awaited()
    bot.download.assert_not_awaited()


async def test_empty_file_rejected(tmp_path):
    message = _message()
    bot = _bot_returning(b"   \n\t  ")

    await handle_document(message, bot, _settings(tmp_path))

    message.answer.assert_awaited_once_with(texts.DOCUMENT_EMPTY)
    message.answer_rich.assert_not_awaited()


async def test_non_utf8_file_rejected(tmp_path):
    message = _message()
    bot = _bot_returning(b"\xff\xfe\x00bad")

    await handle_document(message, bot, _settings(tmp_path))

    message.answer.assert_awaited_once_with(texts.DOCUMENT_READ_ERROR)
    message.answer_rich.assert_not_awaited()


async def test_oversized_file_size_rejected(tmp_path):
    message = _message(file_size=10_000_000)
    bot = _bot_returning(b"# Hello")

    await handle_document(message, bot, _settings(tmp_path))

    message.answer.assert_awaited_once_with(texts.DOCUMENT_TOO_LARGE)
    bot.download.assert_not_awaited()
    message.answer_rich.assert_not_awaited()


async def test_none_file_size_proceeds(tmp_path):
    message = _message(file_size=None)
    bot = _bot_returning(b"# Hello")

    with patch("src.bot.document.markdown_to_rich_html", return_value=("<b>Hello</b>", [])):
        await handle_document(message, bot, _settings(tmp_path))

    bot.download.assert_awaited_once()
    message.answer_rich.assert_awaited_once()


async def test_download_error_replies_with_retry_hint(tmp_path):
    message = _message()
    bot = AsyncMock()
    bot.download = AsyncMock(side_effect=_telegram_error())

    await handle_document(message, bot, _settings(tmp_path))

    message.answer.assert_awaited_once_with(texts.DOCUMENT_DOWNLOAD_ERROR)
    message.answer_rich.assert_not_awaited()


async def test_oversized_downloaded_bytes_rejected(tmp_path):
    # file_size lies (None) but the downloaded blob is over the cap — the
    # post-download size check must still reject it (SEC-T3-01 defense-in-depth).
    message = _message(file_size=None)
    bot = _bot_returning(b"x" * (_MAX_UPLOAD_BYTES + 1))

    await handle_document(message, bot, _settings(tmp_path))

    message.answer.assert_awaited_once_with(texts.DOCUMENT_TOO_LARGE)
    message.answer_rich.assert_not_awaited()


async def test_rich_message_send_error_replies_with_retry_hint(tmp_path):
    message = _message()
    message.answer_rich = AsyncMock(side_effect=_telegram_error())
    bot = _bot_returning(b"# Hello")

    with patch("src.bot.document.markdown_to_rich_html", return_value=("<b>Hello</b>", [])):
        await handle_document(message, bot, _settings(tmp_path))

    message.answer.assert_awaited_once_with(texts.POST_SEND_ERROR)


async def test_length_boundary_32768_accepted(tmp_path):
    message = _message()
    bot = _bot_returning(b"# Hello")
    html = "x" * 32768

    with patch("src.bot.document.markdown_to_rich_html", return_value=(html, [])):
        await handle_document(message, bot, _settings(tmp_path))

    message.answer_rich.assert_awaited_once()
    assert _rich_arg(message).html == html


async def test_length_boundary_32769_rejected(tmp_path):
    message = _message()
    bot = _bot_returning(b"# Hello")
    html = "x" * 32769

    with patch("src.bot.document.markdown_to_rich_html", return_value=(html, [])):
        await handle_document(message, bot, _settings(tmp_path))

    message.answer.assert_awaited_once_with(texts.POST_TOO_LONG)
    message.answer_rich.assert_not_awaited()


async def test_broken_media_notice_not_blocked_by_length_cap(tmp_path):
    # Body at the cap plus a failed-media notice exceeds 32768 if combined.
    # The notice must stay outside the rich payload so a fitting post still sends.
    message = _message()
    sent = MagicMock()
    sent.message_id = 777
    message.answer_rich = AsyncMock(return_value=sent)
    bot = _bot_returning(b"# Hello")
    html = "x" * 32768

    with patch("src.bot.document.markdown_to_rich_html", return_value=(html, [0])):
        await handle_document(message, bot, _settings(tmp_path))

    message.answer_rich.assert_awaited_once()
    sent = _rich_arg(message).html
    assert sent == html
    message.answer.assert_any_await(
        texts.failed_media_notice([0]),
        reply_to_message_id=777,
    )


async def test_broken_media_listed(tmp_path):
    message = _message()
    sent = MagicMock()
    sent.message_id = 777
    message.answer_rich = AsyncMock(return_value=sent)
    bot = _bot_returning(b"# Hello")

    with patch("src.bot.document.markdown_to_rich_html", return_value=("<b>body</b>", [0, 2])):
        await handle_document(message, bot, _settings(tmp_path))

    message.answer_rich.assert_awaited_once()
    html = _rich_arg(message).html
    assert html == "<b>body</b>"
    message.answer.assert_any_await(
        texts.failed_media_notice([0, 2]),
        reply_to_message_id=777,
    )
