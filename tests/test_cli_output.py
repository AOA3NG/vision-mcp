import io
import json

from vision_mcp import cli


class _Stdout:
    def __init__(self):
        self.buffer = io.BytesIO()


def test_json_output_is_always_utf8(monkeypatch):
    stdout = _Stdout()
    monkeypatch.setattr(cli.sys, "stdout", stdout)

    cli._print_json({"error": "智谱：未配置 API Key"})

    raw = stdout.buffer.getvalue()
    assert b"\xef\xbf\xbd" not in raw
    assert json.loads(raw.decode("utf-8"))["error"] == "智谱：未配置 API Key"
