"""Application entry point for the GUI."""
from __future__ import annotations

import sys
from pathlib import Path
import os

from PySide6.QtWidgets import QApplication

from .ui.main_window import MainWindow


def _append_startup_log(message: str) -> None:
    try:
        for base in (os.environ.get("LOCALAPPDATA"), os.environ.get("TEMP"), "."):
            if not base:
                continue
            try:
                path = Path(base) / "EpubToPdf"
                path.mkdir(parents=True, exist_ok=True)
                with (path / "startup.log").open("a", encoding="utf-8") as f:
                    f.write(message + "\n")
                return
            except Exception:
                continue
    except Exception:
        pass


def main() -> int:
    _append_startup_log("app: creating QApplication")
    app = QApplication(sys.argv)
    app.setApplicationName("epub2pdf")
    app.setOrganizationName("epub2pdf")
    _append_startup_log("app: constructing MainWindow")
    window = MainWindow()
    _append_startup_log("app: showing MainWindow")
    window.show()
    try:
        _append_startup_log(f"app: shown winId={int(window.winId())} visible={window.isVisible()}")
    except Exception as e:
        _append_startup_log(f"app: shown, winId failed: {e}")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
