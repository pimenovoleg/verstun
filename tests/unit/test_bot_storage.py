import json
import stat
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from src.bot.storage import BotStateError, BotStateStore


def test_connect_pending_persists(tmp_path):
    store = BotStateStore(str(tmp_path))
    store.set_connect_pending(True)

    reloaded = BotStateStore(str(tmp_path))

    assert reloaded.is_connect_pending() is True


def test_save_channel_upserts_and_lists_active(tmp_path):
    store = BotStateStore(str(tmp_path))

    store.save_channel(chat_id=-1001, title="Old", username=None)
    store.save_channel(chat_id=-1001, title="New", username="channel")

    channels = store.list_channels()
    assert len(channels) == 1
    assert channels[0].chat_id == -1001
    assert channels[0].title == "New"
    assert channels[0].username == "channel"


def test_user_can_be_saved_listed_loaded_and_deleted(tmp_path):
    store = BotStateStore(str(tmp_path))

    store.save_user(telegram_id=123, name="Lena", username="smm_lena")

    user = store.get_user(123)
    assert user is not None
    assert user.telegram_id == 123
    assert user.name == "Lena"
    assert user.username == "smm_lena"
    assert user.channel_ids == []
    assert store.list_users() == [user]
    assert store.is_allowed_user(123) is True

    store.delete_user(123)

    assert store.get_user(123) is None
    assert store.list_users() == []
    assert store.is_allowed_user(123) is False


def test_delete_user_removes_legacy_records_with_same_telegram_id(tmp_path):
    path = tmp_path / "bot-state.json"
    state = {
        "connect_pending": {"pending": False, "created_at": datetime.now(UTC).isoformat()},
        "channels": {},
        "posts": {},
        "users": {
            "legacy-copy": {
                "telegram_id": 123,
                "name": "Legacy",
                "username": "legacy",
                "channel_ids": [-1001],
            }
        },
    }
    path.write_text(json.dumps(state), encoding="utf-8")
    store = BotStateStore(str(tmp_path))

    store.delete_user(123)

    assert store.get_user(123) is None
    assert store.list_users() == []


def test_save_user_preserves_channel_access_on_profile_update(tmp_path):
    store = BotStateStore(str(tmp_path))
    store.save_user(telegram_id=123, name="Old", username=None)
    store.set_user_channel_access(telegram_id=123, channel_id=-1001, allowed=True)

    store.save_user(telegram_id=123, name="New", username="new_name")

    user = store.get_user(123)
    assert user is not None
    assert user.name == "New"
    assert user.username == "new_name"
    assert user.channel_ids == [-1001]


def test_list_users_deduplicates_legacy_records_by_telegram_id(tmp_path):
    path = tmp_path / "bot-state.json"
    state = {
        "connect_pending": {"pending": False, "created_at": datetime.now(UTC).isoformat()},
        "channels": {},
        "posts": {},
        "users": {
            "123": {
                "telegram_id": 123,
                "name": "Old",
                "username": None,
                "channel_ids": [-1001],
            },
            "legacy-copy": {
                "telegram_id": 123,
                "name": "New",
                "username": "new",
                "channel_ids": [-1002],
            },
        },
    }
    path.write_text(json.dumps(state), encoding="utf-8")

    users = BotStateStore(str(tmp_path)).list_users()

    assert len(users) == 1
    assert users[0].telegram_id == 123


def test_get_user_migrates_legacy_only_record_to_canonical_key(tmp_path):
    path = tmp_path / "bot-state.json"
    state = {
        "connect_pending": {"pending": False, "created_at": datetime.now(UTC).isoformat()},
        "channels": {},
        "posts": {},
        "users": {
            "legacy-copy": {
                "telegram_id": 123,
                "name": "Legacy",
                "username": "legacy",
                "channel_ids": [-1001],
            }
        },
    }
    path.write_text(json.dumps(state), encoding="utf-8")
    store = BotStateStore(str(tmp_path))

    user = store.get_user(123)

    assert user is not None
    assert user.telegram_id == 123
    assert user.channel_ids == [-1001]
    raw = json.loads(path.read_text(encoding="utf-8"))["users"]
    assert "legacy-copy" not in raw
    assert raw["123"]["channel_ids"] == [-1001]


def test_save_user_merges_duplicate_channel_grants(tmp_path):
    path = tmp_path / "bot-state.json"
    state = {
        "connect_pending": {"pending": False, "created_at": datetime.now(UTC).isoformat()},
        "channels": {},
        "posts": {},
        "users": {
            "123": {
                "telegram_id": 123,
                "name": "Old",
                "username": None,
                "channel_ids": [-1001],
            },
            "legacy-copy": {
                "telegram_id": 123,
                "name": "Legacy",
                "username": "legacy",
                "channel_ids": [-1002],
            },
        },
    }
    path.write_text(json.dumps(state), encoding="utf-8")
    store = BotStateStore(str(tmp_path))

    store.save_user(telegram_id=123, name="New", username="new")

    user = store.get_user(123)
    assert user is not None
    assert user.name == "New"
    assert user.username == "new"
    assert user.channel_ids == [-1002, -1001]


def test_user_channel_access_toggles_and_filters_channels(tmp_path):
    store = BotStateStore(str(tmp_path))
    store.save_channel(chat_id=-1002, title="Second", username=None)
    store.save_channel(chat_id=-1001, title="First", username=None)
    store.save_user(telegram_id=123, name="Lena", username=None)

    store.set_user_channel_access(telegram_id=123, channel_id=-1002, allowed=True)

    assert [c.chat_id for c in store.list_channels_for_user(123)] == [-1002]
    assert store.user_can_publish_to(telegram_id=123, channel_id=-1002) is True
    assert store.user_can_publish_to(telegram_id=123, channel_id=-1001) is False

    store.set_user_channel_access(telegram_id=123, channel_id=-1002, allowed=False)

    assert store.list_channels_for_user(123) == []
    assert store.user_can_publish_to(telegram_id=123, channel_id=-1002) is False


def test_delete_channel_removes_channel_and_user_access_grants(tmp_path):
    store = BotStateStore(str(tmp_path))
    store.save_channel(chat_id=-1001, title="First", username=None)
    store.save_channel(chat_id=-1002, title="Second", username=None)
    store.save_user(telegram_id=123, name="Lena", username=None)
    store.set_user_channel_access(telegram_id=123, channel_id=-1001, allowed=True)
    store.set_user_channel_access(telegram_id=123, channel_id=-1002, allowed=True)

    store.delete_channel(-1001)

    assert store.get_channel(-1001) is None
    assert [channel.chat_id for channel in store.list_channels()] == [-1002]
    assert store.user_can_publish_to(telegram_id=123, channel_id=-1001) is False
    assert store.user_can_publish_to(telegram_id=123, channel_id=-1002) is True


def test_save_post_can_be_loaded_by_private_chat_and_message_id(tmp_path):
    store = BotStateStore(str(tmp_path))

    store.save_post(private_chat_id=42, message_id=777, html="<h1>Hello</h1>")

    assert store.get_post(private_chat_id=42, message_id=777) == "<h1>Hello</h1>"
    assert store.get_post(private_chat_id=42, message_id=778) is None


def test_blank_spacer_setting_defaults_enabled_and_persists(tmp_path):
    store = BotStateStore(str(tmp_path))

    assert store.get_add_blank_spacers() is True

    store.set_add_blank_spacers(False)

    reloaded = BotStateStore(str(tmp_path))
    assert reloaded.get_add_blank_spacers() is False
    raw = json.loads((tmp_path / "bot-state.json").read_text(encoding="utf-8"))
    assert raw["render_settings"]["add_blank_spacers"] is False

    reloaded.set_add_blank_spacers(True)

    assert BotStateStore(str(tmp_path)).get_add_blank_spacers() is True


def test_save_post_replaces_previous_post_for_same_private_chat(tmp_path):
    store = BotStateStore(str(tmp_path))

    store.save_post(private_chat_id=42, message_id=1, html="old")
    store.save_post(private_chat_id=7, message_id=1, html="other")
    store.save_post(private_chat_id=42, message_id=2, html="new")

    assert store.get_post(private_chat_id=42, message_id=1) is None
    assert store.get_post(private_chat_id=42, message_id=2) == "new"
    assert store.get_post(private_chat_id=7, message_id=1) == "other"


def test_active_controls_can_be_saved_and_popped_once(tmp_path):
    store = BotStateStore(str(tmp_path))

    store.save_active_controls(private_chat_id=42, post_message_id=777, controls_message_id=778)

    assert store.pop_active_controls(private_chat_id=42) == (777, 778)
    assert store.pop_active_controls(private_chat_id=42) is None


def test_post_cache_prunes_oldest_entries(tmp_path):
    store = BotStateStore(str(tmp_path), max_posts=2)

    store.save_post(private_chat_id=1, message_id=1, html="one")
    store.save_post(private_chat_id=2, message_id=2, html="two")
    store.save_post(private_chat_id=3, message_id=3, html="three")

    assert store.get_post(private_chat_id=1, message_id=1) is None
    assert store.get_post(private_chat_id=2, message_id=2) == "two"
    assert store.get_post(private_chat_id=3, message_id=3) == "three"


def test_connect_pending_expires(tmp_path):
    store = BotStateStore(str(tmp_path))
    store.set_connect_pending(True)
    path = tmp_path / "bot-state.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    state["connect_pending"]["created_at"] = (datetime.now(UTC) - timedelta(minutes=11)).isoformat()
    path.write_text(json.dumps(state), encoding="utf-8")

    assert store.is_connect_pending() is False


def test_legacy_boolean_connect_pending_does_not_stay_pending_forever(tmp_path):
    path = tmp_path / "bot-state.json"
    path.write_text(
        json.dumps({"connect_pending": True, "channels": {}, "posts": {}}),
        encoding="utf-8",
    )

    assert BotStateStore(str(tmp_path)).is_connect_pending() is False


def test_state_read_io_error_raises_without_resetting(tmp_path):
    path = tmp_path / "bot-state.json"
    original = {
        "connect_pending": {"pending": False, "created_at": datetime.now(UTC).isoformat()},
        "channels": {},
        "posts": {},
    }
    path.write_text(json.dumps(original), encoding="utf-8")
    store = BotStateStore(str(tmp_path))

    with patch.object(path.__class__, "read_text", side_effect=OSError("busy")):
        with pytest.raises(BotStateError):
            store.list_channels()

    assert json.loads(path.read_text(encoding="utf-8")) == original


def test_corrupt_state_file_is_preserved_and_reset(tmp_path):
    path = tmp_path / "bot-state.json"
    path.write_text("{not-json", encoding="utf-8")

    assert BotStateStore(str(tmp_path)).list_channels() == []

    backups = list(tmp_path.glob("bot-state.json.corrupt-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{not-json"


def test_state_file_permissions_are_private(tmp_path):
    store = BotStateStore(str(tmp_path))

    store.save_post(private_chat_id=42, message_id=777, html="<h1>Hello</h1>")

    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / "bot-state.json").stat().st_mode) == 0o600


def test_state_write_io_error_raises_bot_state_error(tmp_path):
    store = BotStateStore(str(tmp_path))

    with patch("os.replace", side_effect=OSError("disk full")):
        with pytest.raises(BotStateError):
            store.save_post(private_chat_id=42, message_id=777, html="<h1>Hello</h1>")

    assert not (tmp_path / "bot-state.tmp").exists()


def test_publish_marker_blocks_duplicate_publish_and_can_be_cleared(tmp_path):
    store = BotStateStore(str(tmp_path))

    assert store.begin_publish(private_chat_id=42, post_message_id=777, channel_id=-1001) is True
    assert store.begin_publish(private_chat_id=42, post_message_id=777, channel_id=-1001) is False

    store.clear_publish(private_chat_id=42, post_message_id=777, channel_id=-1001)

    assert store.begin_publish(private_chat_id=42, post_message_id=777, channel_id=-1001) is True


def test_published_markers_expire_after_retention(tmp_path):
    store = BotStateStore(str(tmp_path))
    assert store.begin_publish(private_chat_id=42, post_message_id=777, channel_id=-1001) is True
    # Without expiry the marker would block this post's channel forever.
    assert store.begin_publish(private_chat_id=42, post_message_id=777, channel_id=-1001) is False

    path = tmp_path / "bot-state.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    old = (datetime.now(UTC) - timedelta(days=15)).isoformat()
    for marker in state["published_posts"].values():
        marker["created_at"] = old
    path.write_text(json.dumps(state), encoding="utf-8")

    # The expired marker is pruned, so the slot frees up and the count stays bounded.
    assert store.begin_publish(private_chat_id=42, post_message_id=777, channel_id=-1001) is True
    reloaded = json.loads(path.read_text(encoding="utf-8"))
    assert len(reloaded["published_posts"]) == 1


def test_expired_posts_dropped_on_next_save(tmp_path):
    store = BotStateStore(str(tmp_path))
    store.save_post(private_chat_id=1, message_id=1, html="old")

    path = tmp_path / "bot-state.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    state["posts"]["1:1"]["created_at"] = (datetime.now(UTC) - timedelta(days=15)).isoformat()
    path.write_text(json.dumps(state), encoding="utf-8")

    # A later post (different chat, so the per-chat replace does not touch it)
    # triggers age-based pruning of the stale entry.
    store.save_post(private_chat_id=2, message_id=2, html="new")

    assert store.get_post(private_chat_id=1, message_id=1) is None
    assert store.get_post(private_chat_id=2, message_id=2) == "new"
