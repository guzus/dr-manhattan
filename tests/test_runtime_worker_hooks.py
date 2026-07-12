import time
from datetime import datetime, timezone
from threading import Event, Thread

from dr_manhattan.models.order import Order, OrderSide, OrderStatus
from dr_manhattan.runtime import (
    AsyncWorker,
    OrderDecision,
    OrderHookPipeline,
    OrderIntent,
    OrderResult,
    OverflowPolicy,
)


def test_async_worker_processes_items_and_reports_stats():
    processed = []

    worker = AsyncWorker(processed.append, queue_size=4)
    assert worker.submit("a")
    assert worker.submit("b")
    worker.close()

    assert processed == ["a", "b"]
    assert worker.stats.submitted == 2
    assert worker.stats.processed == 2
    assert worker.stats.failed == 0
    assert worker.stats.dropped == 0


def test_async_worker_drop_newest_overflow_is_non_blocking():
    entered = Event()
    release = Event()
    processed = []

    def handler(item):
        entered.set()
        release.wait(timeout=1)
        processed.append(item)

    worker = AsyncWorker(handler, queue_size=1, overflow_policy=OverflowPolicy.DROP_NEWEST)
    assert worker.submit("first")
    assert entered.wait(timeout=1)
    assert worker.submit("second")
    dropped = worker.submit("third")

    release.set()
    worker.close()

    assert dropped is False
    assert processed == ["first", "second"]
    assert worker.stats.dropped == 1


def wait_until(condition, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.005)
    return condition()


def test_async_worker_critical_lane_bypasses_full_queue():
    entered = Event()
    release = Event()
    processed = []

    def handler(item):
        entered.set()
        release.wait(timeout=5)
        processed.append(item)

    worker = AsyncWorker(handler, queue_size=1, overflow_policy=OverflowPolicy.DROP_NEWEST)
    assert worker.submit("first")
    assert entered.wait(timeout=1)
    assert worker.submit("second")
    assert worker.submit("third") is False
    assert worker.submit("critical-1", critical=True)
    assert worker.submit("critical-2", critical=True)
    assert worker.stats.critical_pending == 2

    release.set()
    worker.close()

    assert processed == ["first", "critical-1", "critical-2", "second"]
    assert worker.stats.submitted == 4
    assert worker.stats.dropped == 1
    assert worker.stats.critical_pending == 0


def test_async_worker_critical_wakes_idle_worker():
    processed = []

    worker = AsyncWorker(processed.append, queue_size=4)
    assert worker.submit("money", critical=True)

    assert wait_until(lambda: worker.stats.processed == 1)
    worker.close()

    assert processed == ["money"]


def test_async_worker_close_without_drain_still_flushes_critical():
    entered = Event()
    release = Event()
    processed = []

    def handler(item):
        entered.set()
        release.wait(timeout=5)
        processed.append(item)

    worker = AsyncWorker(handler, queue_size=1)
    assert worker.submit("regular-1")
    assert entered.wait(timeout=1)
    assert worker.submit("regular-2")
    assert worker.submit("critical-1", critical=True)

    closer = Thread(target=lambda: worker.close(drain=False))
    closer.start()
    assert wait_until(lambda: worker.stats.dropped >= 1)
    release.set()
    closer.join(timeout=5)

    assert processed == ["regular-1", "critical-1"]
    assert worker.stats.dropped == 1


def test_order_pipeline_runs_pre_order_hooks_synchronously():
    intent = OrderIntent(
        venue="predictfun",
        market_id="123",
        outcome="Yes",
        side=OrderSide.BUY,
        price=0.42,
        size=10,
    )

    def cap_size(candidate: OrderIntent) -> OrderIntent:
        return candidate.with_updates(size=min(candidate.size, 2.5))

    def reject_low_price(candidate: OrderIntent) -> OrderDecision:
        if candidate.price < 0.05:
            return OrderDecision.reject(candidate, "price_below_floor")
        return OrderDecision.allow(candidate)

    pipeline = OrderHookPipeline(pre_order_hooks=[cap_size, reject_low_price])
    decision = pipeline.prepare(intent)

    assert decision.allowed is True
    assert decision.intent.size == 2.5

    rejected = pipeline.prepare(intent.with_updates(price=0.01))
    assert rejected.allowed is False
    assert rejected.reason == "price_below_floor"


def test_order_pipeline_queues_post_order_hooks():
    received = []
    pipeline = OrderHookPipeline(
        post_order_hooks=[lambda result: received.append(result.order.id)],
        post_order_async=True,
        post_order_queue_size=4,
    )
    intent = OrderIntent("123", "Yes", OrderSide.BUY, 0.42, 2)
    order = sample_order()

    assert pipeline.emit_result(
        OrderResult.success(intent, order, started_ns=1_000_000, finished_ns=2_000_000)
    )
    pipeline.close()

    assert received == ["order-1"]


def test_order_pipeline_emit_result_survives_full_post_order_queue():
    entered = Event()
    release = Event()
    received = []

    def slow_hook(item):
        entered.set()
        release.wait(timeout=5)
        received.append(item)

    pipeline = OrderHookPipeline(
        post_order_hooks=[slow_hook],
        post_order_async=True,
        post_order_queue_size=1,
    )
    worker = pipeline.post_order_worker
    assert worker is not None
    assert worker.submit("blocker")
    assert entered.wait(timeout=1)
    assert worker.submit("filler")
    assert worker.submit("overflow") is False

    intent = OrderIntent("123", "Yes", OrderSide.BUY, 0.42, 2)
    result = OrderResult.success(intent, sample_order(), started_ns=1, finished_ns=2)
    assert pipeline.emit_result(result)

    release.set()
    pipeline.close()

    assert received == ["blocker", result, "filler"]
    assert worker.stats.dropped == 1


def test_order_pipeline_dispatches_post_hooks_without_failing_other_hooks():
    errors = []
    received = []
    intent = OrderIntent("123", "Yes", OrderSide.BUY, 0.42, 2)
    order = sample_order()
    result = OrderResult.success(intent, order, started_ns=1, finished_ns=1_000_001)

    def bad_hook(_result):
        raise RuntimeError("alert backend unavailable")

    def good_hook(hook_result):
        received.append(hook_result.latency_ms)

    pipeline = OrderHookPipeline(
        post_order_hooks=[bad_hook, good_hook],
        on_post_order_error=lambda exc, _result, hook: errors.append((str(exc), hook.__name__)),
    )

    assert pipeline.emit_result(result)

    assert errors == [("alert backend unavailable", "bad_hook")]
    assert received == [1.0]


def sample_order() -> Order:
    return Order(
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
