import random
import re
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, Dict, Optional

from ..base.errors import NetworkError, RateLimitError
from ..models.crypto_hourly import CryptoHourlyMarket
from ..models.market import Market
from ..models.order import Order, OrderSide, OrderTimeInForce
from ..models.position import Position


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
        self.api_key = self.config.get("api_key")
        self.api_secret = self.config.get("api_secret")
        self.timeout = self.config.get("timeout", 30)
        self.verbose = self.config.get("verbose", False)

        # Rate limiting
        self.rate_limit = self.config.get("rate_limit", 10)  # requests per second
        self.last_request_time = 0
        self.request_times = []  # For sliding window rate limiting

        # Retry configuration
        self.max_retries = self.config.get("max_retries", 3)
        self.retry_delay = self.config.get("retry_delay", 1.0)  # Base delay in seconds
        self.retry_backoff = self.config.get(
            "retry_backoff", 2.0
        )  # Multiplier for exponential backoff

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
        Fetch available markets.

        Args:
            params: Optional parameters for filtering/pagination
                - all: If True, fetch all markets with automatic pagination
                - page: Page number (exchange-specific)
                - limit: Maximum markets per page (exchange-specific)

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

    def fetch_markets_by_slug(self, slug_or_url: str) -> list[Market]:
        """
        Fetch all markets from an event by slug or URL.

        For events with multiple markets (e.g., "which day will X happen"),
        this returns all markets in the event.

        Args:
            slug_or_url: Event slug or full URL

        Returns:
            List of Market objects with token IDs populated
        """
        raise NotImplementedError(f"{self.name} does not support fetch_markets_by_slug")

    @abstractmethod
    def create_order(
        self,
        market_id: str,
        outcome: str,
        side: OrderSide,
        price: float,
        size: float,
        params: Optional[Dict[str, Any]] = None,
        time_in_force: OrderTimeInForce = OrderTimeInForce.GTC,
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
            time_in_force: Order time in force (GTC, FOK, IOC). Default is GTC.
                - GTC (Good-Til-Cancel): Order remains active until filled or cancelled
                - FOK (Fill-Or-Kill): Order must be filled immediately and completely or cancelled
                - IOC (Immediate-Or-Cancel): Fill what's available immediately, cancel the rest

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
        self, market_id: Optional[str] = None, params: Optional[Dict[str, Any]] = None
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
        self, market_id: Optional[str] = None, params: Optional[Dict[str, Any]] = None
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

    @abstractmethod
    def fetch_balance(self) -> Dict[str, float]:
        """
        Fetch account balance (synchronous).

        Returns:
            Dictionary with balance info (e.g., {'USDC': 1000.0})
        """
        pass

    def find_tradeable_market(
        self, binary: bool = True, limit: int = 100, min_liquidity: float = 0.0
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
        markets = self.fetch_markets({"limit": limit})

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
            if "clobTokenIds" in market.metadata:
                token_ids = market.metadata.get("clobTokenIds", [])
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
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[tuple["Market", "CryptoHourlyMarket"]]:
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
            token_symbol=token_symbol, min_liquidity=min_liquidity, limit=limit
        )

    def _parse_crypto_hourly_from_markets(
        self,
        token_symbol: Optional[str] = None,
        direction: Optional[str] = None,
        min_liquidity: float = 0.0,
        limit: int = 100,
    ) -> Optional[tuple["Market", "CryptoHourlyMarket"]]:
        """
        Generic parser for crypto hourly markets using pattern matching.
        Used as fallback when exchange doesn't have specific tag/category support.
        """
        markets = self.fetch_markets({"limit": limit})

        # Pattern to match crypto price predictions
        pattern = re.compile(
            r"(?:(?P<token1>BTC|ETH|SOL|BITCOIN|ETHEREUM|SOLANA)\s+.*?"
            r"(?P<direction>above|below|over|under|reach)\s+"
            r"[\$]?(?P<price1>[\d,]+(?:\.\d+)?))|"
            r"(?:[\$]?(?P<price2>[\d,]+(?:\.\d+)?)\s+.*?"
            r"(?P<token2>BTC|ETH|SOL|BITCOIN|ETHEREUM|SOLANA))",
            re.IGNORECASE,
        )

        for market in markets:
            # Must be binary and open
            if not market.is_binary or not market.is_open:
                continue

            # Check liquidity
            if market.liquidity < min_liquidity:
                continue

            # Check has token IDs
            if "clobTokenIds" in market.metadata:
                token_ids = market.metadata.get("clobTokenIds", [])
                if not token_ids or len(token_ids) < 2:
                    continue

            # Try to parse the question
            match = pattern.search(market.question)
            if not match:
                continue

            # Extract matched groups (pattern has two alternatives)
            parsed_token = (match.group("token1") or match.group("token2") or "").upper()
            parsed_price_str = match.group("price1") or match.group("price2") or "0"
            parsed_direction_raw = (match.group("direction") or "reach").lower()

            # Normalize token names
            if parsed_token in ["BITCOIN"]:
                parsed_token = "BTC"
            elif parsed_token in ["ETHEREUM"]:
                parsed_token = "ETH"
            elif parsed_token in ["SOLANA"]:
                parsed_token = "SOL"

            # Normalize direction: over/above/reach -> up, under/below -> down
            if parsed_direction_raw in ["above", "over", "reach"]:
                parsed_direction = "up"
            elif parsed_direction_raw in ["below", "under"]:
                parsed_direction = "down"
            else:
                parsed_direction = parsed_direction_raw

            parsed_price = float(parsed_price_str.replace(",", ""))

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
                direction=parsed_direction,  # type: ignore
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
            "id": self.id,
            "name": self.name,
            "has": {
                "fetch_markets": True,
                "fetch_market": True,
                "create_order": True,
                "cancel_order": True,
                "fetch_order": True,
                "fetch_open_orders": True,
                "fetch_positions": True,
                "fetch_balance": True,
                "rate_limit": True,
                "retry_logic": True,
            },
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
                        delay = self.retry_delay * (self.retry_backoff**attempt) + random.uniform(
                            0, 1
                        )
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
