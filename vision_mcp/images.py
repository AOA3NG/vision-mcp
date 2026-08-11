from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_OUTPUT_BYTES = 6 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_SIDE = 1568
ALLOWED = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp", "GIF": "image/gif"}


def prepare_image(path_value: str) -> tuple[str, bytes]:
    path = Path(path_value)
    if not path.is_file():
        raise ValueError(f"图片文件不存在: {path}")
    size = path.stat().st_size
    if size <= 0 or size > MAX_SOURCE_BYTES:
        raise ValueError("图片文件为空或超过 16MB")
    raw = path.read_bytes()
    if len(raw) != size or len(raw) > MAX_SOURCE_BYTES:
        raise ValueError("图片文件读取期间发生变化或超过 16MB")
    try:
        with Image.open(io.BytesIO(raw)) as image:
            fmt = image.format
            if fmt not in ALLOWED:
                raise ValueError(f"不支持的图片格式: {fmt or '未知'}")
            width, height = image.size
            if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
                raise ValueError("图片像素数量超过 4000 万上限")
            image.seek(0)
            image.load()
            image = ImageOps.exif_transpose(image)
            image.thumbnail((MAX_SIDE, MAX_SIDE))
            out = io.BytesIO()
            if image.mode not in ("RGB", "L"):
                background = Image.new("RGB", image.size, "white")
                if "A" in image.getbands():
                    background.paste(image, mask=image.getchannel("A"))
                else:
                    background.paste(image)
                image = background
            else:
                image = image.convert("RGB")
            # Re-encode pixels only. This intentionally strips EXIF/XMP/GPS and
            # avoids forwarding hidden metadata to the configured provider.
            image.save(out, format="JPEG", quality=88, optimize=True)
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("文件不是有效图片或图片已损坏") from exc
    data = out.getvalue()
    if len(data) > MAX_OUTPUT_BYTES:
        raise ValueError("图片压缩后仍超过 6MB")
    return "image/jpeg", data
