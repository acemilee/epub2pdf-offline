import pytest

pytest.importorskip("PySide6")

from epub2pdf.core.orchestrator import ConversionTask, Orchestrator


class _FakePool:
    def __init__(self):
        self.started = []

    def start(self, task):
        self.started.append(task)

    def activeThreadCount(self):
        return 0


def test_finished_task_is_dropped_from_tracking():
    pool = _FakePool()
    orchestrator = Orchestrator(pool)
    task = ConversionTask("input.epub", "output.pdf")

    orchestrator.submit(task)

    assert pool.started == [task]
    assert task.task_id in orchestrator._tasks

    task.signals.finished.emit(task.task_id, True, "output.pdf")

    assert task.task_id not in orchestrator._tasks
    assert orchestrator.active_count() == 0
