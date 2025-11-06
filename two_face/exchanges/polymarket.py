import sys
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "poly-mm"))

try:
    from poly_mm.core.client import PolymarketClient
    from poly_mm.core.config import Config
    POLY_MM_AVAILABLE = True
except ImportError:
    POLY_MM_AVAILABLE = False
    PolymarketClient = None
    Config = None

try:
    from py_builder_signing_sdk import BuilderConfig, BuilderApiKeyCreds
    BUILDER_SDK_AVAILABLE = True
except ImportError:
    BUILDER_SDK_AVAILABLE = False
    BuilderConfig = None
    BuilderApiKeyCreds = None

from ..base.exchange import Exchange
from ..base.errors import NetworkError, ExchangeError, MarketNotFound
from ..models.market import Market
from ..models.order import Order, OrderSide, OrderStatus
from ..models.position import Position


class Polymarket(Exchange):
    """Polymarket exchange implementation using symbolic link"""

    BASE_URL = "https://gamma-api.polymarket.com"

    @property
    def id(self) -> str:
        return "polymarket"

    @property
    def name(self) -> str:
        return "Polymarket"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize Polymarket exchange

        Args:
            config: Configuration dictionary with optional keys:
                - private_key: Private key for authenticated trading
                - builder_api_key: Builder API key for order attribution
                - builder_secret: Builder secret for order attribution
                - builder_passphrase: Builder passphrase for order attribution
        """
        super().__init__(config)
        self.poly_client = None
        self.builder_config = None

        if self.config.get('builder_api_key') and self.config.get('builder_secret') and self.config.get('builder_passphrase'):
            self._initialize_builder_config()

        if self.config.get('private_key'):
            self._initialize_client()

    def _initialize_client(self):
        """Initialize Polymarket client"""
        if not POLY_MM_AVAILABLE:
            raise ExchangeError("poly-mm package not available. Please install dependencies from poly-mm/")

        try:
            poly_config = Config(
                private_key=self.config['private_key'],
                condition_id=self.config.get('condition_id', ''),
                yes_token_id=self.config.get('yes_token_id', ''),
                no_token_id=self.config.get('no_token_id', ''),
                dry_run=self.config.get('dry_run', False)
            )
            self.poly_client = PolymarketClient(poly_config)
            self.poly_client.initialize()
        except Exception as e:
            raise ExchangeError(f"Client initialization failed: {e}")

    def _initialize_builder_config(self):
        """Initialize builder configuration for order attribution"""
        if not BUILDER_SDK_AVAILABLE:
            raise ExchangeError("py-builder-signing-sdk not available. Install with: uv pip install py-builder-signing-sdk")

        try:
            creds = BuilderApiKeyCreds(
                key=self.config['builder_api_key'],
                secret=self.config['builder_secret'],
                passphrase=self.config['builder_passphrase']
            )
            self.builder_config = BuilderConfig(local_builder_creds=creds)
        except Exception as e:
            raise ExchangeError(f"Builder config initialization failed: {e}")

    def _request(self, method: str, endpoint: str, params: Optional[Dict] = None, json_data: Optional[Dict] = None) -> Any:
        """Make HTTP request to Polymarket API"""
        import requests
        import json as json_module

        url = f"{self.BASE_URL}{endpoint}"
        headers = {"Content-Type": "application/json"}

        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        if self.builder_config:
            body = json_module.dumps(json_data) if json_data else ""
            builder_headers = self.builder_config.generate_builder_headers(method, endpoint, body)
            headers.update(builder_headers)

        try:
            response = requests.request(
                method,
                url,
                params=params,
                json=json_data,
                headers=headers,
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            if isinstance(e, requests.Timeout):
                raise NetworkError(f"Request timeout: {e}")
            raise ExchangeError(f"Request failed: {e}")

    def fetch_markets(self, params: Optional[Dict[str, Any]] = None) -> list[Market]:
        """Fetch all markets from Polymarket"""
        data = self._request("GET", "/markets", params)

        markets = []
        for item in data:
            market = self._parse_market(item)
            markets.append(market)

        return markets

    def fetch_market(self, market_id: str) -> Market:
        """Fetch specific market by ID"""
        try:
            data = self._request("GET", f"/markets/{market_id}")
            return self._parse_market(data)
        except ExchangeError:
            raise MarketNotFound(f"Market {market_id} not found")

    def _parse_market(self, data: Dict[str, Any]) -> Market:
        """Parse market data from API response"""
        return Market(
            id=data.get("id", ""),
            question=data.get("question", ""),
            outcomes=data.get("outcomes", []),
            close_time=self._parse_datetime(data.get("end_date")),
            volume=float(data.get("volume", 0)),
            liquidity=float(data.get("liquidity", 0)),
            prices={
                outcome: float(price)
                for outcome, price in data.get("prices", {}).items()
            },
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
        """Create order on Polymarket"""
        if self.poly_client:
            token_id = params.get('token_id') if params else None
            if not token_id:
                raise ExchangeError("token_id required in params when using authenticated client")

            result = self.poly_client.create_limit_order(
                token_id=token_id,
                price=Decimal(str(price)),
                size=Decimal(str(size)),
                side=side.value.upper()
            )

            if result:
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

        payload = {
            "market_id": market_id,
            "outcome": outcome,
            "side": side.value,
            "price": price,
            "size": size,
            **(params or {})
        }

        data = self._request("POST", "/orders", json_data=payload)
        return self._parse_order(data)

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
        """Fetch account balance"""
        if self.poly_client:
            try:
                balance = self.poly_client.get_usdc_balance()
                return {"USDC": float(balance)}
            except Exception as e:
                raise ExchangeError(f"Failed to fetch balance: {e}")

        data = self._request("GET", "/balance")
        return {
            "USDC": float(data.get("balance", 0))
        }

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
