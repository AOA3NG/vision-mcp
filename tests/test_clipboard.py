from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError
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
    monkeypatch.setattr(clipboard, "_grab_native_png", lambda: None)

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


def test_clipboard_retries_while_screenshot_tool_owns_clipboard(monkeypatch):
    attempts = iter([OSError("busy"), OSError("busy"), Image.new("RGB", (3, 2), "blue")])
    sleeps = []

    def grabclipboard():
        result = next(attempts)
        if isinstance(result, OSError):
            raise result
        return result

    monkeypatch.setattr(clipboard.ImageGrab, "grabclipboard", grabclipboard)
    monkeypatch.setattr(clipboard.time, "sleep", sleeps.append)

    value = clipboard._grab_with_retry()

    assert isinstance(value, Image.Image)
    assert value.size == (3, 2)
    assert sleeps == [clipboard.CLIPBOARD_RETRY_DELAY_SECONDS] * 2


def test_custom_png_clipboard_format_is_used_as_fallback(monkeypatch):
    monkeypatch.setattr(clipboard.os, "name", "nt")
    monkeypatch.setattr(clipboard, "_grab_with_retry", lambda: None)
    monkeypatch.setattr(clipboard, "_grab_native_png", lambda: Image.new("RGBA", (5, 4), "green"))

    with clipboard.clipboard_image_path() as value:
        with Image.open(value) as image:
            assert image.size == (5, 4)


def test_image_analysis_tools_default_to_clipboard(monkeypatch, tmp_path):
    source = tmp_path / "clipboard.png"
    source.write_bytes(b"placeholder")

    @contextmanager
    def fake_clipboard():
        yield str(source)

    received = []

    def fake_run(paths, question, detail, output_format, provider_id=None):
        received.append(paths)
        return "ok"

    monkeypatch.setattr(service, "clipboard_image_path", fake_clipboard)
    monkeypatch.setattr(service, "_run", fake_run)

    assert service.analyze_image() == "ok"
    assert service.analyze_ui() == "ok"
    assert service.extract_text() == "ok"
    assert service.analyze_images() == "ok"
    assert service.analyze_document() == "ok"
    assert service.locate_objects(target="按钮") == "ok"
    assert received == [[str(source)]] * 6


def test_compare_images_can_use_clipboard_for_one_side(monkeypatch, tmp_path):
    clipboard_source = tmp_path / "clipboard.png"
    clipboard_source.write_bytes(b"placeholder")
    explicit_source = tmp_path / "before.png"
    explicit_source.write_bytes(b"placeholder")

    @contextmanager
    def fake_clipboard():
        yield str(clipboard_source)

    received = {}

    def fake_run(paths, question, detail, output_format, provider_id=None):
        received["paths"] = paths
        return "ok"

    monkeypatch.setattr(service, "clipboard_image_path", fake_clipboard)
    monkeypatch.setattr(service, "_run", fake_run)

    assert service.compare_images(str(explicit_source)) == "ok"
    assert received["paths"] == [str(explicit_source), str(clipboard_source)]

    with pytest.raises(ToolError, match="一次只能提供一张"):
        service.compare_images()


def test_explicit_image_path_does_not_read_clipboard(monkeypatch):
    @contextmanager
    def fail_clipboard():
        raise AssertionError("clipboard should not be read")
        yield ""

    monkeypatch.setattr(service, "clipboard_image_path", fail_clipboard)
    monkeypatch.setattr(service, "_run", lambda paths, *args, **kwargs: paths[0])

    assert service.analyze_image("C:/images/example.png") == "C:/images/example.png"
