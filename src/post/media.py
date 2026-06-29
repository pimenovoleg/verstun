"""Hosting store for inline base64 images referenced by Markdown posts.

Decodes base64 image payloads, sniffs magic bytes to allow-list raster types,
writes them under a sha256 content-hash filename, and returns a public URL so
the rich-message converter can swap a `data:` URI for an `<img src>` Telegram
will accept. All rejections (decode error, non-raster content, size/count caps)
return ``None`` so the converter can record the image as failed.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
import time
from pathlib import Path

import structlog

log = structlog.get_logger()

# Magic-byte signatures for the raster types we host. The extension is derived
# from the sniffed bytes here, never from the (attacker-supplied) data-URI label.
_PNG = b"\x89PNG\r\n\x1a\n"
_GIF87 = b"GIF87a"
_GIF89 = b"GIF89a"
_JPEG = b"\xff\xd8\xff"
_RIFF = b"RIFF"
_WEBP = b"WEBP"

# Strips RFC-2045 line-wrap whitespace from a base64 payload before decoding.
_B64_WHITESPACE = str.maketrans("", "", " \t\n\r")

# Prune grace window for files written by another in-flight message. aiogram may
# process updates concurrently; without this, MediaStore B can delete fresh files
# written by MediaStore A before A sends the Rich Message that references them.
_PRUNE_GRACE_SECONDS = 30 * 60


def _sniff_extension(data: bytes) -> str | None:
    if data.startswith(_PNG):
        return "png"
    if data.startswith(_JPEG):
        return "jpg"
    if data.startswith(_GIF87) or data.startswith(_GIF89):
        return "gif"
    if data.startswith(_RIFF) and data[8:12] == _WEBP:
        return "webp"
    return None


class MediaStore:
    """Content-addressed store for decoded base64 images on a shared volume.

    Constructed once per message: ``max_images_per_message`` caps how many
    distinct images a single message may host, so a flood cannot exhaust the
    backend container.
    """

    def __init__(
        self,
        media_dir: str,
        media_base_url: str,
        media_max_bytes: int,
        max_image_bytes: int,
        max_images_per_message: int,
    ) -> None:
        self._dir = Path(media_dir).resolve()
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.warning("media_dir_create_failed", path=str(self._dir), exc_info=exc)
        self._base_url = media_base_url.rstrip("/")
        self._media_max_bytes = media_max_bytes
        self._max_image_bytes = max_image_bytes
        self._max_images_per_message = max_images_per_message
        self._saved_hashes: set[str] = set()

    def save(self, b64_data: str) -> str | None:
        """Decode, validate, and host one base64 image.

        Returns the public ``MEDIA_BASE_URL/<hash>.<ext>`` URL, or ``None`` if the
        payload is rejected (bad base64, non-raster, oversized, or over the
        per-message count cap).
        """
        # Per-image cap on the base64 STRING length (~4/3 of decoded size) BEFORE
        # decoding, so an oversized blob is never fully materialised in memory.
        if len(b64_data) > self._max_image_bytes:
            return None

        # Google-Docs data URIs may wrap base64 at 76 chars (RFC 2045), so strip
        # whitespace before decoding; validate=True then rejects any non-base64
        # character that remains.
        clean = b64_data.translate(_B64_WHITESPACE)
        try:
            data = base64.b64decode(clean, validate=True)
        except (binascii.Error, ValueError):
            return None

        ext = _sniff_extension(data)
        if ext is None:
            return None

        digest = hashlib.sha256(data).hexdigest()

        # Dedupe: identical bytes resolve to the same file and URL, and must not
        # count again toward the per-message cap or re-trigger a prune.
        if digest in self._saved_hashes:
            return self._url_for(digest, ext)

        if len(self._saved_hashes) >= self._max_images_per_message:
            return None

        filename = f"{digest}.{ext}"
        dest = (self._dir / filename).resolve()
        # Path-traversal guard: the resolved write path must stay under MEDIA_DIR.
        if dest.parent != self._dir:
            return None

        try:
            if not dest.exists():
                dest.write_bytes(data)
        except OSError as exc:
            log.warning("media_write_failed", path=str(dest), exc_info=exc)
            return None

        self._saved_hashes.add(digest)
        self._prune()
        return self._url_for(digest, ext)

    def _url_for(self, digest: str, ext: str) -> str:
        return f"{self._base_url}/{digest}.{ext}"

    def _prune(self) -> None:
        """Delete oldest files until the dir is under ``media_max_bytes``.

        Every image hosted for the CURRENT message (this store's ``_saved_hashes``)
        is protected, even if they alone exceed the cap. Fresh files from other
        MediaStore instances are also protected for a short grace window: aiogram
        may process updates concurrently, and another message can still be between
        hosting images and sending the Rich Message. Older prior-message files are
        eligible for pruning. Filenames are ``<sha256>.<ext>``, so the stem is the
        content hash we match against ``_saved_hashes``.
        """
        try:
            files = [p for p in self._dir.iterdir() if p.is_file()]
            total = sum(p.stat().st_size for p in files)
        except OSError as exc:
            log.warning("media_prune_scan_failed", path=str(self._dir), exc_info=exc)
            return
        if total <= self._media_max_bytes:
            return

        cutoff_mtime = time.time() - _PRUNE_GRACE_SECONDS
        candidates = []
        for path in files:
            if path.stem in self._saved_hashes:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_mtime > cutoff_mtime:
                continue
            candidates.append((path, stat.st_mtime, stat.st_size))
        candidates.sort(key=lambda item: item[1])

        for path, _, size in candidates:
            if total <= self._media_max_bytes:
                break
            try:
                os.remove(path)
            except OSError:
                continue
            total -= size
