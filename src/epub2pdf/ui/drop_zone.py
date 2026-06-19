"""DropZone — accepts drag-and-drop of .epub files."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
)


class DropZone(QFrame):
    """A bordered frame that accepts drag-and-drop .epub files.

    Emits ``files_dropped(list[str])`` with the accepted file paths.
    """

    files_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("DropZone")
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._hover = False

        self.title = QLabel("把 .epub 文件拖到这里")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = self.title.font()
        font.setPointSize(13)
        font.setBold(True)
        self.title.setFont(font)

        self.subtitle = QLabel("（支持多文件 — 每个文件独立任务）")
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle.setStyleSheet("color: #888;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 24, 12, 24)
        layout.addStretch(1)
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)
        layout.addStretch(1)

        self._apply_style()

    # ---------- Drag & drop ----------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() and any(
            u.toLocalFile().lower().endswith(".epub")
            for u in event.mimeData().urls()
        ):
            event.acceptProposedAction()
            self._set_hover(True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._set_hover(False)
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_hover(False)
        paths = [
            u.toLocalFile()
            for u in event.mimeData().urls()
            if u.toLocalFile().lower().endswith(".epub")
        ]
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            event.ignore()

    # ---------- Style ----------

    def _set_hover(self, hover: bool) -> None:
        self._hover = hover
        self._apply_style()

    def _apply_style(self) -> None:
        if self._hover:
            border = "#1976d2"
            bg = "#e3f2fd"
        else:
            border = "#bbb"
            bg = "#fafafa"
        self.setStyleSheet(
            f"#DropZone {{ border: 2px dashed {border}; "
            f"background: {bg}; border-radius: 8px; }}"
        )