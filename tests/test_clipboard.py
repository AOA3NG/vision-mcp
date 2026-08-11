from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest
from PIL import Image

from vision_mcp import clipboard, service


def test_clipboard_bitmap_uses_and_removes_temporary_png(monkeypatch):
    monkeypatch.setattr(clipboard.os, "name", "nt")
    monkeypatch.setattr(
        clipboard.ImageGrab,
        "grabclipboard",
        lambda: Image.new("RGB", (4, 3), "orange"),
    )

    with clipboard.clipboard_image_path() as value:
        path = Path(value)
        assert path.is_file()
        with Image.open(path) as image:
            assert image.size == (4, 3)

    assert not path.exists()


def test_clipboard_copied_file_is_not_deleted(monkeypatch, tmp_path):
    source = tmp_path / "copied image.png"
    Image.new("RGB", (2, 2), "white").save(source)
    monkeypatch.setattr(clipboard.os, "name", "nt")
    monkeypatch.setattr(clipboard.ImageGrab, "grabclipboard", lambda: [str(source)])

    with clipboard.clipboard_image_path() as value:
        assert Path(value) == source.resolve()

    assert source.is_file()


def test_clipboard_without_image_has_actionable_error(monkeypatch):
    monkeypatch.setattr(clipboard.os, "name", "nt")
    monkeypatch.setattr(clipboard.ImageGrab, "grabclipboard", lambda: None)

    with pytest.raises(ValueError, match="不要粘贴"):
        with clipboard.clipboard_image_path():
            pass


def test_clipboard_tool_forwards_the_temporary_path(monkeypatch, tmp_path):
    source = tmp_path / "clipboard.png"
    source.write_bytes(b"placeholder")

    @contextmanager
    def fake_clipboard():
        yield str(source)

    received = {}

    def fake_run(paths, question, detail, output_format, provider_id=None):
        received.update(paths=paths, question=question, detail=detail, output_format=output_format)
        return "ok"

    monkeypatch.setattr(service, "clipboard_image_path", fake_clipboard)
    monkeypatch.setattr(service, "_run", fake_run)

    assert service.analyze_clipboard_image("这里有什么", "brief", "json") == "ok"
    assert received == {
        "paths": [str(source)],
        "question": "这里有什么",
        "detail": "brief",
        "output_format": "json",
    }
