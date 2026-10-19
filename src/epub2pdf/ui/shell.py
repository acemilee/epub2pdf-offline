"""Tiny OS-shell helpers that stay independent of Qt (unit-testable)."""
from __future__ import annotations

import os
import subprocess
import sys


def open_directory(path: str) -> bool:
    """Open ``path`` in the OS file manager. Returns False if it doesn't exist."""
    if not path or not os.path.isdir(path):
        return False
    try:
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except OSError:
        return False


def reveal_file(path: str) -> bool:
    """Open the folder containing ``path`` (used by completed task rows)."""
    folder = os.path.dirname(os.path.abspath(path))
    return open_directory(folder)
