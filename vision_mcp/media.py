from __future__ import annotations

import base64
from pathlib import Path
from urllib.parse import urlparse


MAX_VIDEO_BYTES = 7 * 1024 * 1024
VIDEO_MIME = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
}


def prepare_video(value: str) -> str:
    """Return a validated HTTPS URL or a local video encoded as a data URI."""
    source = str(value).strip()
    parsed = urlparse(source)
    if "://" in source:
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("视频 URL 必须是不含账号信息的有效 HTTPS 地址")
        if len(source) > 2048:
            raise ValueError("视频 URL 过长")
        return source

    path = Path(source)
    if not path.is_file():
        raise ValueError(f"视频文件不存在: {path}")
    size = path.stat().st_size
    if size <= 0 or size > MAX_VIDEO_BYTES:
        raise ValueError("本地视频文件为空或超过 7MB；更大的视频请使用 HTTPS URL")
    mime = VIDEO_MIME.get(path.suffix.lower())
    if not mime:
        raise ValueError("仅支持 MP4、M4V、MOV 和 WebM 视频")
    raw = path.read_bytes()
    if len(raw) != size or len(raw) > MAX_VIDEO_BYTES:
        raise ValueError("视频文件读取期间发生变化或超过大小限制")
    if mime in {"video/mp4", "video/quicktime"} and (len(raw) < 12 or raw[4:8] != b"ftyp"):
        raise ValueError("文件不是有效的 MP4/MOV 视频")
    if mime == "video/webm" and not raw.startswith(b"\x1aE\xdf\xa3"):
        raise ValueError("文件不是有效的 WebM 视频")
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
