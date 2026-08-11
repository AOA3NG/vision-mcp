from __future__ import annotations

from vision_mcp import processes


def test_frozen_child_process_resets_pyinstaller_environment(monkeypatch):
    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", r"C:\stale-parent-temp")

    options = processes.isolated_subprocess_kwargs()

    assert options["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert options["env"]["_PYI_APPLICATION_HOME_DIR"] == r"C:\stale-parent-temp"
    if processes.os.name == "nt":
        assert options["creationflags"] == getattr(
            processes.subprocess, "CREATE_NO_WINDOW", 0x08000000
        )
