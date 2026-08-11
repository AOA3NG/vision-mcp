from __future__ import annotations

import copy
import json
import uuid
from types import SimpleNamespace

import pytest

from vision_mcp import web_manager
from vision_mcp.config import default_config


@pytest.fixture
def manager_api(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(web_manager, "migrate_legacy", lambda cfg: None)
    credentials: dict[str, str] = {}
    monkeypatch.setattr(web_manager, "get_key", lambda provider_id: credentials.get(provider_id))
    monkeypatch.setattr(web_manager, "set_key", lambda provider_id, value: credentials.__setitem__(provider_id, value))
    monkeypatch.setattr(web_manager, "delete_key", lambda provider_id: credentials.pop(provider_id, None))
    return web_manager.ManagerApi(), credentials


def test_web_bridge_exposes_no_plaintext_key_in_initial_state(manager_api):
    api, credentials = manager_api
    provider_id = api._cfg["providers"][0]["id"]
    credentials[provider_id] = "secret-key-value"

    response = api.get_state()

    assert response["ok"] is True
    assert response["state"]["providers"][0]["has_key"] is True
    assert "secret-key-value" not in str(response)
    assert "api_key" not in response["state"]["providers"][0]
    assert not hasattr(api, "get_api_key")


def test_manager_keeps_v2_provider_rows_and_separate_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    cfg = default_config()
    primary = copy.deepcopy(cfg["providers"][0])
    primary.pop("models")
    backup = copy.deepcopy(primary)
    backup["id"] = str(uuid.uuid4())
    backup["model"] = "glm-4.1v-thinking-flash"
    cfg["providers"] = [primary, backup]
    cfg["defaults_revision"] = 2
    path = tmp_path / "roaming" / "VisionMCP" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    credentials = {backup["id"]: "backup-only-secret"}
    monkeypatch.setattr(web_manager, "migrate_legacy", lambda _cfg: None)
    monkeypatch.setattr(web_manager, "get_key", lambda provider_id: credentials.get(provider_id, ""))
    monkeypatch.setattr(web_manager, "set_key", lambda provider_id, value: credentials.__setitem__(provider_id, value))
    monkeypatch.setattr(web_manager, "delete_key", lambda provider_id: credentials.pop(provider_id, None))

    api = web_manager.ManagerApi()

    assert len(api._cfg["providers"]) == 2
    assert primary["id"] not in credentials
    assert credentials[backup["id"]] == "backup-only-secret"
    assert all(provider["credential_ids"] == [provider["id"]] for provider in api._cfg["providers"])


def test_web_bridge_saves_updates_and_deletes_credentials(manager_api):
    api, credentials = manager_api
    original_id = api._cfg["providers"][0]["id"]
    credentials[original_id] = "old-secret"
    replacement_id = str(uuid.uuid4())
    payload = {
        "providers": [{
            "id": replacement_id,
            "preset_id": "zhipu",
            "enabled": True,
            "name": "智谱 GLM Vision",
            "model": "glm-4.6v-flash",
            "api_base": "https://open.bigmodel.cn/api/paas/v4",
            "api_protocol": "openai",
            "key_action": "set",
            "api_key": "new-secret",
        }]
    }

    response = api.save_models(payload)

    assert response["ok"] is True
    assert original_id not in credentials
    assert credentials[replacement_id] == "new-secret"
    assert "new-secret" not in str(response)

    payload["providers"][0]["key_action"] = "delete"
    payload["providers"][0]["api_key"] = ""
    assert api.save_models(payload)["ok"] is True
    assert replacement_id not in credentials


def test_save_without_key_reports_missing_instead_of_credential_success(manager_api):
    api, _ = manager_api
    provider = dict(api._cfg["providers"][0])
    provider.update({"key_action": "keep", "api_key": ""})

    response = api.save_models({"providers": [provider]})

    assert response["ok"] is True
    assert response["warning"] is True
    assert "第 1 个服务商未填写 API Key" in response["message"]
    assert "Windows 凭据管理器" not in response["message"]


def test_one_provider_stores_one_key_for_default_vision_models(manager_api):
    api, credentials = manager_api
    providers = [dict(provider) for provider in api._cfg["providers"]]
    assert len(providers) == 1
    assert providers[0]["models"] == {
        "vision": ["glm-4.6v-flash", "glm-4.1v-thinking-flash"],
        "image_generation": [],
        "video_generation": [],
    }
    providers[0].update({"key_action": "set", "api_key": "shared-zhipu-key"})

    response = api.save_models({"providers": providers})

    assert response["ok"] is True
    assert response["warning"] is False
    assert credentials[providers[0]["id"]] == "shared-zhipu-key"


def test_same_provider_stores_multiple_keys_as_separate_groups(manager_api):
    api, credentials = manager_api
    provider = dict(api._cfg["providers"][0])
    backup_id = str(uuid.uuid4())
    provider.update({"key_action": "set", "api_key": "primary-secret"})
    backup = copy.deepcopy(provider)
    backup.update({"id": backup_id, "name": "备用服务商", "api_key": "backup-secret"})

    response = api.save_models({"providers": [provider, backup]})

    assert response["ok"] is True
    assert credentials[provider["id"]] == "primary-secret"
    assert credentials[backup_id] == "backup-secret"
    assert [item["credential_ids"] for item in response["state"]["providers"]] == [
        [provider["id"]], [backup_id]
    ]
    assert "primary-secret" not in str(response)
    assert "backup-secret" not in str(response)


def test_provider_group_rejects_more_than_one_key_slot(manager_api):
    api, credentials = manager_api
    provider = dict(api._cfg["providers"][0])
    provider["keys"] = [
        {"id": provider["id"], "key_action": "set", "api_key": "first-secret"},
        {"id": str(uuid.uuid4()), "key_action": "set", "api_key": "second-secret"},
    ]

    response = api.save_models({"providers": [provider]})

    assert response["ok"] is False
    assert "只能配置一个 API Key" in response["message"]
    assert credentials == {}


def test_duplicate_provider_endpoint_is_allowed_for_separate_keys(manager_api):
    api, credentials = manager_api
    providers = [dict(provider) for provider in api._cfg["providers"]]
    duplicate = dict(providers[0])
    duplicate["id"] = str(uuid.uuid4())
    duplicate["name"] = "重复服务商"
    providers.append(duplicate)
    providers[0].update({"key_action": "set", "api_key": "first-key"})
    providers[1].update({"key_action": "set", "api_key": "second-key"})

    response = api.save_models({"providers": providers})

    assert response["ok"] is True
    assert credentials[providers[0]["id"]] == "first-key"
    assert credentials[providers[1]["id"]] == "second-key"


def test_configure_and_test_rejects_missing_key_before_agent_changes(manager_api, monkeypatch):
    api, _ = manager_api
    provider = dict(api._cfg["providers"][0])
    provider.update({"key_action": "keep", "api_key": ""})
    configured: list[str] = []
    monkeypatch.setattr(web_manager.agent_ops, "configure_preferred", lambda *args: configured.append(str(args)))

    response = api.configure_and_test({"providers": [provider]}, ["claude"])

    assert response["ok"] is False
    assert "第 1 个服务商未填写 API Key" in response["message"]
    assert configured == []


def test_configure_and_test_hides_frozen_server_windows(manager_api, monkeypatch):
    api, _ = manager_api
    provider = dict(api._cfg["providers"][0])
    provider.update({"key_action": "set", "api_key": "test-secret"})
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(web_manager.agent_ops, "detected", lambda _agent: True)
    monkeypatch.setattr(web_manager.agent_ops, "configure_preferred", lambda *_args: None)
    monkeypatch.setattr(web_manager.agent_ops, "status", lambda *_args: "configured")
    monkeypatch.setattr(web_manager, "server_executable", lambda: r"C:\VisionMCP\vision-mcp-server.exe")

    def fake_run(_command, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(returncode=0, stdout='{"ok": true}', stderr="")

    monkeypatch.setattr(web_manager.subprocess, "run", fake_run)

    response = api.configure_and_test({"providers": [provider]}, ["claude"])

    assert response["ok"] is True
    assert len(calls) == 2
    assert all(call["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1" for call in calls)
    if web_manager.os.name == "nt":
        assert all(call["creationflags"] for call in calls)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("preset_id", "", "未选择服务商"),
        ("models", {"vision": [], "image_generation": [], "video_generation": []}, "至少需要一个视觉理解模型"),
        ("api_base", "", "未填写 API 地址"),
        ("api_protocol", "", "未选择协议"),
        ("name", "", "未填写显示名称"),
    ],
)
def test_model_validation_uses_user_facing_messages(manager_api, field, value, expected):
    api, _ = manager_api
    provider = dict(api._cfg["providers"][0])
    provider.update({"key_action": "keep", "api_key": "", field: value})

    response = api.save_models({"providers": [provider]})

    assert response["ok"] is False
    assert f"第 1 个服务商{expected}" in response["message"]


def test_test_error_detail_extracts_specific_json_error():
    detail = web_manager.ManagerApi._test_error_detail('{"ok": false, "error": "未配置 API Key"}')
    assert detail == "未配置 API Key"


def test_web_bridge_rejects_unknown_provider_without_writing(manager_api):
    api, _ = manager_api
    original = api._cfg
    response = api.save_models({
        "providers": [{
            "id": str(uuid.uuid4()), "preset_id": "unknown", "enabled": True,
            "name": "x", "model": "x", "api_base": "https://example.com/v1",
            "api_protocol": "openai", "key_action": "keep", "api_key": "",
        }]
    })
    assert response["ok"] is False
    assert api._cfg == original


def test_web_bridge_accepts_custom_provider(manager_api):
    api, credentials = manager_api
    provider_id = str(uuid.uuid4())
    response = api.save_models({
        "providers": [{
            "id": provider_id, "preset_id": "custom", "enabled": True,
            "name": "自定义视觉模型", "model": "vision-model-id",
            "api_base": "https://vision.example.com/v1",
            "api_protocol": "anthropic", "key_action": "set",
            "api_key": "custom-secret",
        }]
    })

    assert response["ok"] is True
    assert api._cfg["providers"][0]["preset_id"] == "custom"
    assert api._cfg["providers"][0]["api_protocol"] == "anthropic"
    assert credentials[provider_id] == "custom-secret"
    assert "custom-secret" not in str(response)


def test_copy_manual_config_contains_only_standard_json(manager_api, monkeypatch):
    api, _ = manager_api
    copied: list[str] = []
    monkeypatch.setattr(web_manager, "_copy_to_clipboard", copied.append)
    monkeypatch.setattr(web_manager, "server_executable", lambda: r"C:\Program Files\VisionMCP\vision-mcp-server.exe")

    response = api.copy_manual_config()

    assert response["ok"] is True
    assert len(copied) == 1
    assert json.loads(copied[0]) == {
        "mcpServers": {
            "vision": {
                "command": r"C:\Program Files\VisionMCP\vision-mcp-server.exe",
                "args": ["stdio"],
            }
        }
    }
    assert "Codex config.toml" not in copied[0]


def test_web_bridge_redacts_errors(manager_api, monkeypatch):
    api, _ = manager_api

    def fail(_cfg):
        raise ValueError("Authorization: Bearer super-secret-token data:image/png;base64,AAAA")

    monkeypatch.setattr(web_manager, "save_config", fail)
    provider = dict(api._cfg["providers"][0])
    provider.update({"key_action": "keep", "api_key": ""})
    response = api.save_models({"providers": [provider]})
    assert response["ok"] is False
    assert "super-secret-token" not in response["message"]
    assert "AAAA" not in response["message"]
    assert response["message"].count("[REDACTED]") == 2


def test_credential_changes_roll_back_when_config_write_fails(manager_api, monkeypatch):
    api, credentials = manager_api
    provider = dict(api._cfg["providers"][0])
    provider_id = provider["id"]
    credentials[provider_id] = "old-secret"
    provider.update({"key_action": "set", "api_key": "new-secret"})
    original_cfg = api._cfg
    monkeypatch.setattr(web_manager, "save_config", lambda _cfg: (_ for _ in ()).throw(PermissionError("locked")))

    response = api.save_models({"providers": [provider]})

    assert response["ok"] is False
    assert credentials[provider_id] == "old-secret"
    assert api._cfg is original_cfg


def test_configure_validates_agents_before_saving_models(manager_api, monkeypatch):
    api, _ = manager_api
    provider = dict(api._cfg["providers"][0])
    provider.update({"key_action": "set", "api_key": "temporary-secret"})
    saves = []
    monkeypatch.setattr(web_manager, "save_config", lambda cfg: saves.append(cfg))

    response = api.configure_and_test({"providers": [provider]}, ["unknown-agent"])

    assert response["ok"] is False
    assert saves == []


def test_web_bridge_internal_objects_are_private(manager_api):
    api, _ = manager_api
    assert all(name.startswith("_") for name in vars(api))


def test_close_manager_closes_attached_window(manager_api, monkeypatch):
    api, _ = manager_api
    closed: list[bool] = []

    class Window:
        def destroy(self):
            closed.append(True)

    class ImmediateTimer:
        def __init__(self, _delay, callback):
            self.callback = callback

        def start(self):
            self.callback()

    api._attach_window(Window())
    monkeypatch.setattr(web_manager.threading, "Timer", ImmediateTimer)

    response = api.close_manager()

    assert response["ok"] is True
    assert closed == [True]


def test_rate_limit_page_uses_account_specific_console(manager_api, monkeypatch):
    api, _ = manager_api
    opened: list[str] = []
    monkeypatch.setattr(web_manager.webbrowser, "open", opened.append)

    response = api.open_rate_limit_page()

    assert response["ok"] is True
    assert opened == ["https://bigmodel.cn/usercenter/proj-mgmt/rate-limits"]


def test_web_assets_exist_and_runtime_is_loaded_inline():
    html = web_manager.resource_path("design", "vision-mcp-config-prototype.html").read_text(encoding="utf-8")
    script = web_manager.resource_path("design", "vision-mcp-manager.js").read_text(encoding="utf-8")
    assert '<script src="vision-mcp-manager.js"></script>' in html
    assert "pywebviewready" in script
    assert "api_key" in script
    assert "开发者" in html and "AOA3NG" in html
    assert "github.com/AOA3NG/vision-mcp" in html
    assert "+ 添加其他模型" in script
    assert "split(/[,，" not in script
    assert "+ 添加备用 Key" not in html
    assert "并发限制显示在模型选择中" not in html
    assert "查看账号实时限制" not in html
    assert "Agent 调用时通过 stdio 按需启动，无弹窗" not in html
    assert "按排序调用，异常时自动切换" in html
    assert "key_slots" not in script
    assert "appearance: none" in html
    assert "input::-ms-reveal" in html
    assert '<div class="context-copy">\n          <span class="context-title">' in html
    assert "min-width: 128px" in html
    assert ".action-rail { position: static; }" in html
    assert "@media (max-width: 720px)" in html
    assert "event.composedPath()" in script
    assert "event.stopPropagation()" in script
    assert "event.key !== 'Escape'" in script
    assert "concurrency: 1" in script and "concurrency: 5" in script and "concurrency: 3" in script
    assert 'id="helpDialog"' in html and 'id="aboutDialog"' in html
    assert 'id="uninstallDialog"' not in html
    assert 'id="selectAllAgents"' in html
    assert "window.confirm('确认打开 Vision MCP 卸载向导" not in script
    assert "正式程序中将直接打开卸载向导" in script
    assert "updateSelectAllAgents" in script
    assert "response.passed ? '测试通过' : '测试未通过'" in script
    assert "saveState.textContent = response.message" not in script
    assert "white-space: nowrap" in html
    assert html.count('id="saveState"') == 1
    assert '<span class="results-title">配置与测试结果</span><span class="save-state" id="saveState">' in html
    assert '#runTest { order: 1; margin-left: auto; }' in html
    assert '.agent-columns .card-title' in html
    assert web_manager.resource_path("design", "vision-mcp-icon.png").is_file()


def test_manager_window_geometry_is_restored_on_launch():
    calls = []

    class Window:
        def restore(self):
            calls.append(("restore",))

        def resize(self, width, height):
            calls.append(("resize", width, height))

        def move(self, x, y):
            calls.append(("move", x, y))

    class Screen:
        x = 0
        y = 0
        width = 1920
        height = 1080

    window = Window()
    web_manager._normalize_window_geometry(window, Screen())

    assert calls == [
        ("restore",),
        ("resize", web_manager.MANAGER_WIDTH, web_manager.MANAGER_HEIGHT),
        ("move", 370, 130),
    ]
    assert window.on_top is False


def test_primary_screen_is_selected_from_multi_monitor_layout():
    class Screen:
        def __init__(self, x, y, width, height):
            self.x, self.y, self.width, self.height = x, y, width, height

    secondary = Screen(-2880, 0, 1646, 1029)
    primary = Screen(0, 0, 1920, 1080)

    assert web_manager._select_primary_screen([secondary, primary]) is primary


def test_more_menu_opens_inward_within_the_window():
    html = web_manager.resource_path("design", "vision-mcp-config-prototype.html").read_text(encoding="utf-8")

    menu_css = html.split(".more-menu {", 1)[1].split("}", 1)[0]
    assert "right: 0;" in menu_css
    assert "left: auto;" in menu_css
    assert "max-width: calc(100vw - 28px);" in menu_css


def test_web_ui_offers_custom_provider_and_supported_protocols():
    html = web_manager.resource_path("design", "vision-mcp-config-prototype.html").read_text(encoding="utf-8")
    script = web_manager.resource_path("design", "vision-mcp-manager.js").read_text(encoding="utf-8")
    assert '<option value="custom">自定义</option>' in html
    assert html.count('<option value="anthropic">Anthropic</option>') == 2
    assert 'class="model-picker"' in html
    assert "glm-4.6v-flash" in script
    assert "glm-4.1v-thinking-flash" in script
    assert "cogview-3-flash" in script
    assert "cogvideox-flash" in script
    assert "image_generation: [],\n        video_generation: []" in script
    assert "image_generation: [{id: 'cogview-3-flash', concurrency: 1}]" in script
    assert "video_generation: [{id: 'cogvideox-flash', concurrency: 3}]" in script
    assert "`视觉理解 ${models.vision.length}`" in script
    assert "`图片生成 ${models.image_generation.length}`" in script
    assert "`视频生成 ${models.video_generation.length}`" in script
    assert "custom: {" in script
    assert "请在高级设置中填写 API 地址和协议" in script


def test_web_ui_uses_compact_warm_theme_and_native_checkboxes():
    html = web_manager.resource_path("design", "vision-mcp-config-prototype.html").read_text(encoding="utf-8")
    assert "--accent: #a9583e" in html
    assert "accent-color: var(--accent)" in html
    assert "连接视觉模型与 Agent" in html
    assert "Vision MCP 管理器</h1>" not in html
    assert "API Key</label><a class=\"key-help-link\"" in html
