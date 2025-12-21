"""
Base strategy class for building trading strategies.

Inherit from Strategy to create custom trading strategies with minimal code.
"""

import time
from abc import ABC, abstractmethod
from typing import Callable, Dict, List, Optional, Tuple

from ..models.market import Market, OutcomeToken
from ..models.nav import NAV
from ..models.order import Order, OrderSide
from ..utils import setup_logger
from ..utils.logger import Colors
from ..utils.price import round_to_tick_size
from .exchange_client import (
    DeltaInfo,
    ExchangeClient,
    calculate_delta,
    format_delta_side,
)

logger = setup_logger(__name__)


class Strategy(ABC):
    """
    Base class for trading strategies.

    Provides common functionality:
    - ExchangeClient setup with order tracking
    - Market fetching and token management
    - Position, order, and orderbook helpers
    - Delta and NAV calculation
    - Status logging with colors
    - BBO market making helpers
    - Run loop with configurable interval
    - Graceful shutdown with cleanup

    Example:
        class MyStrategy(Strategy):
            def on_tick(self):
                self.log_status()
                self.place_bbo_orders()

        strategy = MyStrategy(exchange, market_id="123")
        strategy.run()
    """

    def __init__(
        self,
        exchange,
        market_id: str,
        max_position: float = 100.0,
        order_size: float = 5.0,
        max_delta: float = 20.0,
        check_interval: float = 5.0,
        track_fills: bool = True,
    ):
        """
        Initialize strategy.

        Args:
            exchange: Exchange instance (Polymarket, Opinion, etc.)
            market_id: Market ID to trade
            max_position: Maximum position size per outcome
            order_size: Default order size
            max_delta: Maximum position imbalance before reducing exposure
            check_interval: Seconds between strategy ticks
            track_fills: Enable order fill tracking
        """
        self.exchange = exchange
        self.client = ExchangeClient(exchange, track_fills=track_fills)
        self.market_id = market_id
        self.max_position = max_position
        self.order_size = order_size
        self.max_delta = max_delta
        self.check_interval = check_interval

        # Market data (populated by setup())
        self.market: Optional[Market] = None
        self.outcome_tokens: List[OutcomeToken] = []
        self.tick_size: float = 0.01

        # Runtime state
        self.is_running = False

        # Cached state (updated each tick)
        self._positions: Dict[str, float] = {}
        self._open_orders: List[Order] = []
        self._delta_info: Optional[DeltaInfo] = None
        self._nav: Optional[NAV] = None

    def setup(self) -> bool:
        """
        Fetch market and initialize strategy state.

        Override to add custom setup logic (call super().setup() first).

        Returns:
            True if setup successful, False otherwise
        """
        try:
            self.market = self.client.fetch_market(self.market_id)
        except Exception as e:
            logger.error(f"Failed to fetch market: {e}")
            return False

        if not self.market:
            logger.error(f"Market not found: {self.market_id}")
            return False

        token_ids = self.market.metadata.get("clobTokenIds", [])
        outcomes = self.market.outcomes
        self.tick_size = self.market.tick_size

        if not token_ids:
            logger.error("No token IDs found in market")
            return False

        self.outcome_tokens = [
            OutcomeToken(outcome=outcome, token_id=token_id)
            for outcome, token_id in zip(outcomes, token_ids)
        ]

        # Setup WebSocket orderbook
        self.client.setup_orderbook_websocket(self.market_id, token_ids)

        # Load initial positions
        self._positions = self.client.fetch_positions_dict_for_market(self.market)

        self._log_trader_profile()
        self._log_market_info()
        return True

    def _log_trader_profile(self):
        """Log trader profile (address and balance)"""
        logger.info(f"\n{Colors.bold('Trader Profile')}")

        address = getattr(self.exchange, "_address", None)
        if address:
            logger.info(f"Address: {Colors.cyan(address)}")

        try:
            balance = self.client.fetch_balance()
            usdc = balance.get("USDC", 0.0)
            logger.info(f"Balance: {Colors.green(f'${usdc:,.2f}')} USDC")
        except Exception as e:
            logger.warning(f"Failed to fetch balance: {e}")

    def _log_market_info(self):
        """Log market information after setup"""
        logger.info(f"\n{Colors.bold('Market:')} {Colors.cyan(self.market.question)}")
        logger.info(
            f"Outcomes: {Colors.magenta(str(self.outcomes))} | "
            f"Tick: {Colors.yellow(str(self.tick_size))} | "
            f"Vol: {Colors.cyan(f'${self.market.volume:,.0f}')}"
        )

        for i, ot in enumerate(self.outcome_tokens):
            price = self.market.prices.get(ot.outcome, 0)
            outcome_display = ot.outcome[:30] + "..." if len(ot.outcome) > 30 else ot.outcome
            logger.info(
                f"  [{i}] {Colors.magenta(outcome_display)}: {Colors.yellow(f'{price:.4f}')}"
            )

    # State management

    def refresh_state(self):
        """Refresh positions, orders, delta, and NAV"""
        self._positions = self.get_positions()
        self._open_orders = self.get_open_orders()
        self._delta_info = calculate_delta(self._positions)
        self._nav = self.client.calculate_nav(self.market)

    @property
    def positions(self) -> Dict[str, float]:
        """Current positions (call refresh_state() first)"""
        return self._positions

    @property
    def open_orders(self) -> List[Order]:
        """Current open orders (call refresh_state() first)"""
        return self._open_orders

    @property
    def delta(self) -> float:
        """Current delta (call refresh_state() first)"""
        return self._delta_info.delta if self._delta_info else 0.0

    @property
    def nav(self) -> float:
        """Current NAV (call refresh_state() first)"""
        return self._nav.nav if self._nav else 0.0

    @property
    def cash(self) -> float:
        """Current cash (call refresh_state() first)"""
        return self._nav.cash if self._nav else 0.0

    @property
    def outcomes(self) -> List[str]:
        """List of outcome names"""
        return [ot.outcome for ot in self.outcome_tokens]

    @property
    def token_ids(self) -> List[str]:
        """List of token IDs"""
        return [ot.token_id for ot in self.outcome_tokens]

    # Logging helpers

    def log_status(self):
        """Log current status with colors (NAV, positions, delta, orders)"""
        self.refresh_state()

        # Format positions
        if not self._positions:
            pos_str = Colors.gray("None")
        else:
            parts = []
            for outcome, size in self._positions.items():
                abbrev = outcome[0] if len(self.outcomes) == 2 else outcome[:8]
                parts.append(f"{Colors.blue(f'{size:.0f}')} {Colors.magenta(abbrev)}")
            pos_str = " ".join(parts)

        # Format delta side
        delta_side = ""
        if self._delta_info and self._delta_info.delta > 0 and self._delta_info.max_outcome:
            side = format_delta_side(self._delta_info, self.outcomes)
            delta_side = f" {Colors.magenta(side)}" if side else ""

        logger.info(
            f"\n[{time.strftime('%H:%M:%S')}] "
            f"{Colors.bold('NAV:')} {Colors.green(f'${self.nav:,.2f}')} | "
            f"Cash: {Colors.cyan(f'${self.cash:,.2f}')} | "
            f"Pos: {pos_str} | "
            f"Delta: {Colors.yellow(f'{self.delta:.1f}')}{delta_side} | "
            f"Orders: {Colors.cyan(str(len(self._open_orders)))}"
        )

        # Log open orders
        for order in self._open_orders:
            side_colored = (
                Colors.green(order.side.value.upper())
                if order.side == OrderSide.BUY
                else Colors.red(order.side.value.upper())
            )
            outcome_display = order.outcome[:15] if len(order.outcome) > 15 else order.outcome
            size = getattr(order, "original_size", order.size) or order.size
            logger.info(
                f"  {Colors.gray('Open:')} {Colors.magenta(outcome_display)} "
                f"{side_colored} {size:.0f} @ {Colors.yellow(f'{order.price:.4f}')}"
            )

        # Warn if delta too high
        if self.delta > self.max_delta:
            logger.warning(
                f"Delta ({self.delta:.2f}) > max ({self.max_delta:.2f}) - reducing exposure"
            )

    def log_order(
        self, side: OrderSide, size: float, outcome: str, price: float, action: str = "->"
    ):
        """Log order placement"""
        side_colored = Colors.green("BUY") if side == OrderSide.BUY else Colors.red("SELL")
        outcome_display = outcome[:15] if len(outcome) > 15 else outcome
        logger.info(
            f"    {Colors.gray(action)} {side_colored} {size:.0f} "
            f"{Colors.magenta(outcome_display)} @ {Colors.yellow(f'{price:.4f}')}"
        )

    def log_cancel(self, side: OrderSide, price: float):
        """Log order cancellation"""
        side_colored = Colors.green("BUY") if side == OrderSide.BUY else Colors.red("SELL")
        logger.info(
            f"    {Colors.gray('x Cancel')} {side_colored} @ {Colors.yellow(f'{price:.4f}')}"
        )

    # Position and order helpers

    def get_positions(self) -> Dict[str, float]:
        """
        Get current positions as dict.

        Returns:
            Dict mapping outcome name to position size
        """
        return self.client.fetch_positions_dict_for_market(self.market)

    def get_open_orders(self) -> List[Order]:
        """
        Get open orders for this market.

        Returns:
            List of Order objects
        """
        try:
            return self.client.fetch_open_orders(market_id=self.market_id)
        except Exception as e:
            logger.warning(f"Failed to fetch open orders: {e}")
            return []

    def get_orders_for_outcome(self, outcome: str) -> Tuple[List[Order], List[Order]]:
        """
        Get buy and sell orders for an outcome.

        Args:
            outcome: Outcome name

        Returns:
            Tuple of (buy_orders, sell_orders)
        """
        outcome_orders = [o for o in self._open_orders if o.outcome == outcome]
        buy_orders = [o for o in outcome_orders if o.side == OrderSide.BUY]
        sell_orders = [o for o in outcome_orders if o.side == OrderSide.SELL]
        return buy_orders, sell_orders

    def cancel_all_orders(self) -> int:
        """
        Cancel all open orders for this market.

        Returns:
            Number of orders cancelled
        """
        cancelled = self.client.cancel_all_orders(market_id=self.market_id)
        if cancelled > 0:
            logger.info(f"Cancelled {Colors.cyan(str(cancelled))} orders")
        else:
            logger.info("No open orders to cancel")
        return cancelled

    def cancel_stale_orders(
        self, orders: List[Order], target_price: float, tolerance: float = 0.001
    ) -> bool:
        """
        Cancel orders not at target price.

        Args:
            orders: List of orders to check
            target_price: Target price
            tolerance: Price tolerance

        Returns:
            True if any orders were cancelled
        """
        cancelled = False
        for order in orders:
            if abs(order.price - target_price) >= tolerance:
                try:
                    self.client.cancel_order(order.id)
                    self.log_cancel(order.side, order.price)
                    cancelled = True
                except Exception:
                    pass
        return cancelled

    def has_order_at_price(
        self, orders: List[Order], price: float, tolerance: float = 0.001
    ) -> bool:
        """Check if any order is at the given price"""
        return any(abs(o.price - price) < tolerance for o in orders)

    # Orderbook helpers

    def get_orderbook(self, token_id: str) -> Dict:
        """
        Get orderbook for a token.

        Args:
            token_id: Token ID to fetch orderbook for

        Returns:
            Dict with 'bids' and 'asks' lists
        """
        try:
            return self.client.get_orderbook(token_id)
        except Exception as e:
            logger.warning(f"Failed to fetch orderbook: {e}")
            return {"bids": [], "asks": []}

    def get_best_bid_ask(self, token_id: str) -> Tuple[Optional[float], Optional[float]]:
        """
        Get best bid and ask prices.

        Uses WebSocket orderbook if available, otherwise falls back to REST API.

        Args:
            token_id: Token ID to fetch orderbook for

        Returns:
            Tuple of (best_bid, best_ask), None if not available or invalid
        """
        return self.client.get_best_bid_ask(token_id)

    def round_price(self, price: float) -> float:
        """Round price to tick size"""
        return round_to_tick_size(price, self.tick_size)

    # Order helpers

    def get_token_id(self, outcome: str) -> Optional[str]:
        """Get token ID for an outcome"""
        for ot in self.outcome_tokens:
            if ot.outcome == outcome:
                return ot.token_id
        return None

    def create_order(
        self,
        outcome: str,
        side: OrderSide,
        price: float,
        size: float,
        token_id: Optional[str] = None,
        params: Optional[Dict] = None,
    ) -> Order:
        """
        Create an order.

        Args:
            outcome: Outcome to trade
            side: OrderSide.BUY or OrderSide.SELL
            price: Order price
            size: Order size
            token_id: Token ID (auto-resolved if not provided)
            params: Additional parameters

        Returns:
            Created Order
        """
        if token_id is None:
            token_id = self.get_token_id(outcome)

        order_params = params or {}
        if token_id:
            order_params["token_id"] = token_id

        return self.client.create_order(
            market_id=self.market_id,
            outcome=outcome,
            side=side,
            price=self.round_price(price),
            size=size,
            params=order_params,
        )

    # BBO Market Making helpers

    def place_bbo_orders(self, get_bbo: Optional[Callable] = None):
        """
        Place BBO (Best Bid/Offer) orders for all outcomes.

        This is the core market making logic:
        - Get best bid/ask for each outcome
        - Cancel stale orders
        - Place new orders at BBO if conditions met

        Args:
            get_bbo: Optional function(token_id) -> (bid, ask). Uses REST by default.
        """
        if get_bbo is None:
            get_bbo = self.get_best_bid_ask

        for ot in self.outcome_tokens:
            self._place_bbo_for_outcome(ot.outcome, ot.token_id, get_bbo)

    def _place_bbo_for_outcome(
        self,
        outcome: str,
        token_id: str,
        get_bbo: Callable,
    ):
        """Place BBO orders for a single outcome"""
        best_bid, best_ask = get_bbo(token_id)

        if best_bid is None or best_ask is None:
            return

        our_bid = self.round_price(best_bid)
        our_ask = self.round_price(best_ask)

        # Validate spread
        if our_bid >= our_ask:
            return

        position = self._positions.get(outcome, 0)
        buy_orders, sell_orders = self.get_orders_for_outcome(outcome)

        # Delta management - skip if at max position with high delta
        if self._delta_info and self.delta > self.max_delta:
            if position == self._delta_info.max_position:
                return

        # BUY order
        if not self.has_order_at_price(buy_orders, our_bid):
            self.cancel_stale_orders(buy_orders, our_bid)

            if position + self.order_size <= self.max_position:
                if self.cash >= self.order_size:
                    try:
                        self.create_order(
                            outcome, OrderSide.BUY, our_bid, self.order_size, token_id
                        )
                        self.log_order(OrderSide.BUY, self.order_size, outcome, our_bid)
                    except Exception as e:
                        logger.error(f"    BUY failed: {e}")

        # SELL order
        if not self.has_order_at_price(sell_orders, our_ask):
            self.cancel_stale_orders(sell_orders, our_ask)

            if position >= self.order_size:
                try:
                    self.create_order(outcome, OrderSide.SELL, our_ask, self.order_size, token_id)
                    self.log_order(OrderSide.SELL, self.order_size, outcome, our_ask)
                except Exception as e:
                    logger.error(f"    SELL failed: {e}")

    # Cleanup helpers

    def liquidate_positions(self):
        """
        Liquidate all positions by selling at best bid.

        Override for custom liquidation logic.
        """
        positions = self.get_positions()

        if not positions:
            logger.info("No positions to liquidate")
            return

        logger.info(f"{Colors.bold('Liquidating positions...')}")

        for outcome, size in positions.items():
            if size <= 0:
                continue

            token_id = self.get_token_id(outcome)
            if not token_id:
                logger.warning(f"  Cannot find token_id for {outcome}")
                continue

            best_bid, _ = self.get_best_bid_ask(token_id)
            if best_bid is None or best_bid <= 0:
                logger.warning(f"  {outcome}: No bid available, cannot liquidate")
                continue

            sell_size = float(int(size))
            if sell_size <= 0:
                continue

            try:
                self.create_order(outcome, OrderSide.SELL, best_bid, sell_size, token_id)
                self.log_order(OrderSide.SELL, sell_size, outcome, best_bid, "LIQUIDATE")
            except Exception as e:
                logger.error(f"  Failed to liquidate {outcome}: {e}")

    def cleanup(self):
        """
        Cleanup on shutdown.

        Default: cancel orders, liquidate positions, stop client.
        Override for custom cleanup logic.
        """
        logger.info(f"\n{Colors.bold('Cleaning up...')}")

        # Cancel all orders
        self.cancel_all_orders()

        # Liquidate positions
        self.liquidate_positions()

        # Wait for liquidation orders to fill
        time.sleep(3)

        # Check remaining orders and positions
        try:
            remaining_orders = self.client.fetch_open_orders(market_id=self.market_id)
            if remaining_orders:
                logger.warning(f"  {len(remaining_orders)} orders still open (may be unfilled)")

            remaining_positions = self.get_positions()
            if any(size > 0 for size in remaining_positions.values()):
                logger.warning(f"  Positions still open: {remaining_positions}")
        except Exception:
            pass

        self.client.stop()

    # Main loop

    @abstractmethod
    def on_tick(self):
        """
        Called each iteration of the run loop.

        Implement your trading logic here.
        """
        pass

    def on_start(self):
        """Called before the run loop starts. Override for custom startup logic."""
        pass

    def on_stop(self):
        """Called after the run loop ends. Override for custom shutdown logic."""
        pass

    def run(self, duration_minutes: Optional[int] = None):
        """
        Run the strategy.

        Args:
            duration_minutes: Run duration in minutes (None = indefinite)
        """
        logger.info(
            f"\n{Colors.bold('Strategy:')} MaxPos={Colors.blue(f'{self.max_position:.0f}')} | "
            f"Size={Colors.yellow(f'{self.order_size:.0f}')} | "
            f"MaxDelta={Colors.yellow(f'{self.max_delta:.0f}')} | "
            f"Interval={Colors.gray(f'{self.check_interval}s')}"
        )

        if not self.setup():
            logger.error("Setup failed. Exiting.")
            return

        self.on_start()
        self.is_running = True

        start_time = time.time()
        end_time = start_time + (duration_minutes * 60) if duration_minutes else None

        try:
            while self.is_running:
                if end_time and time.time() >= end_time:
                    break

                self.on_tick()
                time.sleep(self.check_interval)

        except KeyboardInterrupt:
            logger.info("\nStopping...")

        finally:
            self.is_running = False
            self.on_stop()
            self.cleanup()
            logger.info("Strategy stopped")

    def stop(self):
        """Signal the strategy to stop"""
        self.is_running = False
