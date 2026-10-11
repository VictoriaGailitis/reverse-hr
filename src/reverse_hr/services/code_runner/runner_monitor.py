"""Bounded admission polling; a stalled check never stalls the execution watchdog."""

import threading
import time
from contextlib import AbstractContextManager

# At most one outstanding monitor per process, including a stalled detached check.
_SLOT = threading.BoundedSemaphore(1)
_REASONS = {"user_cancelled", "access_withdrawn", "admission_unavailable"}


class StopMonitor(AbstractContextManager):
    def __init__(self, check, *, interval=0.25, max_age=1.0):
        self.check = check
        self.interval, self.max_age = interval, max_age
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.reason = None
        self.checked_at = time.monotonic()
        self.thread = None

    def __enter__(self):
        if not _SLOT.acquire(blocking=False):
            self.reason = "admission_unavailable"
            return self
        self.thread = threading.Thread(target=self._poll, daemon=True)
        try:
            self.thread.start()
        except BaseException:
            _SLOT.release()
            raise
        return self

    def _poll(self):
        try:
            while not self.stop.is_set():
                try:
                    reason = self.check()
                    if reason is not None and reason not in _REASONS:
                        reason = "admission_unavailable"
                except Exception:
                    reason = "admission_unavailable"
                with self.lock:
                    self.checked_at = time.monotonic()
                    if self.reason is None:
                        self.reason = reason
                if reason or self.stop.wait(self.interval):
                    break
        finally:
            _SLOT.release()

    def current(self):
        with self.lock:
            if self.reason is None and time.monotonic() - self.checked_at > self.max_age:
                self.reason = "admission_unavailable"
            return self.reason

    def __exit__(self, *_):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=0.05)
        # An outstanding read-only check retains its slot until it exits; never make
        # more threads or wait indefinitely. Late answers cannot publish any result.
        return False
