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
generated post cache data.

## What It Does

- Accepts `.md` files exported from Google Docs.
- Converts Markdown to Telegram Rich Message HTML.
- Hosts embedded PNG/JPEG/GIF/WebP images at `/media/<hash>.<ext>`.
- Supports headings, tables, lists, quotes, code, spoilers, details blocks,
  footnotes, and LaTeX formulas.
- Replies with the generated Rich Message for review.
- Optionally publishes the generated post into a connected Telegram channel.

LaTeX uses regular Markdown math syntax:

```md
Inline: $E = mc^2$

$$
x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}
$$
```

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

Management commands are intended for a private chat with the bot. Do not use the
bot as a group participant for preparing posts.

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
