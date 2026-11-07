"""Runs long jobs outside the GUI thread."""
from __future__ import annotations

import logging
import traceback

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

log = logging.getLogger(__name__)

_alive: set = set()


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(object)
    progress = Signal(float, str)


class Task(QRunnable):
    def __init__(self, fn, *args, progress: bool = False, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = _Signals()
        self.with_progress = progress
        self.cancelled = False
        self.setAutoDelete(False)

    def report(self, frac: float, msg: str = "") -> None:
        self.signals.progress.emit(float(frac), msg)

    @staticmethod
    def _emit(signal, value) -> None:
        try:
            signal.emit(value)
        except RuntimeError:  # the receiver was closed while the job was running
            pass

    def run(self) -> None:
        try:
            if self.with_progress:
                result = self.fn(*self.args, progress=self.report, **self.kwargs)
            else:
                result = self.fn(*self.args, **self.kwargs)
        except BaseException as exc:  # noqa: BLE001 - reported to the GUI
            log.error("error in a background job:\n%s", traceback.format_exc())
            self._emit(self.signals.failed, exc)
        else:
            self._emit(self.signals.done, result)
        finally:
            _alive.discard(self)


def run_task(fn, *args, on_done=None, on_error=None, on_progress=None, **kwargs) -> Task:
    task = Task(fn, *args, progress=on_progress is not None, **kwargs)
    if on_done:
        task.signals.done.connect(on_done)
    if on_error:
        task.signals.failed.connect(on_error)
    if on_progress:
        task.signals.progress.connect(on_progress)
    _alive.add(task)
    QThreadPool.globalInstance().start(task)
    return task
