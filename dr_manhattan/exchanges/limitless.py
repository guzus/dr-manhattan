"""
Limitless Exchange implementation for dr-manhattan.

Limitless is a prediction market on Base chain with CLOB-style orderbook.
Uses REST API for communication and EIP-712 for order signing.
"""

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Literal, Optional, Sequence

import requests
from eth_account import Account
from eth_account.messages import encode_typed_data

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
from .limitless_ws import (
    LimitlessUserWebSocket,
    LimitlessWebSocket,
    OrderbookUpdate,
    PositionUpdate,
    PriceUpdate,
    Trade,
    WebSocketState,
)

__all__ = [
    "Limitless",
    "LimitlessWebSocket",
    "LimitlessUserWebSocket",
    "WebSocketState",
    "OrderbookUpdate",
    "PriceUpdate",
    "PositionUpdate",
    "Trade",
]


@dataclass
class PricePoint:
    """Represents a single price history point"""

    timestamp: datetime
    price: float
    raw: Dict[str, Any]


@dataclass
class PublicTrade:
    """Represents a public trade from Limitless"""

    id: str
    slug: str
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


class Limitless(Exchange):
    """
    Limitless exchange implementation for Base chain prediction markets.

    Supports both public API (market data) and authenticated operations (trading).
    Uses EIP-712 message signing for authentication.
    """

    BASE_URL = "https://api.limitless.exchange"
    WS_URL = "wss://ws.limitless.exchange"
    CHAIN_ID = 8453  # Base mainnet

    SUPPORTED_INTERVALS: Sequence[str] = ("1m", "1h", "1d", "1w")

    @property
    def id(self) -> str:
        return "limitless"

    @property
    def name(self) -> str:
        return "Limitless"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize Limitless exchange.

        Args:
            config: Configuration dictionary with:
                - private_key: Private key for signing transactions (required for trading)
                - host: API host URL (optional, defaults to BASE_URL)
                - chain_id: Chain ID (optional, defaults to 8453 for Base)
        """
        super().__init__(config)

        self.private_key = self.config.get("private_key", "")
        self.host = self.config.get("host", self.BASE_URL)
        self.chain_id = self.config.get("chain_id", self.CHAIN_ID)

        self._session = requests.Session()
        self._account = None
        self._address = None
        self._authenticated = False
        self._owner_id = None  # User profile ID from login response

        # WebSocket instances
        self._ws: Optional[LimitlessWebSocket] = None
        self._user_ws: Optional[LimitlessUserWebSocket] = None

        # Token ID to market slug mapping (for orderbook lookups)
        self._token_to_slug: Dict[str, str] = {}
        # Track which token IDs are "No" tokens (need inverted orderbook)
        self._no_tokens: set = set()

        # Initialize account and authenticate if private key provided
        if self.private_key:
            self._initialize_auth()

    def _initialize_auth(self):
        """Initialize authentication with Limitless."""
        try:
            self._account = Account.from_key(self.private_key)
            self._address = self._account.address

            # Authenticate with Limitless API
            self._authenticate()
        except Exception as e:
            raise AuthenticationError(f"Failed to initialize authentication: {e}")

    def _authenticate(self):
        """Authenticate with Limitless using EIP-712 signing."""
        try:
            # Get signing message from API
            response = self._session.get(f"{self.host}/auth/signing-message", timeout=self.timeout)
            response.raise_for_status()

            # Response is plain text, not JSON
            message = response.text.strip()
            if not message:
                raise AuthenticationError("Failed to get signing message")

            # Sign the message
            signed = self._account.sign_message(signable_message=self._encode_defunct(message))
            signature = signed.signature.hex()
            if not signature.startswith("0x"):
                signature = f"0x{signature}"

            # Hex encode the signing message
            message_hex = "0x" + message.encode("utf-8").hex()

            # Login with signature
            headers = {
                "x-account": self._address,
                "x-signing-message": message_hex,
                "x-signature": signature,
            }

            login_response = self._session.post(
                f"{self.host}/auth/login",
                headers=headers,
                json={"client": "eoa"},
                timeout=self.timeout,
            )
            login_response.raise_for_status()

            # Extract ownerId from login response
            try:
                login_data = login_response.json()
                user_data = login_data.get("user", login_data)
                self._owner_id = user_data.get("id")
            except Exception:
                pass

            self._authenticated = True

            if self.verbose:
                print(f"Authenticated as {self._address}")

        except requests.RequestException as e:
            raise AuthenticationError(f"Authentication failed: {e}")

    def _encode_defunct(self, message: str):
        """Encode message for EIP-191 signing."""
        from eth_account.messages import encode_defunct

        return encode_defunct(text=message)

    def _ensure_authenticated(self):
        """Ensure user is authenticated for operations requiring auth."""
        if not self._authenticated:
            raise AuthenticationError(
                "Not authenticated. Provide private_key in config for trading operations."
            )

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        require_auth: bool = False,
    ) -> Any:
        """Make HTTP request to Limitless API with retry logic."""
        if require_auth:
            self._ensure_authenticated()

        @self._retry_on_failure
        def _make_request():
            url = f"{self.host}{endpoint}"

            try:
                response = self._session.request(
                    method, url, params=params, json=data, timeout=self.timeout
                )

                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 1))
                    raise RateLimitError(f"Rate limited. Retry after {retry_after}s")

                if response.status_code == 401 or response.status_code == 403:
                    # Try to re-authenticate
                    if self.private_key and self._account:
                        self._authenticate()
                        response = self._session.request(
                            method, url, params=params, json=data, timeout=self.timeout
                        )

                response.raise_for_status()
                return response.json()

            except requests.Timeout as e:
                raise NetworkError(f"Request timeout: {e}")
            except requests.ConnectionError as e:
                raise NetworkError(f"Connection error: {e}")
            except requests.HTTPError as e:
                # Try to get error details from response body
                error_detail = ""
                try:
                    error_body = response.json()
                    error_detail = error_body.get("message", str(error_body))
                except Exception:
                    error_detail = response.text[:200] if response.text else ""

                if response.status_code == 404:
                    raise ExchangeError(f"Resource not found: {endpoint}")
                elif response.status_code == 401:
                    raise AuthenticationError(f"Authentication failed: {e}")
                elif response.status_code == 403:
                    raise AuthenticationError(f"Access forbidden: {e}")
                elif response.status_code == 400:
                    raise ExchangeError(f"Bad request: {error_detail}")
                else:
                    raise ExchangeError(f"HTTP error: {e} - {error_detail}")
            except requests.RequestException as e:
                raise ExchangeError(f"Request failed: {e}")

        return _make_request()

    def fetch_markets(self, params: Optional[Dict[str, Any]] = None) -> List[Market]:
        """
        Fetch active markets from Limitless.

        Args:
            params: Optional parameters:
                - all: If True, fetch all markets with pagination (default False)
                - page: Page number (default 1)
                - limit: Items per page (default 25, max 25)
                - category: Filter by category ID
                - sortBy: Sort field

        Returns:
            List of Market objects
        """
        query_params = params or {}

        if query_params.get("all"):
            return self._fetch_all_markets(query_params)

        @self._retry_on_failure
        def _fetch():
            page = query_params.get("page", 1)
            limit = min(query_params.get("limit", 25), 25)  # API max is 25

            response = self._request(
                "GET",
                "/markets/active",
                params={"page": page, "limit": limit, **query_params},
            )

            markets_data = response.get("data", response if isinstance(response, list) else [])
            markets = [self._parse_market(m) for m in markets_data]

            # Apply additional filters
            if query_params.get("active") or (not query_params.get("closed", True)):
                markets = [m for m in markets if m.is_open]

            return markets

        return _fetch()

    def _fetch_all_markets(self, params: Dict[str, Any]) -> List[Market]:
        """Fetch all markets with automatic pagination."""
        all_markets: List[Market] = []
        page = 1
        max_pages = 100

        while page <= max_pages:
            page_params = {**params, "page": page, "limit": 25}
            page_params.pop("all", None)
            batch = self.fetch_markets(page_params)
            if not batch:
                break
            all_markets.extend(batch)
            page += 1

        return all_markets

    def fetch_market(self, market_id: str) -> Market:
        """
        Fetch a specific market by slug or address.

        Args:
            market_id: Market slug or contract address

        Returns:
            Market object
        """

        @self._retry_on_failure
        def _fetch():
            try:
                data = self._request("GET", f"/markets/{market_id}")
                return self._parse_market(data)
            except ExchangeError:
                raise MarketNotFound(f"Market {market_id} not found")

        return _fetch()

    def fetch_markets_by_slug(self, slug: str) -> List[Market]:
        """
        Fetch market(s) by slug, expanding nested markets if present.

        For multi-outcome events (e.g., Fed decision markets with multiple
        outcomes like "No change", "25 bps decrease"), this returns each
        nested market as a separate Market object.

        Args:
            slug: Market slug

        Returns:
            List of Market objects
        """
        try:
            market = self.fetch_market(slug)
        except MarketNotFound:
            return []

        # Check if this is a multi-market event with nested markets
        nested_markets = market.metadata.get("markets", [])
        if not nested_markets:
            return [market]

        # Expand nested markets
        result = []
        for nested_data in nested_markets:
            nested_market = self._parse_nested_market(nested_data, slug)
            result.append(nested_market)

        return result

    def _parse_nested_market(self, data: Dict[str, Any], parent_slug: str) -> Market:
        """Parse a nested market from a multi-outcome event."""
        title = data.get("title", data.get("question", ""))

        # Extract prices (nested markets use [yes, no] format)
        prices = {}
        price_data = data.get("prices", [])
        if isinstance(price_data, list) and len(price_data) >= 2:
            yes_price = float(price_data[0])
            no_price = float(price_data[1])
            prices["Yes"] = yes_price / 100 if yes_price > 1 else yes_price
            prices["No"] = no_price / 100 if no_price > 1 else no_price

        # Extract tokens
        tokens = data.get("tokens", {})
        yes_token = str(tokens.get("yes", "")) if tokens else ""
        no_token = str(tokens.get("no", "")) if tokens else ""
        token_ids = [yes_token, no_token] if yes_token and no_token else []

        # Parse close time
        close_time = None
        deadline = data.get("deadline") or data.get("expirationDate")
        if deadline:
            close_time = self._parse_datetime(deadline)

        # Volume
        volume = float(data.get("volumeFormatted") or data.get("volume") or 0)

        # Build metadata with match_id for cross-exchange matching
        metadata = {
            **data,
            "readable_id": [parent_slug, title],
            "match_id": title,
            "tokens": {"Yes": yes_token, "No": no_token},
            "token_ids": token_ids,
            "clobTokenIds": token_ids,
            "minimum_tick_size": 0.001,
            "closed": data.get("status", "").lower() in ("resolved", "closed"),
        }

        return Market(
            id=title,
            question=title,
            outcomes=["Yes", "No"],
            close_time=close_time,
            volume=volume,
            liquidity=0,
            prices=prices,
            metadata=metadata,
            tick_size=0.001,
        )

    def _parse_market(self, data: Dict[str, Any]) -> Market:
        """Parse market data from Limitless API response."""
        # Handle nested structure
        slug = data.get("slug", data.get("address", ""))
        title = data.get("title", data.get("question", ""))

        # Extract tokens (Yes/No)
        tokens = data.get("tokens", {})
        yes_token_id = str(tokens.get("yes", "")) if tokens else ""
        no_token_id = str(tokens.get("no", "")) if tokens else ""

        outcomes = ["Yes", "No"]
        token_ids = [yes_token_id, no_token_id] if yes_token_id and no_token_id else []

        # Extract prices (API returns percentage 0-100, normalize to 0-1)
        prices = {}
        if "yesPrice" in data:
            yes_price = float(data.get("yesPrice", 0) or 0)
            no_price = float(data.get("noPrice", 0) or 0)
            # Normalize to 0-1 range if in percentage format
            prices["Yes"] = yes_price / 100 if yes_price > 1 else yes_price
            prices["No"] = no_price / 100 if no_price > 1 else no_price
        elif "prices" in data:
            price_data = data.get("prices", {})
            if isinstance(price_data, list):
                # prices: [yes_price, no_price] - may be 0-100 or 0-1
                yes_price = float(price_data[0]) if price_data else 0
                no_price = float(price_data[1]) if len(price_data) > 1 else 0
                prices["Yes"] = yes_price / 100 if yes_price > 1 else yes_price
                prices["No"] = no_price / 100 if no_price > 1 else no_price
            elif isinstance(price_data, dict):
                yes_price = float(price_data.get("yes", 0) or 0)
                no_price = float(price_data.get("no", 0) or 0)
                prices["Yes"] = yes_price / 100 if yes_price > 1 else yes_price
                prices["No"] = no_price / 100 if no_price > 1 else no_price

        # Parse close time
        close_time = None
        deadline = data.get("deadline") or data.get("closeDate") or data.get("expirationDate")
        if deadline:
            close_time = self._parse_datetime(deadline)

        # Volume and liquidity (use formatted values if available)
        volume_raw = data.get("volumeFormatted") or data.get("volume") or 0
        liquidity_raw = data.get("liquidityFormatted") or data.get("liquidity") or 0
        volume = float(volume_raw) if volume_raw else 0
        liquidity = float(liquidity_raw) if liquidity_raw else 0

        # Limitless uses fixed tick size of 0.001 for all markets
        tick_size = 0.001

        # Build metadata
        metadata = {
            **data,
            "slug": slug,
            "clobTokenIds": token_ids,
            "token_ids": token_ids,
            "tokens": {"Yes": yes_token_id, "No": no_token_id},
            "minimum_tick_size": tick_size,
        }

        # Check status
        status = data.get("status", "")
        if status.lower() in ("resolved", "closed"):
            metadata["closed"] = True
        else:
            metadata["closed"] = False

        # Cache token_id -> slug mapping for orderbook lookups
        for token_id in token_ids:
            if token_id:
                self._token_to_slug[token_id] = slug
        # Track No token for orderbook inversion
        if no_token_id:
            self._no_tokens.add(no_token_id)

        return Market(
            id=slug,
            question=title,
            outcomes=outcomes,
            close_time=close_time,
            volume=volume,
            liquidity=liquidity,
            prices=prices,
            metadata=metadata,
            tick_size=tick_size,
            description=data.get("description", ""),
        )

    def get_orderbook(self, market_slug_or_token_id: str) -> Dict[str, Any]:
        """
        Fetch orderbook for a specific market.

        Args:
            market_slug_or_token_id: Market slug or token ID (token ID will be mapped to slug)

        Returns:
            Dictionary with 'bids' and 'asks' arrays

        Note:
            Limitless has one orderbook per market (for Yes token).
            For No token, we invert: No bids = 1-Yes asks, No asks = 1-Yes bids
        """
        # Check if this is a No token (needs inverted orderbook)
        is_no_token = market_slug_or_token_id in self._no_tokens

        # Map token_id to slug
        slug = self._token_to_slug.get(market_slug_or_token_id, market_slug_or_token_id)

        try:
            response = self._request("GET", f"/markets/{slug}/orderbook")

            bids = []
            asks = []

            orders = response.get("orders", response.get("data", []))
            for order in orders:
                side = order.get("side", "").lower()
                price = float(order.get("price", 0) or 0)
                size = float(order.get("size", 0) or 0)

                if price > 0 and size > 0:
                    entry = {"price": str(price), "size": str(size)}
                    if side == "buy":
                        bids.append(entry)
                    else:
                        asks.append(entry)

            # Also check for pre-sorted bids/asks
            if "bids" in response:
                for bid in response["bids"]:
                    bids.append(
                        {"price": str(bid.get("price", 0)), "size": str(bid.get("size", 0))}
                    )
            if "asks" in response:
                for ask in response["asks"]:
                    asks.append(
                        {"price": str(ask.get("price", 0)), "size": str(ask.get("size", 0))}
                    )

            # Sort: bids descending, asks ascending
            bids.sort(key=lambda x: float(x["price"]), reverse=True)
            asks.sort(key=lambda x: float(x["price"]))

            # For No token, invert the orderbook
            # No bids (buy No) = 1 - Yes asks
            # No asks (sell No) = 1 - Yes bids
            if is_no_token:
                inverted_bids = [
                    {"price": str(round(1 - float(a["price"]), 3)), "size": a["size"]} for a in asks
                ]
                inverted_asks = [
                    {"price": str(round(1 - float(b["price"]), 3)), "size": b["size"]} for b in bids
                ]
                # Re-sort after inversion
                inverted_bids.sort(key=lambda x: float(x["price"]), reverse=True)
                inverted_asks.sort(key=lambda x: float(x["price"]))
                return {"bids": inverted_bids, "asks": inverted_asks}

            return {"bids": bids, "asks": asks}

        except Exception as e:
            if self.verbose:
                print(f"Failed to fetch orderbook: {e}")
            return {"bids": [], "asks": []}

    def fetch_token_ids(self, market_id: str) -> List[str]:
        """
        Fetch token IDs for a specific market.

        Args:
            market_id: Market slug or address

        Returns:
            List of token IDs [yes_token_id, no_token_id]
        """
        market = self.fetch_market(market_id)
        token_ids = market.metadata.get("clobTokenIds", [])
        if token_ids:
            return token_ids
        raise ExchangeError(f"No token IDs found for market {market_id}")

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
        Create a new order on Limitless.

        Args:
            market_id: Market slug
            outcome: Outcome to bet on ("Yes" or "No")
            side: OrderSide.BUY or OrderSide.SELL
            price: Price per share (0-1)
            size: Size in USDC
            params: Additional parameters:
                - token_id: Token ID (optional if outcome provided)
                - order_type: "GTC" or "FOK" (default: "GTC")
            time_in_force: Order time in force. Limitless supports GTC and FOK only.
                IOC is not supported and will raise InvalidOrder.

        Returns:
            Order object
        """
        self._ensure_authenticated()

        # Validate time_in_force - Limitless only supports GTC and FOK
        if time_in_force == OrderTimeInForce.IOC:
            raise InvalidOrder("Limitless does not support IOC orders. Use GTC or FOK instead.")

        extra_params = params or {}
        token_id = extra_params.get("token_id")

        # Get market data for token_id and venue
        market = self.fetch_market(market_id)

        if not token_id:
            tokens = market.metadata.get("tokens", {})
            token_id = tokens.get(outcome)
            if not token_id:
                raise InvalidOrder(f"Could not find token_id for outcome '{outcome}'")

        if price <= 0 or price >= 1:
            raise InvalidOrder(f"Price must be between 0 and 1, got: {price}")

        # Map time_in_force to order_type, or use params override
        order_type = extra_params.get("order_type")
        if not order_type:
            order_type = "FOK" if time_in_force == OrderTimeInForce.FOK else "GTC"
        order_type = order_type.upper()

        # Get venue exchange address for EIP-712 signing
        venue = market.metadata.get("venue", {})
        exchange_address = venue.get("exchange") if venue else None
        if not exchange_address:
            raise InvalidOrder("Market does not have venue.exchange address")

        # Fee rate (300 bps = 3%)
        fee_rate_bps = 300

        # Build and sign the order
        try:
            signed_order = self._build_signed_order(
                token_id=str(token_id),
                price=price,
                size=size,
                side=side,
                order_type=order_type,
                exchange_address=exchange_address,
                fee_rate_bps=fee_rate_bps,
            )

            # Build payload
            payload = {
                "order": signed_order,
                "orderType": order_type,
                "marketSlug": market_id,
            }

            # Add ownerId if available
            if self._owner_id:
                payload["ownerId"] = self._owner_id

            result = self._request("POST", "/orders", data=payload, require_auth=True)

            order_data = result.get("order", result)
            order_id = order_data.get("id", order_data.get("orderId", ""))
            status_str = order_data.get("status", "LIVE").upper()

            return Order(
                id=str(order_id),
                market_id=market_id,
                outcome=outcome,
                side=side,
                price=price,
                size=size,
                filled=float(order_data.get("filled", 0) or 0),
                status=self._parse_order_status(status_str),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

        except InvalidOrder:
            raise
        except Exception as e:
            raise InvalidOrder(f"Order placement failed: {e}")

    def _build_signed_order(
        self,
        token_id: str,
        price: float,
        size: float,
        side: OrderSide,
        order_type: str,
        exchange_address: str,
        fee_rate_bps: int = 300,
    ) -> Dict[str, Any]:
        """Build and sign an order using EIP-712."""
        # Generate salt using SDK pattern (timestamp-based, fits in JS safe integer range)
        timestamp_ms = int(time.time() * 1000)
        nano_offset = int((time.perf_counter() * 1_000_000) % 1_000_000)
        one_day_ms = 1000 * 60 * 60 * 24
        salt = timestamp_ms * 1000 + nano_offset + one_day_ms

        # Calculate amounts using SDK algorithm
        # size is in USDC, scale everything to 6 decimals
        shares_scale = 1_000_000
        collateral_scale = 1_000_000
        price_scale = 1_000_000
        price_tick = 0.001

        # Scale inputs
        shares = int(size * shares_scale)
        price_int = int(price * price_scale)
        tick_int = int(price_tick * price_scale)

        # Align shares to tick
        shares_step = price_scale // tick_int
        if shares % shares_step != 0:
            shares = (shares // shares_step) * shares_step

        # Calculate collateral
        numerator = shares * price_int * collateral_scale
        denominator = shares_scale * price_scale

        # side: 0 = BUY, 1 = SELL
        side_int = 0 if side == OrderSide.BUY else 1

        if side == OrderSide.BUY:
            # BUY: Round UP
            collateral = (numerator + denominator - 1) // denominator
            maker_amount = collateral
            taker_amount = shares
        else:
            # SELL: Round DOWN
            collateral = numerator // denominator
            maker_amount = shares
            taker_amount = collateral

        # Build order for signing (all numeric types for EIP-712)
        order_for_signing = {
            "salt": salt,
            "maker": self._address,
            "signer": self._address,
            "taker": "0x0000000000000000000000000000000000000000",
            "tokenId": int(token_id),  # int for signing
            "makerAmount": maker_amount,
            "takerAmount": taker_amount,
            "expiration": 0,  # int for signing
            "nonce": 0,
            "feeRateBps": fee_rate_bps,
            "side": side_int,
            "signatureType": 0,  # EOA
        }

        # Sign with EIP-712
        signature = self._sign_order_eip712(order_for_signing, exchange_address)

        # Build API payload based on API validation requirements
        order = {
            "salt": salt,  # number
            "maker": self._address,
            "signer": self._address,
            "taker": "0x0000000000000000000000000000000000000000",
            "tokenId": token_id,  # string
            "makerAmount": maker_amount,  # number
            "takerAmount": taker_amount,  # number
            "expiration": "0",  # string
            "nonce": 0,  # number
            "feeRateBps": fee_rate_bps,  # number
            "side": side_int,  # number
            "signatureType": 0,  # number
            "signature": signature,
        }

        # Add price for GTC orders
        if order_type == "GTC":
            order["price"] = round(price, 3)

        return order

    def _sign_order_eip712(self, order: Dict[str, Any], exchange_address: str) -> str:
        """Sign order using EIP-712 typed data."""
        domain = {
            "name": "Limitless CTF Exchange",
            "version": "1",
            "chainId": self.chain_id,
            "verifyingContract": exchange_address,
        }

        types = {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "Order": [
                {"name": "salt", "type": "uint256"},
                {"name": "maker", "type": "address"},
                {"name": "signer", "type": "address"},
                {"name": "taker", "type": "address"},
                {"name": "tokenId", "type": "uint256"},
                {"name": "makerAmount", "type": "uint256"},
                {"name": "takerAmount", "type": "uint256"},
                {"name": "expiration", "type": "uint256"},
                {"name": "nonce", "type": "uint256"},
                {"name": "feeRateBps", "type": "uint256"},
                {"name": "side", "type": "uint8"},
                {"name": "signatureType", "type": "uint8"},
            ],
        }

        # Order is already in correct numeric format for EIP-712 signing
        message = {
            "salt": order["salt"],
            "maker": order["maker"],
            "signer": order["signer"],
            "taker": order["taker"],
            "tokenId": order["tokenId"],
            "makerAmount": order["makerAmount"],
            "takerAmount": order["takerAmount"],
            "expiration": order["expiration"],
            "nonce": order["nonce"],
            "feeRateBps": order["feeRateBps"],
            "side": order["side"],
            "signatureType": order["signatureType"],
        }

        typed_data = {
            "types": types,
            "primaryType": "Order",
            "domain": domain,
            "message": message,
        }

        encoded = encode_typed_data(full_message=typed_data)
        signed = self._account.sign_message(encoded)

        signature = signed.signature.hex()
        if not signature.startswith("0x"):
            signature = "0x" + signature

        return signature

    def cancel_order(self, order_id: str, market_id: Optional[str] = None) -> Order:
        """
        Cancel an existing order.

        Args:
            order_id: Order ID to cancel
            market_id: Market slug (optional)

        Returns:
            Updated Order object
        """
        self._ensure_authenticated()

        try:
            self._request("DELETE", f"/orders/{order_id}", require_auth=True)

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

    def cancel_all_orders(
        self, market_id: Optional[str] = None, side: Optional[OrderSide] = None
    ) -> Dict[str, Any]:
        """
        Cancel all open orders for a market.

        Args:
            market_id: Market slug (required)
            side: Optional side filter

        Returns:
            Cancellation result summary
        """
        self._ensure_authenticated()

        if not market_id:
            raise InvalidOrder("market_id required for cancel_all_orders")

        try:
            result = self._request("DELETE", f"/orders/all/{market_id}", require_auth=True)
            return result

        except Exception as e:
            raise ExchangeError(f"Failed to cancel all orders: {e}")

    def fetch_order(self, order_id: str, market_id: Optional[str] = None) -> Order:
        """
        Fetch order details by ID.

        Args:
            order_id: Order ID
            market_id: Market slug (optional)

        Returns:
            Order object
        """
        self._ensure_authenticated()

        try:
            data = self._request("GET", f"/orders/{order_id}", require_auth=True)
            return self._parse_order(data)
        except Exception as e:
            raise ExchangeError(f"Failed to fetch order {order_id}: {e}")

    def fetch_open_orders(
        self, market_id: Optional[str] = None, params: Optional[Dict[str, Any]] = None
    ) -> List[Order]:
        """
        Fetch all open orders.

        Args:
            market_id: Optional market filter (slug)
            params: Additional parameters

        Returns:
            List of Order objects
        """
        self._ensure_authenticated()

        query_params = params or {}
        if market_id:
            endpoint = f"/markets/{market_id}/user-orders"
            query_params["statuses"] = "LIVE"
        else:
            endpoint = "/orders"
            query_params["statuses"] = "LIVE"

        # Build token_id -> outcome mapping if market_id provided
        token_to_outcome: Dict[str, str] = {}
        if market_id:
            try:
                market = self.fetch_market(market_id)
                tokens = market.metadata.get("tokens", {})
                # tokens is {"Yes": "token_id_1", "No": "token_id_2"}
                # We need reverse mapping: {"token_id_1": "Yes", "token_id_2": "No"}
                for outcome, token_id in tokens.items():
                    if token_id:
                        token_to_outcome[str(token_id)] = outcome
            except Exception:
                pass

        try:
            response = self._request("GET", endpoint, params=query_params, require_auth=True)

            # Response can be list directly or {"data": [...]}
            if isinstance(response, list):
                orders_data = response
            else:
                orders_data = response.get("data", [])

            return [self._parse_order(o, token_to_outcome) for o in orders_data]

        except Exception as e:
            if self.verbose:
                print(f"Failed to fetch open orders: {e}")
            return []

    def _parse_order(
        self, data: Dict[str, Any], token_to_outcome: Optional[Dict[str, str]] = None
    ) -> Order:
        """Parse order data from API response."""
        order_id = str(data.get("id", data.get("orderId", "")))
        market_id = data.get("marketSlug", data.get("market_id", ""))

        # Parse side - API returns 0 for BUY, 1 for SELL (or string "buy"/"sell")
        side_raw = data.get("side", "buy")
        if isinstance(side_raw, int):
            side = OrderSide.BUY if side_raw == 0 else OrderSide.SELL
        else:
            side = OrderSide.BUY if str(side_raw).lower() == "buy" else OrderSide.SELL

        # Parse status
        status = self._parse_order_status(data.get("status", "open"))

        # Parse amounts
        price = float(data.get("price", 0) or 0)

        # Determine size from API response
        # Note: makerAmount/takerAmount are scaled (1e6) and differ by side:
        #   BUY: makerAmount = collateral (price * shares), takerAmount = shares
        #   SELL: makerAmount = shares, takerAmount = collateral
        size_raw = data.get("size", 0) or data.get("amount", 0)
        if size_raw:
            size = float(size_raw)
        else:
            maker_amount = float(data.get("makerAmount", 0) or 0)
            taker_amount = float(data.get("takerAmount", 0) or 0)

            if maker_amount or taker_amount:
                # Use takerAmount for BUY (shares), makerAmount for SELL (shares)
                if side == OrderSide.BUY:
                    size = taker_amount / 1_000_000 if taker_amount else 0
                else:
                    size = maker_amount / 1_000_000 if maker_amount else 0
            else:
                size = 0

        filled = float(data.get("filled", 0) or data.get("matchedAmount", 0) or 0)

        created_at = self._parse_datetime(data.get("createdAt"))
        updated_at = self._parse_datetime(data.get("updatedAt"))

        if not created_at:
            created_at = datetime.now(timezone.utc)
        if not updated_at:
            updated_at = created_at

        # Determine outcome: try direct field first, then map from token/tokenId
        outcome = data.get("outcome", "")
        if not outcome and token_to_outcome:
            # API may return "token" or "tokenId"
            token_id = str(data.get("token", "") or data.get("tokenId", ""))
            outcome = token_to_outcome.get(token_id, "")

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

    def _parse_order_status(self, status: Any) -> OrderStatus:
        """Convert string status to OrderStatus enum."""
        if status is None:
            return OrderStatus.OPEN

        status_str = str(status).lower()
        status_map = {
            "pending": OrderStatus.PENDING,
            "open": OrderStatus.OPEN,
            "live": OrderStatus.OPEN,
            "active": OrderStatus.OPEN,
            "filled": OrderStatus.FILLED,
            "matched": OrderStatus.FILLED,
            "partially_filled": OrderStatus.PARTIALLY_FILLED,
            "partial": OrderStatus.PARTIALLY_FILLED,
            "cancelled": OrderStatus.CANCELLED,
            "canceled": OrderStatus.CANCELLED,
            "rejected": OrderStatus.REJECTED,
        }
        return status_map.get(status_str, OrderStatus.OPEN)

    def fetch_positions(
        self, market_id: Optional[str] = None, params: Optional[Dict[str, Any]] = None
    ) -> List[Position]:
        """
        Fetch current positions.

        Args:
            market_id: Optional market filter
            params: Additional parameters

        Returns:
            List of Position objects
        """
        self._ensure_authenticated()

        try:
            response = self._request("GET", "/portfolio/positions", require_auth=True)

            positions = []
            clob_positions = response.get("clob", [])

            for pos_data in clob_positions:
                parsed_positions = self._parse_portfolio_position(pos_data)

                for position in parsed_positions:
                    # Filter by market if specified
                    if market_id and position.market_id != market_id:
                        continue

                    positions.append(position)

            return positions

        except Exception as e:
            if self.verbose:
                print(f"Failed to fetch positions: {e}")
            return []

    def fetch_positions_for_market(self, market: Market) -> List[Position]:
        """
        Fetch positions for a specific market object.

        Args:
            market: Market object

        Returns:
            List of Position objects
        """
        return self.fetch_positions(market_id=market.id)

    def _parse_portfolio_position(self, data: Dict[str, Any]) -> List[Position]:
        """
        Parse position data from portfolio API response.

        The portfolio API returns positions per market with nested structure:
        {
            'market': {'slug': '...', ...},
            'tokensBalance': {'yes': '12345', 'no': '67890'},
            'positions': {'yes': {...}, 'no': {...}},
            'latestTrade': {'latestYesPrice': 0.65, 'latestNoPrice': 0.35, ...}
        }
        """
        positions = []

        market_data = data.get("market", {})
        market_id = market_data.get("slug", "")

        tokens_balance = data.get("tokensBalance", {})
        position_details = data.get("positions", {})
        latest_trade = data.get("latestTrade", {})

        # Parse Yes position
        yes_balance = float(tokens_balance.get("yes", 0) or 0)
        if yes_balance > 0:
            yes_details = position_details.get("yes", {})
            fill_price = float(yes_details.get("fillPrice", 0) or 0)
            # fillPrice is in scaled format (e.g., 650000 = 0.65)
            avg_price = fill_price / 1_000_000 if fill_price > 1 else fill_price
            current_price = float(latest_trade.get("latestYesPrice", 0) or 0)

            # Convert balance from scaled format (6 decimals)
            size = yes_balance / 1_000_000

            positions.append(
                Position(
                    market_id=market_id,
                    outcome="Yes",
                    size=size,
                    average_price=avg_price,
                    current_price=current_price,
                )
            )

        # Parse No position
        no_balance = float(tokens_balance.get("no", 0) or 0)
        if no_balance > 0:
            no_details = position_details.get("no", {})
            fill_price = float(no_details.get("fillPrice", 0) or 0)
            # fillPrice is in scaled format (e.g., 350000 = 0.35)
            avg_price = fill_price / 1_000_000 if fill_price > 1 else fill_price
            current_price = float(latest_trade.get("latestNoPrice", 0) or 0)

            # Convert balance from scaled format (6 decimals)
            size = no_balance / 1_000_000

            positions.append(
                Position(
                    market_id=market_id,
                    outcome="No",
                    size=size,
                    average_price=avg_price,
                    current_price=current_price,
                )
            )

        return positions

    def _parse_position(self, data: Dict[str, Any]) -> Position:
        """Parse position data from API response (legacy format)."""
        # Handle nested market data
        market_data = data.get("market", {})
        market_id = market_data.get("slug", data.get("marketSlug", data.get("market_id", "")))

        outcome = data.get("outcome", data.get("tokenName", ""))
        size = float(data.get("size", data.get("balance", 0)) or 0)
        average_price = float(
            data.get("avgEntryPrice", data.get("averagePrice", data.get("avg_price", 0))) or 0
        )
        current_price = float(data.get("currentPrice", data.get("price", 0)) or 0)

        return Position(
            market_id=market_id,
            outcome=outcome,
            size=size,
            average_price=average_price,
            current_price=current_price,
        )

    def fetch_balance(self) -> Dict[str, float]:
        """
        Fetch account balance from on-chain USDC contract.

        Returns:
            Dictionary with balance info (e.g., {'USDC': 1000.0})
        """
        self._ensure_authenticated()

        # USDC contract on Base
        usdc_address = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
        base_rpc = "https://mainnet.base.org"

        try:
            # ERC20 balanceOf call
            # balanceOf(address) selector = 0x70a08231
            data = f"0x70a08231000000000000000000000000{self._address[2:].lower()}"

            payload = {
                "jsonrpc": "2.0",
                "method": "eth_call",
                "params": [{"to": usdc_address, "data": data}, "latest"],
                "id": 1,
            }

            response = requests.post(base_rpc, json=payload, timeout=10)
            result = response.json().get("result", "0x0")

            # Convert from hex to int, then to USDC (6 decimals)
            balance_wei = int(result, 16)
            usdc_balance = balance_wei / (10**6)

            return {"USDC": usdc_balance}

        except Exception as e:
            # Fallback: try API
            try:
                response = self._request(
                    "GET",
                    "/portfolio/trading/allowance",
                    params={"type": "clob"},
                    require_auth=True,
                )
                usdc_balance = float(response.get("balance", response.get("allowance", 0)) or 0)
                return {"USDC": usdc_balance}
            except Exception:
                pass
            raise ExchangeError(f"Failed to fetch balance: {e}")

    def calculate_nav(self, market: Market) -> NAV:
        """
        Calculate Net Asset Value for a specific market.

        Args:
            market: Market object

        Returns:
            NAV object
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

    def _parse_datetime(self, timestamp: Optional[Any]) -> Optional[datetime]:
        """Parse datetime from various formats."""
        if not timestamp:
            return None

        if isinstance(timestamp, datetime):
            return timestamp

        try:
            if isinstance(timestamp, (int, float)):
                # Unix timestamp
                return datetime.fromtimestamp(timestamp, tz=timezone.utc)
            # ISO format string
            ts_str = str(timestamp).replace("Z", "+00:00")
            return datetime.fromisoformat(ts_str)
        except (ValueError, TypeError):
            return None

    # Search and exploration methods

    def search_markets(
        self,
        *,
        limit: int = 200,
        page: int = 1,
        category_id: Optional[str] = None,
        sort_by: Optional[str] = None,
        # Client-side filters
        query: Optional[str] = None,
        keywords: Optional[Sequence[str]] = None,
        binary: Optional[bool] = None,
        min_liquidity: float = 0.0,
        predicate: Optional[Callable[[Market], bool]] = None,
    ) -> List[Market]:
        """
        Search markets with various filters.

        Args:
            limit: Maximum markets to return
            page: Page number
            category_id: Filter by category
            sort_by: Sort field
            query: Text search query
            keywords: Required keywords
            binary: If True, only binary markets
            min_liquidity: Minimum liquidity
            predicate: Custom filter function

        Returns:
            List of matching Market objects
        """
        if limit <= 0:
            return []

        def _lower_list(values: Optional[Sequence[str]]) -> List[str]:
            return [v.lower() for v in values] if values else []

        query_lower = query.lower() if query else None
        keyword_lowers = _lower_list(keywords)

        # Fetch markets
        params = {"page": page, "limit": min(limit, 50)}
        if category_id:
            params["categoryId"] = category_id
        if sort_by:
            params["sortBy"] = sort_by

        all_markets = self.fetch_markets(params)

        # Client-side filtering
        filtered: List[Market] = []

        for m in all_markets:
            if binary is not None and m.is_binary != binary:
                continue
            if m.liquidity < min_liquidity:
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
    def _build_search_text(market: Market) -> str:
        """Build searchable text from market."""
        meta = market.metadata
        fields = [
            market.question or "",
            meta.get("description", ""),
            meta.get("slug", ""),
            meta.get("category", ""),
        ]
        return " ".join(str(f) for f in fields).lower()

    # Price history

    def fetch_price_history(
        self,
        market: Market | str,
        *,
        outcome: int | str | None = None,
        interval: Literal["1m", "1h", "1d", "1w"] = "1h",
        start_from: Optional[int] = None,
        end_to: Optional[int] = None,
        as_dataframe: bool = False,
    ) -> List[PricePoint] | Any:
        """
        Get price history for a market.

        Args:
            market: Market object or slug
            outcome: Outcome index or name (default: first outcome)
            interval: Time interval
            start_from: Start timestamp (optional)
            end_to: End timestamp (optional)
            as_dataframe: Return as pandas DataFrame

        Returns:
            List of PricePoint objects or DataFrame
        """
        if interval not in self.SUPPORTED_INTERVALS:
            raise ValueError(
                f"Unsupported interval '{interval}'. Pick from {self.SUPPORTED_INTERVALS}."
            )

        market_obj = self._ensure_market(market)

        params = {"interval": interval}
        if start_from:
            params["from"] = start_from
        if end_to:
            params["to"] = end_to

        @self._retry_on_failure
        def _fetch() -> List[Dict[str, Any]]:
            response = self._request(
                "GET", f"/markets/{market_obj.id}/historical-price", params=params
            )
            return response.get("data", response if isinstance(response, list) else [])

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
    def _parse_history(history: Iterable[Dict[str, Any]]) -> List[PricePoint]:
        """Parse price history data."""
        parsed: List[PricePoint] = []
        for row in history:
            t = row.get("timestamp") or row.get("t") or row.get("time")
            p = row.get("price") or row.get("p")

            if t is None or p is None:
                continue

            try:
                if isinstance(t, (int, float)):
                    ts = datetime.fromtimestamp(int(t), tz=timezone.utc)
                else:
                    ts = datetime.fromisoformat(str(t).replace("Z", "+00:00"))

                parsed.append(PricePoint(timestamp=ts, price=float(p), raw=row))
            except (ValueError, TypeError):
                continue

        return sorted(parsed, key=lambda item: item.timestamp)

    def _ensure_market(self, market: Market | str) -> Market:
        """Ensure we have a Market object."""
        if isinstance(market, Market):
            return market
        fetched = self.fetch_market(market)
        if not fetched:
            raise MarketNotFound(f"Market {market} not found")
        return fetched

    @staticmethod
    def _extract_token_ids(market: Market) -> List[str]:
        """Extract token IDs from market metadata."""
        raw_ids = market.metadata.get("clobTokenIds", []) or market.metadata.get("token_ids", [])
        if isinstance(raw_ids, str):
            try:
                raw_ids = json.loads(raw_ids)
            except json.JSONDecodeError:
                raw_ids = [raw_ids]
        return [str(token_id) for token_id in raw_ids if token_id]

    def _lookup_token_id(self, market: Market, outcome: int | str | None) -> str:
        """Look up token ID for a specific outcome."""
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

    # Feed events

    def fetch_feed_events(
        self, market_slug: str, page: int = 1, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Fetch feed events for a market.

        Args:
            market_slug: Market slug
            page: Page number
            limit: Items per page

        Returns:
            List of feed event dictionaries
        """
        try:
            response = self._request(
                "GET",
                f"/markets/{market_slug}/get-feed-events",
                params={"page": page, "limit": limit},
            )
            return response.get("data", response if isinstance(response, list) else [])
        except Exception as e:
            if self.verbose:
                print(f"Failed to fetch feed events: {e}")
            return []

    def fetch_market_events(
        self, market_slug: str, page: int = 1, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Fetch recent market events (trades, orders, liquidity changes).

        Args:
            market_slug: Market slug
            page: Page number
            limit: Items per page

        Returns:
            List of event dictionaries
        """
        try:
            response = self._request(
                "GET",
                f"/markets/{market_slug}/events",
                params={"page": page, "limit": limit},
            )
            return response.get("data", response if isinstance(response, list) else [])
        except Exception as e:
            if self.verbose:
                print(f"Failed to fetch market events: {e}")
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
                "fetch_markets_by_slug": True,
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
                "fetch_feed_events": True,
                "fetch_market_events": True,
                "get_websocket": True,
                "get_user_websocket": True,
            },
        }

    def get_websocket(self) -> LimitlessWebSocket:
        """
        Get WebSocket instance for real-time market data.

        Returns:
            LimitlessWebSocket instance for price/orderbook updates

        Example:
            ws = exchange.get_websocket()
            ws.on_orderbook(lambda update: print(update))
            ws.subscribe_market("btc-above-100k")
            ws.start()
        """
        if self._ws is None:
            self._ws = LimitlessWebSocket(config={"verbose": self.verbose})
        return self._ws

    def get_user_websocket(self) -> LimitlessUserWebSocket:
        """
        Get authenticated WebSocket for user-specific updates.

        Requires authentication (private_key in config).

        Returns:
            LimitlessUserWebSocket instance for position updates

        Example:
            user_ws = exchange.get_user_websocket()
            user_ws.on_position(lambda pos: print(f"Position: {pos}"))
            user_ws.start()
        """
        if not self._authenticated:
            raise AuthenticationError(
                "Not authenticated. Provide private_key in config for user WebSocket."
            )

        if self._user_ws is None:
            # Get session cookie from current session
            session_cookie = None
            for cookie in self._session.cookies:
                if cookie.name == "limitless_session":
                    session_cookie = cookie.value
                    break

            if not session_cookie:
                raise AuthenticationError(
                    "Session cookie not available. Re-authenticate to get session."
                )

            self._user_ws = LimitlessUserWebSocket(
                session_cookie=session_cookie,
                config={"verbose": self.verbose},
            )
        return self._user_ws
