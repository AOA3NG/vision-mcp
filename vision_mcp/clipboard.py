from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterator

from PIL import Image, ImageGrab

SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


@contextmanager
def clipboard_image_path() -> Iterator[str]:
    """Yield an image path from the Windows clipboard.

    Bitmap clipboard data is written to a short-lived PNG. Files copied in
    Explorer are used in place and are never modified or deleted.
    """
    if os.name != "nt":
        raise ValueError("剪贴板图片分析仅支持 Windows")

    try:
        value = ImageGrab.grabclipboard()
    except OSError as exc:
        raise ValueError("无法读取 Windows 剪贴板，请重新复制图片后再试") from exc

    if isinstance(value, Image.Image):
        with TemporaryDirectory(prefix="vision-mcp-clipboard-") as folder:
            path = Path(folder) / "clipboard.png"
            value.save(path, format="PNG")
            yield str(path)
        return

    if isinstance(value, (list, tuple)):
        for item in value:
            path = Path(item)
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
                yield str(path.resolve())
                return

    raise ValueError("剪贴板中没有可用图片。请先复制图片本体或图片文件，不要粘贴到对话框，然后重试")
