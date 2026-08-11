from __future__ import annotations

import sys

import vision_manager
from vision_mcp import cli


def test_maintenance_mode_runs_cli_without_opening_manager(monkeypatch):
    calls: list[list[str]] = []

    monkeypatch.setattr(cli, "main", lambda args: calls.append(args) or 7)
    monkeypatch.setattr(
        sys,
        "argv",
        ["Vision MCP 管理器.exe", "--maintenance", "agent", "status", "all"],
    )

    assert vision_manager.main() == 7
    assert calls == [["agent", "status", "all"]]


def test_cli_print_is_safe_without_console(monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)

    cli._print_json({"ok": True})
