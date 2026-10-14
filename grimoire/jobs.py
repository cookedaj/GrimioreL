# SPDX-License-Identifier: GPL-3.0-or-later
"""Background work for the UI: run a function on a worker thread, hand its result to a callback."""
import traceback

from PySide6.QtCore import QRunnable, QThreadPool

POOL = QThreadPool()
POOL.setMaxThreadCount(4)


class Job(QRunnable):
    """Runs fn() on a pool thread and passes the result to done(). done() usually emits a Qt signal, so the
    result reaches the UI thread safely. If fn() raises, the error is printed and done() isn't called."""

    def __init__(self, fn, done):
        super().__init__()
        self.fn, self.done = fn, done

    def run(self):
        try:
            result = self.fn()
        except Exception:
            traceback.print_exc()
            return
        try:
            self.done(result)
        except RuntimeError:     # the page was closed while this was running
            pass
