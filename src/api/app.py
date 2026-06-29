import os
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException

from src.bot.storage import BotStateError, BotStateStore
from src.config import get_settings


def create_app() -> FastAPI:
    app = FastAPI(title="verstun-bot API")

    @app.get("/health")
    async def health() -> dict[str, object]:
        settings = get_settings()
        data_dir_writable = _state_available(settings.data_dir)
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


def _state_available(path: str) -> bool:
    try:
        BotStateStore(path).healthcheck()
    except BotStateError:
        return False
    return True


def _dir_writable(path: str) -> bool:
    directory = Path(path)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        _write_delete_probe(directory)
    except OSError:
        return False
    return True


def _write_delete_probe(directory: Path) -> None:
    probe = directory / f".healthcheck.{os.getpid()}.{uuid.uuid4().hex}"
    tmp = probe.with_suffix(f"{probe.suffix}.tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(b"ok")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, probe)
        _fsync_dir(directory)
        probe.unlink()
        _fsync_dir(directory)
    except OSError:
        for path in (tmp, probe):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def _fsync_dir(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
