"""Shared pytest fixtures.

Keep test-generated artifacts inside pytest's temporary directories instead of
the repository root (plan v1.0.1, D16 / T1.4). Historical tests write to
relative paths such as ``tests_tmp/<name>``; chdir-ing each test into its own
``tmp_path`` keeps that code untouched while still isolating the workspace.
"""

from __future__ import annotations

import os

import pytest

# GUI tests must not pop real windows during a test run. Set before PySide6 is
# imported (conftest is loaded before test modules). An explicit environment
# value still wins, so a developer can run tests on a real display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def _isolate_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


@pytest.fixture(scope="session")
def qapp():
    """One offscreen QApplication for all GUI tests."""
    pytest.importorskip("PySide6", reason="PySide6 is needed for GUI tests")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
