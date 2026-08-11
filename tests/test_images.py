from pathlib import Path

import pytest
from PIL import Image

from vision_mcp.images import MAX_SIDE, prepare_image


def test_valid_image_is_resized(tmp_path):
    path = tmp_path / "大图.png"
    Image.new("RGB", (2200, 1200), "red").save(path)
    mime, data = prepare_image(str(path))
    assert mime == "image/jpeg"
    output = tmp_path / "out.jpg"
    output.write_bytes(data)
    with Image.open(output) as image:
        assert max(image.size) == MAX_SIDE


def test_small_image_is_reencoded_without_exif(tmp_path):
    path = tmp_path / "with-location.jpg"
    image = Image.new("RGB", (120, 80), "blue")
    exif = Image.Exif()
    exif[270] = "private-location-marker"
    image.save(path, exif=exif)

    mime, data = prepare_image(str(path))

    assert mime == "image/jpeg"
    assert b"private-location-marker" not in data
    with Image.open(__import__("io").BytesIO(data)) as cleaned:
        assert not cleaned.getexif()


def test_fake_image_is_rejected(tmp_path):
    path = tmp_path / "secret.png"
    path.write_text("not an image", encoding="utf-8")
    with pytest.raises(ValueError, match="有效图片"):
        prepare_image(str(path))


def test_missing_image_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="不存在"):
        prepare_image(str(tmp_path / "none.png"))
