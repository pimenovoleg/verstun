import os
from pathlib import Path

from fastapi import FastAPI, HTTPException

from src.config import get_settings


def create_app() -> FastAPI:
    app = FastAPI(title="verstun-bot API")

    @app.get("/health")
    async def health() -> dict[str, object]:
        settings = get_settings()
        data_dir_writable = _dir_writable(settings.data_dir)
        media_dir_writable = _dir_writable(settings.media_dir)
        if not data_dir_writable or not media_dir_writable:
            raise HTTPException(
                status_code=503,
                detail={
                    "status": "degraded",
                    "environment": settings.environment,
                    "bot_token_loaded": bool(settings.bot_token),
                    "data_dir_writable": data_dir_writable,
                    "media_dir_writable": media_dir_writable,
                },
            )
        return {
            "status": "ok",
            "environment": settings.environment,
            "bot_token_loaded": bool(settings.bot_token),
            "data_dir_writable": data_dir_writable,
            "media_dir_writable": media_dir_writable,
        }

    return app


app = create_app()


def _dir_writable(path: str) -> bool:
    directory = Path(path)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    # Probe writability with os.access instead of writing a temp file: health
    # checks can be polled frequently, and writing/deleting a probe on every call
    # is needless disk churn (and races two concurrent checks on a shared name).
    return os.access(directory, os.W_OK | os.X_OK)
