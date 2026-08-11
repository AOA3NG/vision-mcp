from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

SERVICE = "VisionMCP"
LEGACY_BACKUP_MAGIC = b"VisionMCP-DPAPI\0"


def legacy_dir() -> Path:
    return Path(os.environ.get("APPDATA", Path.home())) / "vision-mcp"


def _backend():
    try:
        import keyring
    except ImportError as exc:
        raise RuntimeError("缺少 keyring，无法访问 Windows 凭据管理器") from exc
    backend = keyring.get_keyring()
    if os.name == "nt" and not (
        backend.__class__.__module__ == "keyring.backends.Windows"
        and backend.__class__.__name__ == "WinVaultKeyring"
    ):
        raise RuntimeError(
            f"keyring 未使用 Windows Credential Manager: "
            f"{backend.__class__.__module__}.{backend.__class__.__name__}"
        )
    return keyring


def get_key(provider_id: str) -> str:
    try:
        return _backend().get_password(SERVICE, provider_id) or ""
    except Exception as exc:
        raise RuntimeError(f"无法读取 Windows 凭据: {exc}") from exc


def get_provider_key(provider: dict) -> str:
    """Read the canonical credential, falling back to IDs retained during config migration."""
    value = get_key(str(provider["id"]))
    if value:
        return value
    aliases = provider.get("credential_aliases", [])
    if isinstance(aliases, list):
        for alias in aliases:
            value = get_key(str(alias))
            if value:
                return value
    return ""


def provider_credential_ids(provider: dict) -> list[str]:
    """Return ordered credential slots while accepting pre-v4 configs."""
    values = provider.get("credential_ids")
    if not isinstance(values, list) or not values:
        values = [provider.get("id")]
    result: list[str] = []
    for value in values:
        credential_id = str(value or "").strip()
        if credential_id and credential_id not in result:
            result.append(credential_id)
    return result


def get_provider_keys(provider: dict) -> list[str]:
    """Read all configured keys in fallback order without exposing them in config."""
    result: list[str] = []
    for credential_id in provider_credential_ids(provider):
        value = get_key(credential_id)
        if value and value not in result:
            result.append(value)
    if not result:
        legacy = get_provider_key(provider)
        if legacy:
            result.append(legacy)
    return result


def set_key(provider_id: str, api_key: str) -> None:
    if not api_key.strip():
        delete_key(provider_id)
        return
    try:
        _backend().set_password(SERVICE, provider_id, api_key.strip())
    except Exception as exc:
        raise RuntimeError(f"无法保存 Windows 凭据: {exc}") from exc


def delete_key(provider_id: str) -> None:
    keyring = _backend()
    try:
        keyring.delete_password(SERVICE, provider_id)
    except Exception as exc:
        password_delete_error = getattr(getattr(keyring, "errors", None), "PasswordDeleteError", ())
        if password_delete_error and isinstance(exc, password_delete_error):
            return
        raise RuntimeError(f"无法删除 Windows 凭据: {exc}") from exc


def _protect_bytes(raw: bytes) -> bytes:
    if os.name != "nt":
        raise RuntimeError("旧凭据备份只能在 Windows 上使用 DPAPI 加密")
    try:
        import win32crypt

        encrypted = win32crypt.CryptProtectData(raw, "Vision MCP legacy credential backup", None, None, None, 0)
    except Exception as exc:
        raise RuntimeError(f"无法使用 Windows DPAPI 保护旧凭据备份: {exc}") from exc
    return LEGACY_BACKUP_MAGIC + encrypted


def _atomic_protected_backup(target: Path, raw: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(_protect_bytes(raw))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, target)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _upgrade_plaintext_backup() -> None:
    backup = legacy_dir() / "keys.json.migrated.bak"
    if not backup.is_file():
        return
    raw = backup.read_bytes()
    if raw.startswith(LEGACY_BACKUP_MAGIC):
        return
    _atomic_protected_backup(backup, raw)


def migrate_legacy(cfg: dict) -> int:
    _upgrade_plaintext_backup()
    legacy = legacy_dir() / "keys.json"
    if not legacy.exists():
        return 0
    try:
        raw = legacy.read_bytes()
        values = json.loads(raw.decode("utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return 0
    migrated = 0
    aliases = {
        "zhipu": ("主-智谱免费", "主", "智谱 GLM Vision"),
        "bailian": ("备-百炼", "备用2", "阿里云百炼"),
    }
    found_legacy = False
    for provider in cfg.get("providers", []):
        names = (provider.get("name"),) + aliases.get(provider.get("preset_id"), ())
        key = next((values.get(name) for name in names if values.get(name)), None)
        if key:
            found_legacy = True
            if not get_key(provider["id"]):
                set_key(provider["id"], str(key))
                migrated += 1
    if found_legacy:
        backup = legacy.with_suffix(".json.migrated.bak")
        _atomic_protected_backup(backup, raw)
        legacy.unlink()
    return migrated


def purge_all(cfg: dict) -> int:
    provider_ids = {str(provider["id"]) for provider in cfg.get("providers", []) if provider.get("id")}
    for provider in cfg.get("providers", []):
        provider_ids.update(provider_credential_ids(provider))
        aliases = provider.get("credential_aliases", [])
        if isinstance(aliases, list):
            provider_ids.update(str(alias) for alias in aliases if alias)
    provider_ids.update(_windows_provider_ids())
    removed = 0
    for provider_id in provider_ids:
        if get_key(provider_id):
            delete_key(provider_id)
            removed += 1
    return removed


def _windows_provider_ids() -> set[str]:
    if os.name != "nt":
        return set()
    try:
        import win32cred

        credentials = win32cred.CredEnumerate(None, 0)
    except Exception as exc:
        raise RuntimeError(f"无法枚举 Windows 凭据: {exc}") from exc
    suffix = f"@{SERVICE}"
    return {
        str(credential.get("UserName", ""))
        for credential in credentials
        if credential.get("UserName")
        and (
            credential.get("TargetName") == SERVICE
            or str(credential.get("TargetName", "")).endswith(suffix)
        )
    }


def purge_legacy_data() -> int:
    """Remove legacy plaintext credential files when uninstall requests data removal."""
    removed = 0
    folder = legacy_dir()
    for name in ("keys.json", "keys.json.migrated.bak"):
        path = folder / name
        if path.is_file():
            path.unlink()
            removed += 1
    try:
        folder.rmdir()
    except OSError:
        pass
    return removed
