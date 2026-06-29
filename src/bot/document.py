import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InputRichMessage, Message

from src.bot import common, texts
from src.bot.publish import (
    _deactivate_previous_controls,
    _send_publish_controls,
    _send_reply_message,
)
from src.bot.storage import BotStateError
from src.config import Settings
from src.post import MediaStore, markdown_to_rich_html

log = structlog.get_logger()


async def handle_document(message: Message, bot: Bot, settings: Settings) -> None:
    if not common._is_private_chat(message):
        await message.answer(texts.DOCUMENT_PRIVATE_REQUIRED)
        return

    document = message.document

    file_name = (document.file_name or "").lower()
    mime_type = document.mime_type or ""
    is_md = file_name.endswith(".md") or mime_type in ("text/markdown", "text/x-markdown")
    if not is_md:
        await message.answer(texts.DOCUMENT_MD_REQUIRED)
        return

    if document.file_size is not None and document.file_size > common._MAX_UPLOAD_BYTES:
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
    if len(raw) > common._MAX_UPLOAD_BYTES:
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
        max_image_bytes=common._MAX_IMAGE_B64_BYTES,
        max_images_per_message=common._MAX_IMAGES_PER_MESSAGE,
    )
    try:
        add_blank_spacers = common._store(settings).get_add_blank_spacers()
    except BotStateError:
        await common._answer_state_error(message)
        return
    html, failed_media_indices = markdown_to_rich_html(
        text,
        media_store,
        add_blank_spacers=add_blank_spacers,
    )

    # Cap the post body itself, before appending the failed-media notice — the
    # notice must never push a borderline post over the limit and silence it.
    if len(html) > common._MAX_HTML_CHARS:
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
            common._store(settings).save_post(
                private_chat_id=private_chat_id,
                message_id=sent_message_id,
                html=html,
            )
            saved = True
        except BotStateError:
            log.warning("sent_post_cache_save_failed", message_id=sent_message_id)
    if saved:
        await _send_publish_controls(message, bot, settings, sent_message_id)
