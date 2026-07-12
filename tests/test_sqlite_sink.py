import json
import sqlite3
import time
from datetime import datetime, timezone
from threading import Event

from dr_manhattan.models.order import Order, OrderSide, OrderStatus
from dr_manhattan.runtime import OrderIntent, OrderResult, SqliteEventSink


def wait_until(condition, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.005)
    return condition()


def gate_worker(sink):
    """Wrap the sink's handler so the worker blocks until the gate is set."""
    entered = Event()
    gate = Event()
    inner = sink._worker.handler

    def gated(item):
        entered.set()
        assert gate.wait(timeout=5)
        inner(item)

    sink._worker.handler = gated
    return entered, gate


def read_events(db_path):
    con = sqlite3.connect(db_path)
    try:
        return [row[0] for row in con.execute("SELECT event FROM events ORDER BY id")]
    finally:
        con.close()


def test_sqlite_event_sink_persists_config_and_events(tmp_path):
    db_path = tmp_path / "events.sqlite3"
    sink = SqliteEventSink(
        db_path,
        run_id="run-1",
        name="test-run",
        config={"threshold_bps": 200, "venues": ["polymarket", "target-venue"]},
    )

    assert sink.write("opportunity_seen", market_id="m1", edge_bps=250)
    sink.close()

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        run = con.execute("SELECT * FROM runs WHERE run_id = 'run-1'").fetchone()
        assert run["name"] == "test-run"
        assert json.loads(run["config_json"]) == {
            "threshold_bps": 200,
            "venues": ["polymarket", "target-venue"],
        }
        config_rows = {
            row["key"]: json.loads(row["value_json"])
            for row in con.execute("SELECT key, value_json FROM run_config_values")
        }
        assert config_rows == {
            "threshold_bps": 200,
            "venues": ["polymarket", "target-venue"],
        }
        events = con.execute("SELECT event, payload_json FROM events ORDER BY id").fetchall()
        assert [row["event"] for row in events] == ["run_start", "opportunity_seen"]
        assert json.loads(events[1]["payload_json"]) == {"edge_bps": 250, "market_id": "m1"}
    finally:
        con.close()


def test_sqlite_event_sink_can_be_used_as_post_order_hook(tmp_path):
    db_path = tmp_path / "orders.sqlite3"
    sink = SqliteEventSink(db_path, run_id="run-2", config={"mode": "test"})
    hook = sink.order_result_hook()
    intent = OrderIntent(
        venue="target-venue",
        market_id="123",
        outcome="Yes",
        side=OrderSide.BUY,
        price=0.42,
        size=2,
    )
    order = Order(
        id="order-1",
        market_id="123",
        outcome="Yes",
        side=OrderSide.BUY,
        price=0.42,
        size=2,
        filled=0,
        status=OrderStatus.OPEN,
        created_at=datetime.now(timezone.utc),
    )

    hook(OrderResult.success(intent, order, started_ns=1_000_000, finished_ns=3_000_000))
    sink.close()

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        row = con.execute("SELECT payload_json FROM events WHERE event = 'order_result'").fetchone()
        payload = json.loads(row["payload_json"])
        assert payload["venue"] == "target-venue"
        assert payload["latency_ms"] == 2.0
        assert payload["order"]["id"] == "order-1"
        assert payload["succeeded"] is True
    finally:
        con.close()


def test_sqlite_event_sink_disabled_without_path():
    sink = SqliteEventSink(None, run_id="disabled")

    assert sink.enabled is False
    assert sink.write("event") is False
    assert sink.stats.submitted == 0


def test_sqlite_sink_critical_events_survive_queue_pressure(tmp_path):
    db_path = tmp_path / "pressure.sqlite3"
    sink = SqliteEventSink(db_path, run_id="run-pressure", queue_size=1)
    assert wait_until(lambda: sink.stats.processed >= 1)
    entered, gate = gate_worker(sink)

    assert sink.write("tick", seq=1)
    assert entered.wait(timeout=2)
    assert sink.write("tick", seq=2)
    assert sink.write("tick", seq=3) is False
    assert sink.write("order_result", seq=4)
    assert sink.write("audit", critical=True, seq=5)

    gate.set()
    sink.close()

    events = read_events(db_path)
    assert "order_result" in events
    assert "audit" in events
    assert events.count("tick") == 2
    assert sink.dropped_by_event == {"tick": 1}
    assert sink.stats.dropped == 1


def test_sqlite_sink_custom_critical_events(tmp_path):
    db_path = tmp_path / "custom.sqlite3"
    sink = SqliteEventSink(db_path, run_id="run-custom", queue_size=1, critical_events=("fill",))
    assert wait_until(lambda: sink.stats.processed >= 1)
    entered, gate = gate_worker(sink)

    assert sink.write("tick", seq=1)
    assert entered.wait(timeout=2)
    assert sink.write("tick", seq=2)
    assert sink.write("tick", seq=3) is False
    assert sink.write("fill", size=2.0)

    gate.set()
    sink.close()

    assert "fill" in read_events(db_path)
    assert sink.dropped_by_event == {"tick": 1}


def test_sqlite_sink_recovers_after_transient_write_failure(tmp_path):
    db_path = tmp_path / "recover.sqlite3"
    sink = SqliteEventSink(db_path, run_id="run-recover")
    assert wait_until(lambda: sink.stats.processed >= 1)

    sink._conn.close()

    assert sink.write("after_failure", ok=True)
    assert wait_until(lambda: sink.stats.processed >= 2)
    assert sink.stats.failed == 0
    sink.close()

    assert "after_failure" in read_events(db_path)


def test_sqlite_sink_gives_up_poison_event_after_bounded_retries(tmp_path):
    db_path = tmp_path / "poison.sqlite3"
    sink = SqliteEventSink(db_path, run_id="run-poison")
    assert wait_until(lambda: sink.stats.processed >= 1)

    real_ensure = sink._ensure_connection
    failures = {"count": 0}

    def flaky_ensure():
        if failures["count"] < 3:
            failures["count"] += 1
            raise sqlite3.OperationalError("disk I/O error")
        return real_ensure()

    sink._ensure_connection = flaky_ensure

    assert sink.write("lost_event", seq=1)
    assert sink.write("kept_event", seq=2)
    assert wait_until(lambda: sink.stats.failed >= 1 and sink.stats.processed >= 2)
    sink.close()

    events = read_events(db_path)
    assert "kept_event" in events
    assert "lost_event" not in events
    assert sink.stats.failed == 1


def test_sqlite_sink_close_finalizes_run_after_connection_reset(tmp_path):
    db_path = tmp_path / "finalize.sqlite3"
    sink = SqliteEventSink(db_path, run_id="run-finalize")
    assert wait_until(lambda: sink.stats.processed >= 1)

    sink._conn.close()
    sink._conn = None
    sink.close()

    con = sqlite3.connect(db_path)
    try:
        row = con.execute(
            "SELECT closed_ts_ms, dropped_events FROM runs WHERE run_id = 'run-finalize'"
        ).fetchone()
    finally:
        con.close()
    assert row[0] is not None
    assert row[1] == 0
