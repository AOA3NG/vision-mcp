from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _minimum_release_tree(root: Path) -> None:
    (root / "vision_mcp").mkdir(parents=True)
    (root / "packaging").mkdir(parents=True)
    (root / "pyproject.toml").write_text('[project]\nversion = "1.0.0"\n', encoding="utf-8")
    (root / "vision_mcp" / "__init__.py").write_text('__version__ = "1.0.0"\n', encoding="utf-8")
    (root / "packaging" / "installer.iss").write_text('#define MyAppVersion "1.0.0"\n', encoding="utf-8")


def test_publication_check_rejects_nested_build_and_env_files(tmp_path):
    root = tmp_path / "publication"
    _minimum_release_tree(root)
    nested = root / "design" / "build"
    nested.mkdir(parents=True)
    (nested / "keys.txt").write_text("private material", encoding="utf-8")
    (root / "design" / ".env.local").write_text("TOKEN=secret", encoding="utf-8")
    script = Path(__file__).resolve().parents[1] / "scripts" / "release_check.py"

    result = subprocess.run(
        [sys.executable, str(script), "--publication-root", str(root)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )

    assert result.returncode == 1
    assert "design\\build\\keys.txt" in result.stderr
    assert "design\\.env.local" in result.stderr


def test_source_manifest_is_explicit_complete_and_safe():
    root = Path(__file__).resolve().parents[1]
    manifest_path = root / "packaging" / "source-manifest.txt"
    entries = [
        line.strip() for line in manifest_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]

    assert len(entries) == len(set(entries))
    assert "packaging/source-manifest.txt" in entries
    assert all(not Path(entry).is_absolute() and ".." not in Path(entry).parts for entry in entries)
    assert all((root / Path(entry)).is_file() for entry in entries)
    assert all(not {"build", "dist", "dist-installer", "__pycache__"}.intersection(Path(entry).parts) for entry in entries)

    package_script = (root / "packaging" / "package-source.ps1").read_text(encoding="utf-8")
    assert "source-manifest.txt" in package_script
    assert "Copy-Item -LiteralPath $source" in package_script
    assert "Copy-Item -LiteralPath $source -Destination $destination -Recurse" not in package_script
