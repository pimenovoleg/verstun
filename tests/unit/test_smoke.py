import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.api.app import app
from src.bot.storage import BotStateError, BotStateStore
from src.config import Settings, get_settings


def test_config_loads_with_defaults():
    settings = Settings(_env_file=None)
    assert settings.environment == "dev"
    assert settings.media_base_url == ""


def test_prod_requires_media_base_url():
    with pytest.raises(ValidationError, match="MEDIA_BASE_URL"):
        Settings(
            _env_file=None,
            ENVIRONMENT="prod",
            BOT_TOKEN="123:abc",
            OWNER_TELEGRAM_ID=42,
        )


def test_prod_requires_https_media_base_url():
    with pytest.raises(ValidationError, match="MEDIA_BASE_URL must be an HTTPS URL"):
        Settings(
            _env_file=None,
            ENVIRONMENT="prod",
            BOT_TOKEN="123:abc",
            OWNER_TELEGRAM_ID=42,
            MEDIA_BASE_URL="http://example.com/media",
        )


def test_prod_accepts_required_secrets():
    settings = Settings(
        _env_file=None,
        ENVIRONMENT="prod",
        BOT_TOKEN="123:abc",
        OWNER_TELEGRAM_ID=42,
        MEDIA_BASE_URL="https://example.com/media",
    )
    assert settings.media_base_url == "https://example.com/media"


def test_health_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEDIA_DIR", str(tmp_path / "media"))
    get_settings.cache_clear()
    client = TestClient(app)
    try:
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["data_dir_writable"] is True
        assert body["media_dir_writable"] is True
    finally:
        get_settings.cache_clear()


def test_health_cleans_up_probe_files(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    media_dir = tmp_path / "media"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("MEDIA_DIR", str(media_dir))
    get_settings.cache_clear()
    client = TestClient(app)
    try:
        assert client.get("/health").status_code == 200
        # Health now performs real write/rename/delete probes. The state lock is
        # durable, but transient probe files must be cleaned up.
        assert {path.name for path in data_dir.iterdir()} == {"bot-state.lock"}
        assert list(media_dir.iterdir()) == []
    finally:
        get_settings.cache_clear()


def test_health_reports_degraded_when_state_healthcheck_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEDIA_DIR", str(tmp_path / "media"))

    def fail_healthcheck(self):
        raise BotStateError("state unavailable")

    monkeypatch.setattr(BotStateStore, "healthcheck", fail_healthcheck)
    get_settings.cache_clear()
    client = TestClient(app)
    try:
        response = client.get("/health")
        assert response.status_code == 503
        detail = response.json()["detail"]
        assert detail["status"] == "degraded"
        assert detail["data_dir_writable"] is False
        assert detail["media_dir_writable"] is True
    finally:
        get_settings.cache_clear()


def test_health_reports_degraded_when_state_json_is_corrupt(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    state_path = data_dir / "bot-state.json"
    state_path.write_text("{not-json", encoding="utf-8")
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("MEDIA_DIR", str(tmp_path / "media"))
    get_settings.cache_clear()
    client = TestClient(app)
    try:
        response = client.get("/health")
        assert response.status_code == 503
        detail = response.json()["detail"]
        assert detail["status"] == "degraded"
        assert detail["data_dir_writable"] is False
        assert detail["media_dir_writable"] is True
        assert state_path.read_text(encoding="utf-8") == "{not-json"
        assert list(data_dir.glob("bot-state.json.corrupt-*")) == []
    finally:
        get_settings.cache_clear()


def test_health_reports_degraded_when_media_probe_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEDIA_DIR", str(tmp_path / "media"))

    def fail_probe(directory):
        raise OSError("media unavailable")

    monkeypatch.setattr("src.api.app._write_delete_probe", fail_probe)
    get_settings.cache_clear()
    client = TestClient(app)
    try:
        response = client.get("/health")
        assert response.status_code == 503
        detail = response.json()["detail"]
        assert detail["status"] == "degraded"
        assert detail["data_dir_writable"] is True
        assert detail["media_dir_writable"] is False
    finally:
        get_settings.cache_clear()
