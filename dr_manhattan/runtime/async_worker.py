"""Thread-backed worker for moving slow side effects off a hot path."""

from __future__ import annotations

import queue
import threading
from collections import deque
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
    critical_pending: int = 0


class AsyncWorker(Generic[T]):
    """Run blocking handlers in a background thread.

    The SDK is mostly synchronous, so this class intentionally uses a thread
    rather than requiring users to own an asyncio event loop. It is intended for
    durable side effects such as alerts, metrics, and SQLite writes. Do not use
    it for checks that must approve an order before submit.

    Items submitted with critical=True go through an unbounded lane that the
    worker drains before the bounded queue. They are never dropped and never
    block the caller, regardless of the overflow policy.
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
        self._critical: deque[T] = deque()
        self._sentinel = object()
        self._critical_token = object()
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

    def submit(self, item: T, *, timeout: float | None = None, critical: bool = False) -> bool:
        """Queue an item for background processing.

        Returns False when the configured overflow policy drops the item or the
        worker is already closed.

        With critical=True the item bypasses the overflow policy: it is
        appended to an unbounded lane processed ahead of regular items, so it
        is never dropped under queue pressure and never blocks the caller.
        Losing telemetry degrades analytics; losing a money-path record
        corrupts the ledger.
        """

        self.start()
        with self._lock:
            if self._closed:
                return False

        if critical:
            self._critical.append(item)
            self._increment_submitted()
            try:
                # Wake the worker if it is blocked on an empty queue. A full
                # queue means it is already busy and will drain the critical
                # lane before its next regular item.
                self._queue.put_nowait(self._critical_token)
            except queue.Full:
                pass
            return True

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
        worker exits. With drain=False, queued regular items are discarded
        first, but pending critical items are still processed: money-path
        records must outlive a fast shutdown. Both flushes are bounded by
        timeout: a handler stuck in retries (e.g. the SQLite sink's ~6s worst
        case for a poison event) can outlive the default 5s join, so pass a
        larger timeout when the final flush must complete.
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
                critical_pending=len(self._critical),
            )

    def _run(self) -> None:
        while True:
            self._drain_critical()
            item = self._queue.get()
            try:
                if item is self._sentinel:
                    self._drain_critical()
                    return
                if item is self._critical_token:
                    continue
                self._process(item)  # type: ignore[arg-type]
            finally:
                self._queue.task_done()

    def _drain_critical(self) -> None:
        while True:
            try:
                item = self._critical.popleft()
            except IndexError:
                return
            self._process(item)

    def _process(self, item: T) -> None:
        try:
            self.handler(item)
            self._increment_processed()
        except BaseException as exc:
            self._increment_failed()
            if self.on_error is not None:
                self.on_error(exc, item)

    def _drop_oldest_pending(self) -> bool:
        try:
            item = self._queue.get_nowait()
        except queue.Empty:
            return False
        self._queue.task_done()
        if item is not self._critical_token:
            self._increment_dropped()
        return True

    def _drop_all_pending(self) -> None:
        dropped = 0
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is not self._sentinel and item is not self._critical_token:
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
