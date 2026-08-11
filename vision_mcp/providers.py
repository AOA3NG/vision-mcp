from __future__ import annotations

import base64
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from .config import provider_models
from .credentials import get_provider_keys

RETRYABLE_HTTP = {429, 500, 502, 503, 504}
MAX_PROVIDER_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_PROVIDER_REQUEST_BYTES = 16 * 1024 * 1024
MAX_CHAIN_ATTEMPTS = 12
MAX_CHAIN_SECONDS = 240


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Never forward credentials or media to a redirect target."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_URL_OPENER = urllib.request.build_opener(_NoRedirectHandler())


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False, credential_related: bool = False):
        super().__init__(message)
        self.retryable = retryable
        self.credential_related = credential_related


class _AttemptBudget:
    def __init__(self, timeout: float):
        self.remaining = MAX_CHAIN_ATTEMPTS
        self.deadline = time.monotonic() + min(float(timeout), MAX_CHAIN_SECONDS)

    def claim(self) -> None:
        if self.remaining <= 0 or time.monotonic() >= self.deadline:
            raise ProviderError("本次请求的备用尝试次数已用完，请检查配置或稍后重试")
        self.remaining -= 1

    def timeout(self, configured: float) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ProviderError("本次请求已达到总等待时间上限")
        return min(float(configured), remaining)


def _provider_key(provider: dict) -> str:
    value = str(provider.get("_runtime_api_key", ""))
    if value:
        return value
    values = get_provider_keys(provider)
    return values[0] if values else ""


def _call_with_provider_keys(provider: dict, operation, budget: _AttemptBudget):
    """Try credential slots in order without putting a secret into persisted config."""
    keys = get_provider_keys(provider)
    if not keys:
        raise ProviderError("未配置 API Key", retryable=True)
    last_error: ProviderError | None = None
    for key in keys:
        budget.claim()
        current = dict(provider)
        current["_runtime_api_key"] = key
        current["_runtime_deadline"] = budget.deadline
        try:
            return operation(current)
        except ProviderError as exc:
            last_error = exc
            if not (exc.retryable or exc.credential_related):
                raise
    assert last_error is not None
    raise last_error


def _safe_http_error(code: int, body: bytes = b"") -> str:
    try:
        value = json.loads(body.decode("utf-8", "replace")) if body else {}
        error = value.get("error", value) if isinstance(value, dict) else {}
        upstream_code = str(error.get("code", "")) if isinstance(error, dict) else ""
    except (AttributeError, TypeError, json.JSONDecodeError):
        upstream_code = ""
    if upstream_code == "1302":
        return "账号请求频率受限，请降低并发或稍后重试"
    if upstream_code == "1305":
        return "智谱模型当前访问量过大，请稍后再试"
    labels = {400: "请求参数或模型配置无效", 401: "API Key 无效", 403: "API Key 无权限", 404: "API 地址或模型不存在", 429: "请求频率受限，请稍后重试"}
    return labels.get(code, f"上游服务返回 HTTP {code}")


def _request_timeout(timeout: float, deadline: float | None) -> float:
    if not deadline:
        return float(timeout)
    remaining = float(deadline) - time.monotonic()
    if remaining <= 0:
        raise ProviderError("本次请求已达到总等待时间上限")
    return min(float(timeout), remaining)


def _retry_pause(attempt: int, deadline: float | None) -> None:
    delay = float(1 << attempt)
    if deadline:
        remaining = float(deadline) - time.monotonic()
        if remaining <= 0:
            raise ProviderError("本次请求已达到总等待时间上限")
        delay = min(delay, remaining)
    time.sleep(delay)


def _post(
    url: str, headers: dict, body: dict, timeout: float, attempts: int = 2,
    deadline: float | None = None,
) -> dict:
    encoded_body = json.dumps(body, ensure_ascii=False).encode("utf-8")
    if len(encoded_body) > MAX_PROVIDER_REQUEST_BYTES:
        raise ProviderError("发送给模型的请求内容过大")
    for attempt in range(attempts):
        req = urllib.request.Request(
            url, data=encoded_body, headers=headers, method="POST"
        )
        try:
            with _URL_OPENER.open(req, timeout=_request_timeout(timeout, deadline)) as response:
                content_length = response.headers.get("Content-Length")
                if content_length:
                    try:
                        if int(content_length) > MAX_PROVIDER_RESPONSE_BYTES:
                            raise ProviderError("上游响应过大，已停止读取")
                    except ValueError:
                        pass
                raw = response.read(MAX_PROVIDER_RESPONSE_BYTES + 1)
                if len(raw) > MAX_PROVIDER_RESPONSE_BYTES:
                    raise ProviderError("上游响应过大，已停止读取")
                return json.loads(raw.decode("utf-8"))
        except ProviderError:
            raise
        except urllib.error.HTTPError as exc:
            retryable = exc.code in RETRYABLE_HTTP
            if retryable and attempt + 1 < attempts:
                _retry_pause(attempt, deadline)
                continue
            raise ProviderError(
                _safe_http_error(exc.code, exc.read(65536)),
                retryable=retryable,
                credential_related=exc.code in (401, 403),
            ) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            if attempt + 1 < attempts:
                _retry_pause(attempt, deadline)
                continue
            raise ProviderError("网络连接或请求超时", retryable=True) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderError("上游返回了无法解析的响应") from exc
    raise ProviderError("请求失败", retryable=True)


def _get(
    url: str, headers: dict, timeout: float, attempts: int = 2,
    deadline: float | None = None,
) -> dict:
    for attempt in range(attempts):
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with _URL_OPENER.open(req, timeout=_request_timeout(timeout, deadline)) as response:
                raw = response.read(MAX_PROVIDER_RESPONSE_BYTES + 1)
                if len(raw) > MAX_PROVIDER_RESPONSE_BYTES:
                    raise ProviderError("上游响应过大，已停止读取")
                return json.loads(raw.decode("utf-8"))
        except ProviderError:
            raise
        except urllib.error.HTTPError as exc:
            retryable = exc.code in RETRYABLE_HTTP
            if retryable and attempt + 1 < attempts:
                _retry_pause(attempt, deadline)
                continue
            raise ProviderError(
                _safe_http_error(exc.code, exc.read(65536)),
                retryable=retryable,
                credential_related=exc.code in (401, 403),
            ) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            if attempt + 1 < attempts:
                _retry_pause(attempt, deadline)
                continue
            raise ProviderError("网络连接或请求超时", retryable=True) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderError("上游返回了无法解析的响应") from exc
    raise ProviderError("请求失败", retryable=True)


def _openai(provider: dict, images: list[tuple[str, bytes]], prompt: str, output_format: str, timeout: float) -> str:
    key = _provider_key(provider)
    if not key:
        raise ProviderError("未配置 API Key", retryable=True)

    def request(fmt: str) -> str:
        content = [{"type": "text", "text": prompt}]
        for mime, payload in images:
            encoded = base64.b64encode(payload).decode("ascii")
            url = encoded if fmt == "base64" else f"data:{mime};base64,{encoded}"
            content.append({"type": "image_url", "image_url": {"url": url}})
        body = {
            "model": provider["model"],
            "messages": [{"role": "user", "content": content}],
            "max_tokens": 2048,
        }
        if output_format == "json":
            body["response_format"] = {"type": "json_object"}
        result = _post(
            provider["api_base"].rstrip("/") + "/chat/completions",
            {"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
            body,
            timeout,
            deadline=provider.get("_runtime_deadline"),
        )
        try:
            return result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("上游响应缺少模型输出") from exc

    fmt = provider.get("image_format", "auto")
    try:
        return request("base64" if fmt == "base64" else "data_uri")
    except ProviderError as first:
        if fmt != "auto" or first.retryable or "参数" not in str(first):
            raise
        return request("base64")


def _anthropic(provider: dict, images: list[tuple[str, bytes]], prompt: str, timeout: float) -> str:
    key = _provider_key(provider)
    if not key:
        raise ProviderError("未配置 API Key", retryable=True)
    content = [{"type": "text", "text": prompt}]
    for mime, payload in images:
        content.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": base64.b64encode(payload).decode("ascii")}})
    result = _post(
        provider["api_base"].rstrip("/") + "/v1/messages",
        {"Content-Type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"},
        {"model": provider["model"], "max_tokens": 2048, "messages": [{"role": "user", "content": content}]},
        timeout,
        deadline=provider.get("_runtime_deadline"),
    )
    try:
        return "".join(item.get("text", "") for item in result["content"] if item.get("type") == "text")
    except (KeyError, TypeError) as exc:
        raise ProviderError("上游响应缺少模型输出") from exc


def _openai_video(
    provider: dict,
    video_url: str,
    prompt: str,
    output_format: str,
    timeout: float,
    fps: float,
) -> str:
    key = _provider_key(provider)
    if not key:
        raise ProviderError("未配置 API Key", retryable=True)
    video: dict = {"type": "video_url", "video_url": {"url": video_url}}
    if provider.get("preset_id") == "bailian":
        video["fps"] = fps
    body = {
        "model": provider["model"],
        "messages": [{"role": "user", "content": [video, {"type": "text", "text": prompt}]}],
        "max_tokens": 2048,
    }
    if output_format == "json":
        body["response_format"] = {"type": "json_object"}
    result = _post(
        provider["api_base"].rstrip("/") + "/chat/completions",
        {"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        body,
        timeout,
        deadline=provider.get("_runtime_deadline"),
    )
    try:
        return result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError("上游响应缺少模型输出") from exc


def _provider_for_model(provider: dict, model: str) -> dict:
    value = dict(provider)
    value["model"] = model
    return value


def _validated_media_url(value: object, label: str) -> str:
    url = str(value or "").strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or len(url) > 8192:
        raise ProviderError(f"上游响应缺少有效的{label}地址")
    return url


def _zhipu_generate_image(provider: dict, prompt: str, size: str, timeout: float) -> dict:
    key = _provider_key(provider)
    if not key:
        raise ProviderError("未配置 API Key", retryable=True)
    result = _post(
        provider["api_base"].rstrip("/") + "/images/generations",
        {"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        {"model": provider["model"], "prompt": prompt, "size": size},
        timeout,
        deadline=provider.get("_runtime_deadline"),
    )
    try:
        url = _validated_media_url(result["data"][0]["url"], "图片")
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError("上游响应缺少图片输出") from exc
    return {"model": provider["model"], "url": url}


def _zhipu_generate_video(
    provider: dict,
    prompt: str,
    size: str,
    duration: int,
    fps: int,
    quality: str,
    image_url: str,
    timeout: float,
) -> dict:
    key = _provider_key(provider)
    if not key:
        raise ProviderError("未配置 API Key", retryable=True)
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    body: dict = {
        "model": provider["model"],
        "prompt": prompt,
        "quality": quality,
        "size": size,
        "duration": duration,
        "fps": fps,
        "watermark_enabled": True,
    }
    if image_url:
        body["image_url"] = image_url
    submitted = _post(
        provider["api_base"].rstrip("/") + "/videos/generations",
        headers,
        body,
        min(timeout, 60),
        deadline=provider.get("_runtime_deadline"),
    )
    task_id = str(submitted.get("id", "")).strip()
    if not task_id or len(task_id) > 200:
        raise ProviderError("上游响应缺少视频任务 ID")
    deadline = time.monotonic() + timeout
    result_url = provider["api_base"].rstrip("/") + "/async-result/" + urllib.parse.quote(task_id, safe="")
    while time.monotonic() < deadline:
        result = _get(
            result_url,
            {"Authorization": f"Bearer {key}"},
            min(30, max(1, deadline - time.monotonic())),
            deadline=min(deadline, float(provider.get("_runtime_deadline") or deadline)),
        )
        status = str(result.get("task_status", "")).upper()
        videos = result.get("video_result")
        if isinstance(videos, list) and videos:
            video = videos[0]
            return {
                "model": provider["model"],
                "url": _validated_media_url(video.get("url"), "视频"),
                "cover_image_url": _validated_media_url(video.get("cover_image_url"), "封面图片")
                if video.get("cover_image_url") else "",
            }
        if status in ("FAIL", "FAILED"):
            raise ProviderError("视频生成失败")
        time.sleep(min(3, max(0.1, deadline - time.monotonic())))
    raise ProviderError("视频生成等待超时，任务可能仍在上游处理中", retryable=True)


def call_image_generation_chain(cfg: dict, prompt: str, size: str, provider_id: str | None = None) -> dict:
    providers = [p for p in cfg["providers"] if p.get("enabled", True) and (not provider_id or p["id"] == provider_id)]
    errors: list[str] = []
    budget = _AttemptBudget(cfg["timeout"])
    for provider in providers:
        for model in provider_models(provider, "image_generation"):
            current = _provider_for_model(provider, model)
            try:
                if provider.get("preset_id") != "zhipu":
                    raise ProviderError("当前服务商尚未接入图片生成协议", retryable=True)
                return _call_with_provider_keys(
                    current,
                    lambda keyed: _zhipu_generate_image(keyed, prompt, size, budget.timeout(cfg["timeout"])),
                    budget,
                )
            except ProviderError as exc:
                errors.append(f"{provider['name']} / {model}: {exc}")
                if not (exc.retryable or exc.credential_related):
                    raise ProviderError(errors[-1]) from exc
    if not errors:
        raise ProviderError("没有启用的图片生成模型")
    raise ProviderError("；".join(errors))


def call_video_generation_chain(
    cfg: dict,
    prompt: str,
    size: str,
    duration: int,
    fps: int,
    quality: str,
    image_url: str = "",
    provider_id: str | None = None,
) -> dict:
    providers = [p for p in cfg["providers"] if p.get("enabled", True) and (not provider_id or p["id"] == provider_id)]
    errors: list[str] = []
    budget = _AttemptBudget(cfg["timeout"])
    for provider in providers:
        for model in provider_models(provider, "video_generation"):
            current = _provider_for_model(provider, model)
            try:
                if provider.get("preset_id") != "zhipu":
                    raise ProviderError("当前服务商尚未接入视频生成协议", retryable=True)
                return _call_with_provider_keys(
                    current,
                    lambda keyed: _zhipu_generate_video(
                        keyed, prompt, size, duration, fps, quality, image_url, budget.timeout(cfg["timeout"])
                    ),
                    budget,
                )
            except ProviderError as exc:
                errors.append(f"{provider['name']} / {model}: {exc}")
                if not (exc.retryable or exc.credential_related):
                    raise ProviderError(errors[-1]) from exc
    if not errors:
        raise ProviderError("没有启用的视频生成模型")
    raise ProviderError("；".join(errors))


def call_chain(cfg: dict, images: list[tuple[str, bytes]], prompt: str, output_format: str, provider_id: str | None = None) -> str:
    providers = [p for p in cfg["providers"] if p.get("enabled", True) and (not provider_id or p["id"] == provider_id)]
    if not providers:
        raise ProviderError("没有启用的模型提供商")
    errors: list[str] = []
    budget = _AttemptBudget(cfg["timeout"])
    for provider in providers:
        for model in provider_models(provider, "vision"):
            current = _provider_for_model(provider, model)
            try:
                if provider["api_protocol"] == "anthropic":
                    value = _call_with_provider_keys(
                        current,
                        lambda keyed: _anthropic(keyed, images, prompt, budget.timeout(cfg["timeout"])),
                        budget,
                    )
                else:
                    value = _call_with_provider_keys(
                        current,
                        lambda keyed: _openai(
                            keyed, images, prompt, output_format, budget.timeout(cfg["timeout"])
                        ),
                        budget,
                    )
                if output_format == "json":
                    parsed = json.loads(value)
                    if not isinstance(parsed, dict):
                        raise ProviderError("模型没有返回 JSON 对象")
                    return json.dumps(parsed, ensure_ascii=False)
                return value
            except ProviderError as exc:
                errors.append(f"{provider['name']} / {model}: {exc}")
                if not (exc.retryable or exc.credential_related):
                    raise ProviderError(errors[-1]) from exc
    raise ProviderError("；".join(errors))


def call_video_chain(
    cfg: dict,
    video_url: str,
    prompt: str,
    output_format: str,
    fps: float,
    provider_id: str | None = None,
) -> str:
    providers = [p for p in cfg["providers"] if p.get("enabled", True) and (not provider_id or p["id"] == provider_id)]
    if not providers:
        raise ProviderError("没有启用的模型提供商")
    errors: list[str] = []
    budget = _AttemptBudget(cfg["timeout"])
    for provider in providers:
        for model in provider_models(provider, "vision"):
            current = _provider_for_model(provider, model)
            try:
                if provider["api_protocol"] != "openai":
                    raise ProviderError("当前协议不支持视频输入", retryable=True)
                value = _call_with_provider_keys(
                    current,
                    lambda keyed: _openai_video(
                        keyed, video_url, prompt, output_format, budget.timeout(cfg["timeout"]), fps
                    ),
                    budget,
                )
                if output_format == "json":
                    parsed = json.loads(value)
                    if not isinstance(parsed, dict):
                        raise ProviderError("模型没有返回 JSON 对象")
                    return json.dumps(parsed, ensure_ascii=False)
                return value
            except (json.JSONDecodeError, ProviderError) as exc:
                if isinstance(exc, json.JSONDecodeError):
                    exc = ProviderError("模型没有返回有效 JSON 对象")
                errors.append(f"{provider['name']} / {model}: {exc}")
                if not (exc.retryable or exc.credential_related):
                    raise ProviderError(errors[-1]) from exc
    raise ProviderError("；".join(errors))
