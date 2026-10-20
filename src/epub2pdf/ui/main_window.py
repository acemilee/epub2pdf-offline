"""Main window for epub2pdf — drop zone + task list + log panel."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QSettings, QThreadPool
from PySide6.QtGui import QAction, QCloseEvent, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .drop_zone import DropZone
from .log_panel import LogPanel
from . import shell
from .task_row import TaskRow
from ..core.orchestrator import ConversionTask, Orchestrator


MAX_CONCURRENT_CONVERSIONS = 1

PAGE_SIZE_CHOICES = (
    ("自动（按封面比例）", "auto"),
    ("A4", "A4"),
    ("Letter", "Letter"),
    ("B5", "B5"),
    ("6×9 in", "6x9"),
    ("7×10 in", "7x10"),
)

FONT_SCALE_CHOICES = (
    ("自动", "auto"),
    ("紧凑", "compact"),
    ("标准", "normal"),
    ("宽松", "loose"),
)


@dataclass
class PendingConversion:
    """A dropped/added EPUB that waits for the 开始转换 button."""

    epub_path: str
    output_path: str
    row: TaskRow


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("epub2pdf — 离线 EPUB 转 PDF")
        self.resize(780, 720)

        self._settings = QSettings("epub2pdf", "app")
        self._thread_pool = QThreadPool(self)
        self._thread_pool.setMaxThreadCount(MAX_CONCURRENT_CONVERSIONS)
        self._orchestrator = Orchestrator(self._thread_pool)

        # Track active TaskRows by task id
        self._task_rows: dict[str, TaskRow] = {}
        # Added files wait here until the user presses 开始转换 (v1.1.2)
        self._pending: list[PendingConversion] = []
        # Count submitted-but-not-finished conversions (covers the window
        # between QThreadPool.start() and the thread actually running).
        self._active_tasks = 0

        # ---------------- Central widget ----------------
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        # --- Drop zone ---
        self.drop_zone = DropZone()
        self.drop_zone.files_dropped.connect(self._on_files_dropped)
        outer.addWidget(self.drop_zone)

        # --- Toolbar row ---
        toolbar = QHBoxLayout()
        self.add_btn = QPushButton("添加文件…")
        self.add_btn.clicked.connect(self._on_add_clicked)
        toolbar.addWidget(self.add_btn)

        self.output_label = QLabel(self._output_dir_text())
        self.output_label.setStyleSheet("color: #555;")
        toolbar.addWidget(self.output_label, 1)

        self.change_out_btn = QPushButton("更改输出目录")
        self.change_out_btn.clicked.connect(self._on_change_output_dir)
        toolbar.addWidget(self.change_out_btn)

        self.open_out_btn = QPushButton("打开输出目录")
        self.open_out_btn.clicked.connect(self._on_open_output_dir)
        toolbar.addWidget(self.open_out_btn)

        self.clear_done_btn = QPushButton("清空已完成")
        self.clear_done_btn.clicked.connect(self._on_clear_done)
        toolbar.addWidget(self.clear_done_btn)

        outer.addLayout(toolbar)

        # --- Layout / start row (v1.1.2: explicit start + page format) ---
        layout_bar = QHBoxLayout()
        layout_bar.addWidget(QLabel("页面尺寸:"))
        self.page_size_combo = QComboBox()
        for label, value in PAGE_SIZE_CHOICES:
            self.page_size_combo.addItem(label, value)
        layout_bar.addWidget(self.page_size_combo)

        layout_bar.addSpacing(12)
        layout_bar.addWidget(QLabel("字号:"))
        self.font_scale_combo = QComboBox()
        for label, value in FONT_SCALE_CHOICES:
            self.font_scale_combo.addItem(label, value)
        layout_bar.addWidget(self.font_scale_combo)

        layout_bar.addStretch(1)
        self.pending_label = QLabel("待开始: 0")
        self.pending_label.setStyleSheet("color: #555;")
        layout_bar.addWidget(self.pending_label)

        self.start_btn = QPushButton("开始转换")
        self.start_btn.setDefault(True)
        self.start_btn.clicked.connect(self._on_start_clicked)
        layout_bar.addWidget(self.start_btn)

        outer.addLayout(layout_bar)
        self._restore_layout_choices()
        self._refresh_toolbar_state()

        # --- Task list ---
        self.task_list_holder = QWidget()
        self.task_list_layout = QVBoxLayout(self.task_list_holder)
        self.task_list_layout.setContentsMargins(0, 0, 0, 0)
        self.task_list_layout.setSpacing(6)
        self.task_list_layout.addStretch(1)  # filler

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.task_list_holder)
        scroll.setMinimumHeight(240)
        outer.addWidget(scroll, 1)

        # --- Log panel ---
        self.log_panel = LogPanel()
        outer.addWidget(self.log_panel, 1)

        # ---------------- Status bar ----------------
        self.setStatusBar(QStatusBar())
        self._update_status_bar()

    # ---------- File handling ----------

    def _output_dir_text(self) -> str:
        d = self._settings.value("output_dir", "")
        if not d:
            d = str(Path.home() / "Documents" / "EpubToPdf")
        return f"输出目录: {d}"

    def _on_files_dropped(self, paths: list[str]) -> None:
        for p in paths:
            self._enqueue(p)

    def _on_add_clicked(self) -> None:
        start_dir = self._settings.value("last_open_dir", str(Path.home()))
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择 EPUB 文件",
            start_dir,
            "EPUB files (*.epub);;All files (*.*)",
        )
        if not files:
            return
        self._settings.setValue("last_open_dir", str(Path(files[0]).parent))
        for f in files:
            self._enqueue(f)

    def _on_change_output_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, "选择输出目录", self.output_label.text().replace("输出目录: ", "")
        )
        if d:
            self._settings.setValue("output_dir", d)
            self.output_label.setText(self._output_dir_text())
            self._refresh_toolbar_state()

    def _current_output_dir(self) -> str:
        return self._settings.value("output_dir", "") \
               or str(Path.home() / "Documents" / "EpubToPdf")

    def _refresh_toolbar_state(self) -> None:
        """Enable the folder button only when the output directory exists."""
        self.open_out_btn.setEnabled(os.path.isdir(self._current_output_dir()))
        running = self._active_tasks > 0 or self._thread_pool.activeThreadCount() > 0
        if hasattr(self, "start_btn"):
            self.start_btn.setEnabled(bool(self._pending) and not running)
        if hasattr(self, "page_size_combo"):
            self.page_size_combo.setEnabled(not running)
            self.font_scale_combo.setEnabled(not running)
        if hasattr(self, "pending_label"):
            self.pending_label.setText(f"待开始: {len(self._pending)}")

    # ---------- Layout choices ----------

    def _restore_layout_choices(self) -> None:
        page_size = self._settings.value("page_size", "auto")
        index = self.page_size_combo.findData(page_size)
        self.page_size_combo.setCurrentIndex(max(0, index))
        font_scale = self._settings.value("font_scale", "auto")
        index = self.font_scale_combo.findData(font_scale)
        self.font_scale_combo.setCurrentIndex(max(0, index))

    def _save_layout_choices(self) -> None:
        self._settings.setValue("page_size", self.page_size_combo.currentData())
        self._settings.setValue("font_scale", self.font_scale_combo.currentData())

    def _selected_layout_options(self) -> tuple[str, str]:
        return (
            str(self.page_size_combo.currentData() or "auto"),
            str(self.font_scale_combo.currentData() or "auto"),
        )

    def _on_open_output_dir(self) -> None:
        target = self._current_output_dir()
        if not shell.open_directory(target):
            QMessageBox.information(
                self,
                "打开输出目录",
                f"目录不存在或无法打开：\n{target}\n\n转换一个文件后目录会自动创建。",
            )
        self._refresh_toolbar_state()

    def _on_clear_done(self) -> None:
        for task_id, row in list(self._task_rows.items()):
            if row.status_label.text() in (TaskRow.STATUS_LABEL["done"],
                                           TaskRow.STATUS_LABEL["failed"],
                                           TaskRow.STATUS_LABEL["cancelled"]):
                self._remove_task(task_id)

    # ---------- Task lifecycle ----------

    def _enqueue(self, epub_path: str) -> None:
        """Add a file to the pending list; conversion starts with 开始转换."""
        epub_path = str(Path(epub_path).resolve())
        if not os.path.isfile(epub_path):
            self.log_panel.append(os.path.basename(epub_path), "文件不存在，跳过")
            return

        # Build output path
        out_dir = self._settings.value("output_dir", "") \
                  or str(Path.home() / "Documents" / "EpubToPdf")
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        out_path = str(Path(out_dir) / (Path(epub_path).stem + ".pdf"))

        # Create TaskRow UI
        row = TaskRow(epub_path)
        row.mark_pending()
        row.cancel_requested.connect(self._on_cancel_requested)
        # Insert before the final stretch
        self.task_list_layout.insertWidget(
            self.task_list_layout.count() - 1, row
        )
        self._pending.append(PendingConversion(epub_path, out_path, row))
        self.log_panel.append(
            os.path.basename(epub_path), "已加入待开始队列（点击「开始转换」）"
        )
        self._update_status_bar()

    def _on_start_clicked(self) -> None:
        """Start conversions for every pending file."""
        if not self._pending:
            return
        self._save_layout_choices()
        page_size, font_scale = self._selected_layout_options()

        started: list[ConversionTask] = []
        for item in self._pending:
            task = ConversionTask(
                input_path=item.epub_path,
                output_path=item.output_path,
                page_size=page_size,
                font_scale=font_scale,
            )
            task.signals.progress.connect(
                lambda stage, pct, r=item.row: r.setStatus(stage, pct)
            )
            task.signals.log.connect(self.log_panel.append)
            task.signals.finished.connect(self._on_task_finished)
            self._task_rows[task.task_id] = item.row
            started.append(task)
            self.log_panel.append(
                item.row.basename,
                f"开始转换（页面={page_size}，字号={font_scale}）",
            )

        self._pending.clear()
        self._active_tasks += len(started)
        self.start_btn.setEnabled(False)
        self.page_size_combo.setEnabled(False)
        self.font_scale_combo.setEnabled(False)
        for task in started:
            self._orchestrator.submit(task)
        self._update_status_bar()

    def _on_cancel_requested(self, row: TaskRow) -> None:
        for item in list(self._pending):
            if item.row is row:
                self._pending.remove(item)
                self._remove_pending_row(item.row)
                self.log_panel.append(row.basename, "已从待开始队列移除")
                self._update_status_bar()
                return
        for task_id, r in self._task_rows.items():
            if r is row:
                self._orchestrator.cancel(task_id)
                self.log_panel.append(row.basename, "已请求取消")
                break

    def _remove_pending_row(self, row: TaskRow) -> None:
        self.task_list_layout.removeWidget(row)
        row.setParent(None)
        row.deleteLater()

    def _on_task_finished(self, task_id: str, success: bool, result) -> None:
        self._active_tasks = max(0, self._active_tasks - 1)
        row = self._task_rows.get(task_id)
        if row is None:
            return
        if success:
            row.mark_done(result)
            self.log_panel.append(row.basename, f"完成 → {result}")
        else:
            err = str(result) if result else "unknown error"
            row.mark_failed(err)
            self.log_panel.append(row.basename, f"失败: {err}")
        self._update_status_bar()

    def _remove_task(self, task_id: str) -> None:
        row = self._task_rows.pop(task_id, None)
        if row is not None:
            self.task_list_layout.removeWidget(row)
            row.setParent(None)
            row.deleteLater()

    def _update_status_bar(self) -> None:
        active = self._thread_pool.activeThreadCount()
        queued = len(self._task_rows)
        pending = len(self._pending)
        self.statusBar().showMessage(
            f"待开始: {pending}  活跃: {active}  任务总数: {queued}  "
            f"最大并发: {self._thread_pool.maxThreadCount()}"
        )
        self._refresh_toolbar_state()

    # ---------- Window lifecycle ----------

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._thread_pool.activeThreadCount() > 0:
            ret = QMessageBox.question(
                self,
                "退出",
                "有任务正在运行，确定要退出吗？\n（取消中的任务会被中止）",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ret != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._orchestrator.cancel_all()
            self._thread_pool.waitForDone(3000)
        event.accept()
