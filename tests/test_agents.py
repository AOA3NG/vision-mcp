import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from vision_mcp import agents


def _detect(app_env, key):
    agent = agents.agents()[key]
    agent.detect_path.mkdir(parents=True, exist_ok=True) if agent.detect_path.suffix == "" else agent.detect_path.parent.mkdir(parents=True, exist_ok=True)
    if agent.detect_path.suffix:
        agent.detect_path.write_text("{}", encoding="utf-8")
    return agent


def test_trae_detects_current_and_legacy_roaming_paths(app_env):
    current = app_env["roaming"] / "Trae CN" / "User" / "mcp.json"
    current.parent.mkdir(parents=True)
    current.write_text("{}", encoding="utf-8")

    agent = agents.agents()["trae"]

    assert agent.path == current
    assert agents.detected(agent) is True
    assert app_env["roaming"] / "TRAE SOLO CN" in agent.detect_paths


def test_trae_backup_is_bound_to_original_config_path(app_env):
    legacy = app_env["roaming"] / "TRAE SOLO CN" / "User" / "mcp.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text('{"legacy": true}', encoding="utf-8")
    os.utime(legacy, (1, 1))
    agents._backup(legacy, "trae")

    current = app_env["roaming"] / "Trae CN" / "User" / "mcp.json"
    current.parent.mkdir(parents=True)
    current.write_text('{"current": true}', encoding="utf-8")
    os.utime(current, (2, 2))

    assert agents.latest_backup("trae") is None
    with pytest.raises(ValueError, match="没有可恢复"):
        agents.restore_latest("trae")
    assert current.read_text(encoding="utf-8") == '{"current": true}'


@pytest.mark.parametrize("key", ["claude", "cursor", "trae", "workbuddy"])
def test_json_agents_configure_idempotently_and_remove(app_env, key):
    agent = _detect(app_env, key)
    server = str(app_env["local"] / "Programs" / "Vision MCP" / "vision-mcp-server.exe")
    agents.configure(key, server)
    agents.configure(key, server)
    obj = json.loads(agent.path.read_text(encoding="utf-8"))
    assert obj["mcpServers"]["vision"]["command"] == str(Path(server).resolve())
    assert obj["mcpServers"]["vision"]["args"] == ["stdio"]
    assert agents.status(key, server) == "configured"
    assert agents.remove(key, server)
    assert "vision" not in json.loads(agent.path.read_text(encoding="utf-8"))["mcpServers"]


def test_codex_toml_preserves_other_sections(app_env):
    agent = _detect(app_env, "codex")
    agent.path.parent.mkdir(parents=True, exist_ok=True)
    agent.path.write_text('[model]\nname = "保留"\n', encoding="utf-8")
    server = str(app_env["local"] / "Vision MCP" / "vision-mcp-server.exe")
    agents.configure("codex", server)
    text = agent.path.read_text(encoding="utf-8")
    assert 'name = "保留"' in text
    assert "[mcp_servers.vision]" in text
    agents.remove("codex", server)
    assert '[model]\nname = "保留"' in agent.path.read_text(encoding="utf-8")


def test_invalid_json_is_never_overwritten(app_env):
    agent = _detect(app_env, "cursor")
    agent.path.parent.mkdir(parents=True, exist_ok=True)
    agent.path.write_bytes(b"{ invalid user data")
    before = agent.path.read_bytes()
    with pytest.raises(ValueError):
        agents.configure("cursor", "C:/Vision MCP/vision-mcp-server.exe")
    assert agent.path.read_bytes() == before


def test_conflicting_vision_entry_is_not_overwritten(app_env):
    agent = _detect(app_env, "cursor")
    agent.path.write_text(json.dumps({"mcpServers": {"vision": {"command": "other.exe", "args": []}}}), encoding="utf-8")
    before = agent.path.read_bytes()
    with pytest.raises(ValueError, match="未覆盖"):
        agents.configure("cursor", "C:/VisionMCP/vision-mcp-server.exe")
    assert agent.path.read_bytes() == before


def test_remove_preserves_same_name_entry_from_other_install(app_env):
    agent = _detect(app_env, "cursor")
    agent.path.write_text(
        json.dumps({"mcpServers": {"vision": {"command": "C:/Other/Vision/vision-mcp-server.exe", "args": ["stdio"]}}}),
        encoding="utf-8",
    )
    before = agent.path.read_bytes()

    backup = agents.remove("cursor", "C:/VisionMCP/vision-mcp-server.exe")

    assert backup is None
    assert agent.path.read_bytes() == before


def test_preferred_cli_falls_back_when_cli_absent(app_env, monkeypatch):
    agent = _detect(app_env, "codex")
    monkeypatch.setattr("vision_mcp.agents._trusted_cli", lambda _name: None)
    server = str(app_env["local"] / "Vision MCP" / "vision-mcp-server.exe")
    agents.configure_preferred("codex", server)
    assert agents.status("codex", server) == "configured"


def test_cli_failure_restores_original_bytes_exactly(app_env, monkeypatch):
    agent = _detect(app_env, "codex")
    original = b'\xef\xbb\xbf[model]\r\nname = "keep"\r\n'
    agent.path.write_bytes(original)
    monkeypatch.setattr("vision_mcp.agents._trusted_cli", lambda _name: "codex.exe")

    def fake_run(command, **_kwargs):
        if "add" in command:
            agent.path.write_text('[mcp_servers.vision]\ncommand = "partial.exe"\nargs = []\n', encoding="utf-8")
            return SimpleNamespace(returncode=1, stdout="", stderr="CLI failed")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("vision_mcp.agents.subprocess.run", fake_run)
    with pytest.raises(ValueError, match="CLI failed"):
        agents.configure_preferred("codex", "C:/Vision MCP/vision-mcp-server.exe")
    assert agent.path.read_bytes() == original


def test_cli_failure_removes_partial_file_when_original_was_absent(app_env, monkeypatch):
    agent = _detect(app_env, "codex")
    assert not agent.path.exists()
    monkeypatch.setattr("vision_mcp.agents._trusted_cli", lambda _name: "codex.exe")

    def fake_run(command, **_kwargs):
        if "add" in command:
            agent.path.write_text('[mcp_servers.vision]\ncommand = "partial.exe"\n', encoding="utf-8")
            return SimpleNamespace(returncode=1, stdout="", stderr="failed")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("vision_mcp.agents.subprocess.run", fake_run)
    with pytest.raises(ValueError):
        agents.configure_preferred("codex", "C:/Vision MCP/vision-mcp-server.exe")
    assert not agent.path.exists()


def test_stale_codex_cli_restores_then_falls_back_to_toml(app_env, monkeypatch):
    agent = _detect(app_env, "codex")
    original = b'\xef\xbb\xbf[model]\r\nname = "keep"\r\n'
    agent.path.write_bytes(original)
    monkeypatch.setattr("vision_mcp.agents._trusted_cli", lambda _name: "codex.cmd")

    def fake_run(command, **_kwargs):
        if "add" in command:
            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr='Codex CLI executable not found: "C:/missing/codex.exe"',
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("vision_mcp.agents.subprocess.run", fake_run)
    server = str(app_env["local"] / "Vision MCP" / "vision-mcp-server.exe")
    backup = agents.configure_preferred("codex", server)

    assert backup is not None
    text = agent.path.read_text(encoding="utf-8-sig")
    assert 'name = "keep"' in text
    assert "[mcp_servers.vision]" in text
    assert agents.status("codex", server) == "configured"


def test_missing_cli_process_falls_back_even_when_cleanup_cannot_launch(app_env, monkeypatch):
    _detect(app_env, "codex")
    monkeypatch.setattr("vision_mcp.agents._trusted_cli", lambda _name: "missing-codex.exe")
    monkeypatch.setattr(
        "vision_mcp.agents.subprocess.run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError("No such file or directory")),
    )
    server = str(app_env["local"] / "Vision MCP" / "vision-mcp-server.exe")

    agents.configure_preferred("codex", server)

    assert agents.status("codex", server) == "configured"


def test_cli_uses_user_scope_and_absolute_stdio_command(app_env, monkeypatch):
    agent = _detect(app_env, "claude")
    server = str(app_env["local"] / "Programs" / "Vision MCP" / "vision-mcp-server.exe")
    calls = []
    monkeypatch.setattr("vision_mcp.agents._trusted_cli", lambda _name: "claude.exe")

    def fake_run(command, **_kwargs):
        calls.append(command)
        if "add" in command:
            entry = {"type": "stdio", **agents._expected(server)}
            agent.path.write_text(json.dumps({"mcpServers": {"vision": entry}}), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("vision_mcp.agents.subprocess.run", fake_run)
    agents.configure_preferred("claude", server)
    assert calls == [["claude.exe", "mcp", "add", "-s", "user", "vision", "--", str(Path(server).resolve()), "stdio"]]


def test_cli_capture_uses_utf8_with_replacement(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("vision_mcp.agents.subprocess.run", fake_run)
    agents._run_cli(["agent.exe", "mcp"], 12)
    assert captured["capture_output"] is True
    assert captured["text"] is True
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"
    assert captured["timeout"] == 12
    assert captured["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"


def test_atomic_replace_failure_preserves_original_bytes(app_env, monkeypatch):
    agent = _detect(app_env, "cursor")
    original = b'{"mcpServers": {}, "keep": true}\r\n'
    agent.path.write_bytes(original)
    monkeypatch.setattr("vision_mcp.agents.os.replace", lambda *_args: (_ for _ in ()).throw(PermissionError("locked")))
    with pytest.raises(PermissionError, match="locked"):
        agents.configure("cursor", "C:/Vision MCP/vision-mcp-server.exe")
    assert agent.path.read_bytes() == original


def test_agent_detection_and_config_paths(app_env):
    found = agents.agents()
    assert found["claude"].path == app_env["home"] / ".claude.json"
    assert found["codex"].path == app_env["home"] / ".codex" / "config.toml"
    assert found["cursor"].path == app_env["home"] / ".cursor" / "mcp.json"
    assert found["trae"].path == app_env["roaming"] / "TRAE SOLO CN" / "User" / "mcp.json"
    assert found["workbuddy"].path == app_env["home"] / ".workbuddy" / "mcp.json"


def test_remove_invalid_config_preserves_original_bytes(app_env):
    agent = _detect(app_env, "workbuddy")
    original = b"{broken user config"
    agent.path.write_bytes(original)
    with pytest.raises(ValueError):
        agents.remove("workbuddy", "C:/Vision MCP/vision-mcp-server.exe")
    assert agent.path.read_bytes() == original


def test_restore_latest_preserves_backup_bytes(app_env):
    agent = _detect(app_env, "cursor")
    original = b'\xef\xbb\xbf{"mcpServers": {}, "name": "before"}\r\n'
    agent.path.write_bytes(original)
    backup = agents._backup(agent.path, agent.key)
    agent.path.write_text('{"mcpServers": {}, "name": "after"}\n', encoding="utf-8")

    restored = agents.restore_latest("cursor")

    assert restored == backup
    assert agent.path.read_bytes() == original


def test_agent_backups_are_bounded(app_env):
    agent = _detect(app_env, "cursor")
    agent.path.write_text('{"mcpServers": {}}', encoding="utf-8")

    for _ in range(agents.MAX_BACKUPS_PER_AGENT + 3):
        agents._backup(agent.path, agent.key)

    folder = app_env["roaming"] / "VisionMCP" / "backups" / "agents" / "cursor"
    assert len(list(folder.glob("*/*.bak"))) == agents.MAX_BACKUPS_PER_AGENT
