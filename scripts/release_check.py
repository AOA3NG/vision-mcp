from __future__ import annotations

import re
import os
import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {
    ".git", ".venv", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "__pycache__", "build", "dist", "dist-installer",
}
TEXT_SUFFIXES = {
    ".css", ".html", ".ini", ".iss", ".js", ".json", ".md",
    ".ps1", ".py", ".toml", ".txt", ".yaml", ".yml",
}
FORBIDDEN_FILES = {".env", "config.json", "keys.json", "keys.json.migrated.bak"}
SENSITIVE_SUFFIXES = {".p12", ".pem", ".pfx", ".key", ".snk", ".cer", ".crt"}
FORBIDDEN_SUFFIXES = {".log", ".sqlite", ".db"}
CONTENT_RULES = {
    "Windows 用户目录": re.compile(r"(?i)[A-Z]:\\Users\\[^\\\s`]+"),
    "macOS 用户目录": re.compile("/" + r"Users/[^/\s`]+"),
    "Linux 用户目录": re.compile("/" + r"home/[^/\s`]+"),
    "智谱格式 API Key": re.compile(r"\b[0-9a-fA-F]{32}\.[A-Za-z0-9_-]{16,}\b"),
    "OpenAI 格式 API Key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    "私钥正文": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}


def source_files(root: Path, *, publication: bool = False) -> list[Path]:
    found: list[Path] = []
    for folder, dirnames, filenames in os.walk(root):
        if not publication:
            dirnames[:] = [name for name in dirnames if name not in EXCLUDED_PARTS]
        found.extend(Path(folder) / name for name in filenames)
    return found


def read_text(path: Path) -> str | None:
    if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {"LICENSE", ".gitignore", ".gitattributes", ".editorconfig"}:
        return None
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return None


def version_errors(root: Path) -> list[str]:
    expected = re.search(r'^version = "([^"]+)"', (root / "pyproject.toml").read_text(encoding="utf-8"), re.MULTILINE)
    package = re.search(r'^__version__ = "([^"]+)"', (root / "vision_mcp" / "__init__.py").read_text(encoding="utf-8"), re.MULTILINE)
    installer = re.search(r'^#define MyAppVersion "([^"]+)"', (root / "packaging" / "installer.iss").read_text(encoding="utf-8-sig"), re.MULTILINE)
    values = [match.group(1) if match else "<missing>" for match in (expected, package, installer)]
    return [] if len(set(values)) == 1 else [f"版本不一致: pyproject/package/installer = {values}"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--publication-root", type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.publication_root.resolve()
    errors = version_errors(root)
    publication = root != ROOT.resolve()
    for path in source_files(root, publication=publication):
        relative = path.relative_to(root)
        lowered_parts = {part.lower() for part in relative.parts[:-1]}
        if publication and lowered_parts.intersection(EXCLUDED_PARTS):
            errors.append(f"发布目录包含缓存或构建产物: {relative}")
            continue
        lowered_name = path.name.lower()
        if (
            lowered_name in FORBIDDEN_FILES
            or lowered_name.startswith(".env.")
            or path.suffix.lower() in SENSITIVE_SUFFIXES
            or path.suffix.lower() in FORBIDDEN_SUFFIXES
        ):
            errors.append(f"禁止发布的文件: {relative}")
        text = read_text(path)
        if text is None:
            continue
        for label, pattern in CONTENT_RULES.items():
            match = pattern.search(text)
            if match:
                line = text.count("\n", 0, match.start()) + 1
                errors.append(f"{label}: {relative}:{line}")
    if errors:
        print("Open-source release check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Open-source release check passed: no personal paths, credential files, or known key patterns found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
