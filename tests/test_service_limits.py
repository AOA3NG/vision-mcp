from __future__ import annotations

import pytest
from fastmcp.exceptions import ToolError

from vision_mcp import service


def test_image_question_length_is_bounded_before_file_access():
    with pytest.raises(ToolError, match="问题不能超过"):
        service.analyze_image("missing.png", "x" * (service.MAX_QUESTION_CHARS + 1))


def test_object_target_length_is_bounded_before_file_access():
    with pytest.raises(ToolError, match="目标不能超过"):
        service.locate_objects("missing.png", "x" * (service.MAX_TARGET_CHARS + 1))


def test_video_question_and_path_are_bounded():
    with pytest.raises(ToolError, match="视频路径或地址不能超过"):
        service.analyze_video("x" * (service.MAX_PATH_OR_URL_CHARS + 1))
    with pytest.raises(ToolError, match="问题不能超过"):
        service.analyze_video("https://example.com/video.mp4", "x" * (service.MAX_QUESTION_CHARS + 1))
