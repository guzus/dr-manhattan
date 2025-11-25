"""
Order tracking and fill detection for exchanges.

Provides callbacks for order lifecycle events (fill, partial fill, cancel).
Uses WebSocket trade events for real-time fill detection.
"""

import threading
from typing import Dict, List, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

from ..models.order import Order, OrderStatus
from ..utils import setup_logger

logger = setup_logger(__name__)


class OrderEvent(Enum):
    """Order lifecycle events"""
    CREATED = "created"
    PARTIAL_FILL = "partial_fill"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass
class TrackedOrder:
    """Tracks the state of an order"""
    order: Order
    total_filled: float = 0.0
    created_time: datetime = field(default_factory=datetime.now)


OrderCallback = Callable[[OrderEvent, Order, float], None]


class OrderTracker:
    """
    Tracks orders and detects fill events via WebSocket trade notifications.

    Usage:
        tracker = OrderTracker(verbose=True)

        # Register callbacks
        tracker.on_fill(lambda event, order, fill_size: print(f"Filled: {order.id}"))

        # Track orders
        tracker.track_order(order)

        # Connect to WebSocket trade events
        user_ws = exchange.get_user_websocket()
        user_ws.on_trade(tracker.handle_trade)
        user_ws.start()
    """

    def __init__(self, verbose: bool = False):
        """
        Initialize order tracker.

        Args:
            verbose: Enable verbose logging
        """
        self.verbose = verbose
        self._tracked_orders: Dict[str, TrackedOrder] = {}
        self._callbacks: List[OrderCallback] = []
        self._lock = threading.Lock()

    def on_fill(self, callback: OrderCallback) -> "OrderTracker":
        """
        Register a callback for order fill events.

        The callback receives (event, order, fill_size) where:
        - event: OrderEvent (FILLED, PARTIAL_FILL, CANCELLED, etc.)
        - order: The Order object with updated state
        - fill_size: Size filled in this event

        Returns self for chaining.
        """
        self._callbacks.append(callback)
        return self

    def on(self, callback: OrderCallback) -> "OrderTracker":
        """Alias for on_fill"""
        return self.on_fill(callback)

    def track_order(self, order: Order) -> None:
        """
        Start tracking an order for fill events.

        Args:
            order: Order to track
        """
        with self._lock:
            if order.id in self._tracked_orders:
                return

            self._tracked_orders[order.id] = TrackedOrder(
                order=order,
                total_filled=order.filled,
            )

            if self.verbose:
                logger.debug(f"Tracking order {order.id[:16]}...")

    def untrack_order(self, order_id: str) -> None:
        """Stop tracking an order"""
        with self._lock:
            self._tracked_orders.pop(order_id, None)

    def handle_trade(self, trade) -> None:
        """
        Handle a trade event from WebSocket.

        Args:
            trade: Trade object from PolymarketUserWebSocket
        """
        order_id = trade.order_id

        with self._lock:
            tracked = self._tracked_orders.get(order_id)
            if not tracked:
                return

            # Update tracked state
            tracked.total_filled += trade.size

            # Create updated order for callback
            updated_order = Order(
                id=tracked.order.id,
                market_id=trade.market_id or tracked.order.market_id,
                outcome=trade.outcome or tracked.order.outcome,
                side=tracked.order.side,
                price=trade.price,
                size=tracked.order.size,
                filled=tracked.total_filled,
                status=OrderStatus.FILLED if tracked.total_filled >= tracked.order.size else OrderStatus.PARTIALLY_FILLED,
                created_at=tracked.order.created_at,
                updated_at=datetime.now(),
            )
            tracked.order = updated_order

            # Determine event type
            is_complete = tracked.total_filled >= tracked.order.size
            event = OrderEvent.FILLED if is_complete else OrderEvent.PARTIAL_FILL

        # Emit event outside lock
        self._emit(event, updated_order, trade.size)

        # Remove if complete
        if is_complete:
            self.untrack_order(order_id)

    def _emit(self, event: OrderEvent, order: Order, fill_size: float) -> None:
        """Emit an event to all callbacks"""
        for callback in self._callbacks:
            try:
                callback(event, order, fill_size)
            except Exception as e:
                if self.verbose:
                    logger.warning(f"Callback error: {e}")

    @property
    def tracked_count(self) -> int:
        """Number of orders currently being tracked"""
        with self._lock:
            return len(self._tracked_orders)

    def get_tracked_orders(self) -> List[Order]:
        """Get list of all tracked orders"""
        with self._lock:
            return [t.order for t in self._tracked_orders.values()]

    def start(self) -> None:
        """No-op for backwards compatibility. WebSocket handles events."""
        pass

    def stop(self) -> None:
        """Clear tracked orders."""
        with self._lock:
            self._tracked_orders.clear()


def create_fill_logger():
    """
    Create a simple fill callback that logs to console.

    Usage:
        tracker.on_fill(create_fill_logger())
    """
    from ..utils.logger import Colors

    def log_fill(event: OrderEvent, order: Order, fill_size: float):
        side_str = order.side.value.upper() if hasattr(order.side, 'value') else str(order.side).upper()

        if event == OrderEvent.FILLED:
            logger.info(
                f"{Colors.green('FILLED')} "
                f"{Colors.magenta(order.outcome)} "
                f"{side_str} {fill_size:.2f} @ {Colors.yellow(f'{order.price:.4f}')}"
            )
        elif event == OrderEvent.PARTIAL_FILL:
            logger.info(
                f"{Colors.cyan('PARTIAL')} "
                f"{Colors.magenta(order.outcome)} "
                f"{side_str} +{fill_size:.2f} ({order.filled:.2f}/{order.size:.2f}) "
                f"@ {Colors.yellow(f'{order.price:.4f}')}"
            )
        elif event == OrderEvent.CANCELLED:
            logger.info(
                f"{Colors.red('CANCELLED')} "
                f"{Colors.magenta(order.outcome)} "
                f"{side_str} {order.size:.2f} @ {Colors.yellow(f'{order.price:.4f}')} "
                f"(filled: {order.filled:.2f})"
            )

    return log_fill
