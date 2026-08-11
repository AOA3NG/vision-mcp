from __future__ import annotations

import ctypes
from ctypes import wintypes
import base64
import json
import logging
import os
import re
import subprocess
import sys
import threading
import uuid
import webbrowser
from pathlib import Path
from typing import Any

from . import __version__
from . import agents as agent_ops
from .cli import server_executable
from .config import MODEL_CAPABILITIES, load_config, provider_models, save_config
from .credentials import delete_key, get_key, migrate_legacy, provider_credential_ids, set_key
from .logging_setup import redact_text, setup_logging
from .processes import isolated_subprocess_kwargs


LOGGER = logging.getLogger(__name__)
KEY_URLS = {
    "zhipu": "https://docs.bigmodel.cn/cn/guide/models/free/glm-4.6v-flash",
    "bailian": "https://help.aliyun.com/zh/model-studio/coding-plan",
}
RATE_LIMIT_URL = "https://bigmodel.cn/usercenter/proj-mgmt/rate-limits"
PROJECT_URL = "https://github.com/AOA3NG/vision-mcp"
MANAGER_WIDTH = 1180
MANAGER_HEIGHT = 820
MANAGER_MIN_WIDTH = 1000
MANAGER_MIN_HEIGHT = 680
STATUS_LABELS = {
    "configured": "已配置",
    "not_configured": "未配置",
    "not_detected": "未检测到",
    "conflict": "存在冲突",
    "invalid_config": "配置损坏",
}


def resource_path(*parts: str) -> Path:
    if getattr(sys, "frozen", False):
        root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        root = Path(__file__).resolve().parents[1]
    return root.joinpath(*parts)


def _select_primary_screen(screens: list[Any]) -> Any:
    if not screens:
        raise RuntimeError("未检测到显示器")
    return next(
        (
            item for item in screens
            if item.x <= 0 < item.x + item.width and item.y <= 0 < item.y + item.height
        ),
        screens[0],
    )


def _normalize_window_geometry(window: Any, screen: Any | None = None) -> None:
    """Restore a predictable launch size and center it on the primary screen."""
    try:
        window.restore()
        window.resize(MANAGER_WIDTH, MANAGER_HEIGHT)
        if screen is None:
            import webview

            screen = _select_primary_screen(list(webview.screens))
        target = screen
        x = target.x + max(0, (target.width - MANAGER_WIDTH) // 2)
        y = target.y + max(0, (target.height - MANAGER_HEIGHT) // 2)
        window.move(x, y)
        # Launch above the installer, then immediately return to normal window
        # ordering so the manager does not remain permanently topmost.
        window.on_top = False
    except Exception:
        LOGGER.exception("Failed to normalize manager window geometry")


def _copy_to_clipboard(text: str) -> None:
    if os.name != "nt":  # pragma: no cover - Windows release target
        raise RuntimeError("剪贴板功能仅支持 Windows")
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.CloseClipboard.restype = wintypes.BOOL
    encoded = (text + "\0").encode("utf-16-le")
    handle = kernel32.GlobalAlloc(0x0002, len(encoded))
    if not handle:
        raise OSError("无法分配剪贴板内存")
    locked = False
    opened = False
    try:
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            raise OSError("无法写入剪贴板内存")
        locked = True
        ctypes.memmove(pointer, encoded, len(encoded))
        kernel32.GlobalUnlock(handle)
        locked = False
        if not user32.OpenClipboard(None):
            raise OSError("无法打开剪贴板")
        opened = True
        user32.EmptyClipboard()
        if not user32.SetClipboardData(13, handle):  # CF_UNICODETEXT
            raise OSError("无法设置剪贴板内容")
        handle = None  # ownership transferred to the clipboard
    finally:
        if locked:
            kernel32.GlobalUnlock(handle)
        if opened:
            user32.CloseClipboard()
        if handle:
            kernel32.GlobalFree(handle)


class ManagerApi:
    """Small, explicitly whitelisted bridge exposed to the local WebView page."""

    def __init__(self) -> None:
        self._cfg = load_config(create=True)
        self._migrate_credential_aliases()
        migrate_legacy(self._cfg)
        self._window: Any | None = None
        self._operation_lock = threading.Lock()

    def _migrate_credential_aliases(self) -> None:
        changed = False
        for provider in self._cfg.get("providers", []):
            aliases = provider.get("credential_aliases", [])
            if not isinstance(aliases, list) or not aliases:
                continue
            canonical = get_key(provider["id"])
            if not canonical:
                for alias in aliases:
                    canonical = get_key(str(alias))
                    if canonical:
                        set_key(provider["id"], canonical)
                        break
            for alias in aliases:
                delete_key(str(alias))
            provider.pop("credential_aliases", None)
            changed = True
        if changed:
            save_config(self._cfg)

    def _attach_window(self, window: Any) -> None:
        self._window = window

    @staticmethod
    def _ok(message: str = "", **values: Any) -> dict[str, Any]:
        return {"ok": True, "message": message, **values}

    @staticmethod
    def _error(exc: object) -> dict[str, Any]:
        message = redact_text(exc, 500)
        LOGGER.error("Manager operation failed: %s", message)
        return {"ok": False, "message": message}

    def _server_cmd(self, *args: str) -> list[str]:
        server = server_executable()
        if server.endswith(".py"):
            return [sys.executable, server, *args]
        return [server, *args]

    def _agent_state(self) -> list[dict[str, Any]]:
        server = server_executable()
        values = []
        for key, agent in agent_ops.agents().items():
            installed = agent_ops.detected(agent)
            status = agent_ops.status(key, server)
            values.append({
                "key": key,
                "name": agent.name,
                "installed": installed,
                "status": status,
                "status_label": STATUS_LABELS.get(status, status),
                "selected": installed and status not in ("conflict", "invalid_config"),
            })
        return values

    def _public_state(self) -> dict[str, Any]:
        providers = []
        for provider in self._cfg["providers"]:
            item = dict(provider)
            item.pop("credential_aliases", None)
            item["has_key"] = bool(get_key(provider["id"]))
            providers.append(item)
        return {
            "version": __version__,
            "providers": providers,
            "agents": self._agent_state(),
        }

    def get_state(self) -> dict[str, Any]:
        try:
            self._cfg = load_config(create=True)
            return self._ok(state=self._public_state())
        except Exception as exc:
            return self._error(exc)

    @staticmethod
    def _bounded_text(value: object, field: str, limit: int = 2048) -> str:
        text = str(value or "").strip()
        if len(text) > limit:
            raise ValueError(f"{field}过长")
        return text

    @staticmethod
    def _missing_key_message(indexes: list[int]) -> str:
        numbers = "、".join(str(index) for index in indexes)
        return f"第 {numbers} 个服务商未填写 API Key"

    def _payload_models(self, row: dict[str, Any], index: int) -> dict[str, list[str]]:
        raw = row.get("models")
        if raw is None:
            raw = {"vision": [row.get("model")], "image_generation": [], "video_generation": []}
        if not isinstance(raw, dict):
            raise ValueError(f"第 {index} 个服务商的模型配置格式错误")
        result: dict[str, list[str]] = {}
        all_models: set[str] = set()
        for capability in MODEL_CAPABILITIES:
            values = raw.get(capability, [])
            if not isinstance(values, list):
                raise ValueError(f"第 {index} 个服务商的模型列表格式错误")
            if len(values) > 20:
                raise ValueError(f"第 {index} 个服务商的模型数量过多")
            normalized = [self._bounded_text(value, "模型 ID", 300) for value in values]
            normalized = [value for value in normalized if value]
            lowered = [value.lower() for value in normalized]
            if len(lowered) != len(set(lowered)) or all_models.intersection(lowered):
                raise ValueError(f"第 {index} 个服务商包含重复模型")
            all_models.update(lowered)
            result[capability] = normalized
        if not result["vision"]:
            raise ValueError(f"第 {index} 个服务商至少需要一个视觉理解模型")
        return result

    @staticmethod
    def _test_error_detail(output: str) -> str:
        text = str(output or "").strip()
        try:
            value = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            value = None
        if isinstance(value, dict):
            text = str(value.get("error") or value.get("message") or text)
        return redact_text(text, 300) or "未返回具体错误信息"

    def _save_payload(self, payload: object, *, require_keys: bool = False) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("模型配置格式错误")
        rows = payload.get("providers")
        if not isinstance(rows, list) or not rows:
            raise ValueError("至少需要保留一个模型配置")
        if len(rows) > 20:
            raise ValueError("最多支持 20 个模型配置")

        old_ids = {
            credential_id
            for provider in self._cfg["providers"]
            for credential_id in provider_credential_ids(provider)
        }
        providers = []
        key_actions: list[tuple[str, str, str]] = []
        seen_credential_ids: set[str] = set()
        missing_key_indexes: list[int] = []
        for index, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                raise ValueError(f"第 {index} 个模型配置格式错误")
            provider_id = self._bounded_text(row.get("id"), "模型 ID", 64) or str(uuid.uuid4())
            try:
                uuid.UUID(provider_id)
            except ValueError as exc:
                raise ValueError(f"第 {index} 个模型配置 ID 无效") from exc
            preset_id = self._bounded_text(row.get("preset_id"), "服务商", 40)
            if not preset_id:
                raise ValueError(f"第 {index} 个服务商未选择服务商")
            if preset_id not in ("zhipu", "bailian", "custom"):
                raise ValueError(f"第 {index} 个服务商无效")
            name = self._bounded_text(row.get("name"), "显示名称", 200)
            models = self._payload_models(row, index)
            model = models["vision"][0]
            api_base = self._bounded_text(row.get("api_base"), "API 地址")
            api_protocol = self._bounded_text(row.get("api_protocol"), "协议", 30)
            if not api_base:
                raise ValueError(f"第 {index} 个服务商未填写 API 地址")
            if not api_protocol:
                raise ValueError(f"第 {index} 个服务商未选择协议")
            if not name:
                raise ValueError(f"第 {index} 个服务商未填写显示名称")
            raw_keys = row.get("keys")
            if raw_keys is None:
                raw_keys = [{
                    "id": provider_id,
                    "key_action": row.get("key_action", "keep"),
                    "api_key": row.get("api_key", ""),
                }]
            if not isinstance(raw_keys, list) or len(raw_keys) != 1:
                raise ValueError(f"第 {index} 个服务商只能配置一个 API Key；备用 Key 请添加服务商")
            credential_ids: list[str] = []
            has_available_key = False
            for key_index, key_row in enumerate(raw_keys, 1):
                if not isinstance(key_row, dict):
                    raise ValueError(f"第 {index} 个服务商的第 {key_index} 个 API Key 格式错误")
                credential_id = self._bounded_text(key_row.get("id"), "凭据 ID", 64) or str(uuid.uuid4())
                try:
                    uuid.UUID(credential_id)
                except ValueError as exc:
                    raise ValueError(f"第 {index} 个服务商的第 {key_index} 个 API Key ID 无效") from exc
                if credential_id in seen_credential_ids:
                    raise ValueError("API Key 槽位不能重复")
                if credential_id != provider_id:
                    raise ValueError(f"第 {index} 个服务商的凭据 ID 必须与服务商 ID 一致")
                seen_credential_ids.add(credential_id)
                credential_ids.append(credential_id)
                action = self._bounded_text(key_row.get("key_action", "keep"), "凭据操作", 10)
                if action not in ("keep", "set", "delete"):
                    raise ValueError("凭据操作无效")
                api_key = str(key_row.get("api_key") or "")
                if len(api_key) > 8192:
                    raise ValueError("API Key 过长")
                if action == "set" and not api_key:
                    raise ValueError("API Key 不能为空")
                stored_key = get_key(credential_id) if action == "keep" else ""
                if (action == "set" and api_key) or stored_key:
                    has_available_key = True
                key_actions.append((credential_id, action, api_key))
            if require_keys and not has_available_key:
                missing_key_indexes.append(index)

            providers.append({
                "id": provider_id,
                "credential_ids": [provider_id],
                "preset_id": preset_id,
                "enabled": bool(row.get("enabled", True)),
                "name": name,
                "model": model,
                "models": models,
                "api_base": api_base,
                "api_protocol": api_protocol,
                "image_format": "auto",
            })
        if require_keys and missing_key_indexes:
            raise ValueError(self._missing_key_message(missing_key_indexes))

        cfg = {
            "version": 1,
            "defaults_revision": self._cfg.get("defaults_revision", 4),
            "timeout": self._cfg.get("timeout", 180),
            "providers": providers,
        }
        new_ids = {
            credential_id
            for provider in providers
            for credential_id in provider_credential_ids(provider)
        }
        planned: dict[str, tuple[str, str]] = {
            provider_id: (action, api_key)
            for provider_id, action, api_key in key_actions
            if action != "keep"
        }
        for provider_id in old_ids - new_ids:
            planned[provider_id] = ("delete", "")
        snapshots = {provider_id: get_key(provider_id) for provider_id in planned}
        try:
            for provider_id, (action, api_key) in planned.items():
                if action == "set":
                    set_key(provider_id, api_key)
                else:
                    delete_key(provider_id)
            # The atomic config file replacement is the transaction commit.
            save_config(cfg)
        except Exception:
            rollback_errors = []
            for provider_id, previous in snapshots.items():
                try:
                    if previous:
                        set_key(provider_id, previous)
                    else:
                        delete_key(provider_id)
                except Exception as rollback_exc:
                    rollback_errors.append(redact_text(rollback_exc, 200))
            if rollback_errors:
                LOGGER.error("Credential rollback failed: %s", "; ".join(rollback_errors))
            raise
        self._cfg = cfg
        return self._public_state()

    def save_models(self, payload: object) -> dict[str, Any]:
        try:
            state = self._save_payload(payload)
            missing = [index for index, provider in enumerate(state["providers"], 1) if not provider["has_key"]]
            if missing:
                message = f"模型配置已保存；{self._missing_key_message(missing)}"
                return self._ok(message, state=state, warning=True)
            return self._ok("模型配置已保存；API Key 已安全保存到 Windows 凭据管理器", state=state, warning=False)
        except Exception as exc:
            return self._error(exc)

    def _emit(self, name: str, *args: Any) -> None:
        if not self._window:
            return
        encoded = ",".join(json.dumps(arg, ensure_ascii=False) for arg in args)
        script = f"window.visionApp && window.visionApp.{name}({encoded});"
        try:
            self._window.evaluate_js(script)
        except Exception as exc:  # window may be closing
            LOGGER.debug("WebView callback skipped: %s", redact_text(exc, 200))

    def configure_and_test(self, payload: object, selected: object) -> dict[str, Any]:
        if not self._operation_lock.acquire(blocking=False):
            return {"ok": False, "message": "已有配置或测试任务正在执行"}
        logs: list[str] = []

        def add_log(text: str) -> None:
            safe = redact_text(text, 1000)
            logs.append(safe)
            self._emit("appendLog", safe)

        try:
            if not isinstance(selected, list) or not selected:
                raise ValueError("请先选择至少一个已安装的 Agent")
            known = agent_ops.agents()
            selected_keys = [str(key) for key in selected]
            if any(key not in known for key in selected_keys):
                raise ValueError("包含未知 Agent")
            if any(not agent_ops.detected(known[key]) for key in selected_keys):
                raise ValueError("所选 Agent 中包含未安装项目")
            state = self._save_payload(payload, require_keys=True)

            server = server_executable()
            self._emit("stageUpdate", "agent", "running", "正在写入所选 Agent 配置")
            agent_failed = False
            failure_messages: list[str] = []
            for key in selected_keys:
                try:
                    backup = agent_ops.configure_preferred(key, server)
                    suffix = "（已创建备份）" if backup else ""
                    add_log(f"{known[key].name}：配置成功{suffix}")
                except Exception as exc:
                    agent_failed = True
                    detail = redact_text(exc, 500)
                    failure_messages.append(f"{known[key].name}：{detail}")
                    add_log(f"{known[key].name}：配置失败 - {detail}")
            self._emit(
                "stageUpdate", "agent", "failed" if agent_failed else "success",
                "；".join(failure_messages) if agent_failed else "所选 Agent 配置完成",
            )

            stages_ok = not agent_failed
            for stage_name, label, args in (
                ("protocol", "MCP 协议", ("protocol-test",)),
                ("model", "视觉模型", ("self-test",)),
            ):
                self._emit("stageUpdate", stage_name, "running", f"正在检查{label}")
                try:
                    run = subprocess.run(
                        self._server_cmd(*args), capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=210,
                        **isolated_subprocess_kwargs(),
                    )
                    output = redact_text((run.stdout or run.stderr).strip(), 1000)
                    ok = run.returncode == 0
                    stages_ok = stages_ok and ok
                    detail = self._test_error_detail(output)
                    add_log(f"{label}自检：{'通过' if ok else '失败'} {output}")
                    if not ok:
                        failure_messages.append(f"{label}：{detail}")
                    self._emit(
                        "stageUpdate", stage_name, "success" if ok else "failed",
                        "检查通过" if ok else detail,
                    )
                except Exception as exc:
                    stages_ok = False
                    detail = redact_text(exc, 500)
                    failure_messages.append(f"{label}：{detail}")
                    add_log(f"{label}自检：失败 - {detail}")
                    self._emit("stageUpdate", stage_name, "failed", detail)
            state["agents"] = self._agent_state()
            return self._ok(
                "配置与测试已完成" if stages_ok else f"配置与测试未通过：{'；'.join(failure_messages)}",
                passed=stages_ok, logs=logs, state=state,
            )
        except Exception as exc:
            return self._error(exc)
        finally:
            self._operation_lock.release()

    @staticmethod
    def _validated_agent_keys(selected: object) -> list[str]:
        if not isinstance(selected, list) or not selected:
            raise ValueError("请先选择至少一个 Agent")
        known = agent_ops.agents()
        keys = [str(key) for key in selected]
        if any(key not in known for key in keys):
            raise ValueError("包含未知 Agent")
        return keys

    def remove_agents(self, selected: object) -> dict[str, Any]:
        try:
            keys = self._validated_agent_keys(selected)
            server = server_executable()
            logs = []
            for key in keys:
                try:
                    changed = agent_ops.remove(key, server)
                    logs.append(f"{agent_ops.agents()[key].name}：{'已移除' if changed else '未修改（不是本程序配置）'}")
                except Exception as exc:
                    logs.append(f"{agent_ops.agents()[key].name}：移除失败 - {redact_text(exc, 500)}")
            return self._ok("已处理所选 Agent 的移除操作", logs=logs, agents=self._agent_state())
        except Exception as exc:
            return self._error(exc)

    def restore_backups(self, selected: object) -> dict[str, Any]:
        try:
            keys = self._validated_agent_keys(selected)
            logs = []
            for key in keys:
                try:
                    agent_ops.restore_latest(key)
                    logs.append(f"{agent_ops.agents()[key].name}：已恢复最近备份")
                except Exception as exc:
                    logs.append(f"{agent_ops.agents()[key].name}：恢复失败 - {redact_text(exc, 500)}")
            return self._ok("已处理所选 Agent 的备份恢复", logs=logs, agents=self._agent_state())
        except Exception as exc:
            return self._error(exc)

    def copy_manual_config(self) -> dict[str, Any]:
        try:
            server = str(Path(server_executable()).resolve())
            json_entry = json.dumps(
                {"mcpServers": {"vision": {"command": server, "args": ["stdio"]}}},
                ensure_ascii=False, indent=2,
            )
            _copy_to_clipboard(json_entry)
            return self._ok("MCP 配置已复制到剪贴板")
        except Exception as exc:
            return self._error(exc)

    def open_key_page(self, preset_id: str) -> dict[str, Any]:
        try:
            url = KEY_URLS.get(str(preset_id))
            if not url:
                raise ValueError("该服务商没有可用的 API Key 页面")
            webbrowser.open(url)
            return self._ok()
        except Exception as exc:
            return self._error(exc)

    def open_rate_limit_page(self) -> dict[str, Any]:
        try:
            webbrowser.open(RATE_LIMIT_URL)
            return self._ok()
        except Exception as exc:
            return self._error(exc)

    def open_project_page(self) -> dict[str, Any]:
        try:
            webbrowser.open(PROJECT_URL)
            return self._ok()
        except Exception as exc:
            return self._error(exc)

    def close_manager(self) -> dict[str, Any]:
        try:
            if not self._window:
                raise ValueError("管理器窗口尚未就绪")
            threading.Timer(0.1, self._window.destroy).start()
            return self._ok("正在关闭管理器")
        except Exception as exc:
            return self._error(exc)

    def uninstall(self) -> dict[str, Any]:
        try:
            install_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(server_executable()).resolve().parent
            candidates = sorted(install_dir.glob("unins*.exe"))
            if not candidates:
                raise ValueError("开发环境中没有卸载程序，安装后可从这里打开卸载向导")
            subprocess.Popen([str(candidates[0])], **isolated_subprocess_kwargs())
            if self._window:
                threading.Timer(0.25, self._window.destroy).start()
            return self._ok("正在打开卸载向导")
        except Exception as exc:
            return self._error(exc)


def _show_startup_error(message: str) -> None:
    safe = redact_text(message, 1000)
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(None, safe, "Vision MCP 启动失败", 0x10)
    else:  # pragma: no cover
        print(safe, file=sys.stderr)


def main() -> None:
    setup_logging("manager")
    try:
        import webview

        html_path = resource_path("design", "vision-mcp-config-prototype.html")
        html = html_path.read_text(encoding="utf-8")
        runtime_js = resource_path("design", "vision-mcp-manager.js").read_text(encoding="utf-8")
        icon_data = base64.b64encode(
            resource_path("design", "vision-mcp-icon.png").read_bytes()
        ).decode("ascii")
        html = html.replace("vision-mcp-icon.png", f"data:image/png;base64,{icon_data}")
        html = re.sub(
            r'<script type="text/plain" id="prototype-demo-script">.*?</script>\s*',
            "", html, flags=re.DOTALL,
        )
        html = html.replace(
            '<script src="vision-mcp-manager.js"></script>',
            "<script>" + runtime_js.replace("</script>", "<\\/script>") + "</script>",
        )
        api = ManagerApi()
        window = webview.create_window(
            f"Vision MCP 管理器 {__version__}", html=html, js_api=api,
            width=MANAGER_WIDTH, height=MANAGER_HEIGHT,
            min_size=(MANAGER_MIN_WIDTH, MANAGER_MIN_HEIGHT),
            background_color="#ffffff", text_select=True,
            on_top=True,
        )
        api._attach_window(window)
        webview.start(
            _normalize_window_geometry,
            window,
            gui="edgechromium",
            debug=False,
            http_server=False,
            private_mode=True,
        )
    except Exception as exc:
        LOGGER.exception("Manager startup failed")
        _show_startup_error(
            "Vision MCP 管理器无法启动。请确认 Microsoft Edge WebView2 Runtime 已安装。\n\n"
            + redact_text(exc, 700)
        )
        raise


if __name__ == "__main__":
    main()
