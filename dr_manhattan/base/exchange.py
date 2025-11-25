from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, Coroutine
import time
import random
import asyncio
from functools import wraps
from ..models.market import Market
from ..models.order import Order, OrderSide
from ..models.position import Position
from ..models.nav import NAV, PositionBreakdown
from ..base.errors import NetworkError, RateLimitError


class Exchange(ABC):
    """
    Base class for all prediction market exchanges.
    Follows CCXT-style unified API pattern.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize exchange with optional configuration.

        Args:
            config: Dictionary containing API keys, options, etc.
        """
        self.config = config or {}
        self.api_key = self.config.get('api_key')
        self.api_secret = self.config.get('api_secret')
        self.timeout = self.config.get('timeout', 30)
        self.verbose = self.config.get('verbose', False)

        # Rate limiting
        self.rate_limit = self.config.get('rate_limit', 10)  # requests per second
        self.last_request_time = 0
        self.request_times = []  # For sliding window rate limiting

        # Retry configuration
        self.max_retries = self.config.get('max_retries', 3)
        self.retry_delay = self.config.get('retry_delay', 1.0)  # Base delay in seconds
        self.retry_backoff = self.config.get('retry_backoff', 2.0)  # Multiplier for exponential backoff

        # Cached account state (managed internally)
        self._balance_cache = {}
        self._positions_cache = []
        self._balance_last_updated = 0
        self._positions_last_updated = 0
        self._cache_ttl = self.config.get('cache_ttl', 2.0)  # Cache TTL in seconds (default 2s for Polygon block time)

        # Mid-price cache: maps token_id/market_id -> yes_price
        # Updated by exchange implementations when orderbook data arrives
        self._mid_price_cache: Dict[str, float] = {}

    @property
    @abstractmethod
    def id(self) -> str:
        """Exchange identifier (e.g., 'polymarket', 'kalshi')"""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable exchange name"""
        pass

    @abstractmethod
    def fetch_markets(self, params: Optional[Dict[str, Any]] = None) -> list[Market]:
        """
        Fetch all available markets.

        Args:
            params: Optional parameters for filtering/pagination

        Returns:
            List of Market objects
        """
        pass

    @abstractmethod
    def fetch_market(self, market_id: str) -> Market:
        """
        Fetch a specific market by ID.

        Args:
            market_id: Market identifier

        Returns:
            Market object
        """
        pass

    @abstractmethod
    def create_order(
        self,
        market_id: str,
        outcome: str,
        side: OrderSide,
        price: float,
        size: float,
        params: Optional[Dict[str, Any]] = None
    ) -> Order:
        """
        Create a new order.

        Args:
            market_id: Market identifier
            outcome: Outcome to bet on
            side: Buy or sell
            price: Price per share (0-1 or 0-100 depending on exchange)
            size: Number of shares
            params: Additional exchange-specific parameters

        Returns:
            Order object
        """
        pass

    @abstractmethod
    def cancel_order(self, order_id: str, market_id: Optional[str] = None) -> Order:
        """
        Cancel an existing order.

        Args:
            order_id: Order identifier
            market_id: Market identifier (required by some exchanges)

        Returns:
            Updated Order object
        """
        pass

    @abstractmethod
    def fetch_order(self, order_id: str, market_id: Optional[str] = None) -> Order:
        """
        Fetch order details.

        Args:
            order_id: Order identifier
            market_id: Market identifier (required by some exchanges)

        Returns:
            Order object
        """
        pass

    @abstractmethod
    def fetch_open_orders(
        self,
        market_id: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> list[Order]:
        """
        Fetch all open orders.

        Args:
            market_id: Optional market filter
            params: Additional parameters

        Returns:
            List of Order objects
        """
        pass

    @abstractmethod
    def fetch_positions(
        self,
        market_id: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> list[Position]:
        """
        Fetch current positions.

        Args:
            market_id: Optional market filter
            params: Additional parameters

        Returns:
            List of Position objects
        """
        pass

    def get_tick_size(self, market: Market) -> float:
        """
        Get the minimum tick size (price increment) for a market.

        This is a common interface method that exchanges should override
        if they support dynamic tick sizes. Default implementation returns 0.01.

        Args:
            market: Market object

        Returns:
            Minimum tick size (default: 0.01)

        Example:
            >>> tick_size = exchange.get_tick_size(market)
            >>> valid_price = exchange.round_to_tick_size(0.1234, tick_size)
        """
        # Check metadata first (exchange-specific)
        tick_size = market.metadata.get('tick_size') or market.metadata.get('minimum_tick_size')
        if tick_size:
            return float(tick_size)

        # Default to 0.01 (1 cent)
        return 0.01

    def round_to_tick_size(self, price: float, tick_size: Optional[float] = None) -> float:
        """
        Round a price to the nearest valid tick increment.

        Args:
            price: The price to round
            tick_size: The minimum tick size (default: 0.01)

        Returns:
            Price rounded to nearest tick

        Example:
            >>> rounded = exchange.round_to_tick_size(0.1234, 0.01)
            >>> # Returns: 0.12
        """
        if tick_size is None:
            tick_size = 0.01

        if tick_size <= 0:
            return price

        return round(price / tick_size) * tick_size

    def is_valid_price(self, price: float, tick_size: Optional[float] = None) -> bool:
        """
        Check if a price is valid for the given tick size.

        Args:
            price: Price to check
            tick_size: Minimum tick size (default: 0.01)

        Returns:
            True if price is valid
        """
        if tick_size is None:
            tick_size = 0.01

        if tick_size <= 0:
            return True

        rounded = self.round_to_tick_size(price, tick_size)
        return abs(price - rounded) < (tick_size / 10)

    @abstractmethod
    def fetch_balance(self) -> Dict[str, float]:
        """
        Fetch account balance (synchronous).

        Returns:
            Dictionary with balance info (e.g., {'USDC': 1000.0})
        """
        pass

    def get_balance(self) -> Dict[str, float]:
        """
        Get cached balance (non-blocking). Updates cache in background if stale.
        This is the recommended method for high-frequency access.

        Returns:
            Dictionary with cached balance info
        """
        current_time = time.time()

        # If cache is stale, trigger async update
        if current_time - self._balance_last_updated > self._cache_ttl:
            try:
                # Non-blocking update
                self._update_balance_cache()
            except Exception as e:
                if self.verbose:
                    print(f"Background balance update failed: {e}")

        return self._balance_cache.copy()

    def get_positions(self, market_id: Optional[str] = None) -> list[Position]:
        """
        Get cached positions (non-blocking). Updates cache in background if stale.
        This is the recommended method for high-frequency access.

        Args:
            market_id: Optional market filter

        Returns:
            List of cached Position objects
        """
        current_time = time.time()

        # If cache is stale, trigger async update
        if current_time - self._positions_last_updated > self._cache_ttl:
            try:
                # Non-blocking update
                self._update_positions_cache(market_id)
            except Exception as e:
                if self.verbose:
                    print(f"Background positions update failed: {e}")

        # Filter by market_id if provided
        if market_id:
            return [p for p in self._positions_cache if p.market_id == market_id]
        return self._positions_cache.copy()

    def _update_balance_cache(self):
        """Internal method to update balance cache"""
        try:
            balance = self.fetch_balance()
            self._balance_cache = balance
            self._balance_last_updated = time.time()
        except Exception as e:
            if self.verbose:
                print(f"Failed to update balance cache: {e}")
            raise

    def _update_positions_cache(self, market_id: Optional[str] = None):
        """Internal method to update positions cache"""
        try:
            positions = self.fetch_positions(market_id=market_id)
            self._positions_cache = positions
            self._positions_last_updated = time.time()
        except Exception as e:
            if self.verbose:
                print(f"Failed to update positions cache: {e}")
            raise

    def refresh_account_state(self, market_id: Optional[str] = None):
        """
        Force refresh of both balance and positions cache (blocking).
        Call this before starting a trading session or when you need guaranteed fresh data.

        Args:
            market_id: Optional market filter for positions
        """
        self._update_balance_cache()
        self._update_positions_cache(market_id)

    def calculate_nav(self, market: Optional[Market] = None) -> NAV:
        """
        Calculate Net Asset Value (NAV) using cached mid-prices.

        Mid-prices are automatically updated by exchange implementations
        when orderbook data is received.

        Args:
            market: Market to calculate NAV for. If provided, uses cached
                   mid-prices for that market. If None, uses position.current_price.

        Returns:
            NAV dataclass with breakdown:
                nav: Total NAV in USD
                cash: USDC balance
                positions_value: Total position value
                positions: List of PositionBreakdown objects
        """
        positions = self.get_positions()
        balance = self.get_balance()

        # Get mid-prices from cache if market provided
        prices = None
        if market:
            mid_prices = self.get_mid_prices(market)
            if mid_prices:
                prices = {market.id: mid_prices}

        return self._calculate_nav_internal(positions, prices, balance)

    def _calculate_nav_internal(
        self,
        positions: list[Position],
        prices: Optional[Dict[str, Dict[str, float]]],
        balance: Dict[str, float],
    ) -> NAV:
        """Internal NAV calculation with explicit parameters."""
        cash = balance.get('USDC', 0.0) + balance.get('USD', 0.0)

        positions_breakdown = []
        positions_value = 0.0

        for pos in positions:
            if pos.size <= 0:
                continue

            # Get mid-price from provided prices or use current_price
            mid_price = pos.current_price
            if prices and pos.market_id in prices:
                market_prices = prices[pos.market_id]
                if pos.outcome in market_prices:
                    mid_price = market_prices[pos.outcome]

            value = pos.size * mid_price
            positions_value += value

            positions_breakdown.append(PositionBreakdown(
                market_id=pos.market_id,
                outcome=pos.outcome,
                size=pos.size,
                mid_price=mid_price,
                value=value,
            ))

        return NAV(
            nav=cash + positions_value,
            cash=cash,
            positions_value=positions_value,
            positions=positions_breakdown,
        )

    def update_mid_price(self, token_id: str, mid_price: float) -> None:
        """
        Update cached mid-price for a token/market.

        Call this when orderbook data is received to keep cache current.

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

        Call this when orderbook data is received.

        Args:
            token_id: Token ID or market identifier
            orderbook: Orderbook dict with 'bids' and 'asks'

        Returns:
            Calculated mid-price or None if orderbook invalid
        """
        if not orderbook:
            return None

        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])

        if not bids or not asks:
            return None

        # Get best bid - handle both tuple and dict formats
        if isinstance(bids[0], (list, tuple)):
            best_bid = bids[0][0]
        elif isinstance(bids[0], dict):
            best_bid = bids[0].get('price', 0)
        else:
            best_bid = float(bids[0]) if bids[0] else 0

        # Get best ask - handle both tuple and dict formats
        if isinstance(asks[0], (list, tuple)):
            best_ask = asks[0][0]
        elif isinstance(asks[0], dict):
            best_ask = asks[0].get('price', 0)
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

        For binary markets, uses cached Yes mid-price and derives No price
        as (1 - Yes mid-price).

        Args:
            market: Market object

        Returns:
            Dict mapping outcome name to mid-price, e.g. {'Yes': 0.55, 'No': 0.45}
        """
        mid_prices = {}

        # Try to find Yes token mid-price from cache
        yes_mid = None

        # Try token IDs first (Polymarket style)
        token_ids = market.metadata.get('clobTokenIds', [])
        tokens = market.metadata.get('tokens', {})

        yes_token_id = None
        if tokens:
            yes_token_id = tokens.get('yes') or tokens.get('Yes')
        elif token_ids:
            yes_token_id = token_ids[0]

        # Check cache for Yes token
        if yes_token_id:
            yes_mid = self.get_mid_price(str(yes_token_id))

        # Try market.id if token lookup failed
        if yes_mid is None:
            yes_mid = self.get_mid_price(market.id)

        # Build mid-prices dict
        if yes_mid is not None:
            if market.is_binary:
                mid_prices['Yes'] = yes_mid
                mid_prices['No'] = 1.0 - yes_mid
            else:
                # For non-binary, just use as first outcome price
                if market.outcomes:
                    mid_prices[market.outcomes[0]] = yes_mid
            return mid_prices

        # Fallback: use market prices if available
        if market.prices:
            for outcome in market.outcomes:
                if outcome in market.prices:
                    mid_prices[outcome] = market.prices[outcome]

        return mid_prices

    def find_tradeable_market(
        self,
        binary: bool = True,
        limit: int = 100,
        min_liquidity: float = 0.0
    ) -> Optional[Market]:
        """
        Find a suitable market for trading.
        Filters for open markets with valid token IDs.

        Args:
            binary: Only return binary markets
            limit: Maximum markets to fetch
            min_liquidity: Minimum liquidity required

        Returns:
            Market object or None if no suitable market found
        """
        import random

        markets = self.fetch_markets({'limit': limit})

        suitable_markets = []
        for market in markets:
            # Check binary
            if binary and not market.is_binary:
                continue

            # Check open
            if not market.is_open:
                continue

            # Check liquidity
            if market.liquidity < min_liquidity:
                continue

            # Check has token IDs (exchange-specific, but generally in metadata)
            if 'clobTokenIds' in market.metadata:
                token_ids = market.metadata.get('clobTokenIds', [])
                if not token_ids or len(token_ids) < 1:
                    continue

            suitable_markets.append(market)

        if not suitable_markets:
            return None

        # Return random market
        return random.choice(suitable_markets)

    def find_crypto_hourly_market(
        self,
        token_symbol: Optional[str] = None,
        min_liquidity: float = 0.0,
        limit: int = 100,
        is_active: bool = True,
        is_expired: bool = False,
        params: Optional[Dict[str, Any]] = None
    ) -> Optional[tuple['Market', 'CryptoHourlyMarket']]:
        """
        Find a crypto hourly price market.

        These are markets that predict whether a token's price will be above/below
        a certain threshold at a specific time (usually hourly expiry).

        This is a generic implementation that can be overridden by exchanges
        for more efficient filtering (e.g., using tags, categories).

        Args:
            token_symbol: Filter by token (e.g., "BTC", "ETH", "SOL"). None = any token
            min_liquidity: Minimum liquidity required
            limit: Maximum markets to fetch and search
            is_active: If True, only return markets currently in progress (expiring within 1 hour)
            is_expired: If True, only return expired markets. If False, exclude expired markets.
            params: Exchange-specific parameters

        Returns:
            Tuple of (Market, CryptoHourlyMarket) or None if no match found
        """
        # Default implementation - can be overridden by specific exchanges
        return self._parse_crypto_hourly_from_markets(
            token_symbol=token_symbol,
            min_liquidity=min_liquidity,
            limit=limit
        )

    def _parse_crypto_hourly_from_markets(
        self,
        token_symbol: Optional[str] = None,
        direction: Optional[str] = None,
        min_liquidity: float = 0.0,
        limit: int = 100
    ) -> Optional[tuple['Market', 'CryptoHourlyMarket']]:
        """
        Generic parser for crypto hourly markets using pattern matching.
        Used as fallback when exchange doesn't have specific tag/category support.
        """
        import re
        from datetime import datetime, timedelta
        from ..models import CryptoHourlyMarket

        markets = self.fetch_markets({'limit': limit})

        # Pattern to match crypto price predictions
        pattern = re.compile(
            r'(?:(?P<token1>BTC|ETH|SOL|BITCOIN|ETHEREUM|SOLANA)\s+.*?'
            r'(?P<direction>above|below|over|under|reach)\s+'
            r'[\$]?(?P<price1>[\d,]+(?:\.\d+)?))|'
            r'(?:[\$]?(?P<price2>[\d,]+(?:\.\d+)?)\s+.*?'
            r'(?P<token2>BTC|ETH|SOL|BITCOIN|ETHEREUM|SOLANA))',
            re.IGNORECASE
        )

        for market in markets:
            # Must be binary and open
            if not market.is_binary or not market.is_open:
                continue

            # Check liquidity
            if market.liquidity < min_liquidity:
                continue

            # Check has token IDs
            if 'clobTokenIds' in market.metadata:
                token_ids = market.metadata.get('clobTokenIds', [])
                if not token_ids or len(token_ids) < 2:
                    continue

            # Try to parse the question
            match = pattern.search(market.question)
            if not match:
                continue

            # Extract matched groups (pattern has two alternatives)
            parsed_token = (match.group('token1') or match.group('token2') or '').upper()
            parsed_price_str = match.group('price1') or match.group('price2') or '0'
            parsed_direction_raw = (match.group('direction') or 'reach').lower()

            # Normalize token names
            if parsed_token in ['BITCOIN']:
                parsed_token = 'BTC'
            elif parsed_token in ['ETHEREUM']:
                parsed_token = 'ETH'
            elif parsed_token in ['SOLANA']:
                parsed_token = 'SOL'

            # Normalize direction: over/above/reach -> up, under/below -> down
            if parsed_direction_raw in ['above', 'over', 'reach']:
                parsed_direction = 'up'
            elif parsed_direction_raw in ['below', 'under']:
                parsed_direction = 'down'
            else:
                parsed_direction = parsed_direction_raw

            parsed_price = float(parsed_price_str.replace(',', ''))

            # Apply filters
            if token_symbol and parsed_token != token_symbol.upper():
                continue

            if direction and parsed_direction != direction.lower():
                continue

            # Estimate expiry time from close_time
            # For hourly markets, close_time is typically the settlement time
            expiry = market.close_time if market.close_time else datetime.now() + timedelta(hours=1)

            crypto_market = CryptoHourlyMarket(
                token_symbol=parsed_token,
                strike_price=parsed_price,
                expiry_time=expiry,
                direction=parsed_direction  # type: ignore
            )

            return (market, crypto_market)

        return None

    def describe(self) -> Dict[str, Any]:
        """
        Return exchange metadata and capabilities.

        Returns:
            Dictionary containing exchange information
        """
        return {
            'id': self.id,
            'name': self.name,
            'has': {
                'fetch_markets': True,
                'fetch_market': True,
                'create_order': True,
                'cancel_order': True,
                'fetch_order': True,
                'fetch_open_orders': True,
                'fetch_positions': True,
                'fetch_balance': True,
                'rate_limit': True,
                'retry_logic': True,
            }
        }

    def _check_rate_limit(self):
        """Check and enforce rate limiting"""
        current_time = time.time()
        
        # Clean old requests (older than 1 second)
        self.request_times = [t for t in self.request_times if current_time - t < 1.0]
        
        # Check if we've exceeded the rate limit
        if len(self.request_times) >= self.rate_limit:
            sleep_time = 1.0 - (current_time - self.request_times[0])
            if sleep_time > 0:
                if self.verbose:
                    print(f"Rate limit reached, sleeping for {sleep_time:.2f}s")
                time.sleep(sleep_time)
        
        # Record this request
        self.request_times.append(current_time)

    def _retry_on_failure(self, func):
        """Decorator for retry logic with exponential backoff"""
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(self.max_retries + 1):
                try:
                    self._check_rate_limit()
                    return func(*args, **kwargs)
                except (NetworkError, RateLimitError) as e:
                    last_exception = e
                    if attempt < self.max_retries:
                        delay = self.retry_delay * (self.retry_backoff ** attempt) + random.uniform(0, 1)
                        if self.verbose:
                            print(f"Attempt {attempt + 1} failed, retrying in {delay:.2f}s: {e}")
                        time.sleep(delay)
                    else:
                        raise last_exception
                except Exception as e:
                    # Don't retry on non-network errors
                    raise e
            
            raise last_exception
        return wrapper

    def calculate_spread(self, market: Market) -> Optional[float]:
        """Calculate bid-ask spread for a market"""
        return market.spread

    def calculate_implied_probability(self, price: float) -> float:
        """Convert price to implied probability"""
        return price

    def calculate_expected_value(self, market: Market, outcome: str, price: float) -> float:
        """Calculate expected value for a given outcome and price"""
        if not market.is_binary:
            return 0.0
        
        # For binary markets, EV = probability * payoff - cost
        probability = self.calculate_implied_probability(price)
        payoff = 1.0 if outcome == market.outcomes[0] else 0.0
        cost = price
        
        return probability * payoff - cost

    def get_optimal_order_size(self, market: Market, max_position_size: float) -> float:
        """Calculate optimal order size based on market liquidity"""
        # Simple heuristic: use smaller of max position or 10% of liquidity
        liquidity_based_size = market.liquidity * 0.1
        return min(max_position_size, liquidity_based_size)

    def stream_market_data(self, market_ids: list[str], callback):
        """
        Stream real-time market data for specified markets.
        
        Args:
            market_ids: List of market IDs to stream
            callback: Function to call with market updates
        """
        import threading
        import time
        
        def _stream_worker():
            """Worker thread for streaming market data"""
            while True:
                try:
                    for market_id in market_ids:
                        market = self.fetch_market(market_id)
                        callback(market_id, market)
                    time.sleep(1)  # Update every second
                except Exception as e:
                    if self.verbose:
                        print(f"Streaming error: {e}")
                    time.sleep(5)  # Wait longer on error
        
        stream_thread = threading.Thread(target=_stream_worker, daemon=True)
        stream_thread.start()
        return stream_thread

    def watch_order_book(self, market_id: str, callback):
        """
        Watch order book changes for a specific market.
        DEPRECATED: Use WebSocket implementation via get_websocket() for real-time updates.

        Args:
            market_id: Market ID to watch
            callback: Function to call with order book updates
        """
        import threading
        import time

        def _order_book_worker():
            """Worker thread for watching order book"""
            last_prices = None

            while True:
                try:
                    market = self.fetch_market(market_id)
                    current_prices = market.prices

                    # Only call callback if prices changed
                    if current_prices != last_prices:
                        callback(market_id, current_prices)
                        last_prices = current_prices.copy()

                    time.sleep(0.5)  # Check every 500ms

                except Exception as e:
                    if self.verbose:
                        print(f"Order book watch error: {e}")
                    time.sleep(2)

        watch_thread = threading.Thread(target=_order_book_worker, daemon=True)
        watch_thread.start()
        return watch_thread

    def get_websocket(self):
        """
        Get WebSocket instance for interrupt-driven orderbook updates.
        Exchange implementations should override this to provide their WebSocket.

        Returns:
            OrderBookWebSocket instance or None if not supported

        Example:
            ws = exchange.get_websocket()
            if ws:
                await ws.watch_orderbook(market_id, callback)
                ws.start()
        """
        return None
