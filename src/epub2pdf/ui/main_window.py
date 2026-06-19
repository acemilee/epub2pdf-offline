"""Main window for epub2pdf — drop zone + task list + log panel."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QSettings, QThreadPool
from PySide6.QtGui import QAction, QCloseEvent, QFont
from PySide6.QtWidgets import (
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
from .task_row import TaskRow
from ..core.orchestrator import ConversionTask, Orchestrator


MAX_CONCURRENT_CONVERSIONS = 1


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

        self.clear_done_btn = QPushButton("清空已完成")
        self.clear_done_btn.clicked.connect(self._on_clear_done)
        toolbar.addWidget(self.clear_done_btn)

        outer.addLayout(toolbar)

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

    def _on_clear_done(self) -> None:
        for task_id, row in list(self._task_rows.items()):
            if row.status_label.text() in (TaskRow.STATUS_LABEL["done"],
                                           TaskRow.STATUS_LABEL["failed"],
                                           TaskRow.STATUS_LABEL["cancelled"]):
                self._remove_task(task_id)

    # ---------- Task lifecycle ----------

    def _enqueue(self, epub_path: str) -> None:
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
        row.cancel_requested.connect(self._on_cancel_requested)
        # Insert before the final stretch
        self.task_list_layout.insertWidget(
            self.task_list_layout.count() - 1, row
        )

        # Create ConversionTask and wire signals
        task = ConversionTask(
            input_path=epub_path,
            output_path=out_path,
        )
        task.signals.progress.connect(
            lambda stage, pct, r=row: r.setStatus(stage, pct)
        )
        task.signals.log.connect(self.log_panel.append)
        task.signals.finished.connect(self._on_task_finished)

        self._task_rows[task.task_id] = row
        self._orchestrator.submit(task)
        self.log_panel.append(
            os.path.basename(epub_path), f"已加入队列 (共 {self._thread_pool.activeThreadCount()} 活跃线程)"
        )
        self._update_status_bar()

    def _on_cancel_requested(self, row: TaskRow) -> None:
        for task_id, r in self._task_rows.items():
            if r is row:
                self._orchestrator.cancel(task_id)
                self.log_panel.append(row.basename, "已请求取消")
                break

    def _on_task_finished(self, task_id: str, success: bool, result) -> None:
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
        self.statusBar().showMessage(
            f"活跃: {active}  任务总数: {queued}  最大并发: {self._thread_pool.maxThreadCount()}"
        )

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
