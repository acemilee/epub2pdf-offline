"""Orchestrator: queues ConversionTasks on a QThreadPool.

Each ``ConversionTask`` emits progress + log signals that the UI listens to.
Tasks can be cancelled via ``Orchestrator.cancel(task_id)``; the cancel
flag is polled by ``cli.convert`` between stages.
"""
from __future__ import annotations

import os
import threading
import uuid
from typing import Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from ..cli import convert, ConversionCancelled


# ---------- Signals ----------

class TaskSignals(QObject):
    progress = Signal(str, int)          # (stage, percent)
    log = Signal(str, str)               # (task_name, message)
    finished = Signal(str, bool, object) # (task_id, success, result_or_error)


# ---------- Task ----------

class ConversionTask(QRunnable):
    def __init__(
        self,
        input_path: str,
        output_path: str,
        keep_temp: bool = False,
        with_cover: bool = True,
    ):
        super().__init__()
        self.input_path = input_path
        self.output_path = output_path
        self.keep_temp = keep_temp
        self.with_cover = with_cover
        self.task_id = uuid.uuid4().hex
        self.signals = TaskSignals()
        self._cancel_flag = threading.Event()

    def cancel(self) -> None:
        self._cancel_flag.set()

    def is_cancelled(self) -> bool:
        return self._cancel_flag.is_set()

    def run(self) -> None:
        name = os.path.basename(self.input_path)

        def on_progress(stage: str, percent: int) -> None:
            self.signals.progress.emit(stage, percent)
            self.signals.log.emit(name, f"[{stage}] {percent}%")

        def on_cancel_check() -> bool:
            return self._cancel_flag.is_set()

        try:
            out = convert(
                self.input_path,
                self.output_path,
                keep_temp=self.keep_temp,
                with_cover=self.with_cover,
                progress_cb=on_progress,
                cancel_check=on_cancel_check,
            )
            self.signals.finished.emit(self.task_id, True, out)
        except ConversionCancelled:
            self.signals.log.emit(name, "已取消")
            self.signals.finished.emit(self.task_id, False, "cancelled")
        except Exception as e:
            self.signals.log.emit(name, f"ERROR: {e}")
            self.signals.finished.emit(self.task_id, False, str(e))


# ---------- Orchestrator ----------

class Orchestrator:
    """Thin wrapper around QThreadPool with task id tracking."""

    def __init__(self, pool: QThreadPool):
        self._pool = pool
        self._tasks: dict[str, ConversionTask] = {}

    def submit(self, task: ConversionTask) -> None:
        self._tasks[task.task_id] = task
        self._pool.start(task)

    def cancel(self, task_id: str) -> None:
        t = self._tasks.get(task_id)
        if t is not None:
            t.cancel()

    def cancel_all(self) -> None:
        for t in self._tasks.values():
            t.cancel()

    def active_count(self) -> int:
        return self._pool.activeThreadCount()