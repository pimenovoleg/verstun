# Verstun

[Русская версия](README.md)

Verstun converts Google Docs Markdown exports into Telegram Rich Messages.
It preserves rich formatting and embedded images by hosting the images on your
server and replacing Google Docs base64 image data with public HTTPS URLs that
Telegram can fetch.

The bot is self-hosted. You run it with your own Telegram bot token and your
own domain.

Runtime state is stored in a JSON file under `DATA_DIR`: connected channels,
managed users, per-channel access grants, the short-lived channel connect flag, and
generated post cache data, and rendering settings.

## What It Does

- Accepts `.md` files exported from Google Docs.
- Converts Markdown to Telegram Rich Message HTML.
- Hosts embedded PNG/JPEG/GIF/WebP images at `/media/<hash>.<ext>`.
- Supports headings, tables, lists, quotes, code, spoilers, details blocks,
  footnotes, LaTeX formulas, embedded images, and external video/GIF/audio URLs.
- Replies with the generated Rich Message for review.
- Optionally publishes the generated post into a connected Telegram channel.

LaTeX uses regular Markdown math syntax:

```md
Inline: $E = mc^2$

$$
x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}
$$
```

External media uses the same Markdown syntax as images:

```md
![](https://example.com/photo.jpg)
![](https://example.com/animation.gif)
![](https://example.com/video.mp4)
![](https://example.com/iphone-video.mov)
![](https://example.com/audio.mp3)
![](https://example.com/iphone-audio.m4a)
```

External media types are detected only from the URL path extension. Supported
extensions: `jpg`, `jpeg`, `png`, `webp`, `heic`, `heif`, `gif`, `mp4`, `mov`,
`m4v`, `webm`, `mp3`, `ogg`, `oga`, `m4a`, `aac`, `wav`, `flac`. Extensionless
URLs and risky formats such as `svg`, `html`, `pdf`, `exe`, `js`, archives, or
playlists are not emitted into the Rich Message.

## Markdown Syntax

### Headings

```md
# Heading H1
## Heading H2
### Heading H3
#### Heading H4
##### Heading H5
###### Heading H6
```

### Text

```md
**bold**
*italic*
~~strikethrough~~
`inline code`
[link](https://example.com)
||spoiler||
```

### Lists, Quotes, Code, Tables

````md
- item
- another item

1. first
2. second

> Quote

```python
print("hello")
```

| Element | Status |
|---|---|
| Tables | work |
| Media | works |
````

### Details Blocks

```md
:::details Block title
Hidden content.
:::

:::details-open Open by default
Content.
:::
```

### Footnotes And LaTeX

```md
Text with a footnote[^note].

[^note]: Footnote text.

Inline: $E = mc^2$

$$
x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}
$$
```

### Images, Video, GIF, And Audio

Media links must be standalone blocks with blank lines around them:

```md
![](https://example.com/photo.jpg)
![](https://example.com/animation.gif)
![](https://example.com/video.mp4)
![](https://example.com/iphone-video.mov)
![](https://example.com/audio.mp3)
![](https://example.com/iphone-audio.m4a)
```

Captions use the Markdown title:

```md
![](https://example.com/video.mp4 "Video caption")
```

If a media link is placed inside text, a table, or a footnote, it is rendered as
plain alt text instead of `<img>`, `<video>`, or `<audio>`. Telegram expects Rich
Message media as separate blocks.

## Requirements

- A Linux server or VPS.
- Docker and Docker Compose.
- A domain or subdomain pointing to the server.
- A Telegram bot token from `@BotFather`.
- Your numeric Telegram user ID from `@userinfobot`.

Telegram must be able to fetch images over public HTTPS, so a domain with a
valid TLS certificate is required when your Markdown contains embedded `data:` /
base64 images, which is common for Google Docs Markdown exports.

If your Markdown already uses normal public image URLs such as
`https://example.com/image.png`, Verstun passes those URLs through. In that
case, local `/media/*` hosting is not required for those images; Telegram
fetches them from their existing public URLs.

The same rule applies to external GIF, video, and audio links: the bot does not
run `GET` or `HEAD`, does not download files, does not sniff MIME types, and does
not become a CDN. It only validates the `http/https` scheme and URL path
extension, then emits a safe media tag into the Rich Message. If the URL points
to different content, Telegram may refuse or fail to render it.

The standard Docker setup in this repository is a production setup and still
requires `MEDIA_BASE_URL=https://...`, because it is meant to safely support
Google Docs exports with embedded images. If you are sure you will only use
external `https://...` image URLs and want to run without a domain/Caddy, treat
that as an advanced/dev setup: run the backend separately with `ENVIRONMENT=dev`.

## Setup

Before starting the stack, point your domain or subdomain to the server with an
A record and make sure ports 80 and 443 are reachable from the internet.

Clone the repository:

```bash
git clone https://github.com/pavel-molyanov/verstun.git
cd verstun
```

Create configuration files:

```bash
cp .env.example .env
cp Caddyfile.example Caddyfile
chmod 600 .env
```

Edit `.env`:

```env
BOT_TOKEN=<botfather-token>
OWNER_TELEGRAM_ID=<telegram-user-id>
MEDIA_BASE_URL=https://your-domain.com/media
ENVIRONMENT=prod
```

Edit `Caddyfile` and replace `your-domain.com` with your real domain.

Start the stack:

```bash
docker compose up -d --build
```

Check health:

```bash
curl https://your-domain.com/health
```

If startup fails, check:

```bash
docker compose ps
docker compose logs -f caddy
docker compose logs -f backend
```

Open Telegram, send `/start` to your bot, then send `/demo` to check that Rich
Messages render correctly. After that, send a `.md` file exported from Google
Docs.

## Commands

- `/start` - short welcome message.
- `/demo` - Rich Message demo with the main formatting elements, including
  LaTeX.
- `/channels` - connect and disconnect Telegram channels.
- `/users` - manage users and their channel access grants.
- `/settings` - owner-only rendering settings.

Management commands are intended for a private chat with the bot. Do not use the
bot as a group participant for preparing posts.

## Rendering Settings

`/settings` is available only to the instance owner. It currently contains a
toggle for blank lines between blocks.

By default, the bot inserts blank lines between adjacent paragraphs, and between
paragraphs, headings, and horizontal rules. Telegram Rich Messages collapse
ordinary whitespace between blocks, so without these spacer blocks the rendered
post can visually glue text to headings and dividers. If you want a denser post,
the owner can disable these blank lines in `/settings`.

## Users and Access

`OWNER_TELEGRAM_ID` is the instance owner. The owner can use every command,
connect channels, and manage other users with `/users`.

Users added through `/users` can send `.md` files and publish through the bot
only to the channels you explicitly grant to them. Users who are not the owner
and are not added in `/users` are ignored by the bot.

Access grants restrict bot-mediated publishing. They do not prevent a user from
manually forwarding or copying a generated preview to places where that user
already has Telegram posting rights.

## Channel Publishing

To publish directly into a channel:

1. Add your bot to the channel as an administrator.
2. Grant only the right to post messages.
3. Send `/channels` to the bot and press **Add new channel**.
4. Forward any post from the channel to the bot.
5. Send a `.md` file; the bot will reply with publishing buttons under the generated Rich Message.

Publishing buttons are shown only for channels where the current user has
access and the bot currently has posting rights. You can also forward the
generated Rich Message manually instead of granting the bot channel rights.

## Security Notes

The bot needs channel administrator rights only for direct publishing through
buttons. Grant the minimum permissions: allow posting messages, and avoid edit,
delete, invite, promote, and other unrelated rights.

Treat the bot token as a publishing credential. Do not share it, paste it into
chats, commit `.env`, or expose it in logs and screenshots. Rotate the token in
`@BotFather` periodically and immediately after any suspected leak. Add only
trusted people through `/users`, and grant each user only the channels they need.

For maximum safety, remove the bot's posting rights when you are not actively
publishing: grant rights, publish the post, then remove rights again.

The `/media/*` route is public. Embedded images from Markdown files are stored
in the `media` Docker volume and served over HTTPS without authentication. Do
not send secret images, personal documents, token screenshots, or private drafts
to the bot.

To report a vulnerability, use a GitHub Security Advisory or contact the author
privately. Do not publish working exploit details before a fix is available.

## Development

This section is only for local development; Docker self-host setup does not
require it.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/pytest tests/unit/ -q
```

## License

MIT

## Author

Pavel Molyanov - [molyanov.ru](https://molyanov.ru)

I write a Telegram channel about AI, entrepreneurship, management, and
vibecoding: [@molyanov_blog](https://t.me/+LATr_Jgwz5EzNDM6)
