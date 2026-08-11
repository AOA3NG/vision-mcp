import json
import urllib.error

import pytest

from vision_mcp import providers
from vision_mcp.providers import (
    MAX_PROVIDER_RESPONSE_BYTES,
    ProviderError,
    _get,
    _openai_video,
    _post,
    _safe_http_error,
    call_chain,
    call_image_generation_chain,
    call_video_generation_chain,
    call_video_chain,
)


def _cfg():
    return {"timeout": 5, "providers": [
        {"id": "1", "name": "主", "enabled": True, "api_protocol": "openai", "api_base": "https://one/v1", "model": "m", "image_format": "data_uri"},
        {"id": "2", "name": "备", "enabled": True, "api_protocol": "openai", "api_base": "https://two/v1", "model": "m", "image_format": "data_uri"},
    ]}


def test_retryable_failure_uses_backup(monkeypatch):
    calls = []
    monkeypatch.setattr("vision_mcp.providers.get_provider_keys", lambda _provider: ["secret"])
    def fake(provider, images, prompt, output_format, timeout):
        calls.append(provider["id"])
        if provider["id"] == "1":
            raise ProviderError("timeout", retryable=True)
        return "ok"
    monkeypatch.setattr("vision_mcp.providers._openai", fake)
    assert call_chain(_cfg(), [("image/png", b"x")], "q", "text") == "ok"
    assert calls == ["1", "2"]


def test_auth_failure_does_not_use_backup(monkeypatch):
    calls = []
    monkeypatch.setattr("vision_mcp.providers.get_provider_keys", lambda _provider: ["secret"])
    def fake(provider, *_args):
        calls.append(provider["id"])
        raise ProviderError("API Key 无效", retryable=False)
    monkeypatch.setattr("vision_mcp.providers._openai", fake)
    with pytest.raises(ProviderError, match="主"):
        call_chain(_cfg(), [("image/png", b"x")], "q", "text")
    assert calls == ["1"]


def test_json_output_must_be_object(monkeypatch):
    monkeypatch.setattr("vision_mcp.providers.get_provider_keys", lambda _provider: ["secret"])
    monkeypatch.setattr("vision_mcp.providers._openai", lambda *_args: "[]")
    with pytest.raises(ProviderError, match="JSON 对象"):
        call_chain(_cfg(), [("image/png", b"x")], "q", "json", provider_id="1")


def test_missing_primary_key_uses_backup(monkeypatch):
    monkeypatch.setattr(
        "vision_mcp.providers.get_provider_keys",
        lambda provider: [] if provider["id"] == "1" else ["secret"],
    )
    monkeypatch.setattr("vision_mcp.providers._post", lambda *_args, **_kwargs: {"choices": [{"message": {"content": "backup"}}]})
    assert call_chain(_cfg(), [("image/png", b"x")], "q", "text") == "backup"


def test_rate_limit_error_includes_actionable_retry_hint():
    assert _safe_http_error(429) == "请求频率受限，请稍后重试"
    assert _safe_http_error(429, b'{"error":{"code":"1302"}}') == "账号请求频率受限，请降低并发或稍后重试"
    assert _safe_http_error(429, b'{"error":{"code":"1305"}}') == "智谱模型当前访问量过大，请稍后再试"


def test_provider_success_response_is_size_limited(monkeypatch):
    class Response:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, limit):
            assert limit == MAX_PROVIDER_RESPONSE_BYTES + 1
            return b"x" * limit

    monkeypatch.setattr("vision_mcp.providers._URL_OPENER.open", lambda *_args, **_kwargs: Response())
    with pytest.raises(ProviderError, match="响应过大"):
        _post("https://example.com", {}, {}, 1, attempts=1)


@pytest.mark.parametrize(("preset_id", "expects_fps"), [("zhipu", False), ("bailian", True)])
def test_video_request_matches_provider_openai_format(monkeypatch, preset_id, expects_fps):
    captured = {}
    provider = {
        "id": "1", "preset_id": preset_id, "api_base": "https://example.com/v1", "model": "vision-model"
    }
    monkeypatch.setattr("vision_mcp.providers.get_provider_keys", lambda _provider: ["secret"])

    def fake_post(url, headers, body, timeout, **_kwargs):
        captured.update({"url": url, "headers": headers, "body": body, "timeout": timeout})
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr("vision_mcp.providers._post", fake_post)

    assert _openai_video(provider, "https://example.com/video.mp4", "分析", "text", 5, 2.0) == "ok"
    video = captured["body"]["messages"][0]["content"][0]
    assert video["type"] == "video_url"
    assert video["video_url"]["url"].endswith("video.mp4")
    assert ("fps" in video) is expects_fps


def test_video_chain_skips_unsupported_protocol(monkeypatch):
    cfg = _cfg()
    cfg["providers"][0]["api_protocol"] = "anthropic"
    monkeypatch.setattr("vision_mcp.providers.get_provider_keys", lambda _provider: ["secret"])
    monkeypatch.setattr("vision_mcp.providers._openai_video", lambda provider, *_args: provider["id"])

    assert call_video_chain(cfg, "https://example.com/video.mp4", "q", "text", 1.0) == "2"


def test_vision_models_fallback_inside_one_provider(monkeypatch):
    cfg = _cfg()
    cfg["providers"] = [cfg["providers"][0]]
    cfg["providers"][0]["models"] = {
        "vision": ["primary", "backup"], "image_generation": [], "video_generation": []
    }
    calls = []
    monkeypatch.setattr("vision_mcp.providers.get_provider_keys", lambda _provider: ["secret"])

    def fake(provider, *_args):
        calls.append(provider["model"])
        if provider["model"] == "primary":
            raise ProviderError("rate limited", retryable=True)
        return "ok"

    monkeypatch.setattr("vision_mcp.providers._openai", fake)
    assert call_chain(cfg, [("image/png", b"x")], "q", "text") == "ok"
    assert calls == ["primary", "backup"]


def test_separate_provider_groups_fall_back_on_invalid_key(monkeypatch):
    cfg = _cfg()
    calls = []
    monkeypatch.setattr(
        "vision_mcp.providers.get_provider_keys",
        lambda provider: ["primary"] if provider["id"] == "1" else ["backup"],
    )

    def fake(provider, *_args):
        calls.append((provider["id"], provider["_runtime_api_key"]))
        if provider["_runtime_api_key"] == "primary":
            raise ProviderError("API Key 无效", credential_related=True)
        return "ok"

    monkeypatch.setattr("vision_mcp.providers._openai", fake)
    assert call_chain(cfg, [("image/png", b"x")], "q", "text") == "ok"
    assert calls == [("1", "primary"), ("2", "backup")]


def test_chain_has_total_attempt_budget(monkeypatch):
    cfg = _cfg()
    cfg["providers"] = [cfg["providers"][0]]
    cfg["providers"][0]["models"] = {
        "vision": [f"model-{index}" for index in range(20)],
        "image_generation": [],
        "video_generation": [],
    }
    calls = []
    monkeypatch.setattr("vision_mcp.providers.get_provider_keys", lambda _provider: ["secret"])

    def fake(provider, *_args):
        calls.append(provider["model"])
        raise ProviderError("暂时不可用", retryable=True)

    monkeypatch.setattr("vision_mcp.providers._openai", fake)
    with pytest.raises(ProviderError, match="备用尝试次数"):
        call_chain(cfg, [("image/png", b"x")], "q", "text")
    assert len(calls) == 12


def test_transport_retry_stops_at_request_deadline(monkeypatch):
    calls = []
    times = iter([0.0, 2.0])
    monkeypatch.setattr("vision_mcp.providers.time.monotonic", lambda: next(times))

    def fail(*_args, **_kwargs):
        calls.append(True)
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("vision_mcp.providers._URL_OPENER.open", fail)
    with pytest.raises(ProviderError, match="总等待时间"):
        _post("https://example.com", {}, {}, 10, deadline=1.0)
    assert len(calls) == 1


def test_provider_redirects_are_not_followed():
    request = providers.urllib.request.Request(
        "https://trusted.example/v1/chat",
        headers={"Authorization": "Bearer secret"},
        data=b"{}",
    )

    assert providers._NoRedirectHandler().redirect_request(
        request, None, 307, "Temporary Redirect", {}, "http://attacker.example/collect"
    ) is None


def test_provider_request_body_is_bounded(monkeypatch):
    monkeypatch.setattr(providers, "MAX_PROVIDER_REQUEST_BYTES", 10)

    with pytest.raises(ProviderError, match="请求内容过大"):
        providers._post("https://example.com", {}, {"prompt": "x" * 100}, 1)


def test_image_generation_uses_configured_capability_model(monkeypatch):
    cfg = _cfg()
    provider = cfg["providers"][0]
    provider["preset_id"] = "zhipu"
    provider["models"] = {
        "vision": ["vision"], "image_generation": ["cogview-3-flash"], "video_generation": []
    }
    captured = {}
    monkeypatch.setattr("vision_mcp.providers.get_provider_keys", lambda _provider: ["secret"])

    def fake_post(url, headers, body, timeout, **_kwargs):
        captured.update(url=url, headers=headers, body=body, timeout=timeout)
        return {"data": [{"url": "https://example.com/generated.png"}]}

    monkeypatch.setattr("vision_mcp.providers._post", fake_post)
    result = call_image_generation_chain(cfg, "橙色圆形", "1024x1024")
    assert result == {"model": "cogview-3-flash", "url": "https://example.com/generated.png"}
    assert captured["url"].endswith("/images/generations")
    assert captured["body"]["model"] == "cogview-3-flash"


def test_video_generation_submits_and_polls_without_background_process(monkeypatch):
    cfg = _cfg()
    cfg["timeout"] = 10
    provider = cfg["providers"][0]
    provider["preset_id"] = "zhipu"
    provider["models"] = {
        "vision": ["vision"], "image_generation": [], "video_generation": ["cogvideox-flash"]
    }
    captured = {}
    monkeypatch.setattr("vision_mcp.providers.get_provider_keys", lambda _provider: ["secret"])

    def fake_post(url, headers, body, timeout, **_kwargs):
        captured.update(url=url, body=body)
        return {"id": "task-1", "task_status": "PROCESSING"}

    monkeypatch.setattr("vision_mcp.providers._post", fake_post)
    monkeypatch.setattr("vision_mcp.providers._get", lambda *_args, **_kwargs: {
        "task_status": "SUCCESS",
        "video_result": [{"url": "https://example.com/result.mp4", "cover_image_url": "https://example.com/cover.jpg"}],
    })
    result = call_video_generation_chain(cfg, "云朵移动", "1280x720", 5, 30, "speed")
    assert result["model"] == "cogvideox-flash"
    assert result["url"].endswith("result.mp4")
    assert captured["url"].endswith("/videos/generations")
    assert captured["body"]["watermark_enabled"] is True
