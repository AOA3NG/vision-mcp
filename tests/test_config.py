import json
import copy
import uuid

import pytest

from vision_mcp.config import default_config, load_config, save_config


def test_config_round_trip_is_utf8_and_has_no_key(app_env):
    cfg = default_config()
    cfg["providers"][0]["name"] = "中文 模型"
    save_config(cfg)
    raw = (app_env["roaming"] / "VisionMCP" / "config.json").read_text(encoding="utf-8")
    assert "中文 模型" in raw
    assert "api_key" not in raw
    assert load_config() == cfg


def test_default_config_keeps_generation_models_opt_in():
    cfg = default_config()
    providers = cfg["providers"]
    assert cfg["defaults_revision"] == 6
    assert len(providers) == 1
    assert providers[0]["preset_id"] == "zhipu"
    assert providers[0]["models"] == {
        "vision": ["glm-4.6v-flash", "glm-4.1v-thinking-flash"],
        "image_generation": [],
        "video_generation": [],
    }


def test_v5_automatic_generation_defaults_are_unselected_once(app_env):
    cfg = default_config()
    cfg["defaults_revision"] = 5
    cfg["providers"][0]["models"]["image_generation"] = ["cogview-3-flash"]
    cfg["providers"][0]["models"]["video_generation"] = ["cogvideox-flash"]
    path = app_env["roaming"] / "VisionMCP" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    upgraded = load_config(create=True)

    assert upgraded["defaults_revision"] == 6
    assert upgraded["providers"][0]["models"]["image_generation"] == []
    assert upgraded["providers"][0]["models"]["video_generation"] == []


def test_v5_custom_generation_selection_is_preserved(app_env):
    cfg = default_config()
    cfg["defaults_revision"] = 5
    cfg["providers"][0]["models"]["image_generation"] = [
        "cogview-3-flash", "user-image-model"
    ]
    cfg["providers"][0]["models"]["video_generation"] = ["user-video-model"]
    path = app_env["roaming"] / "VisionMCP" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    upgraded = load_config(create=True)

    assert upgraded["providers"][0]["models"]["image_generation"] == [
        "cogview-3-flash", "user-image-model"
    ]
    assert upgraded["providers"][0]["models"]["video_generation"] == ["user-video-model"]


def test_old_two_zhipu_rows_keep_separate_credential_groups(app_env):
    cfg = default_config()
    primary = copy.deepcopy(cfg["providers"][0])
    primary.pop("models")
    backup = copy.deepcopy(primary)
    backup["id"] = str(uuid.uuid4())
    backup["model"] = "glm-4.1v-thinking-flash"
    backup["name"] = "智谱 GLM-4.1V-Thinking-Flash"
    cfg["providers"] = [primary, backup]
    cfg["defaults_revision"] = 2
    path = app_env["roaming"] / "VisionMCP" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    upgraded = load_config(create=True)

    assert upgraded["defaults_revision"] == 6
    assert len(upgraded["providers"]) == 2
    assert [provider["id"] for provider in upgraded["providers"]] == [primary["id"], backup["id"]]
    assert all(provider["credential_ids"] == [provider["id"]] for provider in upgraded["providers"])
    assert all(provider["models"]["vision"] == [
        "glm-4.6v-flash", "glm-4.1v-thinking-flash"
    ] for provider in upgraded["providers"])
    assert len(load_config(create=True)["providers"]) == 2


def test_v4_multi_key_group_is_split_into_provider_groups(app_env):
    cfg = default_config()
    provider = cfg["providers"][0]
    backup_id = str(uuid.uuid4())
    provider["credential_ids"] = [provider["id"], backup_id]
    cfg["defaults_revision"] = 4
    path = app_env["roaming"] / "VisionMCP" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    upgraded = load_config(create=True)

    assert upgraded["defaults_revision"] == 6
    assert [item["id"] for item in upgraded["providers"]] == [provider["id"], backup_id]
    assert all(item["credential_ids"] == [item["id"]] for item in upgraded["providers"])


def test_invalid_url_does_not_replace_existing(app_env):
    cfg = default_config()
    save_config(cfg)
    path = app_env["roaming"] / "VisionMCP" / "config.json"
    before = path.read_bytes()
    cfg["providers"][0]["api_base"] = "http://unsafe.example"
    with pytest.raises(ValueError):
        save_config(cfg)
    assert path.read_bytes() == before


def test_corrupt_config_is_reported(app_env):
    path = app_env["roaming"] / "VisionMCP" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError, match="无法读取"):
        load_config()


def test_same_provider_endpoint_is_allowed_with_separate_credentials(app_env):
    cfg = default_config()
    duplicate = copy.deepcopy(cfg["providers"][0])
    duplicate["id"] = str(uuid.uuid4())
    duplicate["credential_ids"] = [duplicate["id"]]
    cfg["providers"].append(duplicate)

    save_config(cfg)
    loaded = load_config()
    assert len(loaded["providers"]) == 2
    assert loaded["providers"][0]["id"] != loaded["providers"][1]["id"]
    assert loaded["providers"][0]["credential_ids"] != loaded["providers"][1]["credential_ids"]


def test_provider_rejects_duplicate_models_across_capabilities(app_env):
    cfg = default_config()
    cfg["providers"][0]["models"]["image_generation"] = ["glm-4.6v-flash"]
    with pytest.raises(ValueError, match="不能跨能力重复"):
        save_config(cfg)


def test_v2_upgrade_preserves_custom_zhipu_vision_model(app_env):
    cfg = default_config()
    provider = copy.deepcopy(cfg["providers"][0])
    provider.pop("models")
    provider["model"] = "user-custom-vision"
    cfg["providers"] = [provider]
    cfg["defaults_revision"] = 2
    path = app_env["roaming"] / "VisionMCP" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    upgraded = load_config()

    assert upgraded["providers"][0]["models"]["vision"] == [
        "user-custom-vision", "glm-4.6v-flash", "glm-4.1v-thinking-flash"
    ]
