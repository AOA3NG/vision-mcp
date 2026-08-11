from __future__ import annotations

import base64
import json
from contextlib import contextmanager
from typing import Iterator
from typing import Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from . import __version__
from .clipboard import clipboard_image_path
from .config import load_config, provider_models
from .images import prepare_image
from .media import prepare_video
from .providers import (
    ProviderError,
    call_chain,
    call_image_generation_chain,
    call_video_chain,
    call_video_generation_chain,
)

MCP_INSTRUCTIONS = (
    "当用户提到‘这张图’、‘刚才的截图’或‘剪贴板图片’，但没有提供图片路径或 URL 时，"
    "直接调用最符合意图的图片工具并省略图片来源参数；工具会自动读取 Windows 剪贴板。"
    "界面审查使用 analyze_ui，文字识别使用 extract_text，普通识图使用 analyze_image。"
)
mcp = FastMCP("vision", version=__version__, instructions=MCP_INSTRUCTIONS)

UI_PROMPT = """分析页面截图并只输出 JSON 对象，字段为 layout、components、texts、colors、typography、spacing、notes。components 是包含 type、text、position 的数组。"""
MAX_QUESTION_CHARS = 16_000
MAX_TARGET_CHARS = 500
MAX_PATH_OR_URL_CHARS = 8_192


def _bounded_text(value: str, label: str, limit: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label}必须是文本")
    if len(value) > limit:
        raise ValueError(f"{label}不能超过 {limit} 个字符")
    return value


def enabled_generation_tools(cfg: dict) -> set[str]:
    """Return generation tools that have at least one configured model."""
    enabled: set[str] = set()
    for provider in cfg.get("providers", []):
        if not provider.get("enabled", True):
            continue
        if provider_models(provider, "image_generation"):
            enabled.add("generate_image")
        if provider_models(provider, "video_generation"):
            enabled.add("generate_video")
    return enabled


def configure_tool_availability(server: FastMCP, cfg: dict) -> set[str]:
    """Hide optional tools that cannot succeed with the current configuration."""
    enabled = enabled_generation_tools(cfg)
    for name in ("generate_image", "generate_video"):
        if name not in enabled:
            server.local_provider.remove_tool(name)
    return enabled


def _run(paths: list[str], question: str, detail: str, output_format: str, provider_id: str | None = None) -> str:
    try:
        question = _bounded_text(question, "问题", MAX_QUESTION_CHARS)
        if not 1 <= len(paths) <= 12:
            raise ValueError("每次需要传入 1 到 12 张图片")
        images = [prepare_image(path) for path in paths]
        if sum(len(data) for _mime, data in images) > 8 * 1024 * 1024:
            raise ValueError("图片总大小超过 8MB 请求上限")
        prefix = {"brief": "用一两句话简明回答。", "standard": "", "detailed": "尽可能详尽描述所有可见信息。"}[detail]
        if output_format == "json":
            question = "只输出 JSON 对象，不要 Markdown 代码块。" + question
        return call_chain(load_config(), images, "\n".join(x for x in (prefix, question) if x), output_format, provider_id)
    except (ValueError, ProviderError, OSError) as exc:
        raise ToolError(str(exc)) from exc


@contextmanager
def _resolve_image_sources(paths: list[str] | None) -> Iterator[list[str]]:
    values = list(paths or [""])
    missing = [index for index, value in enumerate(values) if not isinstance(value, str) or not value.strip()]
    if len(missing) > 1:
        raise ValueError("剪贴板一次只能提供一张图片；请为其他图片提供本地路径或 HTTPS 地址")
    if not missing:
        yield values
        return

    with clipboard_image_path() as clipboard_path:
        values[missing[0]] = clipboard_path
        yield values


def _run_with_sources(
    paths: list[str] | None,
    question: str,
    detail: str,
    output_format: str,
    provider_id: str | None = None,
) -> str:
    try:
        with _resolve_image_sources(paths) as resolved:
            return _run(resolved, question, detail, output_format, provider_id)
    except (ValueError, OSError) as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
def analyze_image(image_path: str = "", question: str = "请详细描述这张图片", detail: Literal["brief", "standard", "detailed"] = "standard", output_format: Literal["text", "json"] = "text") -> str:
    """识别图片、截图、图表或照片；未提供 image_path 时自动读取 Windows 剪贴板图片。"""
    return _run_with_sources([image_path], question, detail, output_format)


@mcp.tool()
def analyze_clipboard_image(question: str = "请详细描述剪贴板中的图片", detail: Literal["brief", "standard", "detailed"] = "standard", output_format: Literal["text", "json"] = "text") -> str:
    """读取 Windows 剪贴板中的图片并识别；保留用于兼容已按此工具名调用的 Agent。"""
    return _run_with_sources(None, question, detail, output_format)


@mcp.tool()
def analyze_ui(image_path: str = "", question: str = "", detail: Literal["brief", "standard", "detailed"] = "standard", output_format: Literal["text", "json"] = "json") -> str:
    """分析 UI 截图的布局、组件、文字、颜色、排版和间距；未提供路径时读取剪贴板。"""
    return _run_with_sources([image_path], UI_PROMPT + ("\n额外要求：" + question if question.strip() else ""), detail, output_format)


@mcp.tool()
def extract_text(image_path: str = "") -> str:
    """按阅读顺序原样提取图片中全部可见文字；未提供路径时读取剪贴板。"""
    return _run_with_sources([image_path], "按阅读顺序逐行原样输出全部可见文字，不翻译、不解释。", "standard", "text")


@mcp.tool()
def compare_images(image_path_a: str = "", image_path_b: str = "", question: str = "指出两张图片的差异和共同点", detail: Literal["brief", "standard", "detailed"] = "standard", output_format: Literal["text", "json"] = "text") -> str:
    """比较两张图片；可省略其中一个路径以使用剪贴板，不能同时省略两个路径。"""
    return _run_with_sources([image_path_a, image_path_b], question, detail, output_format)


@mcp.tool()
def analyze_images(image_paths: list[str] | None = None, question: str = "综合分析这些图片", detail: Literal["brief", "standard", "detailed"] = "standard", output_format: Literal["text", "json"] = "text") -> str:
    """通用多图视觉问答；未提供图片列表时读取剪贴板，也可用一个空项表示剪贴板图片。"""
    return _run_with_sources(image_paths, question, detail, output_format)


@mcp.tool()
def analyze_document(image_paths: list[str] | None = None, question: str = "提取并分析文档内容", output_format: Literal["text", "json"] = "text") -> str:
    """分析文档图片；未提供图片列表时读取剪贴板，原始 PDF 需先转为页面图片。"""
    prompt = "按页面顺序理解文档，保留标题、段落、列表、表格和关键数值。" + question
    return _run_with_sources(image_paths, prompt, "detailed", output_format)


@mcp.tool()
def locate_objects(image_path: str = "", target: str = "", include_count: bool = True) -> str:
    """定位指定物体并返回边界框；未提供 image_path 时自动读取剪贴板图片。"""
    try:
        target = _bounded_text(target, "目标", MAX_TARGET_CHARS)
        if not target.strip():
            raise ValueError("目标不能为空")
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    prompt = (
        f"定位图片中的“{target}”。只输出 JSON 对象，字段为 target、count、objects、notes；"
        "objects 数组每项包含 label、bbox、confidence，bbox 为 [x1,y1,x2,y2] 且坐标归一化到 0-1000。"
        + ("必须统计总数。" if include_count else "count 可为 null。")
    )
    return _run_with_sources([image_path], prompt, "detailed", "json")


@mcp.tool()
def analyze_video(video_path_or_url: str, question: str = "描述视频内容和关键事件", fps: float = 1.0, output_format: Literal["text", "json"] = "text") -> str:
    """理解本地小视频或 HTTPS 视频，支持内容问答、摘要、关键事件和时间线分析。"""
    try:
        video_path_or_url = _bounded_text(video_path_or_url, "视频路径或地址", MAX_PATH_OR_URL_CHARS)
        question = _bounded_text(question, "问题", MAX_QUESTION_CHARS)
        if not 0.1 <= fps <= 10:
            raise ValueError("fps 必须在 0.1 到 10 之间")
        video_url = prepare_video(video_path_or_url)
        if output_format == "json":
            question = "只输出 JSON 对象，不要 Markdown 代码块。" + question
        return call_video_chain(load_config(), video_url, question, output_format, fps)
    except (ValueError, ProviderError, OSError) as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
def generate_image(
    prompt: str,
    size: Literal[
        "1024x1024", "768x1344", "864x1152", "1344x768", "1152x864", "1440x720", "720x1440"
    ] = "1024x1024",
) -> str:
    """根据文字描述生成图片，返回包含模型和 HTTPS 图片地址的 JSON。"""
    try:
        prompt = prompt.strip()
        if not prompt:
            raise ValueError("图片提示词不能为空")
        if len(prompt) > 1000:
            raise ValueError("图片提示词不能超过 1000 个字符")
        result = call_image_generation_chain(load_config(), prompt, size)
        return json.dumps(result, ensure_ascii=False)
    except (ValueError, ProviderError, OSError) as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
def generate_video(
    prompt: str,
    image_path_or_url: str = "",
    size: Literal["1280x720", "720x1280", "1024x1024", "1920x1080", "1080x1920"] = "1280x720",
    duration: Literal[5, 10] = 5,
    fps: Literal[30, 60] = 30,
    quality: Literal["speed", "quality"] = "speed",
) -> str:
    """根据文字生成视频；也可传入本地图片或 HTTPS 图片地址进行图生视频，返回结果 URL。"""
    try:
        prompt = prompt.strip()
        if not prompt and not image_path_or_url.strip():
            raise ValueError("视频提示词和参考图片不能同时为空")
        if len(prompt) > 512:
            raise ValueError("视频提示词不能超过 512 个字符")
        image_url = image_path_or_url.strip()
        image_url = _bounded_text(image_url, "参考图片路径或地址", MAX_PATH_OR_URL_CHARS)
        if image_url and not image_url.lower().startswith("https://"):
            mime, data = prepare_image(image_url)
            image_url = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
        result = call_video_generation_chain(
            load_config(), prompt, size, duration, fps, quality, image_url
        )
        return json.dumps(result, ensure_ascii=False)
    except (ValueError, ProviderError, OSError) as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
def get_config() -> str:
    """返回脱敏后的模型备用链状态。"""
    cfg = load_config()
    lines = [f"配置版本: {cfg['version']}", f"请求超时: {cfg['timeout']} 秒", "模型链:"]
    for index, provider in enumerate(cfg["providers"], 1):
        state = "启用" if provider.get("enabled", True) else "停用"
        capabilities = []
        for key, label in (
            ("vision", "视觉理解"),
            ("image_generation", "图片生成"),
            ("video_generation", "视频生成"),
        ):
            values = provider_models(provider, key)
            if values:
                capabilities.append(f"{label}: {', '.join(values)}")
        lines.append(f"{index}. {provider['name']} | {'；'.join(capabilities)} | {provider['api_protocol']} | {state}")
    return "\n".join(lines)
