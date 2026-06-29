import base64
import hashlib
import struct
import zlib
from unittest.mock import patch

from src.post.media import MediaStore

BASE_URL = "https://example.test/media"


def _png_bytes(width: int = 1, height: int = 1, color: bytes = b"\x00\x00\x00") -> bytes:
    """Build a minimal valid 1x1 (or NxN) PNG with the given pixel color."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b""
    for _ in range(height):
        raw += b"\x00" + color * width
    idat = zlib.compress(raw)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def _jpeg_bytes() -> bytes:
    return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 16 + b"\xff\xd9"


def _gif_bytes() -> bytes:
    return b"GIF89a" + b"\x01\x00\x01\x00\x00\x00\x00\x3b"


def _webp_bytes() -> bytes:
    body = b"WEBPVP8 " + b"\x00" * 16
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _store(tmp_path, **overrides) -> MediaStore:
    kwargs = {
        "media_dir": str(tmp_path),
        "media_base_url": BASE_URL,
        "media_max_bytes": 10_000_000,
        "max_image_bytes": 5_000_000,
        "max_images_per_message": 10,
    }
    kwargs.update(overrides)
    return MediaStore(**kwargs)


def test_save_writes_content_hash_filename(tmp_path):
    png = _png_bytes()
    store = _store(tmp_path)
    url = store.save(_b64(png))
    assert url is not None
    expected = hashlib.sha256(png).hexdigest()
    written = list(tmp_path.iterdir())
    assert len(written) == 1
    assert written[0].name == f"{expected}.png"


def test_extension_from_magic_bytes_not_data_uri_label(tmp_path):
    # The data-URI MIME label is stripped by the markdown render rule before save()
    # is ever called, so save() only sees raw base64 and must derive the extension
    # from the sniffed magic bytes. Here PNG bytes -> .png regardless of any label.
    png = _png_bytes()
    store = _store(tmp_path)
    url = store.save(_b64(png))
    assert url is not None
    assert url.endswith(".png")
    assert list(tmp_path.iterdir())[0].suffix == ".png"


def test_save_returns_public_media_url(tmp_path):
    png = _png_bytes()
    store = _store(tmp_path)
    url = store.save(_b64(png))
    expected = hashlib.sha256(png).hexdigest()
    assert url == f"{BASE_URL}/{expected}.png"


def test_dedupe_same_bytes_single_file(tmp_path):
    png = _png_bytes()
    store = _store(tmp_path)
    url1 = store.save(_b64(png))
    url2 = store.save(_b64(png))
    assert url1 == url2
    assert len(list(tmp_path.iterdir())) == 1


def test_magic_byte_sniff_accepts_raster(tmp_path):
    for data, ext in [
        (_png_bytes(), ".png"),
        (_jpeg_bytes(), ".jpg"),
        (_gif_bytes(), ".gif"),
        (_webp_bytes(), ".webp"),
    ]:
        store = _store(tmp_path)
        url = store.save(_b64(data))
        assert url is not None, ext
        assert url.endswith(ext)


def test_rejects_svg_payload(tmp_path):
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    store = _store(tmp_path)
    assert store.save(_b64(svg)) is None
    assert list(tmp_path.iterdir()) == []


def test_rejects_non_image_payload(tmp_path):
    html = b"<html><body>not an image</body></html>"
    store = _store(tmp_path)
    assert store.save(_b64(html)) is None
    assert list(tmp_path.iterdir()) == []


def test_realpath_guard_blocks_traversal(tmp_path):
    # Every written file's resolved path must stay under MEDIA_DIR.
    png = _png_bytes()
    store = _store(tmp_path)
    url = store.save(_b64(png))
    assert url is not None
    written = list(tmp_path.iterdir())[0]
    media_root = tmp_path.resolve()
    assert written.resolve().is_relative_to(media_root)


def test_per_image_size_cap_pre_decode(tmp_path):
    png = _png_bytes(width=10, height=10)
    b64 = _b64(png)
    # Cap below the base64 string length → rejected before decode.
    store = _store(tmp_path, max_image_bytes=len(b64) - 1)
    assert store.save(b64) is None
    assert list(tmp_path.iterdir()) == []


def test_per_message_image_count_cap(tmp_path):
    store = _store(tmp_path, max_images_per_message=2)
    assert store.save(_b64(_png_bytes(color=b"\x01\x01\x01"))) is not None
    assert store.save(_b64(_png_bytes(color=b"\x02\x02\x02"))) is not None
    # Third distinct image exceeds the per-message cap.
    assert store.save(_b64(_png_bytes(color=b"\x03\x03\x03"))) is None


def test_size_cap_prune_removes_oldest_from_prior_message(tmp_path):
    import os
    import time

    img_a = _png_bytes(width=20, height=20, color=b"\xaa\xaa\xaa")
    img_b = _png_bytes(width=20, height=20, color=b"\xbb\xbb\xbb")
    # A leftover file from a previous message (a fresh MediaStore is built per
    # message, so its hash is not in this store's _saved_hashes).
    hash_a = hashlib.sha256(img_a).hexdigest()
    (tmp_path / f"{hash_a}.png").write_bytes(img_a)
    old = time.time() - 60 * 60
    os.utime(tmp_path / f"{hash_a}.png", (old, old))

    # Cap allows only one image of this size at a time.
    cap = len(img_a) + len(img_b) - 1
    store = _store(tmp_path, media_max_bytes=cap)

    url_b = store.save(_b64(img_b))
    assert url_b is not None
    names = {p.name for p in tmp_path.iterdir()}
    hash_b = hashlib.sha256(img_b).hexdigest()
    # Prior-message file pruned, just-saved file kept.
    assert f"{hash_b}.png" in names
    assert f"{hash_a}.png" not in names


def test_prune_keeps_all_images_of_current_message(tmp_path):
    # Regression for the prune-before-send bug: every image hosted by THIS store
    # (one MediaStore == one post) must survive prune, even when their combined
    # size blows past media_max_bytes — otherwise an early image of a post could
    # be deleted before the Rich Message is sent, vanishing without being marked
    # as failed.
    img_a = _png_bytes(width=20, height=20, color=b"\xaa\xaa\xaa")
    img_b = _png_bytes(width=20, height=20, color=b"\xbb\xbb\xbb")
    # Cap below even a single image, so a naive prune would drop the earlier one.
    store = _store(tmp_path, media_max_bytes=1)

    url_a = store.save(_b64(img_a))
    url_b = store.save(_b64(img_b))
    assert url_a is not None and url_b is not None

    names = {p.name for p in tmp_path.iterdir()}
    assert names == {
        f"{hashlib.sha256(img_a).hexdigest()}.png",
        f"{hashlib.sha256(img_b).hexdigest()}.png",
    }


def test_prune_keeps_recent_prior_message_file_for_concurrent_send(tmp_path):
    img_a = _png_bytes(width=20, height=20, color=b"\xaa\xaa\xaa")
    img_b = _png_bytes(width=20, height=20, color=b"\xbb\xbb\xbb")
    hash_a = hashlib.sha256(img_a).hexdigest()
    (tmp_path / f"{hash_a}.png").write_bytes(img_a)

    cap = len(img_a) + len(img_b) - 1
    store = _store(tmp_path, media_max_bytes=cap)

    url_b = store.save(_b64(img_b))
    assert url_b is not None

    names = {p.name for p in tmp_path.iterdir()}
    assert names == {
        f"{hash_a}.png",
        f"{hashlib.sha256(img_b).hexdigest()}.png",
    }


def test_invalid_base64_returns_none(tmp_path):
    store = _store(tmp_path)
    assert store.save("!!!not base64!!!") is None
    assert list(tmp_path.iterdir()) == []


def test_newline_wrapped_base64_hosted(tmp_path):
    # Google Docs may wrap base64 at 76 chars (RFC 2045). Whitespace must be
    # stripped before decode so a real wrapped payload still hosts successfully.
    png = _png_bytes(width=10, height=10)
    b64 = _b64(png)
    wrapped = "\n".join(b64[i : i + 76] for i in range(0, len(b64), 76))
    assert "\n" in wrapped
    store = _store(tmp_path)
    url = store.save(wrapped)
    assert url is not None
    expected = hashlib.sha256(png).hexdigest()
    assert url == f"{BASE_URL}/{expected}.png"


def test_dedupe_hit_does_not_consume_count_cap(tmp_path):
    # A repeated image returns early via dedupe BEFORE the per-message count check,
    # so re-sending the same bytes must not spend an extra count-cap slot. With a
    # cap of 2, one distinct image saved twice still leaves room for a second.
    store = _store(tmp_path, max_images_per_message=2)
    img_a = _b64(_png_bytes(color=b"\x01\x01\x01"))
    assert store.save(img_a) is not None
    assert store.save(img_a) is not None  # dedupe hit, no new slot consumed
    # A second distinct image still fits under the cap of 2.
    assert store.save(_b64(_png_bytes(color=b"\x02\x02\x02"))) is not None
    # A third distinct image exceeds the cap.
    assert store.save(_b64(_png_bytes(color=b"\x03\x03\x03"))) is None


def test_save_never_prunes_just_saved_file(tmp_path):
    img = _png_bytes(width=30, height=30)
    b64 = _b64(img)
    # Cap smaller than a single image — the just-saved file must still survive.
    store = _store(tmp_path, media_max_bytes=1)
    url = store.save(b64)
    assert url is not None
    assert len(list(tmp_path.iterdir())) == 1


def test_save_returns_none_when_media_write_fails(tmp_path):
    store = _store(tmp_path)

    with patch("pathlib.Path.write_bytes", side_effect=OSError("disk full")):
        assert store.save(_b64(_png_bytes())) is None

    assert list(tmp_path.iterdir()) == []
