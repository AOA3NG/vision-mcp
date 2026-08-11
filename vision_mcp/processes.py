from __future__ import annotations

import os
import subprocess
from typing import Any


def isolated_subprocess_kwargs(*, hide_window: bool = True) -> dict[str, Any]:
    """Return safe options for launching a child process from a frozen app.

    PyInstaller executables export their extraction directory to child
    processes.  A separately frozen child (the server, maintenance manager or
    uninstaller) must reset that environment or it may try to load Python from
    the parent's already removed temporary directory.
    """
    env = os.environ.copy()
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    options: dict[str, Any] = {"env": env}
    if hide_window and os.name == "nt":
        options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    return options
