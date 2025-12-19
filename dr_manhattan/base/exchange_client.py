"""
Exchange client with state management.

Provides stateful wrapper around Exchange for tracking positions, NAV, and client state.
Exchange is regarded as stateless; ExchangeClient maintains client-specific state.
"""

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..models.market import Market
from ..models.nav import NAV, PositionBreakdown
from ..models.order import Order, OrderSide
from ..models.position import Position
from .order_tracker import OrderCallback, OrderTracker, create_fill_logger


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
        self._positions_cache: List[Position] = []
        self._balance_last_updated: float = 0
        self._positions_last_updated: float = 0

        # Mid-price cache: maps token_id/market_id -> yes_price
        self._mid_price_cache: Dict[str, float] = {}

        # Order tracking
        self._track_fills = track_fills
        self._order_tracker: Optional[OrderTracker] = None
        self._user_ws = None

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
            except Exception:
                pass  # WebSocket not available, will use polling

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

    def get_tick_size(self, market: Market) -> float:
        """Get tick size for a market"""
        if hasattr(self._exchange, "get_tick_size"):
            return self._exchange.get_tick_size(market)
        return 0.01

    def round_to_tick_size(self, price: float, tick_size: float) -> float:
        """Round price to tick size"""
        if hasattr(self._exchange, "round_to_tick_size"):
            return self._exchange.round_to_tick_size(price, tick_size)
        return round(round(price / tick_size) * tick_size, 3)

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

    def stop(self):
        """Stop order tracking and WebSocket connections"""
        if self._order_tracker:
            self._order_tracker.stop()
        if self._user_ws:
            self._user_ws.stop()

    def get_balance(self) -> Dict[str, float]:
        """
        Get cached balance (non-blocking). Updates cache in background if stale.

        Returns:
            Dictionary with cached balance info
        """
        current_time = time.time()

        if current_time - self._balance_last_updated > self._cache_ttl:
            try:
                self._update_balance_cache()
            except Exception as e:
                if self.verbose:
                    print(f"Background balance update failed: {e}")

        return self._balance_cache.copy()

    def get_positions(self, market_id: Optional[str] = None) -> List[Position]:
        """
        Get cached positions (non-blocking). Updates cache in background if stale.

        Args:
            market_id: Optional market filter

        Returns:
            List of cached Position objects
        """
        current_time = time.time()

        if current_time - self._positions_last_updated > self._cache_ttl:
            try:
                self._update_positions_cache(market_id)
            except Exception as e:
                if self.verbose:
                    print(f"Background positions update failed: {e}")

        if market_id:
            return [p for p in self._positions_cache if p.market_id == market_id]
        return self._positions_cache.copy()

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
            if self.verbose:
                print(f"Failed to fetch positions: {e}")
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
                if self.verbose:
                    print(f"Failed to cancel order {order.id}: {e}")

        return cancelled

    def liquidate_positions(
        self,
        market: Market,
        get_best_bid: callable,
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
                if self.verbose:
                    print(f"Cannot find token_id for {outcome}")
                continue

            # Get best bid
            best_bid = get_best_bid(token_id)
            if best_bid is None or best_bid <= 0:
                if self.verbose:
                    print(f"{outcome}: No bid available, cannot liquidate")
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
                if self.verbose:
                    print(f"Failed to liquidate {outcome}: {e}")

        return liquidated

    def _update_balance_cache(self):
        """Internal method to update balance cache"""
        try:
            balance = self._exchange.fetch_balance()
            self._balance_cache = balance
            self._balance_last_updated = time.time()
        except Exception as e:
            if self.verbose:
                print(f"Failed to update balance cache: {e}")
            raise

    def _update_positions_cache(self, market_id: Optional[str] = None):
        """Internal method to update positions cache"""
        try:
            positions = self._exchange.fetch_positions(market_id=market_id)
            self._positions_cache = positions
            self._positions_last_updated = time.time()
        except Exception as e:
            if self.verbose:
                print(f"Failed to update positions cache: {e}")
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
            market: Market to calculate NAV for. If provided, uses cached
                   mid-prices for that market.

        Returns:
            NAV dataclass with breakdown
        """
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
