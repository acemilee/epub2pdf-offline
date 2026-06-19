"""TaskRow — one row in the task list. Owns its own progress + cancel state."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class TaskRow(QFrame):
    """One conversion task.

    Emits:
        cancel_requested: user pressed the Cancel button.
    """

    cancel_requested = Signal(object)  # emits self

    STATUS_LABEL = {
        "queued":     "排队中",
        "parsing":    "解析中",
        "normalizing":"规范化中",
        "rendering":  "渲染中",
        "assembling": "装配中",
        "done":       "完成",
        "failed":     "失败",
        "cancelled":  "已取消",
    }

    def __init__(self, epub_path: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.epub_path = epub_path
        self.basename = os.path.basename(epub_path)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("TaskRow")

        # --- Title row ---
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(10)
        self.title_label = QLabel(self.basename)
        self.title_label.setFont(title_font)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding,
                                       QSizePolicy.Policy.Preferred)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setFixedWidth(60)
        self.cancel_btn.clicked.connect(lambda: self.cancel_requested.emit(self))

        # --- Status row ---
        self.status_label = QLabel("排队中")
        self.status_label.setStyleSheet("color: #666;")

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")

        # --- Layout ---
        top_row = QHBoxLayout()
        top_row.setContentsMargins(8, 4, 8, 0)
        top_row.addWidget(self.title_label, 1)
        top_row.addWidget(self.cancel_btn, 0)

        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(8, 0, 8, 4)
        bottom_row.addWidget(self.status_label, 0)
        bottom_row.addWidget(self.progress_bar, 1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)
        outer.addLayout(top_row)
        outer.addLayout(bottom_row)

        self.setStatus("queued", 0)

    # ---------- Public API ----------

    def setStatus(self, stage: str, percent: int) -> None:
        text = self.STATUS_LABEL.get(stage, stage)
        self.status_label.setText(text)
        self.progress_bar.setValue(max(0, min(100, int(percent))))

    def mark_done(self, output_path: str) -> None:
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("打开")
        try:
            self.cancel_btn.clicked.disconnect()
        except RuntimeError:
            pass
        self.cancel_btn.clicked.connect(
            lambda: os.startfile(str(Path(output_path).parent))
            if hasattr(os, "startfile") else None
        )
        self.status_label.setStyleSheet("color: #2e7d32; font-weight: bold;")
        self.setStatus("done", 100)

    def mark_failed(self, error_msg: str) -> None:
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("失败")
        self.status_label.setText(f"失败: {error_msg[:60]}")
        self.status_label.setStyleSheet("color: #c62828;")
        self.progress_bar.setValue(0)

    def mark_cancelled(self) -> None:
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("已取消")
        self.setStatus("cancelled", 0)
        self.status_label.setStyleSheet("color: #999;")

    def disable_cancel(self) -> None:
        self.cancel_btn.setEnabled(False)