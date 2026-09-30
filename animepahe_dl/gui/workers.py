"""Run blocking calls on Qt's thread pool and deliver results on the GUI thread."""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _Signals(QObject):
    succeeded = Signal(object)
    failed = Signal(object)


class _Job(QRunnable):
    def __init__(self, fn: Callable[[], Any]) -> None:
        super().__init__()
        self.fn = fn
        self.signals = _Signals()

    def run(self) -> None:  # executed on a worker thread
        try:
            result = self.fn()
        except Exception as exc:  # noqa: BLE001
            self.signals.failed.emit(exc)
        else:
            self.signals.succeeded.emit(result)


class JobRunner(QObject):
    """Keeps a strong reference to running jobs so their signals are not garbage collected."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._jobs: set[_Job] = set()
        self.pool = QThreadPool.globalInstance()

    def submit(
        self,
        fn: Callable[[], Any],
        on_success: Callable[[Any], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        job = _Job(fn)
        job.setAutoDelete(False)
        self._jobs.add(job)

        def done_ok(result: Any) -> None:
            self._jobs.discard(job)
            if on_success:
                on_success(result)

        def done_err(exc: Exception) -> None:
            self._jobs.discard(job)
            if on_error:
                on_error(exc)

        job.signals.succeeded.connect(done_ok)
        job.signals.failed.connect(done_err)
        self.pool.start(job)
