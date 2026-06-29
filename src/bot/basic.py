from base64 import b64encode
from importlib import resources

from aiogram.types import InputRichMessage, Message

from src.bot import common, texts
from src.config import Settings
from src.post import MediaStore


async def start(message: Message) -> None:
    await message.answer(texts.START_TEXT)


async def handle_demo(message: Message, settings: Settings) -> None:
    media_store = MediaStore(
        media_dir=settings.media_dir,
        media_base_url=settings.media_base_url,
        media_max_bytes=settings.media_max_bytes,
        max_image_bytes=common._MAX_IMAGE_B64_BYTES,
        max_images_per_message=common._MAX_IMAGES_PER_MESSAGE,
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
