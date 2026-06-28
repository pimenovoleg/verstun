from aiogram.types import BotCommand

START_TEXT = "\n".join(
    [
        "Привет. Я помогаю сверстать пост из Google Docs в Telegram Rich Message "
        "и опубликовать его в канале.",
        "",
        "Как это работает:",
        "1. Напиши пост в Google Docs.",
        "2. Добавь картинки, таблицы, списки и другие элементы.",
        "3. Скачай документ как Markdown (.md).",
        "4. Пришли .md файл сюда — я соберу такой же пост в Telegram.",
        "5. Выбери канал, и я опубликую пост в нем.",
        "",
        "Команды:",
        "/channels — подключенные каналы",
        "/users — пользователи и доступы",
        "/demo — посмотреть, какие элементы верстки поддерживает бот",
    ]
)

DEMO_HTML = r"""
<h1>Демонстрация Verstun</h1>
<p>Так выглядит пост, который бот собирает из Google Docs Markdown.</p>
<h2>Текст</h2>
<p>Поддерживаются <b>жирный текст</b>, <i>курсив</i>, <s>зачеркивание</s>, <code>inline code</code>, безопасные <a href="https://telegram.org/blog/watch-apps-and-more">гиперссылки</a> и <tg-spoiler>спойлеры</tg-spoiler>.</p>
<h3>Заголовки H3</h3>
<h4>Заголовки H4</h4>
<h5>Заголовки H5</h5>
<h6>Заголовки H6</h6>
<h2>Списки</h2>
<ul><li>обычный пункт списка</li><li>пункт с <b>форматированием</b></li><li>вложенные списки из Markdown тоже сохраняются</li></ul>
<ol><li>нумерованный пункт</li><li>еще один пункт</li></ol>
<h2>Цитаты и раскрывающиеся блоки</h2>
<blockquote>Цитата сохраняется отдельным блоком.</blockquote>
<details><summary>Раскрывающийся блок</summary><p>Внутри можно прятать дополнительный текст, ссылки и списки.</p></details>
<h2>Таблица</h2>
<table><thead><tr><th>Элемент</th><th>Статус</th></tr></thead><tbody><tr><td>Заголовки</td><td>работают</td></tr><tr><td>Таблицы</td><td>работают</td></tr><tr><td>Картинки</td><td>работают</td></tr><tr><td>Видео, GIF и аудио</td><td>работают по внешним HTTPS-ссылкам</td></tr><tr><td>Сноски</td><td>работают</td></tr><tr><td>Формулы</td><td>работают</td></tr></tbody></table>
<h2>Код</h2>
<pre><code>print("Markdown → Rich Message")</code></pre>
<h2>Формулы</h2>
<p>Inline LaTeX: <tg-math>E = mc^2</tg-math></p>
<tg-math-block>x = \frac{{-b \pm \sqrt{{b^2 - 4ac}}}}{{2a}}</tg-math-block>
<hr>
<h2>Картинка</h2>
<p>Картинки из Markdown хостятся по HTTPS и встраиваются прямо в Rich Message.</p>
{demo_image}
<h2>Внешние медиа</h2>
<p>GIF, видео и аудио можно вставлять в Markdown как обычные media-ссылки. Бот не скачивает внешние файлы, а передает Telegram только публичный URL.</p>
<video src="https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4"></video>
<audio src="https://www.w3schools.com/html/horse.mp3"></audio>
<h2>Сноски</h2>
<p>В тексте можно поставить ссылку на примечание<a name="footnote-ref-1"></a><sup><a href="#footnote-1">1</a></sup>, а само примечание будет видно внизу поста.</p>
<a name="footnote-1"></a><footer>1. Так выглядят сноски после конвертации из Google Docs Markdown. <a href="#footnote-ref-1">↩</a></footer>
""".strip()

BOT_COMMANDS = [
    BotCommand(command="start", description="Как пользоваться ботом"),
    BotCommand(command="demo", description="Элементы верстки"),
    BotCommand(command="channels", description="Подключенные каналы"),
    BotCommand(command="users", description="Пользователи и доступы"),
]

CONNECT_TEXT = (
    "Чтобы подключить канал, добавь бота в администраторы канала, "
    "выдай ему право публикации сообщений и перешли сюда любой пост из этого канала."
)

STATE_READ_ERROR = "Не смог прочитать состояние бота. Попробуй еще раз."
PRIVATE_CHAT_REQUIRED = "Эта команда работает только в личном чате с ботом."

USER_IS_OWNER = "Это владелец бота. У владельца уже есть доступ ко всем каналам."
USER_ADDED = "Пользователь добавлен."
USER_ALREADY_ADDED = "Пользователь уже добавлен."
USER_PICKER_PROMPT = "Выбери пользователя через кнопку ниже."
USER_PICKER_BUTTON = "Выбрать пользователя"
USERS_MENU_STALE = "Меню устарело. Отправь /users заново."
USERS_PRIVATE_REQUIRED = "Меню пользователей работает только в личном чате с ботом."
NO_GRANTED_CHANNELS = "У тебя пока нет доступных каналов. Попроси владельца выдать доступ."

CHANNEL_FORWARD_REQUIRED = "Перешли именно пост из канала."
CHANNEL_POSTING_RIGHTS_MISSING = (
    "Не вижу права публикации. Проверь, что бот добавлен в канал администратором "
    "и может публиковать сообщения."
)
CHANNELS_MENU_STALE = "Меню устарело. Отправь /channels заново."
CHANNELS_PRIVATE_REQUIRED = "Управление каналами работает только в личном чате с ботом."
CHANNELS_EMPTY = "Каналы не подключены."
CHANNEL_DELETE_PROMPT = "Выбери канал, который нужно отключить."

POST_BUTTON_STALE = "Кнопка устарела. Отправь .md файл заново."
PUBLISH_PRIVATE_REQUIRED = "Публикация работает только в личном чате с ботом."
PUBLISH_NO_ACCESS = "Нет доступа к этому каналу. Попроси владельца выдать доступ."
PUBLISHING = "Публикую..."
PUBLISH_RIGHTS_MISSING = (
    "Не получилось опубликовать пост. Выдай боту право публикации сообщений в этом канале."
)
PUBLISH_SEND_ERROR = "Не смог отправить пост. Проверь права бота в канале и попробуй еще раз."
PUBLISH_ALREADY_SENT = "Этот пост уже отправлен в этот канал."
PUBLISH_CONTROLS_PROMPT = "Выбери канал, в который отправить пост."
OWNER_NO_PUBLISHABLE_CHANNELS = (
    "Пост готов, но сейчас нет каналов, куда бот может публиковать.\n"
    "Открой /channels и подключи канал или выдай боту право публикации сообщений."
)
USER_NO_PUBLISHABLE_CHANNELS = (
    "Пост готов, но сейчас нет доступных каналов, куда бот может публиковать.\n"
    "Попроси владельца проверить доступы и права бота в канале."
)

DOCUMENT_PRIVATE_REQUIRED = "Пришли .md файл в личном чате с ботом."
DOCUMENT_MD_REQUIRED = "Пришли Markdown-файл с расширением .md."
DOCUMENT_TOO_LARGE = "Файл слишком большой. Максимальный размер — 5 МБ."
DOCUMENT_DOWNLOAD_ERROR = "Не смог скачать файл из Telegram. Попробуй отправить .md еще раз."
DOCUMENT_READ_ERROR = "Не смог прочитать файл. Пришли текстовый .md в UTF-8."
DOCUMENT_EMPTY = "Файл пустой. Пришли .md с текстом поста."
POST_TOO_LONG = "Пост слишком длинный: больше 32768 символов."
POST_SEND_ERROR = "Не смог отправить Rich Message. Проверь файл и попробуй еще раз."
PUBLISH_CONTROLS_SEND_ERROR = (
    "Пост готов, но не смог показать кнопки публикации. Отправь .md еще раз."
)

BUTTON_ADD_USER = "➕ Добавить пользователя"
BUTTON_DELETE_USER = "🗑 Удалить пользователя"
BUTTON_BACK = "↩️ Назад"
BUTTON_CONNECT_CHANNEL = "➕ Подключить новый канал"
BUTTON_DISCONNECT_CHANNEL = "🗑 Отключить канал"


def channel_connected(title: str) -> str:
    return f"Канал подключен: {title}"


def channel_disconnected(title: str) -> str:
    return f"Канал отключен: {title}"


def channels_overview(channels: list[str]) -> str:
    return "Подключенные каналы:\n" + "\n".join(f"• {title}" for title in channels)


def channel_delete_button(title: str) -> str:
    return f"🗑 {title}"


def publish_channel_button(title: str) -> str:
    return f"Опубликовать: {title}"


def publish_success(title: str) -> str:
    return f"Пост отправлен в канал: {title}"


def failed_media_notice(indices: list[int]) -> str:
    numbers = ", ".join(f"№{index + 1}" for index in indices)
    return f"Пост готов, но не удалось добавить медиафайлы: {numbers}."


def users_list_text(has_users: bool) -> str:
    text = "Пользователи и доступы\n\nВыбери пользователя или добавь нового."
    if not has_users:
        text += "\n\nПока никого нет."
    return text


def user_card_text(
    *,
    name: str,
    telegram_id: int,
    username: str | None,
    has_channels: bool,
) -> str:
    username_text = f"@{username}" if username else "нет"
    text = "\n".join(
        [
            name,
            f"ID: {telegram_id}",
            f"Username: {username_text}",
            "",
            "Доступы к каналам:",
        ]
    )
    if not has_channels:
        text += "\nКаналы не подключены."
    return text


def user_channel_access_button(title: str, allowed: bool) -> str:
    return f"{'✅' if allowed else '❌'} {title}"
