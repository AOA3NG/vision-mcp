from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from . import __version__
from . import agents as agent_ops
from .config import load_config, save_config, validate_config
from .credentials import get_key, migrate_legacy, purge_all, purge_legacy_data
from .service import _run, configure_tool_availability, enabled_generation_tools, mcp
from .logging_setup import redact_text, setup_logging


def _print_json(value: object, *, indent: int | None = None) -> None:
    """Write deterministic UTF-8 JSON even when a Windows GUI parent has no console."""
    data = (json.dumps(value, ensure_ascii=False, indent=indent) + "\n").encode("utf-8")
    stdout = getattr(sys, "stdout", None)
    if stdout is None:
        return
    stream = getattr(stdout, "buffer", None)
    if stream is not None:
        stream.write(data)
        stream.flush()
    else:  # pragma: no cover - StringIO and unusual embedded runtimes
        stdout.write(data.decode("utf-8"))


def server_executable() -> str:
    override = os.environ.get("VISION_MCP_SERVER")
    if override:
        return str(Path(override).resolve())
    if getattr(sys, "frozen", False):
        filename = "vision-mcp-server.exe" if os.name == "nt" else "vision-mcp-server"
        return str(Path(sys.executable).with_name(filename))
    return str(Path(__file__).resolve().parents[1] / "vision_server.py")


def check_config() -> int:
    cfg = load_config(create=True)
    validate_config(cfg)
    migrate_legacy(cfg)
    enabled = [p for p in cfg["providers"] if p.get("enabled", True)]
    with_key = sum(bool(get_key(p["id"])) for p in enabled)
    _print_json({"ok": True, "providers": len(cfg["providers"]), "enabled": len(enabled), "with_key": with_key})
    return 0 if enabled and with_key else 2


def self_test(provider_id: str | None) -> int:
    cfg = load_config()
    with tempfile.TemporaryDirectory(prefix="vision-mcp-test-") as folder:
        path = Path(folder) / "test.png"
        image = Image.new("RGB", (480, 240), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((40, 40, 440, 200), fill="#4a90d9")
        draw.text((150, 105), "VISION MCP", fill="white")
        image.save(path)
        try:
            result = _run([str(path)], "一句话说明图片中的颜色和文字。", "brief", "text", provider_id)
        except Exception as exc:
            _print_json({"ok": False, "error": str(exc)})
            return 1
    _print_json({"ok": True, "result": result[:500]})
    return 0


async def _protocol_test() -> int:
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    server = server_executable()
    if server.endswith(".py"):
        transport = StdioTransport(command=sys.executable, args=[server, "stdio"])
    else:
        transport = StdioTransport(command=server, args=["stdio"])
    try:
        async with Client(transport) as client:
            tools = await client.list_tools()
    except Exception as exc:
        _print_json({"ok": False, "error": str(exc)})
        return 1
    names = sorted(tool.name for tool in tools)
    expected = [
        "analyze_clipboard_image", "analyze_document", "analyze_image", "analyze_images", "analyze_ui", "analyze_video",
        "compare_images", "extract_text", "get_config", "locate_objects",
    ]
    expected.extend(enabled_generation_tools(load_config()))
    expected = sorted(expected)
    ok = names == expected
    _print_json({"ok": ok, "tools": names})
    return 0 if ok else 1


def _agent_command(args) -> int:
    server = str(Path(args.server or server_executable()).resolve())
    keys = list(agent_ops.agents()) if args.name == "all" else [args.name]
    result = {}
    failed = False
    for key in keys:
        try:
            if args.action == "configure":
                backup = agent_ops.configure_preferred(key, server)
                result[key] = {"status": "configured", "backup": str(backup) if backup else None}
            elif args.action == "remove":
                backup = agent_ops.remove(key, server)
                result[key] = {"status": "removed" if backup else "unchanged", "backup": str(backup) if backup else None}
            else:
                result[key] = {"status": agent_ops.status(key, server)}
        except Exception as exc:
            failed = True
            result[key] = {"status": "error", "error": redact_text(exc, 500)}
    _print_json(result, indent=2)
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    setup_logging("server")
    parser = argparse.ArgumentParser(prog="vision-mcp-server")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("stdio")
    sub.add_parser("check-config")
    sub.add_parser("protocol-test", help=argparse.SUPPRESS)
    sub.add_parser("purge-data", help=argparse.SUPPRESS)
    test_parser = sub.add_parser("self-test")
    test_parser.add_argument("--provider")
    agent_parser = sub.add_parser("agent")
    agent_parser.add_argument("action", choices=["configure", "remove", "status"])
    agent_parser.add_argument("name", choices=[*agent_ops.agents().keys(), "all"])
    agent_parser.add_argument("--server")
    args = parser.parse_args(argv)
    if args.command == "stdio":
        configure_tool_availability(mcp, load_config())
        mcp.run(transport="stdio")
        return 0
    if args.command == "check-config":
        return check_config()
    if args.command == "self-test":
        return self_test(args.provider)
    if args.command == "protocol-test":
        return asyncio.run(_protocol_test())
    if args.command == "purge-data":
        cfg = load_config()
        count = purge_all(cfg)
        legacy_count = purge_legacy_data()
        _print_json({"ok": True, "credentials_removed": count, "legacy_files_removed": legacy_count})
        return 0
    return _agent_command(args)


if __name__ == "__main__":
    raise SystemExit(main())
