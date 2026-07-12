"""SQLite event sink backed by AsyncWorker."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from dr_manhattan.models.order import Order

from .async_worker import AsyncWorker, OverflowPolicy, WorkerStats
from .order_hooks import OrderResult

SCHEMA_VERSION = 1

# Attempts per event before it is surfaced to on_error; the connection is
# reset between attempts so a broken cached connection cannot wedge the sink.
SQLITE_WRITE_ATTEMPTS = 3

SQLITE_EVENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    started_ts_ms INTEGER NOT NULL,
    started_at_utc TEXT NOT NULL,
    pid INTEGER NOT NULL,
    name TEXT NOT NULL,
    config_json TEXT NOT NULL,
    sqlite_queue_size INTEGER NOT NULL,
    overflow_policy TEXT NOT NULL,
    closed_ts_ms INTEGER,
    dropped_events INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS run_config_values (
    run_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    PRIMARY KEY (run_id, key),
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    ts_ms INTEGER NOT NULL,
    event TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_events_run_ts ON events(run_id, ts_ms);
CREATE INDEX IF NOT EXISTS idx_events_event_ts ON events(event, ts_ms);
"""


@dataclass(frozen=True)
class SqliteEvent:
    event: str
    ts_ms: int
    payload: Mapping[str, Any]


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def iso_utc_ms(ts_ms: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts_ms / 1000))


class SqliteEventSink:
    """Persist JSON events to SQLite without blocking the caller.

    The hot path only serializes a small event object and submits it to
    AsyncWorker. SQLite connection setup, schema creation, and inserts happen in
    the background thread.

    Events named in critical_events (and writes with critical=True) are
    money-path records: they are never dropped under queue pressure, and they
    are flushed even on close(drain=False).
    """

    def __init__(
        self,
        path: str | os.PathLike[str] | None,
        *,
        run_id: str,
        name: str = "dr-manhattan-run",
        config: Mapping[str, Any] | None = None,
        started_ms: int | None = None,
        queue_size: int = 10_000,
        overflow_policy: OverflowPolicy = OverflowPolicy.DROP_NEWEST,
        critical_events: Iterable[str] = ("order_result",),
    ) -> None:
        self.path = Path(path).expanduser() if path else None
        if self.path and not self.path.is_absolute():
            self.path = Path.cwd() / self.path
        self.run_id = run_id
        self.name = name
        self.config = dict(config or {})
        self.started_ms = started_ms or now_ms()
        self.queue_size = max(1, int(queue_size))
        self.overflow_policy = overflow_policy
        self.critical_events = frozenset(critical_events)
        self._conn: sqlite3.Connection | None = None
        self._closed = False
        self._worker: AsyncWorker[SqliteEvent] | None = None
        self._drop_lock = threading.Lock()
        self._dropped_by_event: dict[str, int] = {}
        self._dropped_total = 0
        self._write_failures = 0

        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._worker = AsyncWorker(
                self._handle_event,
                name=f"{self.name}-sqlite-sink",
                queue_size=self.queue_size,
                overflow_policy=self.overflow_policy,
                on_error=self._on_worker_error,
            )
            self.write("run_start", name=self.name)

    @property
    def enabled(self) -> bool:
        return self._worker is not None

    @property
    def stats(self) -> WorkerStats:
        if self._worker is None:
            return WorkerStats()
        return self._worker.stats

    @property
    def dropped_by_event(self) -> dict[str, int]:
        """Copy of per-event drop counts for regular events lost to queue pressure."""
        with self._drop_lock:
            return dict(self._dropped_by_event)

    def write(
        self,
        event: str,
        *,
        ts_ms: int | None = None,
        critical: bool | None = None,
        **payload: Any,
    ) -> bool:
        """Queue an event for SQLite persistence.

        critical=None resolves against critical_events; critical events are
        never dropped under queue pressure.
        """
        if self._worker is None or self._closed:
            return False
        record = SqliteEvent(event=event, ts_ms=ts_ms or now_ms(), payload=payload)
        if critical is None:
            critical = event in self.critical_events
        accepted = self._worker.submit(record, critical=critical)
        if not accepted:
            self._record_drop(event)
        return accepted

    def order_result_hook(self, event: str = "order_result") -> Callable[[OrderResult], None]:
        """Return a post-order hook that persists OrderResult values."""

        def hook(result: OrderResult) -> None:
            self.write(event, critical=True, **order_result_payload(result))

        return hook

    def close(self, *, timeout: float | None = 5.0, drain: bool = True) -> None:
        if self._worker is None or self._closed:
            return
        self._closed = True
        self._worker.close(timeout=timeout, drain=drain)
        self._close_connection()

    def _handle_event(self, item: SqliteEvent) -> None:
        payload_json = json_dumps(dict(item.payload))
        # A failed write must never leave the sink permanently dark while the
        # process keeps trading: reset the cached connection and retry before
        # surfacing the event to on_error.
        last_exc: Exception | None = None
        for _ in range(SQLITE_WRITE_ATTEMPTS):
            try:
                conn = self._ensure_connection()
                conn.execute(
                    """
                    INSERT INTO events(run_id, ts_ms, event, payload_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (self.run_id, item.ts_ms, item.event, payload_json),
                )
                conn.commit()
                return
            except Exception as exc:
                last_exc = exc
                self._reset_connection()
        if last_exc is None:
            raise RuntimeError("sqlite write retry loop exited without a result")
        raise last_exc

    def _record_drop(self, event: str) -> None:
        line = None
        with self._drop_lock:
            self._dropped_by_event[event] = self._dropped_by_event.get(event, 0) + 1
            self._dropped_total += 1
            total = self._dropped_total
            if total == 1 or total % 1000 == 0:
                top = sorted(self._dropped_by_event.items(), key=lambda kv: -kv[1])[:3]
                top_text = ",".join(f"{name}:{count}" for name, count in top)
                line = f"sqlite_event_sink queue_full dropped_events={total} top={top_text}"
        if line:
            print(line, file=sys.stderr)

    def _reset_connection(self) -> None:
        conn, self._conn = self._conn, None
        if conn is None:
            return
        try:
            conn.close()
        except Exception:
            pass

    def _ensure_connection(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        if self.path is None:
            raise RuntimeError("SQLite sink path is disabled")
        conn = sqlite3.connect(str(self.path), timeout=1.0, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA busy_timeout=1000")
        conn.executescript(SQLITE_EVENT_SCHEMA)
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES (?, ?)",
            ("schema_version", str(SCHEMA_VERSION)),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO runs (
                run_id, started_ts_ms, started_at_utc, pid, name, config_json,
                sqlite_queue_size, overflow_policy, dropped_events
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                self.run_id,
                self.started_ms,
                iso_utc_ms(self.started_ms),
                os.getpid(),
                self.name,
                json_dumps(self.config),
                self.queue_size,
                self.overflow_policy.value,
            ),
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO run_config_values(run_id, key, value_json)
            VALUES (?, ?, ?)
            """,
            [(self.run_id, key, json_dumps(value)) for key, value in sorted(self.config.items())],
        )
        conn.commit()
        self._conn = conn
        return conn

    def _close_connection(self) -> None:
        if self.path is None:
            return
        stats = self.stats
        # The connection may have been reset by a mid-run write failure;
        # reconnect so the run row still gets finalized.
        try:
            conn = self._ensure_connection()
            conn.execute(
                """
                UPDATE runs
                SET closed_ts_ms = ?, dropped_events = ?
                WHERE run_id = ?
                """,
                (now_ms(), stats.dropped, self.run_id),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            print(f"sqlite_event_sink close failed error={exc}", file=sys.stderr)
        finally:
            self._conn = None

    def _on_worker_error(self, exc: BaseException, item: SqliteEvent) -> None:
        # Called from the worker thread only.
        self._write_failures += 1
        failures = self._write_failures
        if failures == 1 or failures % 100 == 0:
            print(
                f"sqlite_event_sink write failed (failures={failures}) "
                f"event={item.event} error={exc}",
                file=sys.stderr,
            )


def order_result_payload(result: OrderResult) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "venue": result.intent.venue,
        "market_id": result.intent.market_id,
        "outcome": result.intent.outcome,
        "side": result.intent.side.value,
        "price": result.intent.price,
        "size": result.intent.size,
        "params": dict(result.intent.params),
        "context": dict(result.intent.context),
        "started_ns": result.started_ns,
        "finished_ns": result.finished_ns,
        "latency_ms": result.latency_ms,
        "succeeded": result.succeeded,
        "metadata": dict(result.metadata),
    }
    if result.order is not None:
        payload["order"] = order_payload(result.order)
    if result.error is not None:
        payload["error"] = {
            "type": result.error.__class__.__name__,
            "message": str(result.error),
        }
    return payload


def order_payload(order: Order) -> dict[str, Any]:
    return {
        "id": order.id,
        "market_id": order.market_id,
        "outcome": order.outcome,
        "side": order.side.value,
        "price": order.price,
        "size": order.size,
        "filled": order.filled,
        "status": order.status.value,
        "created_at": order.created_at.isoformat(),
        "updated_at": order.updated_at.isoformat() if order.updated_at else None,
        "time_in_force": order.time_in_force.value,
    }
