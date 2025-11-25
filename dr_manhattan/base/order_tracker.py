"""
Order tracking and fill detection for exchanges.

Provides callbacks for order lifecycle events (fill, partial fill, cancel).
Works with any exchange via polling-based status tracking.
"""

import time
import threading
from typing import Dict, List, Callable, Optional, Any
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
class OrderState:
    """Tracks the state of an order"""
    order: Order
    initial_filled: float
    last_filled: float
    last_status: OrderStatus
    created_time: datetime = field(default_factory=datetime.now)
    last_checked: datetime = field(default_factory=datetime.now)


OrderCallback = Callable[[OrderEvent, Order, Optional[float]], None]


class OrderTracker:
    """
    Tracks orders and detects fill events via polling.

    Usage:
        tracker = OrderTracker(exchange, poll_interval=1.0)

        # Register callbacks
        tracker.on_fill(lambda event, order, fill_size: print(f"Filled: {order.id}"))

        # Start tracking
        tracker.start()

        # Create orders through the tracker to auto-track them
        order = tracker.create_order(exchange, market_id, outcome, side, price, size)

        # Or manually track an order
        tracker.track_order(order, market_id)

        # Stop when done
        tracker.stop()
    """

    def __init__(
        self,
        exchange,
        poll_interval: float = 1.0,
        auto_start: bool = False,
        verbose: bool = False,
    ):
        """
        Initialize order tracker.

        Args:
            exchange: Exchange instance to track orders on
            poll_interval: How often to poll for order updates (seconds)
            auto_start: Start polling immediately
            verbose: Enable verbose logging
        """
        self.exchange = exchange
        self.poll_interval = poll_interval
        self.verbose = verbose

        self._tracked_orders: Dict[str, OrderState] = {}
        self._callbacks: List[OrderCallback] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        if auto_start:
            self.start()

    def on_fill(self, callback: OrderCallback) -> "OrderTracker":
        """
        Register a callback for order fill events.

        The callback receives (event, order, fill_size) where:
        - event: OrderEvent (FILLED, PARTIAL_FILL, CANCELLED, etc.)
        - order: The Order object with updated state
        - fill_size: Size filled in this event (for partial fills)

        Returns self for chaining.
        """
        self._callbacks.append(callback)
        return self

    def on(self, callback: OrderCallback) -> "OrderTracker":
        """Alias for on_fill"""
        return self.on_fill(callback)

    def track_order(self, order: Order, market_id: Optional[str] = None) -> None:
        """
        Start tracking an order for fill events.

        Args:
            order: Order to track
            market_id: Market ID (some exchanges need this to fetch order status)
        """
        with self._lock:
            if order.id in self._tracked_orders:
                return

            self._tracked_orders[order.id] = OrderState(
                order=order,
                initial_filled=order.filled,
                last_filled=order.filled,
                last_status=order.status,
            )

            if self.verbose:
                logger.info(f"Tracking order {order.id[:16]}... ({order.side.value} {order.size} @ {order.price})")

    def untrack_order(self, order_id: str) -> None:
        """Stop tracking an order"""
        with self._lock:
            self._tracked_orders.pop(order_id, None)

    def create_order(
        self,
        market_id: str,
        outcome: str,
        side,
        price: float,
        size: float,
        params: Optional[Dict[str, Any]] = None,
    ) -> Order:
        """
        Create an order and automatically track it.

        Uses the exchange's create_order method and adds the order to tracking.
        """
        order = self.exchange.create_order(
            market_id=market_id,
            outcome=outcome,
            side=side,
            price=price,
            size=size,
            params=params,
        )
        self.track_order(order, market_id)
        self._emit(OrderEvent.CREATED, order, 0)
        return order

    def start(self) -> None:
        """Start the background polling thread"""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

        if self.verbose:
            logger.info(f"OrderTracker started (poll interval: {self.poll_interval}s)")

    def stop(self) -> None:
        """Stop the background polling thread"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

        if self.verbose:
            logger.info("OrderTracker stopped")

    def _poll_loop(self) -> None:
        """Background polling loop"""
        while self._running:
            try:
                self._check_orders()
            except Exception as e:
                if self.verbose:
                    logger.warning(f"OrderTracker poll error: {e}")
            time.sleep(self.poll_interval)

    def _check_orders(self) -> None:
        """Check all tracked orders for status changes"""
        with self._lock:
            order_ids = list(self._tracked_orders.keys())

        completed_orders = []

        for order_id in order_ids:
            with self._lock:
                state = self._tracked_orders.get(order_id)
                if not state:
                    continue

            try:
                # Fetch current order status
                market_id = state.order.market_id
                current_order = self.exchange.fetch_order(order_id, market_id=market_id)

                # Detect fill events
                fill_delta = current_order.filled - state.last_filled

                if fill_delta > 0:
                    # There was a fill
                    if current_order.status == OrderStatus.FILLED:
                        self._emit(OrderEvent.FILLED, current_order, fill_delta)
                        completed_orders.append(order_id)
                    else:
                        self._emit(OrderEvent.PARTIAL_FILL, current_order, fill_delta)

                    # Update state
                    with self._lock:
                        if order_id in self._tracked_orders:
                            self._tracked_orders[order_id].last_filled = current_order.filled
                            self._tracked_orders[order_id].last_status = current_order.status
                            self._tracked_orders[order_id].order = current_order
                            self._tracked_orders[order_id].last_checked = datetime.now()

                elif current_order.status != state.last_status:
                    # Status changed without fill (cancelled, rejected, etc.)
                    if current_order.status == OrderStatus.CANCELLED:
                        self._emit(OrderEvent.CANCELLED, current_order, 0)
                        completed_orders.append(order_id)
                    elif current_order.status == OrderStatus.REJECTED:
                        self._emit(OrderEvent.REJECTED, current_order, 0)
                        completed_orders.append(order_id)

                    # Update state
                    with self._lock:
                        if order_id in self._tracked_orders:
                            self._tracked_orders[order_id].last_status = current_order.status
                            self._tracked_orders[order_id].order = current_order

            except Exception as e:
                if self.verbose:
                    logger.debug(f"Error checking order {order_id[:16]}...: {e}")

        # Remove completed orders from tracking
        for order_id in completed_orders:
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
            return [state.order for state in self._tracked_orders.values()]


def create_fill_logger(name: str = "OrderFill"):
    """
    Create a simple fill callback that logs to console.

    Usage:
        tracker.on_fill(create_fill_logger())
    """
    from ..utils.logger import Colors

    def log_fill(event: OrderEvent, order: Order, fill_size: float):
        timestamp = datetime.now().strftime("%H:%M:%S")

        if event == OrderEvent.FILLED:
            logger.info(
                f"[{timestamp}] {Colors.green('FILLED')} "
                f"{Colors.magenta(order.outcome)} "
                f"{order.side.value.upper()} {order.size:.2f} @ {Colors.yellow(f'{order.price:.4f}')} "
                f"| ID: {order.id[:12]}..."
            )
        elif event == OrderEvent.PARTIAL_FILL:
            logger.info(
                f"[{timestamp}] {Colors.cyan('PARTIAL')} "
                f"{Colors.magenta(order.outcome)} "
                f"{order.side.value.upper()} +{fill_size:.2f} ({order.filled:.2f}/{order.size:.2f}) "
                f"@ {Colors.yellow(f'{order.price:.4f}')} "
                f"| ID: {order.id[:12]}..."
            )
        elif event == OrderEvent.CANCELLED:
            logger.info(
                f"[{timestamp}] {Colors.red('CANCELLED')} "
                f"{Colors.magenta(order.outcome)} "
                f"{order.side.value.upper()} {order.size:.2f} @ {Colors.yellow(f'{order.price:.4f}')} "
                f"(filled: {order.filled:.2f}) | ID: {order.id[:12]}..."
            )
        elif event == OrderEvent.CREATED:
            logger.info(
                f"[{timestamp}] {Colors.gray('CREATED')} "
                f"{Colors.magenta(order.outcome)} "
                f"{order.side.value.upper()} {order.size:.2f} @ {Colors.yellow(f'{order.price:.4f}')} "
                f"| ID: {order.id[:12]}..."
            )

    return log_fill
