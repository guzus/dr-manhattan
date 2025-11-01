from typing import Optional, Dict, Any
from datetime import datetime
from decimal import Decimal

from ..base.exchange import Exchange
from ..base.errors import NetworkError, ExchangeError, MarketNotFound
from ..models.market import Market
from ..models.order import Order, OrderSide, OrderStatus
from ..models.position import Position
from .polymarket_ws import PolymarketWebSocket


class Polymarket(Exchange):
    """Polymarket exchange implementation"""

    BASE_URL = "https://gamma-api.polymarket.com"
    CLOB_URL = "https://clob.polymarket.com"

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
        self.private_key = self.config.get('private_key')
        self.funder = self.config.get('funder')

    def _sign_order(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sign an order using EIP-712 for Polymarket CLOB
        
        This implements the proper signing required by Polymarket's CLOB API.
        """
        if not self.private_key:
            raise ExchangeError("Private key required for signing orders")
        
        try:
            from eth_account import Account
            from eth_account.messages import encode_structured_data
        except ImportError:
            raise ExchangeError(
                "eth-account required for order signing. Install with: pip install eth-account"
            )
        
        # EIP-712 domain for Polymarket CLOB
        domain = {
            "name": "ClobAuthDomain",
            "version": "1",
            "chainId": self.config.get('chain_id', 137),  # Polygon mainnet
        }
        
        # Build EIP-712 message
        message = {
            "tokenID": order_data["tokenID"],
            "price": order_data["price"],
            "size": order_data["size"],
            "side": order_data["side"],
            "timestamp": int(datetime.now().timestamp()),
        }
        
        # Add funder if provided (for proxy wallet)
        if self.funder:
            message["funder"] = self.funder
        
        # EIP-712 types
        types = {
            "Order": [
                {"name": "tokenID", "type": "string"},
                {"name": "price", "type": "string"},
                {"name": "size", "type": "string"},
                {"name": "side", "type": "string"},
                {"name": "timestamp", "type": "uint256"},
            ]
        }
        
        if self.funder:
            types["Order"].append({"name": "funder", "type": "address"})
        
        # Create structured data
        structured_data = {
            "types": types,
            "primaryType": "Order",
            "domain": domain,
            "message": message,
        }
        
        # Sign the message
        encoded_data = encode_structured_data(structured_data)
        account = Account.from_key(self.private_key)
        signed_message = account.sign_message(encoded_data)
        
        # Return signed order payload
        return {
            **order_data,
            "signature": signed_message.signature.hex(),
            "signer": account.address,
            "timestamp": message["timestamp"],
        }

    def _request(self, method: str, endpoint: str, params: Optional[Dict] = None) -> Any:
        """Make HTTP request to Polymarket API with retry logic"""
        import requests
        from ..base.errors import RateLimitError

        @self._retry_on_failure
        def _make_request():
            url = f"{self.BASE_URL}{endpoint}"
            headers = {}

            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            try:
                response = requests.request(
                    method,
                    url,
                    params=params,
                    headers=headers,
                    timeout=self.timeout
                )
                
                # Handle rate limiting
                if response.status_code == 429:
                    retry_after = int(response.headers.get('Retry-After', 1))
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

    def fetch_markets(self, params: Optional[Dict[str, Any]] = None) -> list[Market]:
        """Fetch all markets from Polymarket with retry logic"""
        @self._retry_on_failure
        def _fetch():
            # Default to active markets only if not specified
            query_params = params or {}
            if 'active' not in query_params and 'closed' not in query_params:
                query_params = {'active': True, 'closed': False, **query_params}

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

    def _parse_market(self, data: Dict[str, Any]) -> Market:
        """Parse market data from API response"""
        import json

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

        return Market(
            id=data.get("id", ""),
            question=data.get("question", ""),
            outcomes=outcomes,
            close_time=close_time,
            volume=volume,
            liquidity=liquidity,
            prices=prices,
            metadata=data
        )

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
        Create order on Polymarket CLOB
        
        This places a REAL order with REAL money.
        Requires proper authentication and order signing.
        """
        if not self.private_key:
            raise ExchangeError("Private key required to place orders")
        
        # Get token_id from params
        token_id = params.get('token_id') if params else None
        if not token_id:
            raise ExchangeError("token_id required in params")
        
        # Build order payload for CLOB API
        order_payload = {
            "tokenID": token_id,
            "price": str(price),
            "size": str(size),
            "side": side.value.upper(),  # BUY or SELL
        }
        
        # Sign the order
        signed_order = self._sign_order(order_payload)
        
        # Submit to CLOB API
        import requests
        response = requests.post(
            f"{self.CLOB_URL}/order",
            json=signed_order,
            timeout=self.timeout
        )
        
        if response.status_code != 200:
            raise ExchangeError(f"Order placement failed: {response.text}")
        
        result = response.json()
        
        return Order(
            id=result.get("orderID", ""),
            market_id=market_id,
            outcome=outcome,
            side=side,
            price=price,
            size=size,
            filled=0,
            status=OrderStatus.OPEN,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )

    def cancel_order(self, order_id: str, market_id: Optional[str] = None) -> Order:
        """Cancel order on Polymarket"""
        data = self._request("DELETE", f"/orders/{order_id}")
        return self._parse_order(data)

    def fetch_order(self, order_id: str, market_id: Optional[str] = None) -> Order:
        """Fetch order details"""
        data = self._request("GET", f"/orders/{order_id}")
        return self._parse_order(data)

    def fetch_open_orders(
        self,
        market_id: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> list[Order]:
        """Fetch open orders"""
        endpoint = "/orders"
        query_params = {"status": "open", **(params or {})}

        if market_id:
            query_params["market_id"] = market_id

        data = self._request("GET", endpoint, query_params)
        return [self._parse_order(order) for order in data]

    def fetch_positions(
        self,
        market_id: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> list[Position]:
        """Fetch current positions"""
        endpoint = "/positions"
        query_params = params or {}

        if market_id:
            query_params["market_id"] = market_id

        data = self._request("GET", endpoint, query_params)
        return [self._parse_position(pos) for pos in data]

    def fetch_balance(self) -> Dict[str, float]:
        """
        Fetch account balance from Polymarket
        
        Note: This requires implementation of Data API authentication.
        """
        if not self.private_key and not self.funder:
            raise ExchangeError("Private key or funder required to fetch balance")
        
        # TODO: Implement authenticated balance fetching via Data API
        # For now, this needs to be implemented based on Polymarket's Data API spec
        # You would make an authenticated request to the Data API here
        
        raise ExchangeError(
            "Balance fetching via Data API not yet implemented. "
            "You need to implement authentication for Polymarket's Data API endpoint."
        )

    def _parse_order(self, data: Dict[str, Any]) -> Order:
        """Parse order data from API response"""
        return Order(
            id=data.get("id", ""),
            market_id=data.get("market_id", ""),
            outcome=data.get("outcome", ""),
            side=OrderSide(data.get("side", "buy")),
            price=float(data.get("price", 0)),
            size=float(data.get("size", 0)),
            filled=float(data.get("filled", 0)),
            status=self._parse_order_status(data.get("status")),
            created_at=self._parse_datetime(data.get("created_at")),
            updated_at=self._parse_datetime(data.get("updated_at"))
        )

    def _parse_position(self, data: Dict[str, Any]) -> Position:
        """Parse position data from API response"""
        return Position(
            market_id=data.get("market_id", ""),
            outcome=data.get("outcome", ""),
            size=float(data.get("size", 0)),
            average_price=float(data.get("average_price", 0)),
            current_price=float(data.get("current_price", 0))
        )

    def _parse_order_status(self, status: str) -> OrderStatus:
        """Convert string status to OrderStatus enum"""
        status_map = {
            "pending": OrderStatus.PENDING,
            "open": OrderStatus.OPEN,
            "filled": OrderStatus.FILLED,
            "partially_filled": OrderStatus.PARTIALLY_FILLED,
            "cancelled": OrderStatus.CANCELLED,
            "rejected": OrderStatus.REJECTED
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

        Returns:
            PolymarketWebSocket instance

        Example:
            ws = exchange.get_websocket()
            await ws.watch_orderbook(asset_id, callback)
            ws.start()
        """
        if self._ws is None:
            self._ws = PolymarketWebSocket({
                'verbose': self.verbose,
                'auto_reconnect': True
            })
        return self._ws
