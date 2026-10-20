import shutil
import time
from pathlib import Path

from epub2pdf.ui import main_window
from epub2pdf.core import orchestrator


def test_gui_allows_only_one_conversion_at_a_time_by_default():
    assert main_window.MAX_CONCURRENT_CONVERSIONS == 1


class _FakeSettings:
    """In-memory replacement for QSettings so tests never touch the registry."""

    store: dict[str, object] = {}

    def __init__(self, *_args, **_kwargs):
        self._data = _FakeSettings.store

    def value(self, key, default=""):
        return self._data.get(key, default)

    def setValue(self, key, value):  # noqa: N802 - Qt naming
        self._data[key] = value


def _make_window(qapp, monkeypatch, tmp_path):
    _FakeSettings.store = {"output_dir": str(tmp_path / "out")}
    monkeypatch.setattr(main_window, "QSettings", _FakeSettings)
    return main_window.MainWindow()


def _wait_for(qapp, predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_files_wait_for_start_then_convert_with_selected_layout(
    qapp, monkeypatch, tmp_path
):
    calls = {}

    def fake_convert(input_path, output_path, **kwargs):
        calls["input"] = input_path
        calls["page_size"] = kwargs.get("page_size")
        calls["font_scale"] = kwargs.get("font_scale")
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"%PDF fake")
        return str(output_path)

    monkeypatch.setattr(orchestrator, "convert", fake_convert)
    window = _make_window(qapp, monkeypatch, tmp_path)
    epub = tmp_path / "book.epub"
    shutil.copy(Path(__file__).parent / "fixtures" / "basic.epub", epub)

    window.page_size_combo.setCurrentIndex(
        window.page_size_combo.findData("6x9")
    )
    window.font_scale_combo.setCurrentIndex(
        window.font_scale_combo.findData("loose")
    )

    window._enqueue(str(epub))

    # Dropping a file no longer starts a conversion.
    assert len(window._pending) == 1
    assert window.start_btn.isEnabled()
    assert window._thread_pool.activeThreadCount() == 0
    assert not calls

    window._on_start_clicked()

    assert _wait_for(
        qapp,
        lambda: window._thread_pool.activeThreadCount() == 0
        and "page_size" in calls,
    )
    assert calls["page_size"] == "6x9"
    assert calls["font_scale"] == "loose"
    assert calls["input"] == str(epub.resolve())
    assert str(epub.resolve()).endswith("book.epub")
    assert window._pending == []
    assert not window.start_btn.isEnabled()
    # The finished task row remains visible in its done state.
    row = next(iter(window._task_rows.values()))
    assert _wait_for(
        qapp,
        lambda: row.status_label.text() == main_window.TaskRow.STATUS_LABEL["done"],
    )
    # Choices persist through QSettings.
    assert _FakeSettings.store["page_size"] == "6x9"
    assert _FakeSettings.store["font_scale"] == "loose"


def test_removing_a_pending_row_does_not_start_a_conversion(
    qapp, monkeypatch, tmp_path
):
    def fake_convert(*_args, **_kwargs):  # pragma: no cover - should not run
        raise AssertionError("conversion started for a removed pending file")

    monkeypatch.setattr(orchestrator, "convert", fake_convert)
    window = _make_window(qapp, monkeypatch, tmp_path)
    epub = tmp_path / "book.epub"
    shutil.copy(Path(__file__).parent / "fixtures" / "basic.epub", epub)

    window._enqueue(str(epub))
    row = window._pending[0].row
    row.cancel_requested.emit(row)
    qapp.processEvents()

    assert window._pending == []
    assert window._task_rows == {}
    assert not window.start_btn.isEnabled()


def test_dropped_files_show_waiting_state_and_start_is_disabled_when_empty(
    qapp, monkeypatch, tmp_path
):
    window = _make_window(qapp, monkeypatch, tmp_path)
    assert not window.start_btn.isEnabled()

    epub = tmp_path / "book.epub"
    shutil.copy(Path(__file__).parent / "fixtures" / "basic.epub", epub)
    window._on_files_dropped([str(epub)])

    row = window._pending[0].row
    assert row.status_label.text() == main_window.TaskRow.STATUS_LABEL["pending"]
    assert row.cancel_btn.text() == "移除"
    assert window.start_btn.isEnabled()
    assert window.pending_label.text() == "待开始: 1"


def test_start_and_choices_are_disabled_while_a_conversion_runs(
    qapp, monkeypatch, tmp_path
):
    import threading

    started = threading.Event()
    release = threading.Event()

    def blocking_convert(input_path, output_path, **_kwargs):
        started.set()
        assert release.wait(10), "test did not release the converter"
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"%PDF fake")
        return str(output_path)

    monkeypatch.setattr(orchestrator, "convert", blocking_convert)
    window = _make_window(qapp, monkeypatch, tmp_path)
    epub = tmp_path / "book.epub"
    shutil.copy(Path(__file__).parent / "fixtures" / "basic.epub", epub)

    window._enqueue(str(epub))
    window._on_start_clicked()
    assert started.wait(10), "conversion never started"
    qapp.processEvents()

    assert not window.start_btn.isEnabled()
    assert not window.page_size_combo.isEnabled()
    assert not window.font_scale_combo.isEnabled()

    release.set()
    assert _wait_for(qapp, lambda: window.page_size_combo.isEnabled())
    assert window.font_scale_combo.isEnabled()
