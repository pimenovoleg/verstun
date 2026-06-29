from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()

_CONNECT_TTL_SECONDS = 10 * 60
# Cached posts and publish markers describe content already delivered to a
# channel — the channel is the source of truth. The bot only needs them long
# enough to back the inline publish buttons, so drop both after two weeks to keep
# the JSON state from growing without bound.
_RETENTION_SECONDS = 14 * 24 * 60 * 60
_LOCK = threading.RLock()


class BotStateError(RuntimeError):
    pass


@dataclass(frozen=True)
class ConnectedChannel:
    chat_id: int
    title: str
    username: str | None


@dataclass(frozen=True)
class ManagedUser:
    telegram_id: int
    name: str
    username: str | None
    channel_ids: list[int]


class BotStateStore:
    """Small JSON-backed state store for the owner-managed bot."""

    def __init__(self, data_dir: str, *, max_posts: int = 100) -> None:
        self._dir = Path(data_dir).resolve()
        self._path = self._dir / "bot-state.json"
        self._max_posts = max_posts

    def is_connect_pending(self) -> bool:
        with _LOCK:
            pending = self._read().get("connect_pending", {})
            if isinstance(pending, bool):
                return False
            if not isinstance(pending, dict) or not pending.get("pending"):
                return False

            created_at = pending.get("created_at")
            if not isinstance(created_at, str):
                return False
            try:
                created = datetime.fromisoformat(created_at)
            except ValueError:
                return False
            return (datetime.now(UTC) - created).total_seconds() <= _CONNECT_TTL_SECONDS

    def set_connect_pending(self, pending: bool) -> None:
        with _LOCK:
            state = self._read()
            state["connect_pending"] = {
                "pending": pending,
                "created_at": _now_iso(),
            }
            self._write(state)

    def save_channel(self, chat_id: int, title: str, username: str | None) -> None:
        with _LOCK:
            state = self._read()
            channels = state.setdefault("channels", {})
            channels[str(chat_id)] = {
                "chat_id": chat_id,
                "title": title,
                "username": username,
                "active": True,
                "updated_at": _now_iso(),
            }
            self._write(state)

    def list_channels(self) -> list[ConnectedChannel]:
        with _LOCK:
            channels = self._read().get("channels", {})
            active = [c for c in channels.values() if c.get("active", True)]
            active.sort(key=lambda c: str(c.get("title") or ""))
            return [
                ConnectedChannel(
                    chat_id=int(c["chat_id"]),
                    title=str(c.get("title") or c["chat_id"]),
                    username=c.get("username"),
                )
                for c in active
            ]

    def get_channel(self, chat_id: int) -> ConnectedChannel | None:
        with _LOCK:
            raw = self._read().get("channels", {}).get(str(chat_id))
            if not raw or not raw.get("active", True):
                return None
            return ConnectedChannel(
                chat_id=int(raw["chat_id"]),
                title=str(raw.get("title") or raw["chat_id"]),
                username=raw.get("username"),
            )

    def delete_channel(self, chat_id: int) -> None:
        with _LOCK:
            state = self._read()
            state.setdefault("channels", {}).pop(str(chat_id), None)
            for raw in state.setdefault("users", {}).values():
                if not isinstance(raw, dict):
                    continue
                channel_ids = set(_normalise_channel_ids(raw.get("channel_ids")))
                if chat_id in channel_ids:
                    channel_ids.discard(chat_id)
                    raw["channel_ids"] = sorted(channel_ids)
                    raw["updated_at"] = _now_iso()
            self._write(state)

    def save_user(self, telegram_id: int, name: str, username: str | None) -> None:
        with _LOCK:
            state = self._read()
            users = state.setdefault("users", {})
            _canonicalise_user_record(users, telegram_id)
            existing = users.get(str(telegram_id))
            channel_ids = []
            created_at = _now_iso()
            if isinstance(existing, dict):
                channel_ids = _normalise_channel_ids(existing.get("channel_ids"))
                created_at = str(existing.get("created_at") or created_at)
            users[str(telegram_id)] = {
                "telegram_id": telegram_id,
                "name": name,
                "username": username,
                "channel_ids": channel_ids,
                "created_at": created_at,
                "updated_at": _now_iso(),
            }
            self._write(state)

    def delete_user(self, telegram_id: int) -> None:
        with _LOCK:
            state = self._read()
            users = state.setdefault("users", {})
            users.pop(str(telegram_id), None)
            for key, raw in list(users.items()):
                user = _managed_user_from_raw(raw)
                if user is not None and user.telegram_id == telegram_id:
                    users.pop(key, None)
            self._write(state)

    def get_user(self, telegram_id: int) -> ManagedUser | None:
        with _LOCK:
            state = self._read()
            users = state.setdefault("users", {})
            changed = _canonicalise_user_record(users, telegram_id)
            if changed:
                self._write(state)
            raw = users.get(str(telegram_id))
            return _managed_user_from_raw(raw)

    def list_users(self) -> list[ManagedUser]:
        with _LOCK:
            users_by_id = {}
            for raw in self._read().get("users", {}).values():
                user = _managed_user_from_raw(raw)
                if user is not None:
                    users_by_id[user.telegram_id] = user
            result = list(users_by_id.values())
            result.sort(key=lambda user: (user.name.casefold(), user.telegram_id))
            return result

    def is_allowed_user(self, telegram_id: int) -> bool:
        return self.get_user(telegram_id) is not None

    def set_user_channel_access(self, telegram_id: int, channel_id: int, allowed: bool) -> None:
        with _LOCK:
            state = self._read()
            users = state.setdefault("users", {})
            raw = users.get(str(telegram_id))
            if not isinstance(raw, dict):
                return
            channel_ids = set(_normalise_channel_ids(raw.get("channel_ids")))
            if allowed:
                channel_ids.add(channel_id)
            else:
                channel_ids.discard(channel_id)
            raw["channel_ids"] = sorted(channel_ids)
            raw["updated_at"] = _now_iso()
            self._write(state)

    def user_can_publish_to(self, telegram_id: int, channel_id: int) -> bool:
        user = self.get_user(telegram_id)
        return user is not None and channel_id in user.channel_ids

    def list_channels_for_user(self, telegram_id: int) -> list[ConnectedChannel]:
        user = self.get_user(telegram_id)
        if user is None:
            return []
        allowed = set(user.channel_ids)
        return [channel for channel in self.list_channels() if channel.chat_id in allowed]

    def save_post(self, private_chat_id: int, message_id: int, html: str) -> None:
        with _LOCK:
            state = self._read()
            posts = state.setdefault("posts", {})
            prefix = f"{private_chat_id}:"
            for key in list(posts):
                if key.startswith(prefix):
                    posts.pop(key, None)
            posts[_post_key(private_chat_id, message_id)] = {
                "private_chat_id": private_chat_id,
                "message_id": message_id,
                "html": html,
                "created_at": _now_iso(),
            }
            _drop_expired(posts, _RETENTION_SECONDS)

            if len(posts) > self._max_posts:
                oldest = sorted(
                    posts.items(), key=lambda item: str(item[1].get("created_at") or "")
                )
                for key, _ in oldest[: len(posts) - self._max_posts]:
                    posts.pop(key, None)

            self._write(state)

    def get_post(self, private_chat_id: int, message_id: int) -> str | None:
        with _LOCK:
            raw = self._read().get("posts", {}).get(_post_key(private_chat_id, message_id))
            if not raw:
                return None
            html = raw.get("html")
            return html if isinstance(html, str) else None

    def get_add_blank_spacers(self) -> bool:
        with _LOCK:
            settings = self._read().get("render_settings", {})
            if not isinstance(settings, dict):
                return True
            return settings.get("add_blank_spacers") is not False

    def set_add_blank_spacers(self, enabled: bool) -> None:
        with _LOCK:
            state = self._read()
            render_settings = state.setdefault("render_settings", {})
            if not isinstance(render_settings, dict):
                render_settings = {}
                state["render_settings"] = render_settings
            render_settings["add_blank_spacers"] = bool(enabled)
            render_settings["updated_at"] = _now_iso()
            self._write(state)

    def save_active_controls(
        self,
        private_chat_id: int,
        post_message_id: int,
        controls_message_id: int,
    ) -> None:
        with _LOCK:
            state = self._read()
            state.setdefault("active_controls", {})[str(private_chat_id)] = {
                "private_chat_id": private_chat_id,
                "post_message_id": post_message_id,
                "controls_message_id": controls_message_id,
                "created_at": _now_iso(),
            }
            self._write(state)

    def pop_active_controls(self, private_chat_id: int) -> tuple[int, int] | None:
        with _LOCK:
            state = self._read()
            raw = state.setdefault("active_controls", {}).pop(str(private_chat_id), None)
            self._write(state)
        if not isinstance(raw, dict):
            return None
        try:
            return int(raw["post_message_id"]), int(raw["controls_message_id"])
        except (KeyError, TypeError, ValueError):
            return None

    def begin_publish(self, private_chat_id: int, post_message_id: int, channel_id: int) -> bool:
        with _LOCK:
            state = self._read()
            published = state.setdefault("published_posts", {})
            _drop_expired(published, _RETENTION_SECONDS)
            key = _publish_key(private_chat_id, post_message_id, channel_id)
            if key in published:
                return False
            published[key] = {
                "private_chat_id": private_chat_id,
                "post_message_id": post_message_id,
                "channel_id": channel_id,
                "created_at": _now_iso(),
            }
            self._write(state)
            return True

    def clear_publish(self, private_chat_id: int, post_message_id: int, channel_id: int) -> None:
        with _LOCK:
            state = self._read()
            state.setdefault("published_posts", {}).pop(
                _publish_key(private_chat_id, post_message_id, channel_id), None
            )
            self._write(state)

    def _read(self) -> dict[str, Any]:
        if not self._path.exists():
            return _empty_state()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except OSError as exc:
            log.warning("bot_state_read_failed", path=str(self._path), exc_info=exc)
            raise BotStateError("bot state is temporarily unavailable") from exc
        except json.JSONDecodeError as exc:
            backup = self._path.with_name(f"{self._path.name}.corrupt-{_file_stamp()}")
            try:
                os.replace(self._path, backup)
            except OSError:
                backup = None
            log.warning(
                "bot_state_corrupt",
                path=str(self._path),
                backup=str(backup) if backup else None,
                exc_info=exc,
            )
            return _empty_state()
        if not isinstance(raw, dict):
            return _empty_state()
        raw.setdefault("connect_pending", {"pending": False, "created_at": _now_iso()})
        raw.setdefault("channels", {})
        raw.setdefault("posts", {})
        raw.setdefault("users", {})
        raw.setdefault("active_controls", {})
        raw.setdefault("published_posts", {})
        raw.setdefault("render_settings", {"add_blank_spacers": True})
        return raw

    def _write(self, state: dict[str, Any]) -> None:
        tmp = self._path.with_suffix(".tmp")
        try:
            self._dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(self._dir, 0o700)
            data = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, self._path)
            os.chmod(self._path, 0o600)
        except OSError as exc:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            log.warning("bot_state_write_failed", path=str(self._path), exc_info=exc)
            raise BotStateError("bot state is temporarily unavailable") from exc


def _empty_state() -> dict[str, Any]:
    return {
        "connect_pending": {"pending": False, "created_at": _now_iso()},
        "channels": {},
        "posts": {},
        "users": {},
        "active_controls": {},
        "published_posts": {},
        "render_settings": {"add_blank_spacers": True},
    }


def _post_key(private_chat_id: int, message_id: int) -> str:
    return f"{private_chat_id}:{message_id}"


def _publish_key(private_chat_id: int, post_message_id: int, channel_id: int) -> str:
    return f"{private_chat_id}:{post_message_id}:{channel_id}"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _drop_expired(records: dict[str, Any], ttl_seconds: int) -> None:
    """Remove records whose ``created_at`` is older than ``ttl_seconds``.

    Records with a missing or unparseable ``created_at`` are left untouched so a
    malformed timestamp never silently drops live state.
    """
    cutoff = datetime.now(UTC) - timedelta(seconds=ttl_seconds)
    for key, value in list(records.items()):
        created_at = value.get("created_at") if isinstance(value, dict) else None
        if not isinstance(created_at, str):
            continue
        try:
            created = datetime.fromisoformat(created_at)
        except ValueError:
            continue
        if created < cutoff:
            records.pop(key, None)


def _file_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")


def _managed_user_from_raw(raw: Any) -> ManagedUser | None:
    if not isinstance(raw, dict):
        return None
    try:
        telegram_id = int(raw["telegram_id"])
    except (KeyError, TypeError, ValueError):
        return None
    return ManagedUser(
        telegram_id=telegram_id,
        name=str(raw.get("name") or telegram_id),
        username=raw.get("username"),
        channel_ids=_normalise_channel_ids(raw.get("channel_ids")),
    )


def _normalise_channel_ids(raw: Any) -> list[int]:
    if not isinstance(raw, list):
        return []
    result = []
    for item in raw:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return sorted(set(result))


def _canonicalise_user_record(users: dict[str, Any], telegram_id: int) -> bool:
    canonical_key = str(telegram_id)
    canonical = users.get(canonical_key)
    merged_channel_ids = set()
    created_at = None
    changed = False

    if isinstance(canonical, dict):
        merged_channel_ids.update(_normalise_channel_ids(canonical.get("channel_ids")))
        created_at = canonical.get("created_at")

    for key, raw in list(users.items()):
        if key == canonical_key:
            continue
        user = _managed_user_from_raw(raw)
        if user is not None and user.telegram_id == telegram_id:
            merged_channel_ids.update(user.channel_ids)
            if created_at is None and isinstance(raw, dict):
                created_at = raw.get("created_at")
            if canonical is None and isinstance(raw, dict):
                canonical = dict(raw)
            users.pop(key, None)
            changed = True

    if canonical is not None:
        canonical["telegram_id"] = telegram_id
        canonical["channel_ids"] = sorted(merged_channel_ids)
        if created_at is not None:
            canonical["created_at"] = created_at
        users[canonical_key] = canonical
    return changed
