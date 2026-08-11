from __future__ import annotations

from vision_mcp.config import default_config
from vision_mcp.service import configure_tool_availability, enabled_generation_tools


class _Provider:
    def __init__(self):
        self.removed: list[str] = []

    def remove_tool(self, name: str) -> None:
        self.removed.append(name)


class _Server:
    def __init__(self):
        self.local_provider = _Provider()


def test_generation_tools_are_hidden_when_models_are_not_selected():
    cfg = default_config()
    server = _Server()

    enabled = configure_tool_availability(server, cfg)

    assert enabled == set()
    assert server.local_provider.removed == ["generate_image", "generate_video"]


def test_generation_tools_follow_selected_capabilities():
    cfg = default_config()
    cfg["providers"][0]["models"]["image_generation"] = ["cogview-3-flash"]
    server = _Server()

    enabled = configure_tool_availability(server, cfg)

    assert enabled == {"generate_image"}
    assert server.local_provider.removed == ["generate_video"]


def test_disabled_provider_does_not_expose_generation_tools():
    cfg = default_config()
    cfg["providers"][0]["enabled"] = False
    cfg["providers"][0]["models"]["video_generation"] = ["cogvideox-flash"]

    assert enabled_generation_tools(cfg) == set()
