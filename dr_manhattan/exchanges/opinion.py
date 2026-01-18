import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Literal, Optional, Sequence

import requests
from opinion_clob_sdk import Client as OpinionClient
from opinion_clob_sdk import TopicStatus, TopicStatusFilter, TopicType
from opinion_clob_sdk.chain.py_order_utils.model.order import PlaceOrderDataInput
from opinion_clob_sdk.chain.py_order_utils.model.order_type import LIMIT_ORDER, MARKET_ORDER
from opinion_clob_sdk.chain.py_order_utils.model.sides import BUY, SELL

from ..base.errors import (
    AuthenticationError,
    ExchangeError,
    InvalidOrder,
    MarketNotFound,
    NetworkError,
    RateLimitError,
)
from ..base.exchange import Exchange
from ..models.market import Market
from ..models.order import Order, OrderSide, OrderStatus, OrderTimeInForce
from ..models.position import Position


@dataclass
class PricePoint:
    """Represents a single price history point"""

    timestamp: datetime
    price: float
    raw: Dict[str, Any]


@dataclass
class PublicTrade:
    """Represents a public trade from Opinion"""

    id: str
    market_id: str
    token_id: str
    side: str
    price: float
    size: float
    timestamp: datetime
    maker: str = ""
    taker: str = ""
    outcome: str = ""
    transaction_hash: str = ""


@dataclass
class NAV:
    """Net Asset Value calculation result"""

    nav: float
    cash: float
    positions_value: float
    positions: List[Dict[str, Any]]


class Opinion(Exchange):
    """Opinion exchange implementation for BNB Chain prediction markets"""

    BASE_URL = "https://proxy.opinion.trade:8443"
    DATA_API_URL = "https://proxy.opinion.trade:8443"
    CHAIN_ID = 56  # BNB Chain mainnet
    DEFAULT_RPC_URL = "https://bsc-dataseed.binance.org"
    CONDITIONAL_TOKEN_ADDR = "0xAD1a38cEc043e70E83a3eC30443dB285ED10D774"
    MULTISEND_ADDR = "0x998739BFdAAdde7C933B942a68053933098f9EDa"

    SUPPORTED_INTERVALS: Sequence[str] = ("1m", "1h", "1d", "1w", "max")

    @property
    def id(self) -> str:
        return "opinion"

    @property
    def name(self) -> str:
        return "Opinion"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize Opinion exchange.

        Args:
            config: Configuration dictionary with:
                - api_key: API key for Opinion (required for trading)
                - private_key: Private key for signing transactions
                - multi_sig_addr: Multi-signature wallet address
                - rpc_url: RPC endpoint (optional, defaults to public BSC RPC)
                - host: API host URL (optional)
                - chain_id: Chain ID (optional, defaults to 56 for BSC)
        """
        super().__init__(config)

        self.api_key = self.config.get("api_key", "")
        self.private_key = self.config.get("private_key", "")
        self.multi_sig_addr = self.config.get("multi_sig_addr", "")
        self.rpc_url = self.config.get("rpc_url", self.DEFAULT_RPC_URL)
        self.host = self.config.get("host", self.BASE_URL)
        self.chain_id = self.config.get("chain_id", self.CHAIN_ID)

        self._client: Optional[OpinionClient] = None

        # Initialize client if credentials provided
        if self.api_key and self.private_key and self.multi_sig_addr:
            self._initialize_client()

    def _initialize_client(self):
        """Initialize Opinion CLOB client with authentication."""
        try:
            self._client = OpinionClient(
                host=self.host,
                apikey=self.api_key,
                chain_id=self.chain_id,
                rpc_url=self.rpc_url,
                private_key=self.private_key,
                multi_sig_addr=self.multi_sig_addr,
            )
        except Exception as e:
            raise AuthenticationError(f"Failed to initialize Opinion client: {e}")

    def _ensure_client(self):
        """Ensure client is initialized for authenticated operations."""
        if not self._client:
            raise AuthenticationError(
                "Opinion client not initialized. API key, private key, and multi_sig_addr required."
            )

    def _parse_market_id(self, market_id: str) -> int:
        """Safely parse market_id string to int."""
        try:
            return int(market_id)
        except (ValueError, TypeError):
            raise ExchangeError(f"Invalid market_id: {market_id}")

    def _request(self, method: str, endpoint: str, params: Optional[Dict] = None) -> Any:
        """Make HTTP request to Opinion API with retry logic"""

        @self._retry_on_failure
        def _make_request():
            url = f"{self.host}{endpoint}"
            headers = {}

            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
                headers["X-API-Key"] = self.api_key

            try:
                response = requests.request(
                    method, url, params=params, headers=headers, timeout=self.timeout
                )

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
                    raise ExchangeError(f"Authentication failed: {e}")
                elif response.status_code == 403:
                    raise ExchangeError(f"Access forbidden: {e}")
                else:
                    raise ExchangeError(f"HTTP error: {e}")
            except requests.RequestException as e:
                raise ExchangeError(f"Request failed: {e}")

        return _make_request()

    def _parse_market_response(self, response: Any, operation: str = "operation") -> Any:
        """Parse and validate market API response."""
        if hasattr(response, "errno") and response.errno != 0:
            raise ExchangeError(f"Failed to {operation}: {response}")

        if hasattr(response, "result") and hasattr(response.result, "data"):
            return response.result.data

        raise ExchangeError(f"Invalid response format for {operation}")

    def _parse_list_response(self, response: Any, operation: str = "operation") -> List[Any]:
        """Parse response containing a list."""
        if hasattr(response, "errno") and response.errno != 0:
            raise ExchangeError(f"Failed to {operation}: {response}")

        if hasattr(response, "result") and hasattr(response.result, "list"):
            return response.result.list or []

        raise ExchangeError(f"Invalid list response format for {operation}")

    def _parse_market(self, data: Any, fetch_prices: bool = True) -> Market:
        """Parse market data from Opinion API response."""
        # API uses market_id, not topic_id
        market_id = str(
            getattr(data, "market_id", "")
            or getattr(data, "topic_id", "")
            or getattr(data, "id", "")
        )
        # API uses market_title, not title/question
        question = (
            getattr(data, "market_title", "")
            or getattr(data, "title", "")
            or getattr(data, "question", "")
        )

        outcomes = []
        prices = {}
        token_ids = []
        child_markets_data = []

        # API provides yes_token_id/no_token_id directly, not tokens array
        yes_token_id = str(getattr(data, "yes_token_id", "") or "")
        no_token_id = str(getattr(data, "no_token_id", "") or "")
        yes_label = getattr(data, "yes_label", "") or "Yes"
        no_label = getattr(data, "no_label", "") or "No"

        # Check for child_markets (multi-outcome/categorical markets)
        child_markets = getattr(data, "child_markets", None) or []

        if yes_token_id and no_token_id:
            # Binary market with direct token IDs
            outcomes = [yes_label, no_label]
            token_ids = [yes_token_id, no_token_id]
        elif child_markets:
            # Multi-outcome market: extract from child_markets
            for child in child_markets:
                child_title = getattr(child, "market_title", "") or ""
                child_yes_token = str(getattr(child, "yes_token_id", "") or "")
                child_market_id = str(getattr(child, "market_id", "") or "")
                child_volume = getattr(child, "volume", "0") or "0"

                if child_title and child_yes_token:
                    outcomes.append(child_title)
                    token_ids.append(child_yes_token)
                    # Store child market info for reference
                    child_markets_data.append(
                        {
                            "market_id": child_market_id,
                            "title": child_title,
                            "yes_token_id": child_yes_token,
                            "no_token_id": str(getattr(child, "no_token_id", "") or ""),
                            "volume": child_volume,
                        }
                    )
        else:
            # Try legacy tokens array format
            tokens = getattr(data, "tokens", []) or []
            for token in tokens:
                outcome_name = getattr(token, "outcome", "") or getattr(token, "name", "")
                token_id = str(getattr(token, "token_id", ""))
                price = getattr(token, "price", None)

                if outcome_name:
                    outcomes.append(outcome_name)
                if token_id:
                    token_ids.append(token_id)
                if outcome_name and price is not None:
                    try:
                        prices[outcome_name] = float(price)
                    except (ValueError, TypeError):
                        pass

        if not outcomes:
            outcomes = ["Yes", "No"]

        # Fetch prices from orderbook if we have token IDs and client
        if fetch_prices and token_ids and self._client:
            for i, token_id in enumerate(token_ids):
                if i < len(outcomes):
                    try:
                        orderbook = self.get_orderbook(token_id)
                        bids = orderbook.get("bids", [])
                        asks = orderbook.get("asks", [])
                        best_bid = float(bids[0]["price"]) if bids else 0.0
                        best_ask = float(asks[0]["price"]) if asks else 0.0
                        # Use mid-price if both bid and ask exist, otherwise use whichever exists
                        if best_bid > 0 and best_ask > 0:
                            prices[outcomes[i]] = (best_bid + best_ask) / 2
                        elif best_ask > 0:
                            prices[outcomes[i]] = best_ask
                        elif best_bid > 0:
                            prices[outcomes[i]] = best_bid
                    except Exception:
                        pass

        close_time = None
        # API uses cutoff_at, not cutoff_time
        cutoff_time = (
            getattr(data, "cutoff_at", None)
            or getattr(data, "cutoff_time", None)
            or getattr(data, "end_time", None)
        )
        if cutoff_time:
            try:
                if isinstance(cutoff_time, (int, float)) and cutoff_time > 0:
                    close_time = datetime.fromtimestamp(cutoff_time, tz=timezone.utc)
                elif isinstance(cutoff_time, str):
                    close_time = datetime.fromisoformat(cutoff_time.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        volume_raw = getattr(data, "volume", 0) or 0
        try:
            volume = float(volume_raw)
        except (ValueError, TypeError):
            volume = 0.0
        liquidity = float(getattr(data, "liquidity", 0) or 0)

        # Opinion uses fixed tick size of 0.001 for all markets
        tick_size = 0.001

        # Build metadata with clobTokenIds for compatibility with base class
        metadata = {
            "topic_id": market_id,
            "market_id": market_id,
            "condition_id": getattr(data, "condition_id", ""),
            "status": getattr(data, "status", ""),
            "chain_id": getattr(data, "chain_id", self.chain_id),
            "quote_token": getattr(data, "quote_token", ""),
            "token_ids": token_ids,
            "clobTokenIds": token_ids,  # Compatibility with Polymarket pattern
            "tokens": {
                outcomes[i]: token_ids[i] for i in range(min(len(outcomes), len(token_ids)))
            },
            "child_markets": child_markets_data if child_markets_data else None,
            "is_multi_outcome": bool(child_markets_data),
            "description": getattr(data, "description", "") or getattr(data, "rules", ""),
            "category": getattr(data, "category", ""),
            "image_url": getattr(data, "image_url", ""),
            "minimum_tick_size": tick_size,
        }

        status = getattr(data, "status", None)
        if status == TopicStatus.RESOLVED.value:
            metadata["closed"] = True
        elif status == TopicStatus.ACTIVATED.value:
            metadata["closed"] = False
        else:
            metadata["closed"] = False  # Default to open for unknown status

        # Extract description from metadata (already stored there)
        description = metadata.get("description", "")

        return Market(
            id=market_id,
            question=question,
            outcomes=outcomes,
            close_time=close_time,
            volume=volume,
            liquidity=liquidity,
            prices=prices,
            metadata=metadata,
            tick_size=tick_size,
            description=description,
        )

    def fetch_markets(self, params: Optional[Dict[str, Any]] = None) -> List[Market]:
        """
        Fetch markets from Opinion.

        Args:
            params: Optional parameters:
                - all: If True, fetch all markets with pagination (default False)
                - topic_type: TopicType (ALL, BINARY, CATEGORICAL)
                - status: TopicStatusFilter (ALL, ACTIVATED, RESOLVED)
                - page: Page number (default 1)
                - limit: Items per page (1-20, default 20)
                - active: If True, only fetch active markets
                - closed: If True, include closed markets
        """
        self._ensure_client()
        query_params = params or {}

        if query_params.get("all"):
            return self._fetch_all_markets(query_params)

        @self._retry_on_failure
        def _fetch():
            topic_type = query_params.get("topic_type", TopicType.ALL)
            status = query_params.get("status", TopicStatusFilter.ACTIVATED)

            # Handle active/closed filters like Polymarket
            if query_params.get("active") or (not query_params.get("closed", True)):
                status = TopicStatusFilter.ACTIVATED

            page = query_params.get("page", 1)
            limit = min(query_params.get("limit", 20), 20)

            response = self._client.get_markets(
                topic_type=topic_type,
                status=status,
                page=page,
                limit=limit,
            )

            markets_data = self._parse_list_response(response, "fetch markets")
            # Don't fetch prices from orderbook for bulk market listing (performance)
            markets = [self._parse_market(m, fetch_prices=False) for m in markets_data]

            # Apply limit if provided
            if query_params.get("limit"):
                markets = markets[: query_params["limit"]]

            return markets

        return _fetch()

    def _fetch_all_markets(self, params: Dict[str, Any]) -> List[Market]:
        """Fetch all markets with automatic pagination."""
        all_markets: List[Market] = []
        page = 1
        max_pages = 100

        while page <= max_pages:
            page_params = {**params, "page": page, "limit": 20}
            page_params.pop("all", None)
            batch = self.fetch_markets(page_params)
            if not batch:
                break
            all_markets.extend(batch)
            page += 1

        return all_markets

    def fetch_market(self, market_id: str) -> Market:
        """
        Fetch a specific market by ID.

        Args:
            market_id: Market/Topic ID (works for both binary and categorical/multi markets)
        """
        self._ensure_client()

        @self._retry_on_failure
        def _fetch():
            # First try get_market (for binary markets)
            try:
                response = self._client.get_market(self._parse_market_id(market_id))
                if hasattr(response, "errno") and response.errno == 0:
                    market_data = self._parse_market_response(response, f"fetch market {market_id}")
                    return self._parse_market(market_data)
            except Exception:
                pass

            # If get_market fails, try get_categorical_market (for multi-outcome markets)
            try:
                response = self._client.get_categorical_market(self._parse_market_id(market_id))
                if hasattr(response, "errno") and response.errno == 0:
                    market_data = self._parse_market_response(
                        response, f"fetch categorical market {market_id}"
                    )
                    return self._parse_market(market_data)
            except Exception:
                pass

            raise MarketNotFound(f"Market {market_id} not found")

        return _fetch()

    def fetch_market_by_id(self, market_id: str) -> Optional[Market]:
        """
        Fetch market by numeric ID (equivalent to fetch_market_by_slug for Opinion).

        Args:
            market_id: Market ID

        Returns:
            Market object or None if not found
        """
        try:
            return self.fetch_market(market_id)
        except MarketNotFound:
            return None

    def get_orderbook(self, token_id: str) -> Dict[str, Any]:
        """
        Fetch orderbook for a specific token via REST API.

        Args:
            token_id: Token ID to fetch orderbook for

        Returns:
            Dictionary with 'bids' and 'asks' arrays
        """
        self._ensure_client()

        try:
            response = self._client.get_orderbook(token_id)

            if hasattr(response, "errno") and response.errno != 0:
                return {"bids": [], "asks": []}

            result = getattr(response, "result", None)
            if not result:
                return {"bids": [], "asks": []}

            bids = []
            asks = []

            raw_bids = getattr(result, "bids", []) or []
            for bid in raw_bids:
                try:
                    price = float(getattr(bid, "price", 0))
                    size = float(getattr(bid, "size", 0))
                    if price > 0 and size > 0:
                        bids.append({"price": str(price), "size": str(size)})
                except (ValueError, TypeError):
                    continue

            raw_asks = getattr(result, "asks", []) or []
            for ask in raw_asks:
                try:
                    price = float(getattr(ask, "price", 0))
                    size = float(getattr(ask, "size", 0))
                    if price > 0 and size > 0:
                        asks.append({"price": str(price), "size": str(size)})
                except (ValueError, TypeError):
                    continue

            bids.sort(key=lambda x: float(x["price"]), reverse=True)
            asks.sort(key=lambda x: float(x["price"]))

            return {"bids": bids, "asks": asks}

        except Exception as e:
            if self.verbose:
                print(f"Failed to fetch orderbook: {e}")
            return {"bids": [], "asks": []}

    def fetch_token_ids(self, market_id: str) -> List[str]:
        """
        Fetch token IDs for a specific market.

        Args:
            market_id: The market ID

        Returns:
            List of token IDs as strings

        Raises:
            ExchangeError: If token IDs cannot be fetched
        """
        try:
            market = self.fetch_market(market_id)
            token_ids = market.metadata.get("clobTokenIds", [])
            if token_ids:
                return token_ids
            raise ExchangeError(f"No token IDs found for market {market_id}")
        except MarketNotFound:
            raise ExchangeError(f"Market {market_id} not found")

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
        Create a new order on Opinion.

        Args:
            market_id: Market/Topic ID
            outcome: Outcome to bet on (e.g., "Yes", "No")
            side: OrderSide.BUY or OrderSide.SELL
            price: Price per share (0-1)
            size: Number of shares
            params: Additional parameters:
                - token_id: Token ID (required)
                - order_type: "limit" or "market" (default: "limit")
                - check_approval: Whether to check approvals (default: False)
            time_in_force: Order time in force. Opinion only supports GTC.
                FOK and IOC are not supported and will raise InvalidOrder.

        Returns:
            Order object
        """
        self._ensure_client()

        # Validate time_in_force - Opinion only supports GTC
        if time_in_force != OrderTimeInForce.GTC:
            raise InvalidOrder(
                f"Opinion does not support {time_in_force.value.upper()} orders. "
                "Only GTC orders are supported."
            )

        extra_params = params or {}
        token_id = extra_params.get("token_id")

        if not token_id:
            raise InvalidOrder("token_id required in params")

        if price <= 0 or price >= 1:
            raise InvalidOrder(f"Price must be between 0 and 1, got: {price}")

        opinion_side = BUY if side == OrderSide.BUY else SELL

        order_type_str = extra_params.get("order_type", "limit").lower()
        order_type = LIMIT_ORDER if order_type_str == "limit" else MARKET_ORDER

        order_input = PlaceOrderDataInput(
            marketId=self._parse_market_id(market_id),
            tokenId=str(token_id),
            price=str(price),
            side=opinion_side,
            orderType=order_type,
        )

        if side == OrderSide.BUY:
            order_input.makerAmountInQuoteToken = str(size)
        else:
            order_input.makerAmountInBaseToken = str(size)

        check_approval = extra_params.get("check_approval", False)

        try:
            result = self._client.place_order(order_input, check_approval=check_approval)

            order_id = ""
            status = OrderStatus.OPEN

            if hasattr(result, "errno") and result.errno != 0:
                raise InvalidOrder(f"Order placement failed: {result}")

            # Parse order_id from response (result.result.order_data.order_id)
            if hasattr(result, "result"):
                res = result.result
                if hasattr(res, "order_data"):
                    order_id = str(getattr(res.order_data, "order_id", ""))
                elif hasattr(res, "data"):
                    order_id = str(getattr(res.data, "order_id", ""))

            return Order(
                id=order_id,
                market_id=market_id,
                outcome=outcome,
                side=side,
                price=price,
                size=size,
                filled=0,
                status=status,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                time_in_force=time_in_force,
            )

        except InvalidOrder:
            raise
        except Exception as e:
            raise ExchangeError(f"Failed to create order: {e}")

    def cancel_order(self, order_id: str, market_id: Optional[str] = None) -> Order:
        """
        Cancel an existing order.

        Args:
            order_id: Order ID to cancel
            market_id: Market ID (optional)

        Returns:
            Updated Order object
        """
        self._ensure_client()

        try:
            result = self._client.cancel_order(order_id)

            if hasattr(result, "errno") and result.errno != 0:
                raise ExchangeError(f"Failed to cancel order: {result}")

            return Order(
                id=order_id,
                market_id=market_id or "",
                outcome="",
                side=OrderSide.BUY,
                price=0,
                size=0,
                filled=0,
                status=OrderStatus.CANCELLED,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

        except Exception as e:
            raise ExchangeError(f"Failed to cancel order {order_id}: {e}")

    def fetch_order(self, order_id: str, market_id: Optional[str] = None) -> Order:
        """
        Fetch order details by ID.

        Args:
            order_id: Order ID
            market_id: Market ID (optional)

        Returns:
            Order object
        """
        self._ensure_client()

        try:
            response = self._client.get_order_by_id(order_id)

            if hasattr(response, "errno") and response.errno != 0:
                raise ExchangeError(f"Order {order_id} not found")

            data = self._parse_market_response(response, f"fetch order {order_id}")
            return self._parse_order(data)

        except Exception as e:
            raise ExchangeError(f"Failed to fetch order {order_id}: {e}")

    def fetch_open_orders(
        self, market_id: Optional[str] = None, params: Optional[Dict[str, Any]] = None
    ) -> List[Order]:
        """
        Fetch all open orders.

        Args:
            market_id: Optional market filter
            params: Additional parameters:
                - page: Page number (default 1)
                - limit: Items per page (default 10)

        Returns:
            List of Order objects
        """
        self._ensure_client()

        query_params = params or {}
        page = query_params.get("page", 1)
        limit = query_params.get("limit", 10)

        try:
            response = self._client.get_my_orders(
                market_id=self._parse_market_id(market_id) if market_id else 0,
                status="1",
                limit=limit,
                page=page,
            )

            orders_data = self._parse_list_response(response, "fetch open orders")
            return [self._parse_order(o) for o in orders_data]

        except Exception as e:
            if self.verbose:
                print(f"Failed to fetch open orders: {e}")
            return []

    def _parse_order(self, data: Any) -> Order:
        """Parse order data from API response."""
        order_id = str(
            getattr(data, "order_id", "") or getattr(data, "id", "") or getattr(data, "orderID", "")
        )
        market_id = str(getattr(data, "topic_id", "") or getattr(data, "market_id", ""))

        # Opinion API: side=1 is Buy, side=2 is Sell (or use side_enum)
        side_enum = getattr(data, "side_enum", "")
        side_value = getattr(data, "side", 0)
        if side_enum:
            side = OrderSide.BUY if side_enum.lower() == "buy" else OrderSide.SELL
        elif isinstance(side_value, str):
            side = OrderSide.BUY if side_value.lower() == "buy" else OrderSide.SELL
        else:
            # Opinion API: 1=Buy, 2=Sell
            side = OrderSide.BUY if int(side_value) == 1 else OrderSide.SELL

        status_value = getattr(data, "status", 1)
        status = self._parse_order_status(status_value)

        price = float(getattr(data, "price", 0) or 0)
        # Opinion API uses order_shares for size
        size = float(
            getattr(data, "order_shares", 0)
            or getattr(data, "maker_amount", 0)
            or getattr(data, "size", 0)
            or getattr(data, "original_size", 0)
            or getattr(data, "amount", 0)
            or 0
        )
        # Opinion API uses filled_shares for filled amount
        filled = float(
            getattr(data, "filled_shares", 0)
            or getattr(data, "matched_amount", 0)
            or getattr(data, "filled", 0)
            or getattr(data, "matched", 0)
            or 0
        )

        created_at = self._parse_datetime(
            getattr(data, "created_at", None) or getattr(data, "timestamp", None)
        )
        updated_at = self._parse_datetime(getattr(data, "updated_at", None))

        if not created_at:
            created_at = datetime.now(timezone.utc)
        if not updated_at:
            updated_at = created_at

        return Order(
            id=order_id,
            market_id=market_id,
            outcome=getattr(data, "outcome", ""),
            side=side,
            price=price,
            size=size,
            filled=filled,
            status=status,
            created_at=created_at,
            updated_at=updated_at,
        )

    def _parse_order_status(self, status: Any) -> OrderStatus:
        """Convert string/int status to OrderStatus enum"""
        if isinstance(status, int):
            status_map = {
                0: OrderStatus.PENDING,
                1: OrderStatus.OPEN,
                2: OrderStatus.FILLED,
                3: OrderStatus.PARTIALLY_FILLED,
                4: OrderStatus.CANCELLED,
            }
            return status_map.get(status, OrderStatus.OPEN)

        status_str = str(status).lower()
        status_map = {
            "pending": OrderStatus.PENDING,
            "open": OrderStatus.OPEN,
            "live": OrderStatus.OPEN,
            "filled": OrderStatus.FILLED,
            "matched": OrderStatus.FILLED,
            "partially_filled": OrderStatus.PARTIALLY_FILLED,
            "cancelled": OrderStatus.CANCELLED,
            "canceled": OrderStatus.CANCELLED,
            "rejected": OrderStatus.REJECTED,
        }
        return status_map.get(status_str, OrderStatus.OPEN)

    def _parse_datetime(self, timestamp: Optional[Any]) -> Optional[datetime]:
        """Parse datetime from various formats"""
        if not timestamp:
            return None

        if isinstance(timestamp, datetime):
            return timestamp

        try:
            if isinstance(timestamp, (int, float)):
                return datetime.fromtimestamp(timestamp, tz=timezone.utc)
            return datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    def fetch_positions(
        self, market_id: Optional[str] = None, params: Optional[Dict[str, Any]] = None
    ) -> List[Position]:
        """
        Fetch current positions.

        Args:
            market_id: Optional market filter
            params: Additional parameters:
                - page: Page number (default 1)
                - limit: Items per page (default 10)

        Returns:
            List of Position objects
        """
        self._ensure_client()

        query_params = params or {}
        page = query_params.get("page", 1)
        limit = query_params.get("limit", 10)

        try:
            response = self._client.get_my_positions(
                market_id=self._parse_market_id(market_id) if market_id else 0,
                page=page,
                limit=limit,
            )

            positions_data = self._parse_list_response(response, "fetch positions")
            return [self._parse_position(p) for p in positions_data]

        except Exception as e:
            if self.verbose:
                print(f"Failed to fetch positions: {e}")
            return []

    def fetch_positions_for_market(self, market: Market) -> List[Position]:
        """
        Fetch positions for a specific market object.

        Args:
            market: Market object with token IDs in metadata

        Returns:
            List of Position objects
        """
        return self.fetch_positions(market_id=market.id)

    def _parse_position(self, data: Any) -> Position:
        """Parse position data from API response."""
        market_id = str(getattr(data, "topic_id", "") or getattr(data, "market_id", ""))
        outcome = getattr(data, "outcome", "") or getattr(data, "token_name", "")
        # Opinion API uses shares_owned for position size
        size = float(
            getattr(data, "shares_owned", 0)
            or getattr(data, "size", 0)
            or getattr(data, "balance", 0)
            or 0
        )
        # Opinion API uses avg_entry_price for average price
        average_price = float(
            getattr(data, "avg_entry_price", 0)
            or getattr(data, "average_price", 0)
            or getattr(data, "avg_price", 0)
            or 0
        )
        current_price = float(getattr(data, "current_price", 0) or getattr(data, "price", 0) or 0)

        return Position(
            market_id=market_id,
            outcome=outcome,
            size=size,
            average_price=average_price,
            current_price=current_price,
        )

    def fetch_balance(self) -> Dict[str, float]:
        """
        Fetch account balance.

        Returns:
            Dictionary with balance info (e.g., {'USDC': 1000.0})
        """
        self._ensure_client()

        try:
            response = self._client.get_my_balances()

            if hasattr(response, "errno") and response.errno != 0:
                raise ExchangeError(f"Failed to fetch balance: {response}")

            balances = {}

            if hasattr(response, "result"):
                result = response.result
                # Opinion API returns result.balances array
                if hasattr(result, "balances"):
                    for item in result.balances or []:
                        # Use available_balance field
                        balance = float(getattr(item, "available_balance", 0) or 0)
                        # Opinion uses USDT on BSC (quote_token is USDT contract)
                        balances["USDC"] = balance
                        break  # Only one balance expected
                elif hasattr(result, "list"):
                    for item in result.list or []:
                        symbol = getattr(item, "symbol", "") or getattr(item, "currency", "")
                        balance = float(
                            getattr(item, "balance", 0) or getattr(item, "available", 0) or 0
                        )
                        if symbol:
                            balances[symbol] = balance
                elif hasattr(result, "data"):
                    data = result.data
                    if hasattr(data, "balance"):
                        balances["USDC"] = float(data.balance)

            return balances

        except Exception as e:
            raise ExchangeError(f"Failed to fetch balance: {e}")

    def calculate_nav(self, market: Market) -> NAV:
        """
        Calculate Net Asset Value for a specific market.

        NAV = Cash + Sum(position_size * current_price) for all positions

        Args:
            market: Market object to calculate NAV for

        Returns:
            NAV object with nav, cash, positions_value, and positions breakdown
        """
        balances = self.fetch_balance()
        cash = balances.get("USDC", 0.0)

        positions = self.fetch_positions_for_market(market)
        positions_value = 0.0
        positions_breakdown = []

        for pos in positions:
            value = pos.size * pos.current_price
            positions_value += value
            positions_breakdown.append(
                {
                    "outcome": pos.outcome,
                    "size": pos.size,
                    "current_price": pos.current_price,
                    "value": value,
                }
            )

        nav = cash + positions_value

        return NAV(
            nav=nav,
            cash=cash,
            positions_value=positions_value,
            positions=positions_breakdown,
        )

    # TODO: Implement WebSocket when Opinion API provides it
    # - get_websocket() for real-time orderbook updates
    # - get_user_websocket() for trade/fill notifications

    # Opinion-specific methods
    def enable_trading(self) -> bool:
        """
        Enable trading by approving necessary tokens.

        Returns:
            True if successful
        """
        self._ensure_client()

        try:
            tx_hash, safe_tx_hash, return_value = self._client.enable_trading()
            if self.verbose:
                print(f"Trading enabled. TX: {tx_hash}")
            return True
        except Exception as e:
            raise ExchangeError(f"Failed to enable trading: {e}")

    def split(self, market_id: str, amount: int, check_approval: bool = True) -> Dict[str, str]:
        """
        Split collateral into outcome tokens.

        Args:
            market_id: Market ID
            amount: Amount in wei
            check_approval: Whether to check approvals first

        Returns:
            Transaction result
        """
        self._ensure_client()

        try:
            tx_hash, safe_tx_hash, return_value = self._client.split(
                market_id=self._parse_market_id(market_id),
                amount=amount,
                check_approval=check_approval,
            )
            return {
                "tx_hash": tx_hash or "",
                "safe_tx_hash": safe_tx_hash or "",
            }
        except Exception as e:
            raise ExchangeError(f"Failed to split: {e}")

    def merge(self, market_id: str, amount: int, check_approval: bool = True) -> Dict[str, str]:
        """
        Merge outcome tokens back into collateral.

        Args:
            market_id: Market ID
            amount: Amount in wei
            check_approval: Whether to check approvals first

        Returns:
            Transaction result
        """
        self._ensure_client()

        try:
            tx_hash, safe_tx_hash, return_value = self._client.merge(
                market_id=self._parse_market_id(market_id),
                amount=amount,
                check_approval=check_approval,
            )
            return {
                "tx_hash": tx_hash or "",
                "safe_tx_hash": safe_tx_hash or "",
            }
        except Exception as e:
            raise ExchangeError(f"Failed to merge: {e}")

    def redeem(self, market_id: str, check_approval: bool = True) -> Dict[str, str]:
        """
        Redeem winning outcome tokens after market resolution.

        Args:
            market_id: Market ID
            check_approval: Whether to check approvals first

        Returns:
            Transaction result
        """
        self._ensure_client()

        try:
            tx_hash, safe_tx_hash, return_value = self._client.redeem(
                market_id=self._parse_market_id(market_id),
                check_approval=check_approval,
            )
            return {
                "tx_hash": tx_hash or "",
                "safe_tx_hash": safe_tx_hash or "",
            }
        except Exception as e:
            raise ExchangeError(f"Failed to redeem: {e}")

    def cancel_all_orders(
        self, market_id: Optional[str] = None, side: Optional[OrderSide] = None
    ) -> Dict[str, Any]:
        """
        Cancel all open orders.

        Args:
            market_id: Optional market filter
            side: Optional side filter (BUY or SELL)

        Returns:
            Summary of cancellation results
        """
        self._ensure_client()

        try:
            opinion_side = None
            if side:
                opinion_side = BUY if side == OrderSide.BUY else SELL

            result = self._client.cancel_all_orders(
                market_id=self._parse_market_id(market_id) if market_id else None,
                side=opinion_side,
            )
            return result

        except Exception as e:
            raise ExchangeError(f"Failed to cancel all orders: {e}")

    # Helper methods (matching Polymarket)
    def _ensure_market(self, market: Market | str) -> Market:
        """Ensure we have a Market object"""
        if isinstance(market, Market):
            return market
        fetched = self.fetch_market(market)
        if not fetched:
            raise MarketNotFound(f"Market {market} not found")
        return fetched

    @staticmethod
    def _extract_token_ids(market: Market) -> List[str]:
        """Extract token IDs from market metadata"""
        raw_ids = market.metadata.get("clobTokenIds", []) or market.metadata.get("token_ids", [])
        if isinstance(raw_ids, str):
            try:
                raw_ids = json.loads(raw_ids)
            except json.JSONDecodeError:
                raw_ids = [raw_ids]
        return [str(token_id) for token_id in raw_ids if token_id]

    def _lookup_token_id(self, market: Market, outcome: int | str | None) -> str:
        """Look up token ID for a specific outcome"""
        token_ids = self._extract_token_ids(market)
        if not token_ids:
            raise ExchangeError("Cannot find token IDs in market metadata.")

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

    # Price history
    def fetch_price_history(
        self,
        market: Market | str,
        *,
        outcome: int | str | None = None,
        interval: Literal["1m", "1h", "1d", "1w", "max"] = "1h",
        start_at: Optional[int] = None,
        end_at: Optional[int] = None,
        as_dataframe: bool = False,
    ) -> List[PricePoint] | Any:
        """
        Get price history for a market/token.

        Args:
            market: Market object or ID
            outcome: Outcome index or name (default: first outcome)
            interval: Time interval (1m, 1h, 1d, 1w, max)
            start_at: Start timestamp (optional)
            end_at: End timestamp (optional)
            as_dataframe: Return as pandas DataFrame

        Returns:
            List of PricePoint objects or DataFrame
        """
        self._ensure_client()

        if interval not in self.SUPPORTED_INTERVALS:
            raise ValueError(
                f"Unsupported interval '{interval}'. Pick from {self.SUPPORTED_INTERVALS}."
            )

        market_obj = self._ensure_market(market)
        token_id = self._lookup_token_id(market_obj, outcome)

        @self._retry_on_failure
        def _fetch() -> List[Any]:
            response = self._client.get_price_history(
                token_id=token_id,
                interval=interval,
                start_at=start_at,
                end_at=end_at,
            )

            if hasattr(response, "errno") and response.errno != 0:
                return []

            result = getattr(response, "result", None)
            if not result:
                return []

            return getattr(result, "list", []) or getattr(result, "data", []) or []

        history = _fetch()
        points = self._parse_history(history)

        if as_dataframe:
            try:
                import pandas as pd
            except ImportError as exc:
                raise RuntimeError("pandas is required when as_dataframe=True.") from exc

            data = {
                "timestamp": [p.timestamp for p in points],
                "price": [p.price for p in points],
            }
            return pd.DataFrame(data).sort_values("timestamp").reset_index(drop=True)

        return points

    @staticmethod
    def _parse_history(history: Iterable[Any]) -> List[PricePoint]:
        """Parse price history data"""
        parsed: List[PricePoint] = []
        for row in history:
            t = getattr(row, "timestamp", None) or getattr(row, "t", None)
            p = getattr(row, "price", None) or getattr(row, "p", None)

            # Handle dict format
            if isinstance(row, dict):
                t = row.get("timestamp") or row.get("t")
                p = row.get("price") or row.get("p")

            if t is None or p is None:
                continue

            try:
                parsed.append(
                    PricePoint(
                        timestamp=datetime.fromtimestamp(int(t), tz=timezone.utc),
                        price=float(p),
                        raw=row if isinstance(row, dict) else {"timestamp": t, "price": p},
                    )
                )
            except (ValueError, TypeError):
                continue

        return sorted(parsed, key=lambda item: item.timestamp)

    # Search markets
    def search_markets(
        self,
        *,
        limit: int = 200,
        page: int = 1,
        topic_type: TopicType = TopicType.ALL,
        status: TopicStatusFilter = TopicStatusFilter.ACTIVATED,
        # Client-side filters
        query: str | None = None,
        keywords: Sequence[str] | None = None,
        binary: bool | None = None,
        min_liquidity: float = 0.0,
        categories: Sequence[str] | None = None,
        outcomes: Sequence[str] | None = None,
        predicate: Callable[[Market], bool] | None = None,
    ) -> List[Market]:
        """
        Search markets with various filters.

        Args:
            limit: Maximum markets to return
            page: Page number
            topic_type: TopicType filter
            status: TopicStatusFilter
            query: Text search query
            keywords: Required keywords
            binary: If True, only binary markets
            min_liquidity: Minimum liquidity
            categories: Filter by categories
            outcomes: Required outcomes
            predicate: Custom filter function

        Returns:
            List of matching Market objects
        """
        self._ensure_client()

        if limit <= 0:
            return []

        def _lower_list(values: Sequence[str] | None) -> List[str]:
            return [v.lower() for v in values] if values else []

        query_lower = query.lower() if query else None
        keyword_lowers = _lower_list(keywords)
        category_lowers = _lower_list(categories)
        outcome_lowers = _lower_list(outcomes)

        # Fetch markets
        all_markets = self.fetch_markets(
            {
                "topic_type": topic_type,
                "status": status,
                "page": page,
                "limit": min(limit, 20),  # API limit
            }
        )

        # Client-side filtering
        filtered: List[Market] = []

        for m in all_markets:
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

        if len(filtered) > limit:
            filtered = filtered[:limit]

        return filtered

    @staticmethod
    def _extract_categories(market: Market) -> List[str]:
        """Extract categories from market metadata"""
        buckets: List[str] = []
        meta = market.metadata

        raw_cat = meta.get("category")
        if isinstance(raw_cat, str):
            buckets.append(raw_cat.lower())

        for key in ("categories", "topics"):
            raw = meta.get(key)
            if isinstance(raw, str):
                buckets.append(raw.lower())
            elif isinstance(raw, Iterable) and not isinstance(raw, (str, dict)):
                buckets.extend(str(item).lower() for item in raw)

        return buckets

    @staticmethod
    def _build_search_text(market: Market) -> str:
        """Build searchable text from market"""
        meta = market.metadata

        base_fields = [
            market.question or "",
            meta.get("description", ""),
        ]

        extra_keys = ["category", "tags", "topics", "categories"]

        extras: List[str] = []
        for key in extra_keys:
            value = meta.get(key)
            if value is None:
                continue
            if isinstance(value, str):
                extras.append(value)
            elif isinstance(value, Iterable) and not isinstance(value, (str, dict)):
                extras.extend(str(item).lower() for item in value)
            else:
                extras.append(str(value))

        return " ".join(str(field) for field in (base_fields + extras)).lower()

    # Public trades
    def fetch_public_trades(
        self,
        market: Market | str | None = None,
        *,
        limit: int = 100,
        page: int = 1,
        side: Literal["BUY", "SELL"] | None = None,
    ) -> List[PublicTrade]:
        """
        Fetch public trade history.

        Args:
            market: Market object or ID (optional)
            limit: Maximum trades to return
            page: Page number
            side: Filter by side (BUY or SELL)

        Returns:
            List of PublicTrade objects
        """
        self._ensure_client()

        if limit < 0 or limit > 1000:
            raise ValueError("limit must be between 0 and 1000")

        # Note: This requires Opinion API to support public trades endpoint
        # For now, return empty list as placeholder
        # When Opinion adds this endpoint, implement the actual fetch

        if self.verbose:
            print("fetch_public_trades: Opinion API endpoint not yet available")

        return []

    def describe(self) -> Dict[str, Any]:
        """Return exchange metadata and capabilities."""
        return {
            "id": self.id,
            "name": self.name,
            "chain_id": self.chain_id,
            "host": self.host,
            "has": {
                "fetch_markets": True,
                "fetch_market": True,
                "fetch_market_by_id": True,
                "create_order": True,
                "cancel_order": True,
                "cancel_all_orders": True,
                "fetch_order": True,
                "fetch_open_orders": True,
                "fetch_positions": True,
                "fetch_positions_for_market": True,
                "fetch_balance": True,
                "get_orderbook": True,
                "fetch_token_ids": True,
                "fetch_price_history": True,
                "search_markets": True,
                "fetch_public_trades": False,  # Not yet available in Opinion API
                "get_websocket": False,  # TODO: Not yet available in Opinion API
                "get_user_websocket": False,  # TODO: Not yet available in Opinion API
                "enable_trading": True,
                "split": True,
                "merge": True,
                "redeem": True,
            },
        }
