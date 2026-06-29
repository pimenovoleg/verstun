import os

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


def test_health_does_not_write_probe_file(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    media_dir = tmp_path / "media"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("MEDIA_DIR", str(media_dir))
    get_settings.cache_clear()
    client = TestClient(app)
    try:
        assert client.get("/health").status_code == 200
        # Writability is probed via os.access, so no probe file is left behind
        # and the dirs stay empty (no per-call disk churn).
        assert list(data_dir.iterdir()) == []
        assert list(media_dir.iterdir()) == []
    finally:
        get_settings.cache_clear()


def test_health_reports_degraded_when_dir_not_writable(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    media_dir = tmp_path / "media"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("MEDIA_DIR", str(media_dir))
    get_settings.cache_clear()
    os.chmod(data_dir, 0o500)  # read + execute, no write
    client = TestClient(app)
    try:
        response = client.get("/health")
        assert response.status_code == 503
        detail = response.json()["detail"]
        assert detail["status"] == "degraded"
        assert detail["data_dir_writable"] is False
        assert detail["media_dir_writable"] is True
    finally:
        os.chmod(data_dir, 0o700)
        get_settings.cache_clear()
