"""Shared pytest fixtures.

Keep test-generated artifacts inside pytest's temporary directories instead of
the repository root (plan v1.0.1, D16 / T1.4). Historical tests write to
relative paths such as ``tests_tmp/<name>``; chdir-ing each test into its own
``tmp_path`` keeps that code untouched while still isolating the workspace.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
