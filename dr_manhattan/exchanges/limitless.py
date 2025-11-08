import sys
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "limitless-mm"))

try:
    from auth import AuthManager
    from models import Market as LimitlessMarket, OrderSide as LimitlessOrderSide
    LIMITLESS_MM_AVAILABLE = True
except ImportError:
    LIMITLESS_MM_AVAILABLE = False
    AuthManager = None
    LimitlessMarket = None
    LimitlessOrderSide = None

from ..base.exchange import Exchange
from ..base.errors import NetworkError, ExchangeError, MarketNotFound
from ..models.market import Market
from ..models.order import Order, OrderSide, OrderStatus
from ..models.position import Position


class Limitless(Exchange):
    """Limitless exchange implementation using symbolic link"""

    BASE_URL = "https://limitless.exchange/api"

    @property
    def id(self) -> str:
        return "limitless"

    @property
    def name(self) -> str:
        return "Limitless"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize Limitless exchange"""
        super().__init__(config)
        self.auth_manager = None
        if self.config.get('private_key'):
            self._initialize_auth()

    def _initialize_auth(self):
        """Initialize authentication with Limitless"""
        if not LIMITLESS_MM_AVAILABLE:
            raise ExchangeError("limitless-mm package not available. Please install dependencies from limitless-mm/")

        try:
            self.auth_manager = AuthManager()
            if not self.auth_manager.login():
                raise ExchangeError("Failed to authenticate with Limitless")
        except Exception as e:
            raise ExchangeError(f"Authentication initialization failed: {e}")

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None
    ) -> Any:
        """Make HTTP request to Limitless API"""
        if not self.auth_manager or not self.auth_manager.session:
            raise ExchangeError("Not authenticated. Please provide private_key in config")

        url = f"{self.BASE_URL}{endpoint}"

        try:
            response = self.auth_manager.session.request(
                method,
                url,
                params=params,
                json=data,
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            raise ExchangeError(f"Request failed: {e}")

    def fetch_markets(self, params: Optional[Dict[str, Any]] = None) -> list[Market]:
        """Fetch all markets from Limitless"""
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
            question=data.get("title", data.get("question", "")),
            outcomes=data.get("outcomes", ["Yes", "No"]),
            close_time=self._parse_datetime(data.get("closeDate")),
            volume=float(data.get("volume", 0)),
            liquidity=float(data.get("liquidity", 0)),
            prices={
                "Yes": float(data.get("yesPrice", 0)),
                "No": float(data.get("noPrice", 0))
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
        """Create order on Limitless"""
        payload = {
            "marketId": market_id,
            "outcome": outcome,
            "side": side.value,
            "price": price,
            "amount": size,
            **(params or {})
        }

        data = self._request("POST", "/orders", data=payload)
        return self._parse_order(data)

    def cancel_order(self, order_id: str, market_id: Optional[str] = None) -> Order:
        """Cancel order on Limitless"""
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
            query_params["marketId"] = market_id

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
            query_params["marketId"] = market_id

        data = self._request("GET", endpoint, query_params)
        return [self._parse_position(pos) for pos in data]

    def fetch_balance(self) -> Dict[str, float]:
        """Fetch account balance"""
        data = self._request("GET", "/balance")
        return {
            "USD": float(data.get("balance", 0))
        }

    def _parse_order(self, data: Dict[str, Any]) -> Order:
        """Parse order data from API response"""
        return Order(
            id=data.get("id", ""),
            market_id=data.get("marketId", ""),
            outcome=data.get("outcome", ""),
            side=OrderSide(data.get("side", "buy")),
            price=float(data.get("price", 0)),
            size=float(data.get("amount", 0)),
            filled=float(data.get("filled", 0)),
            status=self._parse_order_status(data.get("status")),
            created_at=self._parse_datetime(data.get("createdAt")),
            updated_at=self._parse_datetime(data.get("updatedAt"))
        )

    def _parse_position(self, data: Dict[str, Any]) -> Position:
        """Parse position data from API response"""
        return Position(
            market_id=data.get("marketId", ""),
            outcome=data.get("outcome", ""),
            size=float(data.get("size", 0)),
            average_price=float(data.get("averagePrice", 0)),
            current_price=float(data.get("currentPrice", 0))
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
            return datetime.fromisoformat(str(timestamp).replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return None
