import json
import logging
import re
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Literal, Optional, Sequence

import pandas as pd
import requests
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import AssetType, BalanceAllowanceParams, OrderArgs, OrderType

from ..base.errors import (
    AuthenticationError,
    ExchangeError,
    InvalidOrder,
    MarketNotFound,
    NetworkError,
    RateLimitError,
)
from ..base.exchange import Exchange
from ..models import CryptoHourlyMarket
from ..models.market import Market
from ..models.order import Order, OrderSide, OrderStatus
from ..models.position import Position
from ..utils import setup_logger
from .polymarket_ws import PolymarketUserWebSocket, PolymarketWebSocket


@dataclass
class PublicTrade:
    proxy_wallet: str
    side: str
    asset: str
    condition_id: str
    size: float
    price: float
    timestamp: datetime
    title: str | None
    slug: str | None
    icon: str | None
    event_slug: str | None
    outcome: str | None
    outcome_index: int | None
    name: str | None
    pseudonym: str | None
    bio: str | None
    profile_image: str | None
    profile_image_optimized: str | None
    transaction_hash: str | None


@dataclass
class PricePoint:
    timestamp: datetime
    price: float
    raw: Dict[str, Any]


@dataclass
class Tag:
    id: str
    label: str | None
    slug: str | None
    force_show: bool | None
    force_hide: bool | None
    is_carousel: bool | None
    published_at: str | None
    created_at: str | None
    updated_at: str | None
    raw: dict


class Polymarket(Exchange):
    """Polymarket exchange implementation"""

    BASE_URL = "https://gamma-api.polymarket.com"
    CLOB_URL = "https://clob.polymarket.com"
    PRICES_HISTORY_URL = f"{CLOB_URL}/prices-history"
    DATA_API_URL = "https://data-api.polymarket.com"
    SUPPORTED_INTERVALS: Sequence[str] = ("1m", "1h", "6h", "1d", "1w", "max")
    PRICES_HISTORY_URL = f"{CLOB_URL}/prices-history"
    DATA_API_URL = "https://data-api.polymarket.com"
    SUPPORTED_INTERVALS: Sequence[str] = ("1m", "1h", "6h", "1d", "1w", "max")

    # Market type tags (Polymarket-specific)
    TAG_1H = "102175"  # 1-hour crypto price markets

    # Token normalization mapping
    TOKEN_ALIASES = {
        "BITCOIN": "BTC",
        "ETHEREUM": "ETH",
        "SOLANA": "SOL",
    }

    @staticmethod
    def normalize_token(token: str) -> str:
        """Normalize token symbol to standard format (e.g., BITCOIN -> BTC)"""
        token_upper = token.upper()
        return Polymarket.TOKEN_ALIASES.get(token_upper, token_upper)

    @staticmethod
    def parse_market_identifier(identifier: str) -> str:
        """
        Parse market slug from URL or return slug as-is.

        Supports multiple URL formats:
        - https://polymarket.com/event/SLUG
        - https://polymarket.com/event/SLUG?param=value
        - SLUG (direct slug input)

        Args:
            identifier: Market slug or full URL

        Returns:
            Market slug

        Example:
            >>> Polymarket.parse_market_identifier("fed-decision-in-december")
            'fed-decision-in-december'
            >>> Polymarket.parse_market_identifier("https://polymarket.com/event/fed-decision-in-december")
            'fed-decision-in-december'
        """
        if not identifier:
            return ""

        # If it's a URL, extract the slug
        if identifier.startswith("http"):
            # Remove query parameters
            identifier = identifier.split("?")[0]
            # Extract slug from URL
            # Format: https://polymarket.com/event/SLUG
            parts = identifier.rstrip("/").split("/")
            if "event" in parts:
                idx = parts.index("event")
                if idx + 1 < len(parts):
                    return parts[idx + 1]
            # Fallback: return last part
            return parts[-1]

        return identifier

    @property
    def id(self) -> str:
        return "polymarket"

    @property
    def name(self) -> str:
        return "Polymarket"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize Polymarket exchange"""
        super().__init__(config)
        self._ws = None
        self._user_ws = None
        self.private_key = self.config.get("private_key")
        self.funder = self.config.get("funder")
        self._clob_client = None
        self._address = None

        # Initialize CLOB client if private key is provided
        if self.private_key:
            self._initialize_clob_client()

    def _initialize_clob_client(self):
        """Initialize CLOB client with authentication."""
        try:
            chain_id = self.config.get("chain_id", 137)
            signature_type = self.config.get("signature_type", 2)

            # Initialize authenticated client
            self._clob_client = ClobClient(
                host=self.CLOB_URL,
                key=self.private_key,
                chain_id=chain_id,
                signature_type=signature_type,
                funder=self.funder,
            )

            # Derive and set API credentials for L2 authentication
            api_creds = self._clob_client.create_or_derive_api_creds()
            if not api_creds:
                raise AuthenticationError("Failed to derive API credentials")

            self._clob_client.set_api_creds(api_creds)

            # Verify L2 mode
            if self._clob_client.mode < 2:
                raise AuthenticationError(
                    f"Client not in L2 mode (current mode: {self._clob_client.mode})"
                )

            # Store address
            try:
                self._address = self._clob_client.get_address()
            except Exception:
                self._address = None

        except AuthenticationError:
            raise
        except Exception as e:
            raise AuthenticationError(f"Failed to initialize CLOB client: {e}")

    def _request(self, method: str, endpoint: str, params: Optional[Dict] = None) -> Any:
        """Make HTTP request to Polymarket API with retry logic"""

        @self._retry_on_failure
        def _make_request():
            url = f"{self.BASE_URL}{endpoint}"
            headers = {}

            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            try:
                response = requests.request(
                    method, url, params=params, headers=headers, timeout=self.timeout
                )

                # Handle rate limiting
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 1))
                    raise RateLimitError(f"Rate limited. Retry after {retry_after}s")

                response.raise_for_status()
                return response.json()
            except requests.Timeout as e:
                raise NetworkError(f"Request timeout: {e}")
            except requests.ConnectionError as e:
                raise NetworkError(f"Connection error: {e}")
            except requests.HTTPError as e:
                if response.status_code == 404:
                    raise ExchangeError(f"Resource not found: {endpoint}")
                elif response.status_code == 401:
                    raise AuthenticationError(f"Authentication failed: {e}")
                elif response.status_code == 403:
                    raise AuthenticationError(f"Access forbidden: {e}")
                else:
                    raise ExchangeError(f"HTTP error: {e}")
            except requests.RequestException as e:
                raise ExchangeError(f"Request failed: {e}")

        return _make_request()

    def fetch_markets(self, params: Optional[Dict[str, Any]] = None) -> list[Market]:
        """
        Fetch all markets from Polymarket

        Uses CLOB API instead of Gamma API because CLOB includes token IDs
        which are required for trading.
        """

        @self._retry_on_failure
        def _fetch():
            # Fetch from CLOB API /sampling-markets (includes token IDs and live markets)
            try:
                response = requests.get(f"{self.CLOB_URL}/sampling-markets", timeout=self.timeout)

                if response.status_code == 200:
                    result = response.json()
                    markets_data = result.get("data", result if isinstance(result, list) else [])

                    markets = []
                    for item in markets_data:
                        market = self._parse_sampling_market(item)
                        if market:
                            markets.append(market)

                    # Apply filters if provided
                    query_params = params or {}
                    if query_params.get("active") or (not query_params.get("closed", True)):
                        markets = [m for m in markets if m.is_open]

                    # Apply limit if provided
                    limit = query_params.get("limit")
                    if limit:
                        markets = markets[:limit]

                    if self.verbose:
                        print(f"✓ Fetched {len(markets)} markets from CLOB API (sampling-markets)")

                    return markets

            except Exception as e:
                if self.verbose:
                    print(f"CLOB API fetch failed: {e}, falling back to Gamma API")

            # Fallback to Gamma API (but won't have token IDs)
            query_params = params or {}
            if "active" not in query_params and "closed" not in query_params:
                query_params = {"active": True, "closed": False, **query_params}

            data = self._request("GET", "/markets", query_params)
            markets = []
            for item in data:
                market = self._parse_market(item)
                markets.append(market)
            return markets

        return _fetch()

    def fetch_market(self, market_id: str) -> Market:
        """Fetch specific market by ID with retry logic"""

        @self._retry_on_failure
        def _fetch():
            try:
                data = self._request("GET", f"/markets/{market_id}")
                return self._parse_market(data)
            except ExchangeError:
                raise MarketNotFound(f"Market {market_id} not found")

        return _fetch()

    def fetch_markets_by_slug(self, slug_or_url: str) -> List[Market]:
        """
        Fetch all markets from an event by slug or URL.

        For events with multiple markets (e.g., "which day will X happen"),
        this returns all markets in the event.

        Args:
            slug_or_url: Event slug or full Polymarket URL

        Returns:
            List of Market objects with token IDs populated
        """
        slug = self.parse_market_identifier(slug_or_url)

        if not slug:
            raise ValueError("Empty slug provided")

        try:
            response = requests.get(f"{self.BASE_URL}/events?slug={slug}", timeout=self.timeout)
        except requests.Timeout as e:
            raise NetworkError(f"Request timeout: {e}")
        except requests.ConnectionError as e:
            raise NetworkError(f"Connection error: {e}")
        except requests.RequestException as e:
            raise NetworkError(f"Request failed: {e}")

        if response.status_code == 404:
            raise MarketNotFound(f"Event not found: {slug}")
        elif response.status_code != 200:
            raise ExchangeError(f"Failed to fetch event: HTTP {response.status_code}")

        event_data = response.json()
        if not event_data or len(event_data) == 0:
            raise MarketNotFound(f"Event not found: {slug}")

        event = event_data[0]
        markets_data = event.get("markets", [])

        if not markets_data:
            raise MarketNotFound(f"No markets found in event: {slug}")

        markets = []
        for market_data in markets_data:
            market = self._parse_market(market_data)

            # Get token IDs from market data
            clob_token_ids = market_data.get("clobTokenIds", [])
            if isinstance(clob_token_ids, str):
                try:
                    clob_token_ids = json.loads(clob_token_ids)
                except json.JSONDecodeError:
                    clob_token_ids = []

            if clob_token_ids:
                market.metadata["clobTokenIds"] = clob_token_ids

            markets.append(market)

        return markets

    def get_orderbook(self, token_id: str) -> Dict[str, Any]:
        """
        Fetch orderbook for a specific token via REST API.

        Args:
            token_id: Token ID to fetch orderbook for

        Returns:
            Dictionary with 'bids' and 'asks' arrays
            Each entry: {'price': str, 'size': str}

        Example:
            >>> orderbook = exchange.get_orderbook(token_id)
            >>> best_bid = float(orderbook['bids'][0]['price'])
            >>> best_ask = float(orderbook['asks'][0]['price'])
        """
        try:
            response = requests.get(
                f"{self.CLOB_URL}/book", params={"token_id": token_id}, timeout=self.timeout
            )

            if response.status_code == 200:
                return response.json()

            return {"bids": [], "asks": []}

        except Exception as e:
            if self.verbose:
                print(f"Failed to fetch orderbook: {e}")
            return {"bids": [], "asks": []}

    def _parse_sampling_market(self, data: Dict[str, Any]) -> Optional[Market]:
        """Parse market data from CLOB sampling-markets API response"""
        try:
            # sampling-markets includes more fields than simplified-markets
            condition_id = data.get("condition_id")
            if not condition_id:
                return None

            # Extract question and description
            question = data.get("question", "")

            # Extract tick size (minimum price increment)
            # The API returns minimum_tick_size (e.g., 0.01 or 0.001)
            # Note: minimum_order_size is different - it's the min shares per order
            # Default to 0.01 (standard Polymarket tick size) if not provided
            minimum_tick_size = data.get("minimum_tick_size", 0.01)

            # Extract tokens - sampling-markets has them in "tokens" array
            tokens_data = data.get("tokens", [])
            token_ids = []
            outcomes = []
            prices = {}

            for token in tokens_data:
                if isinstance(token, dict):
                    token_id = token.get("token_id")
                    outcome = token.get("outcome", "")
                    price = token.get("price")

                    if token_id:
                        token_ids.append(str(token_id))
                    if outcome:
                        outcomes.append(outcome)
                    if outcome and price is not None:
                        try:
                            prices[outcome] = float(price)
                        except (ValueError, TypeError):
                            pass

            # Build metadata with token IDs
            metadata = {
                **data,
                "clobTokenIds": token_ids,
                "condition_id": condition_id,
                "minimum_tick_size": minimum_tick_size,
            }

            return Market(
                id=condition_id,
                question=question,
                outcomes=outcomes if outcomes else ["Yes", "No"],
                close_time=None,  # Can parse if needed
                volume=0,  # Not in sampling-markets
                liquidity=0,  # Not in sampling-markets
                prices=prices,
                metadata=metadata,
                tick_size=minimum_tick_size,
                description=data.get("description", ""),
            )
        except Exception as e:
            if self.verbose:
                print(f"Error parsing sampling market: {e}")
            return None

    def _parse_clob_market(self, data: Dict[str, Any]) -> Optional[Market]:
        """Parse market data from CLOB API response"""
        try:
            # CLOB API structure
            condition_id = data.get("condition_id")
            if not condition_id:
                return None

            # Extract tokens (already have token_id, outcome, price, winner)
            tokens = data.get("tokens", [])
            token_ids = []
            outcomes = []
            prices = {}

            for token in tokens:
                if isinstance(token, dict):
                    token_id = token.get("token_id")
                    outcome = token.get("outcome", "")
                    price = token.get("price")

                    if token_id:
                        token_ids.append(str(token_id))
                    if outcome:
                        outcomes.append(outcome)
                    if outcome and price is not None:
                        try:
                            prices[outcome] = float(price)
                        except (ValueError, TypeError):
                            pass

            # Build metadata with token IDs already included
            # Default to 0.01 (standard Polymarket tick size) if not provided
            minimum_tick_size = data.get("minimum_tick_size", 0.01)
            metadata = {
                **data,
                "clobTokenIds": token_ids,
                "condition_id": condition_id,
                "minimum_tick_size": minimum_tick_size,
            }

            return Market(
                id=condition_id,
                question="",  # CLOB API doesn't include question text
                outcomes=outcomes if outcomes else ["Yes", "No"],
                close_time=None,  # CLOB API doesn't include end date
                volume=0,  # CLOB API doesn't include volume
                liquidity=0,  # CLOB API doesn't include liquidity
                prices=prices,
                metadata=metadata,
                tick_size=minimum_tick_size,
                description=data.get("description", ""),
            )
        except Exception as e:
            if self.verbose:
                print(f"Error parsing CLOB market: {e}")
            return None

    def _parse_market(self, data: Dict[str, Any]) -> Market:
        """Parse market data from API response"""
        # Parse outcomes - can be JSON string or list
        outcomes_raw = data.get("outcomes", [])
        if isinstance(outcomes_raw, str):
            try:
                outcomes = json.loads(outcomes_raw)
            except (json.JSONDecodeError, TypeError):
                outcomes = []
        else:
            outcomes = outcomes_raw

        # Parse outcome prices - can be JSON string, list, or None
        prices_raw = data.get("outcomePrices")
        prices_list = []

        if prices_raw is not None:
            if isinstance(prices_raw, str):
                try:
                    prices_list = json.loads(prices_raw)
                except (json.JSONDecodeError, TypeError):
                    prices_list = []
            else:
                prices_list = prices_raw

        # Create prices dictionary mapping outcomes to prices
        prices = {}
        if len(outcomes) == len(prices_list) and prices_list:
            for outcome, price in zip(outcomes, prices_list):
                try:
                    price_val = float(price)
                    # Only add non-zero prices
                    if price_val > 0:
                        prices[outcome] = price_val
                except (ValueError, TypeError):
                    pass

        # Fallback: use bestBid/bestAsk if available and no prices found
        if not prices and len(outcomes) == 2:
            best_bid = data.get("bestBid")
            best_ask = data.get("bestAsk")
            if best_bid is not None and best_ask is not None:
                try:
                    bid = float(best_bid)
                    ask = float(best_ask)
                    if 0 < bid < 1 and 0 < ask <= 1:
                        # For binary: Yes price ~ask, No price ~(1-ask)
                        prices[outcomes[0]] = ask
                        prices[outcomes[1]] = 1.0 - bid
                except (ValueError, TypeError):
                    pass

        # Parse close time - check both endDate and closed status
        close_time = self._parse_datetime(data.get("endDate"))

        # Use volumeNum if available, fallback to volume
        volume = float(data.get("volumeNum", data.get("volume", 0)))
        liquidity = float(data.get("liquidityNum", data.get("liquidity", 0)))

        # Try to extract token IDs from various possible fields
        # Gamma API sometimes includes these in the response
        metadata = dict(data)
        if "tokens" in data and data["tokens"]:
            metadata["clobTokenIds"] = data["tokens"]
        elif "clobTokenIds" not in metadata and "tokenID" in data:
            # Single token ID - might be a simplified response
            metadata["clobTokenIds"] = [data["tokenID"]]

        # Ensure clobTokenIds is always a list, not a JSON string
        if "clobTokenIds" in metadata and isinstance(metadata["clobTokenIds"], str):
            try:
                metadata["clobTokenIds"] = json.loads(metadata["clobTokenIds"])
            except (json.JSONDecodeError, TypeError):
                # If parsing fails, remove it - will be fetched separately
                del metadata["clobTokenIds"]

        # Extract tick size - default to 0.01 (standard Polymarket tick size)
        # Gamma API may not include this field; CLOB API always does
        minimum_tick_size = data.get("minimum_tick_size", 0.01)
        metadata["minimum_tick_size"] = minimum_tick_size

        return Market(
            id=data.get("id", ""),
            question=data.get("question", ""),
            outcomes=outcomes,
            close_time=close_time,
            volume=volume,
            liquidity=liquidity,
            prices=prices,
            metadata=metadata,
            tick_size=minimum_tick_size,
            description=data.get("description", ""),
        )

    def fetch_token_ids(self, condition_id: str) -> list[str]:
        """
        Fetch token IDs for a specific market from CLOB API

        The Gamma API doesn't include token IDs, so we need to fetch them
        from the CLOB API when we need to trade.

        Based on actual CLOB API response structure.

        Args:
            condition_id: The market/condition ID

        Returns:
            List of token IDs as strings

        Raises:
            ExchangeError: If token IDs cannot be fetched
        """
        try:
            # Try simplified-markets endpoint
            # Response structure: {"data": [{"condition_id": ..., "tokens": [{"token_id": ..., "outcome": ...}]}]}
            try:
                response = requests.get(f"{self.CLOB_URL}/simplified-markets", timeout=self.timeout)

                if response.status_code == 200:
                    result = response.json()

                    # Check if response has "data" key
                    markets_list = result.get("data", result if isinstance(result, list) else [])

                    # Find the market with matching condition_id
                    for market in markets_list:
                        market_id = market.get("condition_id") or market.get("id")
                        if market_id == condition_id:
                            # Extract token IDs from tokens array
                            # Each token is an object: {"token_id": "...", "outcome": "...", "price": ...}
                            tokens = market.get("tokens", [])
                            if tokens and isinstance(tokens, list):
                                # Extract just the token_id strings
                                token_ids = []
                                for token in tokens:
                                    if isinstance(token, dict) and "token_id" in token:
                                        token_ids.append(str(token["token_id"]))
                                    elif isinstance(token, str):
                                        # In case it's already a string
                                        token_ids.append(token)

                                if token_ids:
                                    if self.verbose:
                                        print(
                                            f"✓ Found {len(token_ids)} token IDs via simplified-markets"
                                        )
                                        for i, tid in enumerate(token_ids):
                                            outcome = (
                                                tokens[i].get("outcome", f"outcome_{i}")
                                                if isinstance(tokens[i], dict)
                                                else f"outcome_{i}"
                                            )
                                            print(f"  [{i}] {outcome}: {tid}")
                                    return token_ids

                            # Fallback: check for clobTokenIds
                            clob_tokens = market.get("clobTokenIds")
                            if clob_tokens and isinstance(clob_tokens, list):
                                token_ids = [str(t) for t in clob_tokens]
                                if self.verbose:
                                    print(f"✓ Found token IDs via clobTokenIds: {token_ids}")
                                return token_ids
            except Exception as e:
                if self.verbose:
                    print(f"simplified-markets failed: {e}")

            # Try sampling-simplified-markets endpoint
            try:
                response = requests.get(
                    f"{self.CLOB_URL}/sampling-simplified-markets", timeout=self.timeout
                )

                if response.status_code == 200:
                    markets_list = response.json()
                    if not isinstance(markets_list, list):
                        markets_list = markets_list.get("data", [])

                    for market in markets_list:
                        market_id = market.get("condition_id") or market.get("id")
                        if market_id == condition_id:
                            # Extract from tokens array
                            tokens = market.get("tokens", [])
                            if tokens and isinstance(tokens, list):
                                token_ids = []
                                for token in tokens:
                                    if isinstance(token, dict) and "token_id" in token:
                                        token_ids.append(str(token["token_id"]))
                                    elif isinstance(token, str):
                                        token_ids.append(token)

                                if token_ids:
                                    if self.verbose:
                                        print(
                                            f"✓ Found token IDs via sampling-simplified-markets: {len(token_ids)} tokens"
                                        )
                                    return token_ids
            except Exception as e:
                if self.verbose:
                    print(f"sampling-simplified-markets failed: {e}")

            # Try markets endpoint
            try:
                response = requests.get(f"{self.CLOB_URL}/markets", timeout=self.timeout)

                if response.status_code == 200:
                    markets_list = response.json()
                    if not isinstance(markets_list, list):
                        markets_list = markets_list.get("data", [])

                    for market in markets_list:
                        market_id = market.get("condition_id") or market.get("id")
                        if market_id == condition_id:
                            # Extract from tokens array
                            tokens = market.get("tokens", [])
                            if tokens and isinstance(tokens, list):
                                token_ids = []
                                for token in tokens:
                                    if isinstance(token, dict) and "token_id" in token:
                                        token_ids.append(str(token["token_id"]))
                                    elif isinstance(token, str):
                                        token_ids.append(token)

                                if token_ids:
                                    if self.verbose:
                                        print(
                                            f"✓ Found token IDs via markets endpoint: {len(token_ids)} tokens"
                                        )
                                    return token_ids
            except Exception as e:
                if self.verbose:
                    print(f"markets endpoint failed: {e}")

            raise ExchangeError(
                f"Could not fetch token IDs for market {condition_id} from any CLOB endpoint"
            )

        except requests.RequestException as e:
            raise ExchangeError(f"Network error fetching token IDs: {e}")

    def create_order(
        self,
        market_id: str,
        outcome: str,
        side: OrderSide,
        price: float,
        size: float,
        params: Optional[Dict[str, Any]] = None,
    ) -> Order:
        """Create order on Polymarket CLOB"""
        if not self._clob_client:
            raise AuthenticationError("CLOB client not initialized. Private key required.")

        token_id = params.get("token_id") if params else None
        if not token_id:
            raise InvalidOrder("token_id required in params")

        try:
            # Create and sign order
            order_args = OrderArgs(
                token_id=token_id,
                price=float(price),
                size=float(size),
                side=side.value.upper(),
            )

            signed_order = self._clob_client.create_order(order_args)
            result = self._clob_client.post_order(signed_order, OrderType.GTC)

            # Parse result
            order_id = result.get("orderID", "") if isinstance(result, dict) else str(result)
            status_str = result.get("status", "LIVE") if isinstance(result, dict) else "LIVE"

            status_map = {
                "LIVE": OrderStatus.OPEN,
                "MATCHED": OrderStatus.FILLED,
                "CANCELLED": OrderStatus.CANCELLED,
            }

            return Order(
                id=order_id,
                market_id=market_id,
                outcome=outcome,
                side=side,
                price=price,
                size=size,
                filled=0,
                status=status_map.get(status_str, OrderStatus.OPEN),
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )

        except Exception as e:
            raise InvalidOrder(f"Order placement failed: {str(e)}")

    def cancel_order(self, order_id: str, market_id: Optional[str] = None) -> Order:
        """Cancel order on Polymarket"""
        if not self._clob_client:
            raise AuthenticationError("CLOB client not initialized. Private key required.")

        try:
            result = self._clob_client.cancel(order_id)
            if isinstance(result, dict):
                return self._parse_order(result)
            return Order(
                id=order_id,
                market_id=market_id or "",
                outcome="",
                side=OrderSide.BUY,
                price=0,
                size=0,
                filled=0,
                status=OrderStatus.CANCELLED,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
        except Exception as e:
            raise InvalidOrder(f"Failed to cancel order {order_id}: {str(e)}")

    def fetch_order(self, order_id: str, market_id: Optional[str] = None) -> Order:
        """Fetch order details"""
        data = self._request("GET", f"/orders/{order_id}")
        return self._parse_order(data)

    def fetch_open_orders(
        self, market_id: Optional[str] = None, params: Optional[Dict[str, Any]] = None
    ) -> list[Order]:
        """
        Fetch open orders using CLOB client

        Args:
            market_id: Can be either the numeric market ID or the hex conditionId.
                      If numeric, we filter by exact match. If hex (0x...), we use it directly.
        """
        if not self._clob_client:
            raise AuthenticationError("CLOB client not initialized. Private key required.")

        try:
            # Use CLOB client's get_orders method
            response = self._clob_client.get_orders()

            # Response is a list directly
            if isinstance(response, list):
                orders = response
            elif isinstance(response, dict) and "data" in response:
                orders = response["data"]
            else:
                if self.verbose:
                    print(f"Debug: Unexpected response format: {type(response)}")
                return []

            if not orders:
                return []

            # Filter by market_id if provided
            # Note: CLOB orders use hex conditionId (0x...) in the 'market' field
            if market_id:
                orders = [o for o in orders if o.get("market") == market_id]

            # Debug: Print first order's fields to identify size field
            if orders and self.verbose:
                debug_logger = logging.getLogger(__name__)
                debug_logger.debug(f"Sample order fields: {list(orders[0].keys())}")
                debug_logger.debug(f"Sample order data: {orders[0]}")

            # Parse orders
            return [self._parse_order(order) for order in orders]
        except Exception as e:
            if self.verbose:
                print(f"Warning: Failed to fetch open orders: {e}")
                traceback.print_exc()
            return []

    def fetch_positions(
        self, market_id: Optional[str] = None, params: Optional[Dict[str, Any]] = None
    ) -> list[Position]:
        """
        Fetch current positions from Polymarket.

        Note: On Polymarket, positions are represented by conditional token balances.
        This method queries token balances for the specified market.
        Since positions require market-specific token data, we can't query positions
        without a market context. Returns empty list if no market_id is provided.
        """
        if not self._clob_client:
            raise AuthenticationError("CLOB client not initialized. Private key required.")

        # Positions require market context on Polymarket
        # Without market_id, we can't determine which tokens to query
        if not market_id:
            return []

        # For now, return empty positions list
        # Positions will be queried on-demand when we have the market object with token IDs
        # This avoids the chicken-and-egg problem of needing to fetch the market just to get positions
        return []

    def fetch_positions_for_market(self, market: Market) -> list[Position]:
        """
        Fetch positions for a specific market object.
        This is the recommended way to fetch positions on Polymarket.

        Args:
            market: Market object with token IDs in metadata

        Returns:
            List of Position objects
        """
        if not self._clob_client:
            raise AuthenticationError("CLOB client not initialized. Private key required.")

        try:
            positions = []
            token_ids_raw = market.metadata.get("clobTokenIds", [])

            # Parse token IDs if they're stored as JSON string
            if isinstance(token_ids_raw, str):
                token_ids = json.loads(token_ids_raw)
            else:
                token_ids = token_ids_raw

            if not token_ids or len(token_ids) < 2:
                return positions

            # Query balance for each token
            for i, token_id in enumerate(token_ids):
                try:
                    params_obj = BalanceAllowanceParams(
                        asset_type=AssetType.CONDITIONAL, token_id=token_id
                    )
                    balance_data = self._clob_client.get_balance_allowance(params=params_obj)

                    if isinstance(balance_data, dict) and "balance" in balance_data:
                        balance_raw = balance_data["balance"]
                        # Convert from wei (6 decimals)
                        size = float(balance_raw) / 1e6 if balance_raw else 0.0

                        if size > 0:
                            # Determine outcome from market.outcomes
                            outcome = (
                                market.outcomes[i]
                                if i < len(market.outcomes)
                                else ("Yes" if i == 0 else "No")
                            )

                            # Get current price from market.prices
                            current_price = market.prices.get(outcome, 0.0)

                            position = Position(
                                market_id=market.id,
                                outcome=outcome,
                                size=size,
                                average_price=0.0,  # Not available from balance query
                                current_price=current_price,
                            )
                            positions.append(position)
                except Exception as e:
                    if self.verbose:
                        print(f"Failed to fetch balance for token {token_id}: {e}")
                    continue

            return positions

        except Exception as e:
            raise ExchangeError(f"Failed to fetch positions for market: {str(e)}")

    def find_crypto_hourly_market(
        self,
        token_symbol: Optional[str] = None,
        min_liquidity: float = 0.0,
        limit: int = 100,
        is_active: bool = True,
        is_expired: bool = False,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[tuple[Market, Any]]:
        """
        Find crypto hourly markets on Polymarket using tag-based filtering.

        Polymarket uses TAG_1H for 1-hour crypto price markets, which is more
        efficient than pattern matching on all markets.

        Args:
            token_symbol: Filter by token (e.g., "BTC", "ETH", "SOL")
            min_liquidity: Minimum liquidity required
            limit: Maximum markets to fetch
            is_active: If True, only return markets currently in progress (expiring within 1 hour)
            is_expired: If True, only return expired markets. If False, exclude expired markets.
            params: Additional parameters (can include 'tag_id' to override default tag)

        Returns:
            Tuple of (Market, CryptoHourlyMarket) or None
        """
        logger = setup_logger(__name__)

        # Use tag-based filtering for efficiency
        tag_id = (params or {}).get("tag_id", self.TAG_1H)

        if self.verbose:
            logger.info(f"Searching for crypto hourly markets with tag: {tag_id}")

        all_markets = []
        offset = 0
        page_size = 100

        while len(all_markets) < limit:
            # Use gamma-api with tag filtering
            url = f"{self.BASE_URL}/markets"
            query_params = {
                "active": "true",
                "closed": "false",
                "limit": min(page_size, limit - len(all_markets)),
                "offset": offset,
                "order": "volume",
                "ascending": "false",
            }

            if tag_id:
                query_params["tag_id"] = tag_id

            try:
                response = requests.get(url, params=query_params, timeout=10)
                response.raise_for_status()
                data = response.json()

                markets_data = data if isinstance(data, list) else []
                if not markets_data:
                    break

                # Parse markets
                for market_data in markets_data:
                    market = self._parse_market(market_data)
                    if market:
                        all_markets.append(market)

                offset += len(markets_data)

                # If we got fewer markets than requested, we've reached the end
                if len(markets_data) < page_size:
                    break

            except Exception as e:
                if self.verbose:
                    logger.error(f"Failed to fetch tagged markets: {e}")
                break

        if self.verbose:
            logger.info(f"Found {len(all_markets)} markets with tag {tag_id}")

        # Now parse and filter the markets
        # Pattern for "Up or Down" markets (e.g., "Bitcoin Up or Down - November 2, 7AM ET")
        up_down_pattern = re.compile(
            r"(?P<token>Bitcoin|Ethereum|Solana|BTC|ETH|SOL|XRP)\s+Up or Down", re.IGNORECASE
        )

        # Pattern for strike price markets (e.g., "Will BTC be above $95,000 at 5:00 PM ET?")
        strike_pattern = re.compile(
            r"(?:(?P<token1>BTC|ETH|SOL|BITCOIN|ETHEREUM|SOLANA)\s+.*?"
            r"(?P<direction>above|below|over|under|reach)\s+"
            r"[\$]?(?P<price1>[\d,]+(?:\.\d+)?))|"
            r"(?:[\$]?(?P<price2>[\d,]+(?:\.\d+)?)\s+.*?"
            r"(?P<token2>BTC|ETH|SOL|BITCOIN|ETHEREUM|SOLANA))",
            re.IGNORECASE,
        )

        for market in all_markets:
            # Must be binary and open
            if not market.is_binary or not market.is_open:
                continue

            # Check liquidity
            if market.liquidity < min_liquidity:
                continue

            # Check expiry time filtering based on is_active and is_expired parameters
            if market.close_time:
                # Handle timezone-aware datetime
                if market.close_time.tzinfo is not None:
                    now = datetime.now(timezone.utc)
                else:
                    now = datetime.now()

                time_until_expiry = (market.close_time - now).total_seconds()

                # Apply is_expired filter
                if is_expired:
                    # Only include expired markets
                    if time_until_expiry > 0:
                        continue
                else:
                    # Exclude expired markets
                    if time_until_expiry <= 0:
                        continue

                # Apply is_active filter (only applies to non-expired markets)
                if is_active and not is_expired:
                    # For active hourly markets, only include if expiring within 1 hour
                    # This ensures we get currently active hourly candles
                    if time_until_expiry > 3600:  # 1 hour in seconds
                        continue

            # Try "Up or Down" pattern first
            up_down_match = up_down_pattern.search(market.question)
            if up_down_match:
                parsed_token = self.normalize_token(up_down_match.group("token"))

                # Apply token filter
                if token_symbol and parsed_token != self.normalize_token(token_symbol):
                    continue

                expiry = (
                    market.close_time if market.close_time else datetime.now() + timedelta(hours=1)
                )

                crypto_market = CryptoHourlyMarket(
                    token_symbol=parsed_token,
                    expiry_time=expiry,
                    strike_price=None,
                    market_type="up_down",
                )

                return (market, crypto_market)

            # Try strike price pattern
            strike_match = strike_pattern.search(market.question)
            if strike_match:
                parsed_token = self.normalize_token(
                    strike_match.group("token1") or strike_match.group("token2") or ""
                )
                parsed_price_str = (
                    strike_match.group("price1") or strike_match.group("price2") or "0"
                )
                parsed_price = float(parsed_price_str.replace(",", ""))

                # Apply filters
                if token_symbol and parsed_token != self.normalize_token(token_symbol):
                    continue

                expiry = (
                    market.close_time if market.close_time else datetime.now() + timedelta(hours=1)
                )

                crypto_market = CryptoHourlyMarket(
                    token_symbol=parsed_token,
                    expiry_time=expiry,
                    strike_price=parsed_price,
                    market_type="strike_price",
                )

                return (market, crypto_market)

        return None

    def fetch_balance(self) -> Dict[str, float]:
        """
        Fetch account balance from Polymarket using CLOB client

        Returns:
            Dictionary with balance information including USDC
        """
        if not self._clob_client:
            raise AuthenticationError("CLOB client not initialized. Private key required.")

        try:
            # Fetch USDC (collateral) balance
            params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            balance_data = self._clob_client.get_balance_allowance(params=params)

            # Extract balance from response
            usdc_balance = 0.0
            if isinstance(balance_data, dict) and "balance" in balance_data:
                try:
                    # Balance is returned as a string in wei (6 decimals for USDC)
                    usdc_balance = float(balance_data["balance"]) / 1e6
                except (ValueError, TypeError):
                    usdc_balance = 0.0

            return {"USDC": usdc_balance}

        except Exception as e:
            raise ExchangeError(f"Failed to fetch balance: {str(e)}")

    def _parse_order(self, data: Dict[str, Any]) -> Order:
        """Parse order data from API response"""
        order_id = data.get("id") or data.get("orderID") or ""

        # Try multiple field names for size (CLOB API may use different names)
        size = float(
            data.get("size")
            or data.get("original_size")
            or data.get("amount")
            or data.get("original_amount")
            or 0
        )
        filled = float(data.get("filled") or data.get("matched") or data.get("matched_amount") or 0)

        return Order(
            id=order_id,
            market_id=data.get("market_id", ""),
            outcome=data.get("outcome", ""),
            side=OrderSide(data.get("side", "buy").lower()),
            price=float(data.get("price", 0)),
            size=size,
            filled=filled,
            status=self._parse_order_status(data.get("status")),
            created_at=self._parse_datetime(data.get("created_at")),
            updated_at=self._parse_datetime(data.get("updated_at")),
        )

    def _parse_position(self, data: Dict[str, Any]) -> Position:
        """Parse position data from API response"""
        return Position(
            market_id=data.get("market_id", ""),
            outcome=data.get("outcome", ""),
            size=float(data.get("size", 0)),
            average_price=float(data.get("average_price", 0)),
            current_price=float(data.get("current_price", 0)),
        )

    def _parse_order_status(self, status: str) -> OrderStatus:
        """Convert string status to OrderStatus enum"""
        status_map = {
            "pending": OrderStatus.PENDING,
            "open": OrderStatus.OPEN,
            "filled": OrderStatus.FILLED,
            "partially_filled": OrderStatus.PARTIALLY_FILLED,
            "cancelled": OrderStatus.CANCELLED,
            "rejected": OrderStatus.REJECTED,
        }
        return status_map.get(status, OrderStatus.OPEN)

    def _parse_datetime(self, timestamp: Optional[Any]) -> Optional[datetime]:
        """Parse datetime from various formats"""
        if not timestamp:
            return None

        if isinstance(timestamp, datetime):
            return timestamp

        try:
            if isinstance(timestamp, (int, float)):
                return datetime.fromtimestamp(timestamp)
            return datetime.fromisoformat(str(timestamp))
        except (ValueError, TypeError):
            return None

    def get_websocket(self) -> PolymarketWebSocket:
        """
        Get WebSocket instance for real-time orderbook updates.

        The WebSocket automatically updates the exchange's mid-price cache
        when orderbook data is received.

        Returns:
            PolymarketWebSocket instance

        Example:
            ws = exchange.get_websocket()
            await ws.watch_orderbook(asset_id, callback)
            ws.start()
        """
        if self._ws is None:
            self._ws = PolymarketWebSocket(
                config={"verbose": self.verbose, "auto_reconnect": True}, exchange=self
            )
        return self._ws

    def get_user_websocket(self) -> PolymarketUserWebSocket:
        """
        Get User WebSocket instance for real-time trade/fill notifications.

        Requires CLOB client to be initialized (private key required).

        Returns:
            PolymarketUserWebSocket instance

        Example:
            user_ws = exchange.get_user_websocket()
            user_ws.on_trade(lambda trade: print(f"Fill: {trade.size} @ {trade.price}"))
            user_ws.start()
        """
        if not self._clob_client:
            raise AuthenticationError(
                "CLOB client not initialized. Private key required for user WebSocket."
            )

        if self._user_ws is None:
            # Get API credentials from CLOB client
            creds = self._clob_client.creds
            if not creds:
                raise AuthenticationError("API credentials not available")

            self._user_ws = PolymarketUserWebSocket(
                api_key=creds.api_key,
                api_secret=creds.api_secret,
                api_passphrase=creds.api_passphrase,
                verbose=self.verbose,
            )
        return self._user_ws

        # -------------------------------------------------------------------------

    # ---------- polymarket_fetcher ----------

    def _ensure_market(self, market: Market | str) -> Market:
        if isinstance(market, Market):
            return market
        fetched = self.fetch_market(market)
        if not fetched:
            raise MarketNotFound(f"Market {market} not found")
        return fetched

    @staticmethod
    def _extract_token_ids(market: Market) -> List[str]:
        raw_ids = market.metadata.get("clobTokenIds", [])
        if isinstance(raw_ids, str):
            try:
                raw_ids = json.loads(raw_ids)
            except json.JSONDecodeError:
                raw_ids = [raw_ids]
        return [str(token_id) for token_id in raw_ids if token_id]

    def _lookup_token_id(self, market: Market, outcome: int | str | None) -> str:
        token_ids = self._extract_token_ids(market)
        if not token_ids:
            raise ExchangeError("Cannot fetch price history without token IDs in metadata.")

        if outcome is None:
            outcome_index = 0
        elif isinstance(outcome, int):
            outcome_index = outcome
        else:
            try:
                outcome_index = market.outcomes.index(outcome)
            except ValueError as err:
                raise ExchangeError(f"Outcome {outcome} not found in market {market.id}") from err

        if outcome_index < 0 or outcome_index >= len(token_ids):
            raise ExchangeError(
                f"Outcome index {outcome_index} out of range for market {market.id}"
            )

        return token_ids[outcome_index]

    def fetch_price_history(
        self,
        market: Market | str,
        *,
        outcome: int | str | None = None,
        interval: Literal["1m", "1h", "6h", "1d", "1w", "max"] = "1m",
        fidelity: int = 10,
        as_dataframe: bool = False,
    ) -> List[PricePoint] | pd.DataFrame:
        if interval not in self.SUPPORTED_INTERVALS:
            raise ValueError(
                f"Unsupported interval '{interval}'. Pick from {self.SUPPORTED_INTERVALS}."
            )

        market_obj = self._ensure_market(market)
        token_id = self._lookup_token_id(market_obj, outcome)

        params = {
            "market": token_id,
            "interval": interval,
            "fidelity": fidelity,
        }

        @self._retry_on_failure
        def _fetch() -> List[Dict[str, Any]]:
            resp = requests.get(self.PRICES_HISTORY_URL, params=params, timeout=self.timeout)
            resp.raise_for_status()
            payload = resp.json()
            history = payload.get("history", [])
            if not isinstance(history, list):
                raise ExchangeError("Invalid response: 'history' must be a list.")
            return history

        history = _fetch()
        points = self._parse_history(history)

        if as_dataframe:

            data = {
                "timestamp": [p.timestamp for p in points],
                "price": [p.price for p in points],
            }
            return pd.DataFrame(data).sort_values("timestamp").reset_index(drop=True)

        return points

    def _collect_paginated(
        self,
        fetch_page: Callable[[int, int], List[Any]],
        *,
        total_limit: int,
        initial_offset: int = 0,
        page_size: int = 500,
        dedup_key: Callable[[Any], Any] | None = None,
        log: bool | None = False,
    ) -> List[Any]:

        if total_limit <= 0:
            return []

        results: List[Any] = []
        current_offset = int(initial_offset)
        total_limit = int(total_limit)
        page_size = max(1, int(page_size))

        seen: set[Any] = set() if dedup_key else set()

        while len(results) < total_limit:
            remaining = total_limit - len(results)
            page_limit = min(page_size, remaining)

            if log:
                print("current-offset:", current_offset)
                print("page_limit:", page_limit)
                print("----------")

            page = fetch_page(current_offset, page_limit)

            if not page:
                break

            if dedup_key:
                new_items: List[Any] = []
                for item in page:
                    key = dedup_key(item)
                    if key in seen:
                        continue
                    seen.add(key)
                    new_items.append(item)

                if not new_items:
                    break

                results.extend(new_items)
            else:
                results.extend(page)

            current_offset += len(page)

            if len(page) < page_limit:
                break

        if len(results) > total_limit:
            results = results[:total_limit]

        return results

    def search_markets(
        self,
        *,
        # Gamma-side
        limit: int = 200,
        offset: int = 0,
        order: str | None = "id",
        ascending: bool | None = False,
        closed: bool | None = False,
        tag_id: int | None = None,
        ids: Sequence[int] | None = None,
        slugs: Sequence[str] | None = None,
        clob_token_ids: Sequence[str] | None = None,
        condition_ids: Sequence[str] | None = None,
        market_maker_addresses: Sequence[str] | None = None,
        liquidity_num_min: float | None = None,
        liquidity_num_max: float | None = None,
        volume_num_min: float | None = None,
        volume_num_max: float | None = None,
        start_date_min: datetime | None = None,
        start_date_max: datetime | None = None,
        end_date_min: datetime | None = None,
        end_date_max: datetime | None = None,
        related_tags: bool | None = None,
        cyom: bool | None = None,
        uma_resolution_status: str | None = None,
        game_id: str | None = None,
        sports_market_types: Sequence[str] | None = None,
        rewards_min_size: float | None = None,
        question_ids: Sequence[str] | None = None,
        include_tag: bool | None = None,
        extra_params: Dict[str, Any] | None = None,
        # Client-side
        query: str | None = None,
        keywords: Sequence[str] | None = None,
        binary: bool | None = None,
        min_liquidity: float = 0.0,
        categories: Sequence[str] | None = None,
        outcomes: Sequence[str] | None = None,
        predicate: Callable[[Market], bool] | None = None,
        # Log
        log: bool | None = False,
    ) -> List[Market]:

        # ---------- 0) Pre-process ----------
        total_limit = int(limit)
        if total_limit <= 0:
            return []

        initial_offset = max(0, int(offset))
        default_page_size_markets = 200
        page_size = min(default_page_size_markets, total_limit)

        def _dt(v: datetime | None) -> str | None:
            return v.isoformat() if isinstance(v, datetime) else None

        def _lower_list(values: Sequence[str] | None) -> List[str]:
            return [v.lower() for v in values] if values else []

        query_lower = query.lower() if query else None
        keyword_lowers = _lower_list(keywords)
        category_lowers = _lower_list(categories)
        outcome_lowers = _lower_list(outcomes)

        # ---------- 1) Gamma-side params ----------
        gamma_params: Dict[str, Any] = {}

        if order is not None:
            gamma_params["order"] = order
        if ascending is not None:
            gamma_params["ascending"] = ascending

        if closed is not None:
            gamma_params["closed"] = closed
        if tag_id is not None:
            gamma_params["tag_id"] = tag_id

        if ids:
            gamma_params["id"] = list(ids)
        if slugs:
            gamma_params["slug"] = list(slugs)
        if clob_token_ids:
            gamma_params["clob_token_ids"] = list(clob_token_ids)
        if condition_ids:
            gamma_params["condition_ids"] = list(condition_ids)
        if market_maker_addresses:
            gamma_params["market_maker_address"] = list(market_maker_addresses)

        if liquidity_num_min is not None:
            gamma_params["liquidity_num_min"] = liquidity_num_min
        if liquidity_num_max is not None:
            gamma_params["liquidity_num_max"] = liquidity_num_max
        if volume_num_min is not None:
            gamma_params["volume_num_min"] = volume_num_min
        if volume_num_max is not None:
            gamma_params["volume_num_max"] = volume_num_max

        if v := _dt(start_date_min):
            gamma_params["start_date_min"] = v
        if v := _dt(start_date_max):
            gamma_params["start_date_max"] = v
        if v := _dt(end_date_min):
            gamma_params["end_date_min"] = v
        if v := _dt(end_date_max):
            gamma_params["end_date_max"] = v

        if related_tags is not None:
            gamma_params["related_tags"] = related_tags
        if cyom is not None:
            gamma_params["cyom"] = cyom
        if uma_resolution_status is not None:
            gamma_params["uma_resolution_status"] = uma_resolution_status
        if game_id is not None:
            gamma_params["game_id"] = game_id
        if sports_market_types:
            gamma_params["sports_market_types"] = list(sports_market_types)
        if rewards_min_size is not None:
            gamma_params["rewards_min_size"] = rewards_min_size
        if question_ids:
            gamma_params["question_ids"] = list(question_ids)
        if include_tag is not None:
            gamma_params["include_tag"] = include_tag
        if extra_params:
            gamma_params.update(extra_params)

        # ---------- 2) Gamma pagination via helper ----------
        @self._retry_on_failure
        def _fetch_page(offset_: int, limit_: int) -> List[Market]:
            params = {
                **gamma_params,
                "limit": limit_,
                "offset": offset_,
            }
            resp = requests.get(
                f"{self.BASE_URL}/markets",
                params=params,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            raw = resp.json()
            if not isinstance(raw, list):
                raise ExchangeError("Gamma /markets response must be a list.")
            return [self._parse_market(m) for m in raw]

        gamma_results: List[Market] = self._collect_paginated(
            _fetch_page,
            total_limit=total_limit,
            initial_offset=initial_offset,
            page_size=page_size,
            dedup_key=None,
            log=log,
        )

        # ---------- 3) Client-side filtering ----------
        filtered: List[Market] = []

        for m in gamma_results:
            if binary is not None and m.is_binary != binary:
                continue
            if m.liquidity < min_liquidity:
                continue
            if outcome_lowers:
                outs = [o.lower() for o in m.outcomes]
                if not all(x in outs for x in outcome_lowers):
                    continue
            if category_lowers:
                cats = self._extract_categories(m)
                if not cats or not any(c in cats for c in category_lowers):
                    continue
            if query_lower or keyword_lowers:
                text = self._build_search_text(m)
                if query_lower and query_lower not in text:
                    continue
                if any(k not in text for k in keyword_lowers):
                    continue
            if predicate and not predicate(m):
                continue
            filtered.append(m)

        if len(filtered) > total_limit:
            filtered = filtered[:total_limit]

        return filtered

    def fetch_public_trades(
        self,
        market: Market | str | None = None,
        *,
        limit: int = 100,
        offset: int = 0,
        event_id: int | None = None,
        user: str | None = None,
        side: Literal["BUY", "SELL"] | None = None,
        taker_only: bool = True,
        filter_type: Literal["CASH", "TOKENS"] | None = None,
        filter_amount: float | None = None,
        as_dataframe: bool = False,
        log: bool = False,
    ) -> List[PublicTrade] | pd.DataFrame:

        total_limit = int(limit)
        if total_limit <= 0:
            return []

        if offset < 0 or offset > 10000:
            raise ValueError("offset must be between 0 and 10000")

        initial_offset = int(offset)
        default_page_size_trades = 500
        page_size = min(default_page_size_trades, total_limit)

        # ---------- condition_id resolve ----------
        condition_id: str | None = None
        if isinstance(market, Market):
            condition_id = str(market.metadata.get("conditionId", market.id))
        elif isinstance(market, str):
            condition_id = market

        base_params: Dict[str, Any] = {
            "takerOnly": "true" if taker_only else "false",
        }

        if condition_id:
            base_params["market"] = condition_id
        if event_id is not None:
            base_params["eventId"] = event_id
        if user:
            base_params["user"] = user
        if side:
            base_params["side"] = side

        if filter_type or filter_amount is not None:
            if not filter_type or filter_amount is None:
                raise ValueError("filter_type and filter_amount must be provided together")
            base_params["filterType"] = filter_type
            base_params["filterAmount"] = filter_amount

        # ---------- pagination via helper ----------
        @self._retry_on_failure
        def _fetch_page(offset_: int, limit_: int) -> List[Dict[str, Any]]:
            params = {
                **base_params,
                "limit": limit_,
                "offset": offset_,
            }

            resp = requests.get(
                f"{self.DATA_API_URL}/trades",
                params=params,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list):
                raise ExchangeError("Data-API /trades response must be a list.")
            return data

        def _dedup_key(row: Dict[str, Any]) -> tuple[Any, ...]:
            # transactionHash + timestamp + side + asset + size + price
            return (row.get("transactionHash"), row.get("outcomeIndex"))

        raw_trades: List[Dict[str, Any]] = self._collect_paginated(
            _fetch_page,
            total_limit=total_limit,
            initial_offset=initial_offset,
            page_size=page_size,
            dedup_key=_dedup_key,
            log=log,
        )

        # ---------- Dict -> PublicTrade ----------
        trades: List[PublicTrade] = []

        for row in raw_trades[:total_limit]:
            ts = row.get("timestamp")
            if isinstance(ts, (int, float)):
                ts_dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
            elif isinstance(ts, str) and ts.isdigit():
                ts_dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
            else:
                ts_dt = datetime.fromtimestamp(0, tz=timezone.utc)

            trades.append(
                PublicTrade(
                    proxy_wallet=row.get("proxyWallet", ""),
                    side=row.get("side", ""),
                    asset=row.get("asset", ""),
                    condition_id=row.get("conditionId", ""),
                    size=float(row.get("size", 0) or 0),
                    price=float(row.get("price", 0) or 0),
                    timestamp=ts_dt,
                    title=row.get("title"),
                    slug=row.get("slug"),
                    icon=row.get("icon"),
                    event_slug=row.get("eventSlug"),
                    outcome=row.get("outcome"),
                    outcome_index=row.get("outcomeIndex"),
                    name=row.get("name"),
                    pseudonym=row.get("pseudonym"),
                    bio=row.get("bio"),
                    profile_image=row.get("profileImage"),
                    profile_image_optimized=row.get("profileImageOptimized"),
                    transaction_hash=row.get("transactionHash"),
                )
            )

        if not as_dataframe:
            return trades

        # ---------- as_dataframe=True: Convert to DataFrame----------

        df = pd.DataFrame(
            [
                {
                    "timestamp": t.timestamp,
                    "side": t.side,
                    "asset": t.asset,
                    "condition_id": t.condition_id,
                    "size": t.size,
                    "price": t.price,
                    "proxy_wallet": t.proxy_wallet,
                    "title": t.title,
                    "slug": t.slug,
                    "event_slug": t.event_slug,
                    "outcome": t.outcome,
                    "outcome_index": t.outcome_index,
                    "name": t.name,
                    "pseudonym": t.pseudonym,
                    "bio": t.bio,
                    "profile_image": t.profile_image,
                    "profile_image_optimized": t.profile_image_optimized,
                    "transaction_hash": t.transaction_hash,
                }
                for t in trades
            ]
        )

        return df.sort_values("timestamp").reset_index(drop=True)

    @staticmethod
    def _extract_categories(market: Market) -> List[str]:
        buckets: List[str] = []
        meta = market.metadata

        raw_cat = meta.get("category")
        if isinstance(raw_cat, str):
            buckets.append(raw_cat.lower())

        for key in ("categories", "topics"):
            raw = meta.get(key)
            if isinstance(raw, str):
                buckets.append(raw.lower())
            elif isinstance(raw, Iterable):
                buckets.extend(str(item).lower() for item in raw)

        return buckets

    @staticmethod
    def _build_search_text(market: Market) -> str:
        meta = market.metadata

        base_fields = [
            market.question or "",
            meta.get("description", ""),
        ]

        extra_keys = [
            "slug",
            "category",
            "subtitle",
            "seriesSlug",
            "series",
            "seriesTitle",
            "seriesDescription",
            "tags",
            "topics",
            "categories",
        ]

        extras: List[str] = []
        for key in extra_keys:
            value = meta.get(key)
            if value is None:
                continue
            if isinstance(value, str):
                extras.append(value)
            elif isinstance(value, Iterable):
                extras.extend(str(item).lower() for item in value)
            else:
                extras.append(str(value))

        return " ".join(str(field) for field in (base_fields + extras)).lower()

    @staticmethod
    def _parse_history(history: Iterable[Dict[str, Any]]) -> List[PricePoint]:
        parsed: List[PricePoint] = []
        for row in history:
            t = row.get("t")
            p = row.get("p")
            if t is None or p is None:
                continue
            parsed.append(
                PricePoint(
                    timestamp=datetime.fromtimestamp(int(t), tz=timezone.utc),
                    price=float(p),
                    raw=row,
                )
            )
        return sorted(parsed, key=lambda item: item.timestamp)

    def get_tag_by_slug(self, slug: str) -> Tag:
        if not slug:
            raise ValueError("slug must be a non-empty string")

        url = f"{self.BASE_URL}/tags/slug/{slug}"

        @self._retry_on_failure
        def _fetch() -> dict:
            resp = requests.get(url, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict):
                raise ExchangeError("Gamma get_tag_by_slug response must be an object.")
            return data

        data = _fetch()

        return Tag(
            id=str(data.get("id", "")),
            label=data.get("label"),
            slug=data.get("slug"),
            force_show=data.get("forceShow"),
            force_hide=data.get("forceHide"),
            is_carousel=data.get("isCarousel"),
            published_at=data.get("publishedAt"),
            created_at=data.get("createdAt"),
            updated_at=data.get("UpdatedAt") if "UpdatedAt" in data else data.get("updatedAt"),
            raw=data,
        )
