import os

import pytest


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    roaming = tmp_path / "漫游 配置"
    local = tmp_path / "本地 数据"
    home = tmp_path / "用户 空格"
    monkeypatch.setenv("APPDATA", str(roaming))
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("VISION_MCP_CONFIG", str(roaming / "VisionMCP" / "config.json"))
    return {"roaming": roaming, "local": local, "home": home}
