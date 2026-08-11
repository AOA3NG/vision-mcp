"""Compatibility smoke-test entry point."""

from vision_mcp.cli import self_test


if __name__ == "__main__":
    raise SystemExit(self_test(None))
