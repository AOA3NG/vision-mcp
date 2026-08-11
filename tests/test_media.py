import base64

import pytest

from vision_mcp.media import prepare_video


def test_local_mp4_is_validated_and_encoded(tmp_path):
    path = tmp_path / "短 视频.mp4"
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"video-data")

    value = prepare_video(str(path))

    prefix, encoded = value.split(",", 1)
    assert prefix == "data:video/mp4;base64"
    assert base64.b64decode(encoded) == path.read_bytes()


def test_https_video_url_is_passed_through():
    url = "https://example.com/demo.mp4"
    assert prepare_video(url) == url


def test_unsafe_or_fake_video_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="HTTPS"):
        prepare_video("http://example.com/demo.mp4")
    fake = tmp_path / "fake.mp4"
    fake.write_bytes(b"not-a-video")
    with pytest.raises(ValueError, match="有效"):
        prepare_video(str(fake))
