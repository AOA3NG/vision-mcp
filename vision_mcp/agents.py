from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover
    import tomli as tomllib

from .config import roaming_dir
from .processes import isolated_subprocess_kwargs

MAX_BACKUPS_PER_AGENT = 5


def _run_cli(command: list[str], timeout: int):
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        **isolated_subprocess_kwargs(),
    )


@dataclass(frozen=True)
class Agent:
    key: str
    name: str
    kind: str
    path: Path
    detect_path: Path
    detect_paths: tuple[Path, ...] = ()


def _home() -> Path:
    return Path(os.environ.get("USERPROFILE", Path.home()))


def agents() -> dict[str, Agent]:
    home = _home()
    appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    trae_roots = (
        appdata / "TRAE SOLO CN",
        appdata / "Trae CN",
        appdata / "TRAE SOLO",
        home / ".trae",
    )
    trae_configs = tuple(root / "User" / "mcp.json" for root in trae_roots[:-1]) + (trae_roots[-1] / "mcp.json",)
    existing_trae_configs = [path for path in trae_configs if path.is_file()]
    trae_path = max(existing_trae_configs, key=lambda path: path.stat().st_mtime_ns) if existing_trae_configs else trae_configs[0]
    return {
        "claude": Agent("claude", "Claude Code", "json", home / ".claude.json", home / ".claude.json"),
        "codex": Agent("codex", "Codex", "toml", home / ".codex" / "config.toml", home / ".codex"),
        "cursor": Agent("cursor", "Cursor", "json", home / ".cursor" / "mcp.json", home / ".cursor"),
        "trae": Agent("trae", "Trae", "json", trae_path, trae_path.parent.parent, trae_roots),
        "workbuddy": Agent("workbuddy", "WorkBuddy", "json", home / ".workbuddy" / "mcp.json", home / ".workbuddy"),
    }


def detected(agent: Agent) -> bool:
    paths = agent.detect_paths or (agent.detect_path,)
    if any(path.exists() for path in paths):
        return True
    return agent.key == "trae" and _trae_registered()


def _assert_safe_agent_path(agent: Agent) -> None:
    if agent.key != "trae":
        return
    absolute = Path(os.path.abspath(agent.path))
    roots = tuple(Path(os.path.abspath(path)) for path in (agent.detect_paths or (agent.detect_path,)))
    matching = next((root for root in roots if absolute.is_relative_to(root)), None)
    if matching is None:
        raise ValueError("Trae 配置路径不在受支持的用户目录中")
    current = matching
    relative_parent = absolute.parent.relative_to(matching)
    candidates = [current]
    for part in relative_parent.parts:
        current = current / part
        candidates.append(current)
    is_junction = getattr(os.path, "isjunction", lambda _path: False)
    if any(path.exists() and (path.is_symlink() or is_junction(path)) for path in candidates):
        raise ValueError("Trae 配置路径包含不受支持的重解析点，已停止写入")


def _trae_registered() -> bool:
    """Recognize current Trae/TraeWork installers even when roaming data is not created yet."""
    if os.name != "nt":
        return False
    try:
        import winreg

        roots = (
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        )
        for hive, key_name in roots:
            try:
                with winreg.OpenKey(hive, key_name) as parent:
                    for index in range(winreg.QueryInfoKey(parent)[0]):
                        child_name = winreg.EnumKey(parent, index)
                        with winreg.OpenKey(parent, child_name) as child:
                            try:
                                display_name = str(winreg.QueryValueEx(child, "DisplayName")[0])
                            except OSError:
                                continue
                            if re.search(r"\btrae(?:work)?\b", display_name, re.IGNORECASE):
                                return True
            except OSError:
                continue
    except (ImportError, OSError):
        return False
    return False


def _backup(path: Path, agent_key: str) -> Path | None:
    if not path.exists():
        return None
    target_dir = _backup_dir(agent_key, path)
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    target = target_dir / f"{path.name}.{stamp}-{uuid.uuid4().hex[:8]}.bak"
    shutil.copy2(path, target)
    backups = sorted(target_dir.glob("*.bak"), key=lambda item: item.stat().st_mtime_ns, reverse=True)
    for expired in backups[MAX_BACKUPS_PER_AGENT:]:
        expired.unlink(missing_ok=True)
    return target


def _backup_dir(agent_key: str, source_path: Path) -> Path:
    canonical = str(source_path.resolve()).casefold().encode("utf-8")
    path_token = hashlib.sha256(canonical).hexdigest()[:16]
    return roaming_dir() / "backups" / "agents" / agent_key / path_token


def _trusted_cli(agent_key: str) -> str | None:
    """Accept only native executables under the Agent's known install roots."""
    if os.name != "nt" or agent_key not in ("claude", "codex"):
        return None
    candidate = shutil.which(agent_key)
    if not candidate:
        return None
    path = Path(candidate).resolve()
    if path.suffix.lower() != ".exe" or not path.is_file():
        return None
    local = Path(os.environ.get("LOCALAPPDATA", _home() / "AppData" / "Local")).resolve()
    roots = {
        "codex": [local / "OpenAI" / "Codex", local / "Programs" / "Codex"],
        "claude": [local / "AnthropicClaude", local / "Programs" / "Claude"],
    }[agent_key]
    if not any(path.is_relative_to(root.resolve()) for root in roots):
        return None
    return str(path)


def _atomic_write(path: Path, text: str, validator) -> None:
    _atomic_write_bytes(path, text.encode("utf-8"), validator)


def _atomic_write_bytes(path: Path, raw: bytes, validator=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if validator:
            validator(Path(temp_name).read_bytes())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _load_json(path: Path) -> dict:
    if not path.exists() or not path.read_bytes().strip():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path} 不是有效 JSON，已停止写入") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path} 的根节点必须是对象")
    return value


def _json_validate(raw: bytes) -> None:
    value = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("JSON 根节点必须是对象")


def _toml_validate(raw: bytes) -> None:
    tomllib.loads(raw.decode("utf-8-sig"))


def _expected(server: str) -> dict:
    return {"command": str(Path(server).resolve()), "args": ["stdio"]}


def _same_entry(entry: object, server: str) -> bool:
    if not isinstance(entry, dict):
        return False
    try:
        return Path(str(entry.get("command", ""))).resolve() == Path(server).resolve() and entry.get("args") == ["stdio"]
    except OSError:
        return False


def configure(agent_key: str, server: str) -> Path | None:
    agent = agents()[agent_key]
    _assert_safe_agent_path(agent)
    if agent.kind == "json":
        obj = _load_json(agent.path)
        servers = obj.setdefault("mcpServers", {})
        if not isinstance(servers, dict):
            raise ValueError(f"{agent.path} 中的 mcpServers 必须是对象")
        current = servers.get("vision")
        if current is not None and not _same_entry(current, server):
            raise ValueError("已存在非本程序创建的 vision 配置，未覆盖")
        backup = _backup(agent.path, agent.key)
        entry = _expected(server)
        if agent_key == "claude":
            entry["type"] = "stdio"
        servers["vision"] = entry
        _atomic_write(agent.path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n", _json_validate)
        return backup

    content = agent.path.read_text(encoding="utf-8-sig") if agent.path.exists() else ""
    if content.strip():
        try:
            parsed = tomllib.loads(content)
        except Exception as exc:
            raise ValueError(f"{agent.path} 不是有效 TOML，已停止写入") from exc
        current = parsed.get("mcp_servers", {}).get("vision")
        if current is not None and not _same_entry(current, server):
            raise ValueError("已存在非本程序创建的 vision 配置，未覆盖")
    backup = _backup(agent.path, agent.key)
    content = _remove_toml_section(content)
    escaped = str(Path(server).resolve()).replace("\\", "\\\\").replace('"', '\\"')
    section = f'\n[mcp_servers.vision]\ncommand = "{escaped}"\nargs = ["stdio"]\n'
    _atomic_write(agent.path, content.rstrip() + section, _toml_validate)
    return backup


def configure_preferred(agent_key: str, server: str) -> Path | None:
    """Use an official MCP CLI when available, with a verified backup and safe fallback."""
    executable = _trusted_cli(agent_key)
    if not executable:
        return configure(agent_key, server)
    current = status(agent_key, server)
    if current in ("conflict", "invalid_config"):
        raise ValueError("现有 vision 配置冲突或配置文件损坏，未覆盖")
    agent = agents()[agent_key]
    existed = agent.path.exists()
    original = agent.path.read_bytes() if existed else None
    backup = _backup(agent.path, agent.key)
    remove_cmd = [executable, "mcp", "remove"] + (["-s", "user"] if agent_key == "claude" else []) + ["vision"]
    add_cmd = [executable, "mcp", "add"] + (["-s", "user"] if agent_key == "claude" else []) + ["vision", "--", str(Path(server).resolve()), "stdio"]
    try:
        if current == "configured":
            _run_cli(remove_cmd, 20)
        result = _run_cli(add_cmd, 30)
        if result.returncode != 0 or status(agent_key, server) != "configured":
            raise ValueError((result.stderr or result.stdout or "官方 CLI 未写入预期配置").strip()[:500])
        return backup
    except Exception as exc:
        try:
            _run_cli(remove_cmd, 20)
        except Exception:
            # An unavailable executable can fail for both add and cleanup. The
            # byte-for-byte restore below remains the source of truth.
            pass
        finally:
            if existed and original is not None:
                _atomic_write_bytes(agent.path, original)
            elif agent.path.exists():
                agent.path.unlink()
        # Desktop Agent launchers can leave a stale codex.cmd/claude.cmd on PATH
        # after an application update. Fall back only when the CLI is unavailable,
        # and only after the original configuration bytes have been restored.
        unavailable = str(exc).lower()
        if any(marker in unavailable for marker in (
            "executable not found",
            "no such file or directory",
            "the system cannot find the file",
            "is not recognized as an internal or external command",
        )):
            return configure(agent_key, server)
        raise


def _remove_toml_section(content: str) -> str:
    pattern = re.compile(r"(?ms)^\[mcp_servers\.vision\]\s*\n.*?(?=^\[|\Z)")
    return pattern.sub("", content)


def status(agent_key: str, server: str) -> str:
    agent = agents()[agent_key]
    if not detected(agent):
        return "not_detected"
    try:
        if agent.kind == "json":
            entry = _load_json(agent.path).get("mcpServers", {}).get("vision")
        else:
            if not agent.path.exists():
                return "not_configured"
            entry = tomllib.loads(agent.path.read_text(encoding="utf-8-sig")).get("mcp_servers", {}).get("vision")
    except (ValueError, OSError, AttributeError):
        return "invalid_config"
    if entry is None:
        return "not_configured"
    return "configured" if _same_entry(entry, server) else "conflict"


def remove(agent_key: str, server: str) -> Path | None:
    agent = agents()[agent_key]
    _assert_safe_agent_path(agent)
    if not agent.path.exists():
        return None
    if agent.kind == "json":
        obj = _load_json(agent.path)
        servers = obj.get("mcpServers", {})
        if not _same_entry(servers.get("vision"), server):
            return None
        backup = _backup(agent.path, agent.key)
        del servers["vision"]
        _atomic_write(agent.path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n", _json_validate)
        return backup
    parsed = tomllib.loads(agent.path.read_text(encoding="utf-8-sig"))
    if not _same_entry(parsed.get("mcp_servers", {}).get("vision"), server):
        return None
    backup = _backup(agent.path, agent.key)
    _atomic_write(agent.path, _remove_toml_section(agent.path.read_text(encoding="utf-8-sig")).rstrip() + "\n", _toml_validate)
    return backup


def latest_backup(agent_key: str) -> Path | None:
    folder = _backup_dir(agent_key, agents()[agent_key].path)
    files = sorted(folder.glob("*.bak"), key=lambda item: item.stat().st_mtime_ns, reverse=True) if folder.exists() else []
    return files[0] if files else None


def restore_latest(agent_key: str) -> Path:
    agent = agents()[agent_key]
    _assert_safe_agent_path(agent)
    backup = latest_backup(agent_key)
    if not backup:
        raise ValueError("没有可恢复的备份")
    raw = backup.read_bytes()
    (_json_validate if agent.kind == "json" else _toml_validate)(raw)
    _backup(agent.path, agent.key)
    _atomic_write_bytes(agent.path, raw, _json_validate if agent.kind == "json" else _toml_validate)
    return backup
