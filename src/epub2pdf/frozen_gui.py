"""Frozen GUI entry point for PyInstaller builds.

This deliberately bypasses ``run.py``. The launcher in ``run.py`` contains
source-development fallback logic that probes local Python interpreters when
PySide6 import checks fail; that behavior is useful from source but unsafe in
a bundled executable.
"""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

_DLL_DIR_HANDLES = []


def _log_path() -> Path:
    for base in (os.environ.get("LOCALAPPDATA"), os.environ.get("TEMP"), "."):
        if not base:
            continue
        try:
            path = Path(base) / "EpubToPdf"
            path.mkdir(parents=True, exist_ok=True)
            return path / "startup.log"
        except Exception:
            continue
    return Path("startup.log")


def _append_log(message: str) -> None:
    try:
        with _log_path().open("a", encoding="utf-8") as f:
            f.write(message + "\n")
    except Exception:
        pass


def _prepare_dll_paths() -> None:
    """Make PySide6 and shiboken6 DLLs discoverable in frozen builds."""
    base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    candidates = [
        base,
        base / "PySide6",
        base / "shiboken6",
    ]
    existing = [str(path) for path in candidates if path.is_dir()]
    if not existing:
        return

    os.environ["PATH"] = os.pathsep.join(existing + [os.environ.get("PATH", "")])
    add_dll_directory = getattr(os, "add_dll_directory", None)
    if add_dll_directory is not None:
        for path in existing:
            try:
                _DLL_DIR_HANDLES.append(add_dll_directory(path))
            except OSError:
                pass


if __name__ == "__main__":
    try:
        _append_log("frozen_gui: starting")
        _prepare_dll_paths()
        _append_log("frozen_gui: dll paths prepared")
        if "--cli" in sys.argv:
            sys.argv.remove("--cli")
            from epub2pdf.cli import main as cli_main

            _append_log("frozen_gui: running CLI")
            raise SystemExit(cli_main())
        from epub2pdf.app import main

        _append_log("frozen_gui: imported app main")
        raise SystemExit(main())
    except Exception:
        try:
            _append_log(traceback.format_exc())
        except Exception:
            pass
        raise
