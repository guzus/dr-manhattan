"""Thread-backed worker for moving slow side effects off a hot path."""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Generic, TypeVar

T = TypeVar("T")


class OverflowPolicy(str, Enum):
    """How an AsyncWorker handles submissions when its queue is full."""

    DROP_NEWEST = "drop_newest"
    DROP_OLDEST = "drop_oldest"
    BLOCK = "block"
    RAISE = "raise"


@dataclass(frozen=True)
class WorkerStats:
    submitted: int = 0
    processed: int = 0
    failed: int = 0
    dropped: int = 0
    queue_size: int = 0


class AsyncWorker(Generic[T]):
    """Run blocking handlers in a background thread.

    The SDK is mostly synchronous, so this class intentionally uses a thread
    rather than requiring users to own an asyncio event loop. It is intended for
    durable but non-critical side effects such as alerts, metrics, and SQLite
    writes. Do not use it for checks that must approve an order before submit.
    """

    def __init__(
        self,
        handler: Callable[[T], None],
        *,
        name: str = "dr-manhattan-worker",
        queue_size: int = 1000,
        overflow_policy: OverflowPolicy = OverflowPolicy.DROP_NEWEST,
        on_error: Callable[[BaseException, T], None] | None = None,
    ) -> None:
        if queue_size < 1:
            raise ValueError("queue_size must be >= 1")
        self.handler = handler
        self.name = name
        self.overflow_policy = overflow_policy
        self.on_error = on_error
        self._queue: queue.Queue[T | object] = queue.Queue(maxsize=queue_size)
        self._sentinel = object()
        self._lock = threading.Lock()
        self._closed = False
        self._thread: threading.Thread | None = None
        self._submitted = 0
        self._processed = 0
        self._failed = 0
        self._dropped = 0

    def start(self) -> None:
        with self._lock:
            if self._thread is not None:
                return
            self._thread = threading.Thread(target=self._run, name=self.name, daemon=True)
            self._thread.start()

    def submit(self, item: T, *, timeout: float | None = None) -> bool:
        """Queue an item for background processing.

        Returns False when the configured overflow policy drops the item or the
        worker is already closed.
        """

        self.start()
        with self._lock:
            if self._closed:
                return False

        if self.overflow_policy == OverflowPolicy.BLOCK:
            try:
                self._queue.put(item, timeout=timeout)
            except queue.Full:
                self._increment_dropped()
                return False
            self._increment_submitted()
            return True

        try:
            self._queue.put_nowait(item)
        except queue.Full:
            if self.overflow_policy == OverflowPolicy.RAISE:
                raise
            if self.overflow_policy == OverflowPolicy.DROP_OLDEST:
                if not self._drop_oldest_pending():
                    self._increment_dropped()
                    return False
                self._queue.put_nowait(item)
                self._increment_submitted()
                return True
            self._increment_dropped()
            return False

        self._increment_submitted()
        return True

    def close(self, *, timeout: float | None = 5.0, drain: bool = True) -> None:
        """Stop the worker.

        With drain=True, all already queued items are processed before the
        worker exits. With drain=False, queued items are discarded first.
        """

        with self._lock:
            if self._closed:
                return
            self._closed = True

        if not drain:
            self._drop_all_pending()

        self.start()
        self._queue.put(self._sentinel)
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)

    @property
    def stats(self) -> WorkerStats:
        with self._lock:
            return WorkerStats(
                submitted=self._submitted,
                processed=self._processed,
                failed=self._failed,
                dropped=self._dropped,
                queue_size=self._queue.qsize(),
            )

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is self._sentinel:
                    return
                self.handler(item)  # type: ignore[arg-type]
                self._increment_processed()
            except BaseException as exc:
                self._increment_failed()
                if item is not self._sentinel and self.on_error is not None:
                    self.on_error(exc, item)  # type: ignore[arg-type]
            finally:
                self._queue.task_done()

    def _drop_oldest_pending(self) -> bool:
        try:
            self._queue.get_nowait()
        except queue.Empty:
            return False
        self._queue.task_done()
        self._increment_dropped()
        return True

    def _drop_all_pending(self) -> None:
        dropped = 0
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is not self._sentinel:
                dropped += 1
            self._queue.task_done()
        if dropped:
            self._increment_dropped(dropped)

    def _increment_submitted(self) -> None:
        with self._lock:
            self._submitted += 1

    def _increment_processed(self) -> None:
        with self._lock:
            self._processed += 1

    def _increment_failed(self) -> None:
        with self._lock:
            self._failed += 1

    def _increment_dropped(self, count: int = 1) -> None:
        with self._lock:
            self._dropped += count
