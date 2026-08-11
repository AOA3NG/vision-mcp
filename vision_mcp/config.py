from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlparse

APP_NAME = "VisionMCP"
CONFIG_VERSION = 1
DEFAULTS_REVISION = 6

MODEL_CAPABILITIES = ("vision", "image_generation", "video_generation")
ZHIPU_DEFAULT_MODELS = {
    "vision": ["glm-4.6v-flash", "glm-4.1v-thinking-flash"],
    "image_generation": [],
    "video_generation": [],
}
LEGACY_AUTO_SELECTED_GENERATION_MODELS = {
    "image_generation": ["cogview-3-flash"],
    "video_generation": ["cogvideox-flash"],
}

PRESETS = {
    "zhipu": {
        "name": "智谱开放平台",
        "api_base": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4.6v-flash",
        "models": ZHIPU_DEFAULT_MODELS,
        "api_protocol": "openai",
        "image_format": "auto",
    },
    "bailian": {
        "name": "阿里云百炼 Coding Plan",
        "api_base": "https://coding.dashscope.aliyuncs.com/v1",
        "model": "qwen3.7-plus",
        "api_protocol": "openai",
        "image_format": "auto",
    },
}


def roaming_dir() -> Path:
    return Path(os.environ.get("APPDATA", Path.home() / ".config")) / APP_NAME


def local_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) / APP_NAME


def config_path() -> Path:
    override = os.environ.get("VISION_MCP_CONFIG")
    return Path(override) if override else roaming_dir() / "config.json"


def new_provider(preset_id: str = "zhipu") -> dict:
    preset = PRESETS[preset_id].copy()
    if "models" in preset:
        preset["models"] = {key: list(value) for key, value in preset["models"].items()}
    provider_id = str(uuid.uuid4())
    return {
        "id": provider_id,
        "credential_ids": [provider_id],
        "preset_id": preset_id,
        "enabled": True,
        **preset,
    }


def default_config() -> dict:
    return {
        "version": CONFIG_VERSION,
        "defaults_revision": DEFAULTS_REVISION,
        "timeout": 180,
        "providers": [new_provider("zhipu")],
    }


def _upgrade_defaults(cfg: dict) -> bool:
    try:
        revision = int(cfg.get("defaults_revision", 1))
    except (TypeError, ValueError):
        revision = 1
    if revision >= DEFAULTS_REVISION:
        return False
    providers = cfg.get("providers", [])
    merged: list[dict] = []
    zhipu_by_endpoint: dict[tuple[str, str], dict] = {}
    for original in providers:
        provider = dict(original)
        preset_id = str(provider.get("preset_id", "custom"))
        endpoint = str(provider.get("api_base", "")).rstrip("/").lower()
        protocol = str(provider.get("api_protocol", "openai")).lower()
        if preset_id == "zhipu":
            key = (endpoint, protocol)
            target = zhipu_by_endpoint.get(key)
            if target is None:
                provider["name"] = "智谱开放平台"
                existing = {
                    capability: provider_models(provider, capability)
                    for capability in MODEL_CAPABILITIES
                }
                if revision < 6:
                    for capability, legacy_models in LEGACY_AUTO_SELECTED_GENERATION_MODELS.items():
                        if [value.lower() for value in existing[capability]] == [
                            value.lower() for value in legacy_models
                        ]:
                            existing[capability] = []
                for capability, defaults in ZHIPU_DEFAULT_MODELS.items():
                    for model in defaults:
                        if model.lower() not in {value.lower() for value in existing[capability]}:
                            existing[capability].append(model)
                provider["models"] = existing
                provider["model"] = provider["models"]["vision"][0]
                provider.setdefault("credential_aliases", [])
                zhipu_by_endpoint[key] = provider
                merged.append(provider)
            else:
                for capability in MODEL_CAPABILITIES:
                    for model in provider_models(provider, capability):
                        if model.lower() not in {value.lower() for value in target["models"][capability]}:
                            target["models"][capability].append(model)
                alias = str(provider.get("id", ""))
                if alias and alias != target.get("id") and alias not in target["credential_aliases"]:
                    target["credential_aliases"].append(alias)
        else:
            provider.setdefault("models", {
                "vision": [str(provider.get("model", ""))],
                "image_generation": [],
                "video_generation": [],
            })
            merged.append(provider)
    expanded: list[dict] = []
    for provider in merged:
        credential_ids = provider.get("credential_ids")
        if not isinstance(credential_ids, list) or not credential_ids:
            credential_ids = [str(provider.get("id", ""))]
        aliases = provider.pop("credential_aliases", [])
        if isinstance(aliases, list):
            credential_ids.extend(str(value) for value in aliases)
        unique_ids = list(dict.fromkeys(value for value in credential_ids if value))
        for credential_id in unique_ids or [str(provider.get("id", ""))]:
            item = dict(provider)
            item["id"] = credential_id
            item["credential_ids"] = [credential_id]
            item["models"] = {
                capability: list(provider_models(provider, capability))
                for capability in MODEL_CAPABILITIES
            }
            expanded.append(item)
    cfg["providers"] = expanded
    cfg["defaults_revision"] = DEFAULTS_REVISION
    return True


def provider_models(provider: dict, capability: str = "vision") -> list[str]:
    """Return normalized models while accepting pre-v3 single-model configs."""
    if capability not in MODEL_CAPABILITIES:
        raise ValueError(f"未知模型能力: {capability}")
    models = provider.get("models")
    if isinstance(models, dict):
        values = models.get(capability, [])
        if isinstance(values, list):
            return [str(value).strip() for value in values if str(value).strip()]
    if capability == "vision" and str(provider.get("model", "")).strip():
        return [str(provider["model"]).strip()]
    return []


def validate_config(cfg: dict) -> dict:
    if not isinstance(cfg, dict):
        raise ValueError("配置根节点必须是对象")
    if cfg.get("version") != CONFIG_VERSION:
        raise ValueError(f"不支持的配置版本: {cfg.get('version')}")
    timeout = cfg.get("timeout", 180)
    if not isinstance(timeout, (int, float)) or not 1 <= timeout <= 600:
        raise ValueError("timeout 必须在 1 到 600 秒之间")
    providers = cfg.get("providers")
    if not isinstance(providers, list) or not providers:
        raise ValueError("至少需要一个模型提供商")
    ids: set[str] = set()
    credential_ids: set[str] = set()
    for i, p in enumerate(providers, 1):
        if not isinstance(p, dict):
            raise ValueError(f"第 {i} 个提供商格式错误")
        required = ("id", "name", "api_base", "api_protocol", "image_format")
        missing = [k for k in required if not str(p.get(k, "")).strip()]
        if missing:
            raise ValueError(f"第 {i} 个提供商缺少: {', '.join(missing)}")
        try:
            uuid.UUID(str(p["id"]))
        except ValueError as exc:
            raise ValueError(f"第 {i} 个提供商 ID 无效") from exc
        if p["id"] in ids:
            raise ValueError("提供商 ID 不能重复")
        ids.add(p["id"])
        slots = p.get("credential_ids", [p["id"]])
        if not isinstance(slots, list) or len(slots) != 1:
            raise ValueError(f"第 {i} 个服务商只能配置一个 API Key")
        normalized_slots: list[str] = []
        for slot in slots:
            slot_id = str(slot)
            try:
                uuid.UUID(slot_id)
            except ValueError as exc:
                raise ValueError(f"第 {i} 个服务商包含无效的 API Key 槽位 ID") from exc
            if slot_id in credential_ids:
                raise ValueError("API Key 槽位 ID 不能重复")
            credential_ids.add(slot_id)
            normalized_slots.append(slot_id)
        if normalized_slots[0] != str(p["id"]):
            raise ValueError(f"第 {i} 个服务商的凭据 ID 必须与服务商 ID 一致")
        p["credential_ids"] = normalized_slots
        if p["api_protocol"] not in ("openai", "anthropic"):
            raise ValueError(f"第 {i} 个提供商协议无效")
        if p["image_format"] not in ("auto", "data_uri", "base64"):
            raise ValueError(f"第 {i} 个提供商图片格式无效")
        normalized_models: dict[str, list[str]] = {}
        all_models: set[str] = set()
        for capability in MODEL_CAPABILITIES:
            values = provider_models(p, capability)
            if len(values) > 20:
                raise ValueError(f"第 {i} 个提供商的模型数量过多")
            lowered = [value.lower() for value in values]
            if len(lowered) != len(set(lowered)):
                raise ValueError(f"第 {i} 个提供商的 {capability} 模型不能重复")
            overlap = all_models.intersection(lowered)
            if overlap:
                raise ValueError(f"第 {i} 个提供商的模型不能跨能力重复")
            all_models.update(lowered)
            normalized_models[capability] = values
        if not normalized_models["vision"]:
            raise ValueError(f"第 {i} 个提供商至少需要一个视觉理解模型")
        p["models"] = normalized_models
        p["model"] = normalized_models["vision"][0]
        parsed = urlparse(p["api_base"])
        if parsed.scheme != "https" or not parsed.netloc or parsed.username:
            raise ValueError(f"第 {i} 个提供商 API 地址必须是有效 HTTPS 地址")
    return cfg


def load_config(create: bool = False) -> dict:
    path = config_path()
    if not path.exists():
        cfg = default_config()
        if create:
            save_config(cfg)
        return cfg
    try:
        cfg = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"配置文件无法读取: {exc}") from exc
    upgraded = _upgrade_defaults(cfg)
    cfg = validate_config(cfg)
    if upgraded and create:
        save_config(cfg)
    return cfg


def save_config(cfg: dict) -> None:
    validate_config(cfg)
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="config-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(cfg, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        json.loads(Path(temp_name).read_text(encoding="utf-8"))
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
