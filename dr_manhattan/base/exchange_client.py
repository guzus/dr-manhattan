"""
Exchange client with state management.

Provides stateful wrapper around Exchange for tracking positions, NAV, and client state.
Exchange is regarded as stateless; ExchangeClient maintains client-specific state.
"""

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..models.market import Market
from ..models.nav import NAV, PositionBreakdown
from ..models.order import Order, OrderSide
from ..models.orderbook import Orderbook, OrderbookManager
from ..models.position import Position
from ..utils import setup_logger
from .order_tracker import OrderCallback, OrderTracker, create_fill_logger

logger = setup_logger(__name__)


@dataclass
class DeltaInfo:
    """Delta (position imbalance) information"""

    delta: float
    max_position: float
    min_position: float
    max_outcome: Optional[str]

    @property
    def is_balanced(self) -> bool:
        """Check if positions are balanced (delta near zero)"""
        return abs(self.delta) < 0.01


@dataclass
class StrategyState:
    """
    Unified state snapshot for trading strategies.

    Contains NAV, positions, delta, and order information.
    Used by spread strategies to track current state.
    """

    nav: float
    cash: float
    positions_value: float
    positions: Dict[str, float]
    delta_info: DeltaInfo
    open_orders_count: int
    nav_breakdown: Optional[NAV] = None

    @classmethod
    def from_client(
        cls,
        client: "ExchangeClient",
        market: Market,
        positions: Optional[Dict[str, float]] = None,
        open_orders_count: int = 0,
    ) -> "StrategyState":
        """
        Create state snapshot from exchange client.

        Args:
            client: ExchangeClient instance
            market: Market object for NAV calculation
            positions: Dict of outcome -> position size (if already fetched)
            open_orders_count: Number of open orders

        Returns:
            StrategyState instance
        """
        nav_data = client.calculate_nav(market)

        if positions is None:
            positions = {}
            positions_list = client.get_positions(market.id)
            for pos in positions_list:
                positions[pos.outcome] = pos.size

        delta_info = calculate_delta(positions)

        return cls(
            nav=nav_data.nav,
            cash=nav_data.cash,
            positions_value=nav_data.positions_value,
            positions=positions,
            delta_info=delta_info,
            open_orders_count=open_orders_count,
            nav_breakdown=nav_data,
        )

    def get_position(self, outcome: str) -> float:
        """Get position size for an outcome"""
        return self.positions.get(outcome, 0.0)

    def exceeds_max_delta(self, max_delta: float) -> bool:
        """Check if current delta exceeds maximum allowed"""
        return self.delta_info.delta > max_delta

    def is_max_position_outcome(self, outcome: str) -> bool:
        """Check if this outcome has the maximum position"""
        return self.delta_info.max_outcome == outcome


class ExchangeClient:
    """
    Stateful wrapper around Exchange for client state management.

    Maintains:
    - Balance cache
    - Positions cache
    - Mid-price cache for NAV calculation
    - Order tracking

    Exchange is stateless; ExchangeClient provides stateful operations.
    """

    def __init__(self, exchange, cache_ttl: float = 2.0, track_fills: bool = False):
        """
        Initialize exchange client.

        Args:
            exchange: Exchange instance to wrap
            cache_ttl: Cache time-to-live in seconds (default 2s for Polygon block time)
            track_fills: Enable order fill tracking
        """
        self._exchange = exchange

        # Cache configuration
        self._cache_ttl = cache_ttl

        # Cached account state
        self._balance_cache: Dict[str, float] = {}
        self._balance_last_updated: float = 0
        # Per-market positions cache: market_id -> (positions, last_updated)
        self._positions_cache: Dict[str, Tuple[List[Position], float]] = {}

        # Mid-price cache: maps token_id/market_id -> yes_price
        self._mid_price_cache: Dict[str, float] = {}

        # Order tracking
        self._track_fills = track_fills
        self._order_tracker: Optional[OrderTracker] = None
        self._user_ws = None

        # Market data WebSocket for orderbook
        self._market_ws = None
        self._orderbook_manager = None
        self._ws_thread = None

        # Polling fallback for exchanges without WebSocket
        self._polling_thread = None
        self._polling_stop = False
        self._polling_token_ids: List[str] = []

        if track_fills:
            self._setup_order_tracker()

    @property
    def verbose(self) -> bool:
        """Get verbose setting from exchange"""
        return getattr(self._exchange, "verbose", False)

    def _setup_order_tracker(self):
        """Setup order fill tracking"""
        self._order_tracker = OrderTracker(verbose=self.verbose)
        self._order_tracker.on_fill(create_fill_logger())

        # Try to setup user WebSocket for real-time trade notifications
        if hasattr(self._exchange, "get_user_websocket"):
            try:
                self._user_ws = self._exchange.get_user_websocket()
                self._user_ws.on_trade(self._order_tracker.handle_trade)
                self._user_ws.start()
            except ConnectionError:
                logger.debug("WebSocket not available, will use polling")
            except Exception as e:
                logger.warning(f"Failed to setup user WebSocket: {e}")

    def on_fill(self, callback: OrderCallback) -> "ExchangeClient":
        """
        Register a callback for order fill events.

        Args:
            callback: Function(event, order, fill_size) to call on fills

        Returns:
            Self for chaining
        """
        if self._order_tracker is None:
            self._order_tracker = OrderTracker(verbose=self.verbose)
        self._order_tracker.on_fill(callback)
        return self

    def track_order(self, order: Order) -> None:
        """
        Track an order for fill events.

        Args:
            order: Order to track
        """
        if self._order_tracker:
            self._order_tracker.track_order(order)

    # Exchange wrapper methods

    def fetch_market(self, market_id: str) -> Optional[Market]:
        """Fetch a single market by ID"""
        return self._exchange.fetch_market(market_id)

    def fetch_markets(self, params: Optional[Dict] = None) -> List[Market]:
        """Fetch markets from exchange"""
        return self._exchange.fetch_markets(params or {})

    def fetch_markets_by_slug(self, slug: str) -> List[Market]:
        """Fetch markets by slug (if exchange supports it)"""
        if hasattr(self._exchange, "fetch_markets_by_slug"):
            return self._exchange.fetch_markets_by_slug(slug)
        return []

    def fetch_balance(self) -> Dict[str, float]:
        """Fetch fresh balance from exchange (blocking)"""
        return self._exchange.fetch_balance()

    def fetch_positions(self, market_id: Optional[str] = None) -> List[Position]:
        """Fetch positions from exchange"""
        return self._exchange.fetch_positions(market_id=market_id)

    def fetch_positions_for_market(self, market: Market) -> List[Position]:
        """Fetch positions for a specific market"""
        if hasattr(self._exchange, "fetch_positions_for_market"):
            return self._exchange.fetch_positions_for_market(market)
        return self._exchange.fetch_positions(market_id=market.id)

    def create_order(
        self,
        market_id: str,
        outcome: str,
        side: OrderSide,
        price: float,
        size: float,
        params: Optional[Dict] = None,
    ) -> Order:
        """
        Create an order and optionally track it.

        Args:
            market_id: Market ID
            outcome: Outcome name
            side: OrderSide.BUY or OrderSide.SELL
            price: Order price
            size: Order size
            params: Additional parameters

        Returns:
            Created Order object
        """
        order = self._exchange.create_order(
            market_id=market_id,
            outcome=outcome,
            side=side,
            price=price,
            size=size,
            params=params or {},
        )
        self.track_order(order)
        return order

    def get_orderbook(self, token_id: str) -> Dict:
        """Get orderbook for a token (if exchange supports it)"""
        if hasattr(self._exchange, "get_orderbook"):
            return self._exchange.get_orderbook(token_id)
        return {"bids": [], "asks": []}

    def get_websocket(self):
        """Get market data WebSocket (if exchange supports it)"""
        if hasattr(self._exchange, "get_websocket"):
            return self._exchange.get_websocket()
        return None

    def get_user_websocket(self):
        """Get user data WebSocket (if exchange supports it)"""
        if hasattr(self._exchange, "get_user_websocket"):
            return self._exchange.get_user_websocket()
        return None

    def _setup_orderbook_polling(self, token_ids: List[str], interval: float = 0.5) -> bool:
        """
        Setup REST polling for orderbook updates.
        Used as fallback when WebSocket is not supported.

        Args:
            token_ids: List of token IDs to poll
            interval: Polling interval in seconds

        Returns:
            True if polling setup successful
        """
        self._orderbook_manager = OrderbookManager()
        self._polling_token_ids = token_ids
        self._polling_stop = False

        # Initial fetch
        for token_id in token_ids:
            rest_data = self.get_orderbook(token_id)
            if rest_data:
                orderbook = Orderbook.from_rest_response(rest_data, token_id)
                self._orderbook_manager.update(token_id, orderbook.to_dict())
                self.update_mid_price_from_orderbook(token_id, orderbook.to_dict())

        def polling_worker():
            while not self._polling_stop:
                try:
                    for token_id in self._polling_token_ids:
                        if self._polling_stop:
                            break
                        rest_data = self.get_orderbook(token_id)
                        if rest_data:
                            orderbook = Orderbook.from_rest_response(rest_data, token_id)
                            self._orderbook_manager.update(token_id, orderbook.to_dict())
                            self.update_mid_price_from_orderbook(token_id, orderbook.to_dict())
                except Exception as e:
                    logger.warning(f"Orderbook polling error: {e}")
                time.sleep(interval)

        self._polling_thread = threading.Thread(target=polling_worker, daemon=False)
        self._polling_thread.start()
        logger.info(f"Orderbook polling started for {len(token_ids)} tokens")
        return True

    def setup_orderbook_websocket(self, market_id: str, token_ids: List[str]) -> bool:
        """
        Setup WebSocket connection for real-time orderbook updates.
        Falls back to REST polling if WebSocket is not supported.

        Args:
            market_id: Market ID to subscribe to
            token_ids: List of token IDs to subscribe to

        Returns:
            True if setup successful (WebSocket or polling), False otherwise
        """
        if not hasattr(self._exchange, "get_websocket"):
            logger.debug("Exchange does not support WebSocket, using REST polling")
            return self._setup_orderbook_polling(token_ids)

        try:
            self._market_ws = self._exchange.get_websocket()
            self._orderbook_manager = self._market_ws.get_orderbook_manager()

            # Fetch initial orderbook data via REST before connecting WebSocket
            # Parallelized to reduce latency for markets with many outcomes
            fetch_start = time.time()

            def fetch_and_update(token_id: str):
                rest_data = self.get_orderbook(token_id)
                if rest_data:
                    orderbook = Orderbook.from_rest_response(rest_data, token_id)
                    self._orderbook_manager.update(token_id, orderbook.to_dict())
                    self.update_mid_price_from_orderbook(token_id, orderbook.to_dict())

            with ThreadPoolExecutor(max_workers=min(len(token_ids), 5)) as executor:
                executor.map(fetch_and_update, token_ids)

            fetch_duration = time.time() - fetch_start
            if fetch_duration > 1.0:
                logger.info(
                    f"Initial orderbook fetch took {fetch_duration:.2f}s for {len(token_ids)} tokens"
                )

            # Create event loop for WebSocket
            if self._market_ws.loop is None:
                self._market_ws.loop = asyncio.new_event_loop()

            # Callback to update mid price cache on orderbook updates
            def on_orderbook_update(market_id: str, orderbook: dict):
                # Extract token_id from orderbook if available
                token_id = orderbook.get("asset_id", "")
                if token_id:
                    self.update_mid_price_from_orderbook(token_id, orderbook)

            # Define coroutine that connects, subscribes, and runs receive loop
            async def run_websocket():
                try:
                    await self._market_ws.connect()
                    await self._market_ws.watch_orderbook_by_market(
                        market_id, token_ids, callback=on_orderbook_update
                    )
                    await self._market_ws._receive_loop()
                except asyncio.CancelledError:
                    logger.debug("WebSocket task cancelled")
                except Exception as e:
                    logger.warning(f"WebSocket error: {e}")
                finally:
                    if self._market_ws:
                        try:
                            await self._market_ws.close()
                        except Exception:
                            pass

            # Run in background thread with proper event loop management
            def run_loop():
                asyncio.set_event_loop(self._market_ws.loop)
                self._market_ws.loop.create_task(run_websocket())
                self._market_ws.loop.run_forever()

            self._ws_thread = threading.Thread(target=run_loop, daemon=False)
            self._ws_thread.start()

            logger.info("WebSocket orderbook connected")
            return True

        except Exception as e:
            logger.warning(f"Failed to setup WebSocket: {e}")
            self._market_ws = None
            self._orderbook_manager = None
            return False

    def _parse_price_level(self, level: Any) -> Optional[float]:
        """
        Parse price from an orderbook level entry.

        Handles dict format ({"price": x}) and list/tuple format ([price, size]).

        Args:
            level: Price level entry from orderbook

        Returns:
            Parsed price or None if invalid
        """
        try:
            if isinstance(level, dict):
                price = float(level.get("price", 0))
                return price if price > 0 else None
            elif isinstance(level, (list, tuple)):
                price = float(level[0])
                return price if price > 0 else None
        except (ValueError, TypeError, IndexError):
            return None
        return None

    def get_best_bid_ask(self, token_id: str) -> Tuple[Optional[float], Optional[float]]:
        """
        Get best bid and ask prices.

        Uses WebSocket orderbook if available, otherwise falls back to REST API.

        Args:
            token_id: Token ID to fetch orderbook for

        Returns:
            Tuple of (best_bid, best_ask), None if not available or invalid
        """
        # Try WebSocket orderbook first
        if self._orderbook_manager and self._orderbook_manager.has_data(token_id):
            return self._orderbook_manager.get_best_bid_ask(token_id)

        # Fall back to REST API
        orderbook = self.get_orderbook(token_id)

        bids = orderbook.get("bids", [])
        asks = orderbook.get("asks", [])

        best_bid = self._parse_price_level(bids[0]) if bids else None
        best_ask = self._parse_price_level(asks[0]) if asks else None

        return best_bid, best_ask

    def stop(self):
        """Stop order tracking, WebSocket connections, and polling"""
        if self._order_tracker:
            self._order_tracker.stop()
        if self._user_ws:
            self._user_ws.stop()
        if self._market_ws:
            if self._market_ws.loop:
                self._market_ws.loop.call_soon_threadsafe(self._market_ws.loop.stop)
            self._market_ws.stop()
        # Stop polling thread
        if self._polling_thread:
            self._polling_stop = True
            self._polling_thread.join(timeout=2.0)
        if self._ws_thread:
            self._ws_thread.join(timeout=5.0)

    def get_balance(self) -> Dict[str, float]:
        """
        Get cached balance (non-blocking). Updates cache in background if stale.

        Returns:
            Dictionary with cached balance info. Contains '_stale' key (bool)
            indicating if cache update failed and data may be outdated.
        """
        current_time = time.time()
        stale = False

        if current_time - self._balance_last_updated > self._cache_ttl:
            try:
                self._update_balance_cache()
            except Exception as e:
                logger.warning(f"Background balance update failed: {e}")
                stale = True

        result = self._balance_cache.copy()
        result["_stale"] = stale
        return result

    def get_positions(self, market_id: Optional[str] = None) -> List[Position]:
        """
        Get cached positions (non-blocking). Updates cache in background if stale.

        Args:
            market_id: Optional market filter

        Returns:
            List of cached Position objects
        """
        current_time = time.time()
        cache_key = market_id or "__all__"

        # Check if cache exists and is fresh
        if cache_key in self._positions_cache:
            positions, last_updated = self._positions_cache[cache_key]
            if current_time - last_updated <= self._cache_ttl:
                return positions.copy()

        # Cache miss or stale - update
        try:
            self._update_positions_cache(market_id)
            if cache_key in self._positions_cache:
                return self._positions_cache[cache_key][0].copy()
        except Exception as e:
            logger.warning(f"Background positions update failed: {e}")

        # Return stale cache if available, otherwise empty
        if cache_key in self._positions_cache:
            return self._positions_cache[cache_key][0].copy()
        return []

    def get_positions_dict(self, market_id: Optional[str] = None) -> Dict[str, float]:
        """
        Get positions as a dictionary mapping outcome to size.

        Args:
            market_id: Optional market filter

        Returns:
            Dict mapping outcome name to position size
        """
        positions = {}
        for pos in self.get_positions(market_id):
            positions[pos.outcome] = pos.size
        return positions

    def fetch_positions_dict(self, market_id: Optional[str] = None) -> Dict[str, float]:
        """
        Fetch fresh positions from exchange as dictionary (blocking).

        Args:
            market_id: Optional market filter

        Returns:
            Dict mapping outcome name to position size
        """
        positions = {}
        try:
            positions_list = self._exchange.fetch_positions(market_id=market_id)
            for pos in positions_list:
                positions[pos.outcome] = pos.size
        except Exception as e:
            logger.warning(f"Failed to fetch positions: {e}")
        return positions

    def fetch_positions_dict_for_market(self, market: Market) -> Dict[str, float]:
        """
        Fetch fresh positions for a specific market as dictionary (blocking).

        Uses fetch_positions_for_market which properly handles token IDs.

        Args:
            market: Market object

        Returns:
            Dict mapping outcome name to position size
        """
        positions = {}
        try:
            positions_list = self.fetch_positions_for_market(market)
            for pos in positions_list:
                positions[pos.outcome] = pos.size
        except Exception as e:
            logger.warning(f"Failed to fetch positions for market: {e}")
        return positions

    def fetch_open_orders(self, market_id: Optional[str] = None) -> List:
        """
        Fetch open orders from exchange (delegates to exchange).

        Args:
            market_id: Optional market filter

        Returns:
            List of Order objects
        """
        return self._exchange.fetch_open_orders(market_id=market_id)

    def cancel_order(self, order_id: str, market_id: Optional[str] = None):
        """
        Cancel a single order.

        Args:
            order_id: Order ID to cancel
            market_id: Optional market ID
        """
        return self._exchange.cancel_order(order_id, market_id=market_id)

    def cancel_all_orders(self, market_id: Optional[str] = None) -> int:
        """
        Cancel all open orders for a market.

        Args:
            market_id: Market ID to cancel orders for

        Returns:
            Number of orders cancelled
        """
        orders = self.fetch_open_orders(market_id=market_id)
        cancelled = 0

        for order in orders:
            try:
                self.cancel_order(order.id, market_id=market_id)
                cancelled += 1
            except Exception as e:
                logger.warning(f"Failed to cancel order {order.id}: {e}")

        return cancelled

    def liquidate_positions(
        self,
        market: Market,
        get_best_bid: Callable[[str], Optional[float]],
        tick_size: float = 0.001,
    ) -> int:
        """
        Liquidate all positions by selling at best bid.

        Args:
            market: Market object with outcomes and token_ids
            get_best_bid: Callable that takes token_id and returns best bid price
            tick_size: Price tick size for rounding

        Returns:
            Number of positions liquidated
        """
        from ..models.order import OrderSide

        positions = self.fetch_positions_dict(market_id=market.id)
        if not positions:
            return 0

        token_ids = market.metadata.get("clobTokenIds", [])
        outcomes = market.outcomes
        liquidated = 0

        for outcome, size in positions.items():
            if size <= 0:
                continue

            # Find token_id for this outcome
            token_id = None
            for i, out in enumerate(outcomes):
                if out == outcome and i < len(token_ids):
                    token_id = token_ids[i]
                    break

            if not token_id:
                logger.warning(f"Cannot find token_id for {outcome}")
                continue

            # Get best bid
            best_bid = get_best_bid(token_id)
            if best_bid is None or best_bid <= 0:
                logger.warning(f"{outcome}: No bid available, cannot liquidate")
                continue

            # Round price to tick size
            price = round(round(best_bid / tick_size) * tick_size, 3)

            # Floor the size to integer
            sell_size = float(int(size))
            if sell_size <= 0:
                continue

            try:
                self._exchange.create_order(
                    market_id=market.id,
                    outcome=outcome,
                    side=OrderSide.SELL,
                    price=price,
                    size=sell_size,
                    params={"token_id": token_id},
                )
                liquidated += 1
            except Exception as e:
                logger.error(f"Failed to liquidate {outcome}: {e}")

        return liquidated

    def _update_balance_cache(self):
        """Internal method to update balance cache"""
        try:
            balance = self._exchange.fetch_balance()
            self._balance_cache = balance
            self._balance_last_updated = time.time()
        except Exception as e:
            logger.warning(f"Failed to update balance cache: {e}")
            raise

    def _update_positions_cache(self, market_id: Optional[str] = None):
        """Internal method to update positions cache for a specific market"""
        try:
            positions = self._exchange.fetch_positions(market_id=market_id)
            cache_key = market_id or "__all__"
            self._positions_cache[cache_key] = (positions, time.time())
        except Exception as e:
            logger.warning(f"Failed to update positions cache: {e}")
            raise

    def refresh_account_state(self, market_id: Optional[str] = None):
        """
        Force refresh of both balance and positions cache (blocking).

        Args:
            market_id: Optional market filter for positions
        """
        self._update_balance_cache()
        self._update_positions_cache(market_id)

    def calculate_nav(self, market: Optional[Market] = None) -> NAV:
        """
        Calculate Net Asset Value (NAV) using cached mid-prices.

        Args:
            market: Market to calculate NAV for. If provided, uses
                   fetch_positions_for_market and cached mid-prices.

        Returns:
            NAV dataclass with breakdown
        """
        if market:
            positions = self.fetch_positions_for_market(market)
        else:
            positions = self.get_positions()

        balance = self.get_balance()

        prices = None
        if market:
            mid_prices = self.get_mid_prices(market)
            if mid_prices:
                prices = {market.id: mid_prices}

        return self._calculate_nav_internal(positions, prices, balance)

    def _calculate_nav_internal(
        self,
        positions: List[Position],
        prices: Optional[Dict[str, Dict[str, float]]],
        balance: Dict[str, float],
    ) -> NAV:
        """Internal NAV calculation with explicit parameters."""
        cash = balance.get("USDC", 0.0) + balance.get("USD", 0.0)

        positions_breakdown = []
        positions_value = 0.0

        for pos in positions:
            if pos.size <= 0:
                continue

            mid_price = pos.current_price
            if prices and pos.market_id in prices:
                market_prices = prices[pos.market_id]
                if pos.outcome in market_prices:
                    mid_price = market_prices[pos.outcome]

            value = pos.size * mid_price
            positions_value += value

            positions_breakdown.append(
                PositionBreakdown(
                    market_id=pos.market_id,
                    outcome=pos.outcome,
                    size=pos.size,
                    mid_price=mid_price,
                    value=value,
                )
            )

        return NAV(
            nav=cash + positions_value,
            cash=cash,
            positions_value=positions_value,
            positions=positions_breakdown,
        )

    def update_mid_price(self, token_id: str, mid_price: float) -> None:
        """
        Update cached mid-price for a token/market.

        Args:
            token_id: Token ID or market identifier
            mid_price: Mid-price (Yes price for binary markets)
        """
        self._mid_price_cache[str(token_id)] = mid_price

    def update_mid_price_from_orderbook(
        self,
        token_id: str,
        orderbook: Dict[str, Any],
    ) -> Optional[float]:
        """
        Calculate mid-price from orderbook and update cache.

        Args:
            token_id: Token ID or market identifier
            orderbook: Orderbook dict with 'bids' and 'asks'

        Returns:
            Calculated mid-price or None if orderbook invalid
        """
        if not orderbook:
            return None

        bids = orderbook.get("bids", [])
        asks = orderbook.get("asks", [])

        if not bids or not asks:
            return None

        # Get best bid - handle both tuple and dict formats
        if isinstance(bids[0], (list, tuple)):
            best_bid = bids[0][0]
        elif isinstance(bids[0], dict):
            best_bid = bids[0].get("price", 0)
        else:
            best_bid = float(bids[0]) if bids[0] else 0

        # Get best ask - handle both tuple and dict formats
        if isinstance(asks[0], (list, tuple)):
            best_ask = asks[0][0]
        elif isinstance(asks[0], dict):
            best_ask = asks[0].get("price", 0)
        else:
            best_ask = float(asks[0]) if asks[0] else 0

        if best_bid <= 0 or best_ask <= 0:
            return None

        mid_price = (best_bid + best_ask) / 2
        self._mid_price_cache[str(token_id)] = mid_price
        return mid_price

    def get_mid_price(self, token_id: str) -> Optional[float]:
        """
        Get cached mid-price for a token/market.

        Args:
            token_id: Token ID or market identifier

        Returns:
            Cached mid-price or None if not available
        """
        return self._mid_price_cache.get(str(token_id))

    def get_mid_prices(self, market: Market) -> Dict[str, float]:
        """
        Get mid-prices for all outcomes in a market from cache.

        For binary markets, uses cached Yes mid-price and derives No price.

        Args:
            market: Market object

        Returns:
            Dict mapping outcome name to mid-price
        """
        mid_prices = {}

        yes_mid = None

        token_ids = market.metadata.get("clobTokenIds", [])
        tokens = market.metadata.get("tokens", {})

        yes_token_id = None
        if tokens:
            yes_token_id = tokens.get("yes") or tokens.get("Yes")
        elif token_ids:
            yes_token_id = token_ids[0]

        if yes_token_id:
            yes_mid = self.get_mid_price(str(yes_token_id))

        if yes_mid is None:
            yes_mid = self.get_mid_price(market.id)

        if yes_mid is not None:
            if market.is_binary:
                mid_prices["Yes"] = yes_mid
                mid_prices["No"] = 1.0 - yes_mid
            else:
                if market.outcomes:
                    mid_prices[market.outcomes[0]] = yes_mid
            return mid_prices

        if market.prices:
            for outcome in market.outcomes:
                if outcome in market.prices:
                    mid_prices[outcome] = market.prices[outcome]

        return mid_prices


def calculate_delta(positions: Dict[str, float]) -> DeltaInfo:
    """
    Calculate delta (position imbalance) from positions.

    Args:
        positions: Dict mapping outcome name to position size

    Returns:
        DeltaInfo with delta, max/min positions, and max outcome
    """
    if not positions:
        return DeltaInfo(
            delta=0.0,
            max_position=0.0,
            min_position=0.0,
            max_outcome=None,
        )

    position_values = list(positions.values())
    max_pos = max(position_values)
    min_pos = min(position_values)
    delta = max_pos - min_pos

    max_outcome = None
    if delta > 0:
        max_outcome = max(positions, key=positions.get)

    return DeltaInfo(
        delta=delta,
        max_position=max_pos,
        min_position=min_pos,
        max_outcome=max_outcome,
    )


def format_positions_compact(
    positions: Dict[str, float], outcomes: list, abbreviate: bool = True
) -> str:
    """
    Format positions as compact string for display.

    Args:
        positions: Dict mapping outcome name to position size
        outcomes: List of outcome names (to determine abbreviation)
        abbreviate: Whether to abbreviate outcome names

    Returns:
        Formatted string like "10 Y 5 N" or "None"
    """
    if not positions:
        return "None"

    parts = []
    for outcome, size in positions.items():
        if abbreviate and len(outcomes) == 2:
            abbrev = outcome[0]
        elif abbreviate and len(outcomes) > 2:
            abbrev = outcome[:8]
        else:
            abbrev = outcome
        parts.append(f"{size:.0f} {abbrev}")
    return " ".join(parts)


def format_delta_side(delta_info: DeltaInfo, outcomes: list, abbreviate: bool = True) -> str:
    """
    Format delta side indicator for display.

    Args:
        delta_info: DeltaInfo from calculate_delta
        outcomes: List of outcome names (to determine abbreviation)
        abbreviate: Whether to abbreviate outcome names

    Returns:
        Formatted string like "Y" or "Bitcoin" or ""
    """
    if delta_info.delta <= 0 or not delta_info.max_outcome:
        return ""

    max_outcome = delta_info.max_outcome
    if abbreviate and len(outcomes) == 2:
        return max_outcome[0]
    elif abbreviate and len(outcomes) > 2:
        return max_outcome[:8]
    return max_outcome
