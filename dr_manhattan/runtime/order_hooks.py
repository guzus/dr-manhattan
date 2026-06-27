"""Composable order hook primitives."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from time import time_ns
from typing import Any, Callable, Mapping, Protocol

from dr_manhattan.models.order import Order, OrderSide

from .async_worker import AsyncWorker, OverflowPolicy


@dataclass(frozen=True)
class OrderIntent:
    market_id: str
    outcome: str
    side: OrderSide
    price: float
    size: float
    params: Mapping[str, Any] = field(default_factory=dict)
    venue: str | None = None
    context: Mapping[str, Any] = field(default_factory=dict)

    def with_updates(self, **updates: Any) -> "OrderIntent":
        return replace(self, **updates)


@dataclass(frozen=True)
class OrderDecision:
    allowed: bool
    intent: OrderIntent
    reason: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def allow(
        cls,
        intent: OrderIntent,
        *,
        reason: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "OrderDecision":
        return cls(True, intent, reason=reason, metadata=metadata or {})

    @classmethod
    def reject(
        cls,
        intent: OrderIntent,
        reason: str,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> "OrderDecision":
        return cls(False, intent, reason=reason, metadata=metadata or {})


@dataclass(frozen=True)
class OrderResult:
    intent: OrderIntent
    started_ns: int
    finished_ns: int
    order: Order | None = None
    error: BaseException | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def success(
        cls,
        intent: OrderIntent,
        order: Order,
        *,
        started_ns: int,
        finished_ns: int | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "OrderResult":
        return cls(
            intent=intent,
            order=order,
            started_ns=started_ns,
            finished_ns=finished_ns or time_ns(),
            metadata=metadata or {},
        )

    @classmethod
    def failure(
        cls,
        intent: OrderIntent,
        error: BaseException,
        *,
        started_ns: int,
        finished_ns: int | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "OrderResult":
        return cls(
            intent=intent,
            error=error,
            started_ns=started_ns,
            finished_ns=finished_ns or time_ns(),
            metadata=metadata or {},
        )

    @property
    def succeeded(self) -> bool:
        return self.order is not None and self.error is None

    @property
    def latency_ms(self) -> float:
        return max(0.0, (self.finished_ns - self.started_ns) / 1_000_000)


class PreOrderHook(Protocol):
    def __call__(self, intent: OrderIntent) -> OrderDecision | OrderIntent | None: ...


class PostOrderHook(Protocol):
    def __call__(self, result: OrderResult) -> None: ...


class PostOrderDispatcher:
    def __init__(
        self,
        hooks: list[PostOrderHook] | tuple[PostOrderHook, ...],
        *,
        on_error: Callable[[BaseException, OrderResult, PostOrderHook], None] | None = None,
    ) -> None:
        self.hooks = tuple(hooks)
        self.on_error = on_error

    def __call__(self, result: OrderResult) -> None:
        for hook in self.hooks:
            try:
                hook(result)
            except BaseException as exc:
                if self.on_error is not None:
                    self.on_error(exc, result, hook)


class OrderHookPipeline:
    """Run pre-order hooks synchronously and post-order hooks optionally async."""

    def __init__(
        self,
        *,
        pre_order_hooks: list[PreOrderHook] | tuple[PreOrderHook, ...] = (),
        post_order_hooks: list[PostOrderHook] | tuple[PostOrderHook, ...] = (),
        post_order_worker: AsyncWorker[OrderResult] | None = None,
        post_order_async: bool = False,
        post_order_queue_size: int = 1000,
        post_order_overflow_policy: OverflowPolicy = OverflowPolicy.DROP_NEWEST,
        fail_closed: bool = True,
        on_post_order_error: (
            Callable[[BaseException, OrderResult, PostOrderHook], None] | None
        ) = None,
    ) -> None:
        self.pre_order_hooks = tuple(pre_order_hooks)
        self.dispatcher = PostOrderDispatcher(post_order_hooks, on_error=on_post_order_error)
        if post_order_worker is None and post_order_async:
            post_order_worker = AsyncWorker(
                self.dispatcher,
                name="dr-manhattan-post-order-hooks",
                queue_size=post_order_queue_size,
                overflow_policy=post_order_overflow_policy,
            )
            self._owns_post_order_worker = True
        else:
            self._owns_post_order_worker = False
        self.post_order_worker = post_order_worker
        self.fail_closed = fail_closed

    def prepare(self, intent: OrderIntent) -> OrderDecision:
        current = intent
        for hook in self.pre_order_hooks:
            try:
                decision = hook(current)
            except BaseException as exc:
                if self.fail_closed:
                    return OrderDecision.reject(
                        current,
                        "pre_order_hook_error",
                        metadata={"hook": hook_name(hook), "error": str(exc)},
                    )
                continue
            if decision is None:
                continue
            if isinstance(decision, OrderIntent):
                current = decision
                continue
            if not decision.allowed:
                return decision
            current = decision.intent
        return OrderDecision.allow(current)

    def emit_result(self, result: OrderResult) -> bool:
        if self.post_order_worker is not None:
            return self.post_order_worker.submit(result)
        self.dispatcher(result)
        return True

    def close(self, *, timeout: float | None = 5.0) -> None:
        if self._owns_post_order_worker and self.post_order_worker is not None:
            self.post_order_worker.close(timeout=timeout)


def hook_name(hook: Any) -> str:
    return getattr(hook, "__name__", hook.__class__.__name__)
