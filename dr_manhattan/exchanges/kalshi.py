"""
Kalshi exchange implementation for prediction markets.

Kalshi is a CFTC-regulated prediction market exchange in the US.
Authentication uses RSA-PSS with SHA256 signatures.
"""

import base64
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

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
from ..models.order import Order, OrderSide, OrderStatus
from ..models.orderbook import Orderbook
from ..models.position import Position

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
DEMO_URL = "https://demo-api.kalshi.co/trade-api/v2"


class KalshiAuth:
    """RSA-PSS with SHA256 signature authentication for Kalshi API."""

    def __init__(self, private_key_pem: str):
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding, rsa

            private_key = serialization.load_pem_private_key(
                private_key_pem.encode("utf-8"),
                password=None,
            )

            if not isinstance(private_key, rsa.RSAPrivateKey):
                raise AuthenticationError("Private key must be RSA key")

            self._private_key: rsa.RSAPrivateKey = private_key
            self._padding = padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            )
            self._hash_algorithm = hashes.SHA256()
        except ImportError as e:
            raise AuthenticationError(
                "cryptography package required for Kalshi authentication. "
                "Install with: uv pip install cryptography"
            ) from e
        except Exception as e:
            raise AuthenticationError(f"Failed to load RSA private key: {e}") from e

    def sign(self, timestamp_ms: int, method: str, path: str) -> str:
        message = f"{timestamp_ms}{method.upper()}/trade-api/v2{path}"
        signature = self._private_key.sign(
            message.encode("utf-8"),
            self._padding,
            self._hash_algorithm,
        )
        return base64.b64encode(signature).decode("utf-8")

    @classmethod
    def from_file(cls, path: str) -> "KalshiAuth":
        with open(path) as f:
            pem = f.read()
        return cls(pem)


class Kalshi(Exchange):
    """
    Kalshi exchange implementation.

    Kalshi is a CFTC-regulated prediction market in the United States.
    Supports binary markets with Yes/No outcomes.
    Prices are in cents (1-99) internally, converted to decimals (0.01-0.99).
    """

    BASE_URL = BASE_URL
    DEMO_URL = DEMO_URL

    @property
    def id(self) -> str:
        return "kalshi"

    @property
    def name(self) -> str:
        return "Kalshi"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)

        self._demo = self.config.get("demo", False)
        self._api_url = self.config.get("api_url") or (DEMO_URL if self._demo else BASE_URL)
        self._api_key_id = self.config.get("api_key_id")
        self._auth: Optional[KalshiAuth] = None

        if self._api_key_id:
            private_key_path = self.config.get("private_key_path")
            private_key_pem = self.config.get("private_key_pem")

            if private_key_path:
                self._auth = KalshiAuth.from_file(private_key_path)
            elif private_key_pem:
                self._auth = KalshiAuth(private_key_pem)

    def _is_authenticated(self) -> bool:
        return self._api_key_id is not None and self._auth is not None

    def _ensure_auth(self):
        if not self._is_authenticated():
            raise AuthenticationError(
                "Kalshi requires api_key_id and private key for this operation"
            )

    def _get_auth_headers(self, method: str, path: str) -> Dict[str, str]:
        if not self._is_authenticated() or self._auth is None or self._api_key_id is None:
            return {}

        timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        path_for_signing = path.split("?")[0]
        signature = self._auth.sign(timestamp_ms, method, path_for_signing)

        return {
            "KALSHI-ACCESS-KEY": self._api_key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": str(timestamp_ms),
        }

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
    ) -> Any:
        @self._retry_on_failure
        def _make_request():
            url = f"{self._api_url}{path}"
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            headers.update(self._get_auth_headers(method, path))

            try:
                if method.upper() in ("GET", "DELETE"):
                    response = requests.request(
                        method, url, params=params, headers=headers, timeout=self.timeout
                    )
                else:
                    response = requests.request(
                        method, url, json=body, headers=headers, timeout=self.timeout
                    )

                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 1))
                    raise RateLimitError(f"Rate limited. Retry after {retry_after}s")

                if response.status_code == 401 or response.status_code == 403:
                    msg = response.text or "Authentication failed"
                    raise AuthenticationError(msg)

                if response.status_code == 404:
                    raise ExchangeError(f"Resource not found: {path}")

                response.raise_for_status()
                return response.json()

            except requests.Timeout as e:
                raise NetworkError(f"Request timeout: {e}") from e
            except requests.ConnectionError as e:
                raise NetworkError(f"Connection error: {e}") from e
            except requests.HTTPError as e:
                raise ExchangeError(f"HTTP error: {e}") from e
            except requests.RequestException as e:
                raise ExchangeError(f"Request failed: {e}") from e

        return _make_request()

    def _parse_market(self, data: Dict[str, Any]) -> Optional[Market]:
        ticker = data.get("ticker")
        if not ticker:
            return None

        question = data.get("title", "")
        outcomes = ["Yes", "No"]

        yes_ask = data.get("yes_ask")
        yes_bid = data.get("yes_bid")
        last_price = data.get("last_price")

        # Calculate mid price
        if yes_bid is not None and yes_ask is not None:
            yes_price = (yes_bid + yes_ask) / 2 / 100
        elif yes_ask is not None:
            # Only ask exists, assume bid is 0
            yes_price = yes_ask / 2 / 100
        elif yes_bid is not None:
            # Only bid exists, assume ask is 100
            yes_price = (yes_bid + 100) / 2 / 100
        elif last_price is not None:
            yes_price = last_price / 100
        else:
            yes_price = 0.5

        no_price = 1.0 - yes_price

        prices = {
            "Yes": yes_price,
            "No": no_price,
        }

        volume = float(data.get("volume", 0) or 0)
        liquidity = float(data.get("open_interest", 0) or 0)

        close_time = None
        close_time_str = data.get("close_time") or data.get("expiration_time")
        if close_time_str:
            close_time = self._parse_datetime(close_time_str)

        description = data.get("subtitle", "") or data.get("rules_primary", "")
        tick_size = 0.01

        status = data.get("status", "")
        result = data.get("result")
        closed = status.lower() in ("closed", "settled") or result is not None

        metadata = {
            **data,
            "ticker": ticker,
            "event_ticker": data.get("event_ticker"),
            "closed": closed,
            "tokens": {
                "Yes": ticker,
                "No": ticker,
            },
            "clobTokenIds": [ticker, ticker],
        }

        return Market(
            id=ticker,
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

    def _parse_order(self, data: Dict[str, Any]) -> Order:
        order_id = data.get("order_id", "")
        market_id = data.get("ticker", "")

        action = (data.get("action") or "buy").lower()
        side = OrderSide.BUY if action == "buy" else OrderSide.SELL

        outcome_side = (data.get("side") or "yes").lower()
        outcome = "Yes" if outcome_side == "yes" else "No"

        status_str = (data.get("status") or "resting").lower()
        status_map = {
            "resting": OrderStatus.OPEN,
            "active": OrderStatus.OPEN,
            "pending": OrderStatus.PENDING,
            "executed": OrderStatus.FILLED,
            "filled": OrderStatus.FILLED,
            "canceled": OrderStatus.CANCELLED,
            "cancelled": OrderStatus.CANCELLED,
            "partial": OrderStatus.PARTIALLY_FILLED,
        }
        status = status_map.get(status_str, OrderStatus.OPEN)

        price_cents = data.get("yes_price") or data.get("no_price") or 0
        price = price_cents / 100 if price_cents else 0

        size = float(data.get("count") or data.get("remaining_count") or 0)
        filled = float(data.get("filled_count") or 0)

        created_at = self._parse_datetime(data.get("created_time")) or datetime.now(timezone.utc)
        updated_at = self._parse_datetime(data.get("updated_time"))

        return Order(
            id=order_id,
            market_id=market_id,
            outcome=outcome,
            side=side,
            price=price,
            size=size,
            filled=filled,
            status=status,
            created_at=created_at,
            updated_at=updated_at,
        )

    def _parse_position(self, data: Dict[str, Any]) -> Position:
        market_id = data.get("ticker", "")

        position_value = data.get("position", 0) or 0
        outcome = "Yes" if position_value >= 0 else "No"
        size = abs(float(position_value))

        average_price = 0.0
        current_price = 0.0

        return Position(
            market_id=market_id,
            outcome=outcome,
            size=size,
            average_price=average_price,
            current_price=current_price,
        )

    def _parse_datetime(self, timestamp: Optional[Any]) -> Optional[datetime]:
        if not timestamp:
            return None

        if isinstance(timestamp, datetime):
            return timestamp

        try:
            if isinstance(timestamp, (int, float)):
                return datetime.fromtimestamp(timestamp, tz=timezone.utc)

            timestamp_str = str(timestamp)
            if "+" in timestamp_str or "Z" in timestamp_str:
                return datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            return datetime.fromisoformat(timestamp_str)
        except (ValueError, TypeError):
            return None

    def fetch_markets(self, params: Optional[Dict[str, Any]] = None) -> List[Market]:
        @self._retry_on_failure
        def _fetch():
            query_params = params or {}
            limit = min(query_params.get("limit", 100), 200)

            endpoint = f"/markets?limit={limit}"

            if query_params.get("active", True):
                endpoint += "&status=open"

            response = self._request("GET", endpoint)
            markets_data = response.get("markets", [])

            markets = []
            for item in markets_data:
                market = self._parse_market(item)
                if market:
                    markets.append(market)

            return markets

        return _fetch()

    def fetch_market(self, market_id: str) -> Market:
        @self._retry_on_failure
        def _fetch():
            try:
                response = self._request("GET", f"/markets/{market_id}")
                market_data = response.get("market", {})
                market = self._parse_market(market_data)

                if not market:
                    raise MarketNotFound(f"Market {market_id} not found")

                return market
            except ExchangeError as e:
                if "not found" in str(e).lower():
                    raise MarketNotFound(f"Market {market_id} not found") from e
                raise

        return _fetch()

    def fetch_markets_by_slug(self, slug_or_url: str) -> List[Market]:
        @self._retry_on_failure
        def _fetch():
            endpoint = f"/markets?event_ticker={slug_or_url}"
            response = self._request("GET", endpoint)
            markets_data = response.get("markets", [])

            markets = []
            for item in markets_data:
                market = self._parse_market(item)
                if market:
                    markets.append(market)

            if not markets:
                raise MarketNotFound(f"No markets found for event: {slug_or_url}")

            return markets

        return _fetch()

    def get_orderbook(self, token_id: str) -> Dict[str, Any]:
        self._ensure_auth()

        try:
            response = self._request("GET", f"/markets/{token_id}/orderbook")
            orderbook = response.get("orderbook", {})

            bids = []
            asks = []

            yes_levels = orderbook.get("yes", [])
            for level in yes_levels:
                if isinstance(level, list) and len(level) >= 2:
                    price = level[0] / 100
                    size = level[1]
                    bids.append({"price": str(price), "size": str(size)})

            no_levels = orderbook.get("no", [])
            for level in no_levels:
                if isinstance(level, list) and len(level) >= 2:
                    price = 1.0 - (level[0] / 100)
                    size = level[1]
                    asks.append({"price": str(price), "size": str(size)})

            bids.sort(key=lambda x: float(x["price"]), reverse=True)
            asks.sort(key=lambda x: float(x["price"]))

            return {"bids": bids, "asks": asks}

        except Exception as e:
            if self.verbose:
                print(f"Failed to fetch orderbook: {e}")
            return {"bids": [], "asks": []}

    def fetch_orderbook(self, ticker: str) -> Orderbook:
        data = self.get_orderbook(ticker)

        bids = []
        asks = []

        for bid in data.get("bids", []):
            price = float(bid["price"])
            size = float(bid["size"])
            bids.append((price, size))

        for ask in data.get("asks", []):
            price = float(ask["price"])
            size = float(ask["size"])
            asks.append((price, size))

        return Orderbook(
            market_id=ticker,
            asset_id=ticker,
            bids=bids,
            asks=asks,
            timestamp=int(datetime.now(timezone.utc).timestamp() * 1000),
        )

    def create_order(
        self,
        market_id: str,
        outcome: str,
        side: OrderSide,
        price: float,
        size: float,
        params: Optional[Dict[str, Any]] = None,
    ) -> Order:
        self._ensure_auth()

        if price <= 0 or price >= 1:
            raise InvalidOrder("Price must be between 0 and 1")

        outcome_lower = outcome.lower()
        if outcome_lower not in ("yes", "no"):
            raise InvalidOrder("Outcome must be 'Yes' or 'No'")

        action = "buy" if side == OrderSide.BUY else "sell"
        price_cents = int(round(price * 100))

        body: Dict[str, Any] = {
            "ticker": market_id,
            "action": action,
            "side": outcome_lower,
            "type": "limit",
            "count": int(size),
        }

        if outcome_lower == "yes":
            body["yes_price"] = price_cents
        else:
            body["no_price"] = price_cents

        try:
            response = self._request("POST", "/portfolio/orders", body=body)
            order_data = response.get("order", {})
            return self._parse_order(order_data)
        except ExchangeError as e:
            raise InvalidOrder(f"Order placement failed: {e}") from e

    def cancel_order(self, order_id: str, market_id: Optional[str] = None) -> Order:
        self._ensure_auth()

        try:
            response = self._request("DELETE", f"/portfolio/orders/{order_id}")
            order_data = response.get("order", {})
            return self._parse_order(order_data)
        except ExchangeError as e:
            raise ExchangeError(f"Failed to cancel order {order_id}: {e}") from e

    def fetch_order(self, order_id: str, market_id: Optional[str] = None) -> Order:
        self._ensure_auth()

        response = self._request("GET", f"/portfolio/orders/{order_id}")
        order_data = response.get("order", {})
        return self._parse_order(order_data)

    def fetch_open_orders(
        self, market_id: Optional[str] = None, params: Optional[Dict[str, Any]] = None
    ) -> List[Order]:
        self._ensure_auth()

        try:
            endpoint = "/portfolio/orders?status=resting"
            if market_id:
                endpoint += f"&ticker={market_id}"

            response = self._request("GET", endpoint)
            orders_data = response.get("orders", [])
            return [self._parse_order(o) for o in orders_data]
        except Exception as e:
            if self.verbose:
                print(f"Failed to fetch open orders: {e}")
            return []

    def fetch_positions(
        self, market_id: Optional[str] = None, params: Optional[Dict[str, Any]] = None
    ) -> List[Position]:
        self._ensure_auth()

        try:
            endpoint = "/portfolio/positions"
            if market_id:
                endpoint += f"?ticker={market_id}"

            response = self._request("GET", endpoint)
            positions_data = response.get("market_positions", [])

            positions = []
            for p in positions_data:
                position = self._parse_position(p)
                if position.size > 0:
                    positions.append(position)

            return positions
        except Exception as e:
            if self.verbose:
                print(f"Failed to fetch positions: {e}")
            return []

    def fetch_balance(self) -> Dict[str, float]:
        self._ensure_auth()

        try:
            response = self._request("GET", "/portfolio/balance")

            available_balance = response.get("available_balance") or response.get("balance") or 0
            balance = available_balance / 100

            return {"USD": balance}
        except Exception as e:
            raise ExchangeError(f"Failed to fetch balance: {e}") from e

    def describe(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "demo": self._demo,
            "api_url": self._api_url,
            "has": {
                "fetch_markets": True,
                "fetch_market": True,
                "fetch_markets_by_slug": True,
                "create_order": True,
                "cancel_order": True,
                "fetch_order": True,
                "fetch_open_orders": True,
                "fetch_positions": True,
                "fetch_balance": True,
                "get_orderbook": True,
                "get_websocket": False,
                "get_user_websocket": False,
            },
        }
