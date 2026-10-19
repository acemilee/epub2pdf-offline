"""Unit tests for the Qt-free shell helpers (M1)."""
from __future__ import annotations

from epub2pdf.ui import shell


def test_open_directory_missing_path_returns_false(tmp_path):
    assert shell.open_directory(str(tmp_path / "does-not-exist")) is False
    assert shell.open_directory("") is False


def test_open_directory_invokes_os_startfile(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(shell.sys, "platform", "win32")
    monkeypatch.setattr(shell.os, "startfile", lambda path: calls.append(path), raising=False)
    assert shell.open_directory(str(tmp_path)) is True
    assert calls == [str(tmp_path)]


def test_open_directory_swallows_os_errors(monkeypatch, tmp_path):
    def boom(path):
        raise OSError("no association")

    monkeypatch.setattr(shell.sys, "platform", "win32")
    monkeypatch.setattr(shell.os, "startfile", boom, raising=False)
    assert shell.open_directory(str(tmp_path)) is False


def test_reveal_file_opens_parent_folder(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(shell.sys, "platform", "win32")
    monkeypatch.setattr(shell.os, "startfile", lambda path: calls.append(path), raising=False)
    target = tmp_path / "out.pdf"
    target.write_bytes(b"%PDF")
    assert shell.reveal_file(str(target)) is True
    assert calls == [str(tmp_path)]
