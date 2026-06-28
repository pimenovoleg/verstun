import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.api.app import app
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
