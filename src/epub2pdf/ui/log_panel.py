"""LogPanel — bottom panel showing tail of conversion logs."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class LogPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.header = QLabel("日志")
        font = QFont()
        font.setBold(True)
        self.header.setFont(font)

        self.clear_btn = QPushButton("清空")
        self.clear_btn.setFixedWidth(60)
        self.clear_btn.clicked.connect(self._on_clear)

        top = QHBoxLayout()
        top.setContentsMargins(8, 4, 4, 0)
        top.addWidget(self.header, 1)
        top.addWidget(self.clear_btn, 0)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setMaximumBlockCount(2000)
        mono = QFont("Cascadia Code")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.text_edit.setFont(mono)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)
        outer.addLayout(top)
        outer.addWidget(self.text_edit, 1)

    def append(self, task_name: str, message: str) -> None:
        line = f"[{task_name}] {message}"
        self.text_edit.appendPlainText(line)
        # Auto-scroll to bottom
        cursor = self.text_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.text_edit.setTextCursor(cursor)

    def _on_clear(self) -> None:
        self.text_edit.clear()