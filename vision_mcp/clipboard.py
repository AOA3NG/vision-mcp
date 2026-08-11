from __future__ import annotations

import os
import time
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterator

from PIL import Image, ImageGrab

SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
CLIPBOARD_RETRIES = 20
CLIPBOARD_RETRY_DELAY_SECONDS = 0.1


def _grab_with_retry():
    last_error: OSError | None = None
    for attempt in range(CLIPBOARD_RETRIES):
        try:
            return ImageGrab.grabclipboard()
        except OSError as exc:
            last_error = exc
            if attempt + 1 < CLIPBOARD_RETRIES:
                time.sleep(CLIPBOARD_RETRY_DELAY_SECONDS)
    assert last_error is not None
    raise last_error


def _grab_native_png() -> Image.Image | None:
    """Read custom PNG clipboard formats used by some screenshot tools."""
    try:
        import win32clipboard
    except ImportError:
        return None

    for format_name in ("PNG", "image/png"):
        try:
            format_id = win32clipboard.RegisterClipboardFormat(format_name)
            if not win32clipboard.IsClipboardFormatAvailable(format_id):
                continue
            win32clipboard.OpenClipboard()
            try:
                data = win32clipboard.GetClipboardData(format_id)
            finally:
                win32clipboard.CloseClipboard()
            if isinstance(data, bytes) and data:
                with Image.open(BytesIO(data)) as image:
                    return image.copy()
        except OSError:
            continue
    return None


@contextmanager
def clipboard_image_path() -> Iterator[str]:
    """Yield an image path from the Windows clipboard.

    Bitmap clipboard data is written to a short-lived PNG. Files copied in
    Explorer are used in place and are never modified or deleted.
    """
    if os.name != "nt":
        raise ValueError("剪贴板图片分析仅支持 Windows")

    try:
        value = _grab_with_retry()
    except OSError as exc:
        raise ValueError(
            "无法读取 Windows 剪贴板，可能正被 Snipaste 或其他剪贴板工具占用；请稍等后重新复制截图再试"
        ) from exc

    if value is None:
        value = _grab_native_png()

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
