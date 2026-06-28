from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str = Field(default="", alias="BOT_TOKEN")
    environment: Literal["dev", "prod"] = Field(default="dev", alias="ENVIRONMENT")

    owner_telegram_id: int | None = Field(default=None, alias="OWNER_TELEGRAM_ID")
    data_dir: str = Field(default="/srv/data", alias="DATA_DIR")
    media_dir: str = Field(default="/srv/media", alias="MEDIA_DIR")
    media_base_url: str = Field(default="", alias="MEDIA_BASE_URL")
    media_max_bytes: int = Field(default=1_073_741_824, alias="MEDIA_MAX_BYTES")

    @model_validator(mode="after")
    def _require_prod_secrets(self) -> "Settings":
        if self.environment == "prod":
            missing = [
                name
                for name, value in (
                    ("BOT_TOKEN", self.bot_token),
                    ("OWNER_TELEGRAM_ID", self.owner_telegram_id),
                    ("MEDIA_BASE_URL", self.media_base_url),
                )
                if not value
            ]
            if missing:
                raise ValueError(f"Missing required env vars in prod: {', '.join(missing)}")
            parsed_media_url = urlparse(self.media_base_url)
            if parsed_media_url.scheme != "https" or not parsed_media_url.netloc:
                raise ValueError("MEDIA_BASE_URL must be an HTTPS URL in prod")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
