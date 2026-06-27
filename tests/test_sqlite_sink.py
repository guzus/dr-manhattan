import json
import sqlite3
from datetime import datetime, timezone

from dr_manhattan.models.order import Order, OrderSide, OrderStatus
from dr_manhattan.runtime import OrderIntent, OrderResult, SqliteEventSink


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
