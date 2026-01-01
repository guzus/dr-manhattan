"""
Predict.fun Exchange implementation for dr-manhattan.

Predict.fun is a prediction market on BNB Chain with CLOB-style orderbook.
Uses REST API for communication and EIP-712 for order signing.

API Documentation: https://dev.predict.fun/
"""

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
from eth_account import Account
from eth_account.messages import encode_defunct, encode_typed_data

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
from ..models.position import Position

__all__ = ["PredictFun"]


class PredictFun(Exchange):
    """
    Predict.fun exchange implementation for BNB Chain prediction markets.

    Supports both public API (market data) and authenticated operations (trading).
    Uses EIP-712 message signing for authentication.

    API Base: https://api.predict.fun/v1
    Testnet: https://api-testnet.predict.fun/v1
    """

    BASE_URL = "https://api.predict.fun"
    TESTNET_URL = "https://api-testnet.predict.fun"
    CHAIN_ID = 56  # BNB Mainnet
    TESTNET_CHAIN_ID = 97  # BNB Testnet

    # Yield-bearing CTFExchange contract addresses (default for most markets)
    YIELD_BEARING_CTF_EXCHANGE_MAINNET = "0x6bEb5a40C032AFc305961162d8204CDA16DECFa5"
    YIELD_BEARING_CTF_EXCHANGE_TESTNET = "0x8a6B4Fa700A1e310b106E7a48bAFa29111f66e89"
    YIELD_BEARING_NEG_RISK_CTF_EXCHANGE_MAINNET = "0x8A289d458f5a134bA40015085A8F50Ffb681B41d"
    YIELD_BEARING_NEG_RISK_CTF_EXCHANGE_TESTNET = "0x95D5113bc50eD201e319101bbca3e0E250662fCC"

    # Non-yield-bearing CTFExchange contract addresses
    CTF_EXCHANGE_MAINNET = "0x8BC070BEdAB741406F4B1Eb65A72bee27894B689"
    CTF_EXCHANGE_TESTNET = "0x2A6413639BD3d73a20ed8C95F634Ce198ABbd2d7"
    NEG_RISK_CTF_EXCHANGE_MAINNET = "0x365fb81bd4A24D6303cd2F19c349dE6894D8d58A"
    NEG_RISK_CTF_EXCHANGE_TESTNET = "0xd690b2bd441bE36431F6F6639D7Ad351e7B29680"

    # EIP-712 domain name (must match official SDK)
    PROTOCOL_NAME = "predict.fun CTF Exchange"
    PROTOCOL_VERSION = "1"

    @property
    def id(self) -> str:
        return "predictfun"

    @property
    def name(self) -> str:
        return "Predict.fun"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize Predict.fun exchange.

        Args:
            config: Configuration dictionary with:
                - api_key: API key for authenticated requests (required)
                - private_key: Private key for signing orders (required for trading)
                - testnet: Use testnet API (default: False)
                - timeout: Request timeout in seconds (default: 30)
        """
        super().__init__(config)

        self.api_key = self.config.get("api_key", "")
        self.private_key = self.config.get("private_key", "")
        self.testnet = self.config.get("testnet", False)

        # Set URLs and chain ID based on testnet flag
        if self.testnet:
            self.host = self.config.get("host", self.TESTNET_URL)
            self.chain_id = self.TESTNET_CHAIN_ID
            # Yield-bearing exchanges (used for most markets)
            self.yield_bearing_ctf_exchange = self.YIELD_BEARING_CTF_EXCHANGE_TESTNET
            self.yield_bearing_neg_risk_ctf_exchange = (
                self.YIELD_BEARING_NEG_RISK_CTF_EXCHANGE_TESTNET
            )
            # Non-yield-bearing exchanges
            self.ctf_exchange = self.CTF_EXCHANGE_TESTNET
            self.neg_risk_ctf_exchange = self.NEG_RISK_CTF_EXCHANGE_TESTNET
        else:
            self.host = self.config.get("host", self.BASE_URL)
            self.chain_id = self.CHAIN_ID
            # Yield-bearing exchanges (used for most markets)
            self.yield_bearing_ctf_exchange = self.YIELD_BEARING_CTF_EXCHANGE_MAINNET
            self.yield_bearing_neg_risk_ctf_exchange = (
                self.YIELD_BEARING_NEG_RISK_CTF_EXCHANGE_MAINNET
            )
            # Non-yield-bearing exchanges
            self.ctf_exchange = self.CTF_EXCHANGE_MAINNET
            self.neg_risk_ctf_exchange = self.NEG_RISK_CTF_EXCHANGE_MAINNET

        self._session = requests.Session()
        self._account = None
        self._address = None
        self._jwt_token = None
        self._authenticated = False

        # Initialize account if private key provided
        if self.private_key:
            self._initialize_account()

    def _initialize_account(self):
        """Initialize account from private key."""
        try:
            self._account = Account.from_key(self.private_key)
            self._address = self._account.address
        except Exception as e:
            raise AuthenticationError(f"Failed to initialize account: {e}")

    def _get_headers(self, require_auth: bool = False) -> Dict[str, str]:
        """Get headers for API requests."""
        headers = {
            "Content-Type": "application/json",
        }

        if self.api_key:
            headers["x-api-key"] = self.api_key

        if require_auth and self._jwt_token:
            headers["Authorization"] = f"Bearer {self._jwt_token}"

        return headers

    def _ensure_authenticated(self):
        """Ensure user is authenticated for operations requiring auth."""
        if not self._jwt_token:
            if not self.api_key or not self.private_key:
                raise AuthenticationError(
                    "API key and private key required for authenticated operations."
                )
            self._authenticate()

    def _authenticate(self):
        """Authenticate with Predict.fun using EIP-191 signing."""
        if not self.api_key:
            raise AuthenticationError("API key required for authentication.")
        if not self._account:
            raise AuthenticationError("Private key required for authentication.")

        try:
            # Get signing message
            response = self._session.get(
                f"{self.host}/v1/auth/message",
                headers={"x-api-key": self.api_key},
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            message = data.get("data", {}).get("message", "")

            if not message:
                raise AuthenticationError("Failed to get signing message")

            # Sign the message using EIP-191 personal sign
            signable_message = encode_defunct(text=message)
            signed = self._account.sign_message(signable_message)
            signature = signed.signature.hex()
            if not signature.startswith("0x"):
                signature = f"0x{signature}"

            # Get JWT token
            jwt_response = self._session.post(
                f"{self.host}/v1/auth",
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": self.api_key,
                },
                json={
                    "signer": self._address,
                    "message": message,
                    "signature": signature,
                },
                timeout=self.timeout,
            )
            jwt_response.raise_for_status()
            jwt_data = jwt_response.json()

            self._jwt_token = jwt_data.get("data", {}).get("token")
            if not self._jwt_token:
                raise AuthenticationError("Failed to get JWT token")

            self._authenticated = True

            if self.verbose:
                print(f"Authenticated as {self._address}")

        except requests.RequestException as e:
            raise AuthenticationError(f"Authentication failed: {e}")

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        require_auth: bool = False,
    ) -> Any:
        """Make HTTP request to Predict.fun API with retry logic."""
        if require_auth:
            self._ensure_authenticated()

        @self._retry_on_failure
        def _make_request():
            url = f"{self.host}{endpoint}"
            headers = self._get_headers(require_auth)

            try:
                response = self._session.request(
                    method, url, params=params, json=data, headers=headers, timeout=self.timeout
                )

                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 1))
                    raise RateLimitError(f"Rate limited. Retry after {retry_after}s")

                if response.status_code == 401:
                    # Try to re-authenticate
                    if self.api_key and self._account:
                        self._jwt_token = None
                        self._authenticate()
                        headers = self._get_headers(require_auth)
                        response = self._session.request(
                            method,
                            url,
                            params=params,
                            json=data,
                            headers=headers,
                            timeout=self.timeout,
                        )

                response.raise_for_status()
                return response.json()

            except requests.Timeout as e:
                raise NetworkError(f"Request timeout: {e}")
            except requests.ConnectionError as e:
                raise NetworkError(f"Connection error: {e}")
            except requests.HTTPError as e:
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
        Fetch all active markets from Predict.fun.

        Args:
            params: Optional parameters:
                - first: Number of markets to fetch
                - after: Cursor for pagination

        Returns:
            List of Market objects
        """

        @self._retry_on_failure
        def _fetch():
            query_params = params or {}

            response = self._request("GET", "/v1/markets", params=query_params)

            markets_data = response.get("data", [])
            markets = [self._parse_market(m) for m in markets_data]

            return markets

        return _fetch()

    def fetch_market(self, market_id: str) -> Market:
        """
        Fetch a specific market by ID.

        Args:
            market_id: Market ID (numeric string)

        Returns:
            Market object
        """

        @self._retry_on_failure
        def _fetch():
            try:
                data = self._request("GET", f"/v1/markets/{market_id}")
                market_data = data.get("data", data)
                return self._parse_market(market_data)
            except ExchangeError:
                raise MarketNotFound(f"Market {market_id} not found")

        return _fetch()

    def _parse_market(self, data: Dict[str, Any]) -> Market:
        """Parse market data from Predict.fun API response."""
        market_id = str(data.get("id", ""))
        title = data.get("title", "")
        question = data.get("question", title)
        description = data.get("description", "")

        # Extract outcomes
        outcomes_data = data.get("outcomes", [])
        outcomes = [o.get("name", "") for o in outcomes_data]
        if not outcomes:
            outcomes = ["Yes", "No"]  # Default for binary markets

        # Extract token IDs from outcomes (onChainId)
        token_ids = [str(o.get("onChainId", "")) for o in outcomes_data if o.get("onChainId")]

        # Status mapping
        status = data.get("status", "")
        is_closed = status in ("RESOLVED", "PAUSED")

        # Parse decimal precision for tick size
        decimal_precision = data.get("decimalPrecision", 2)
        tick_size = 10 ** (-decimal_precision)  # 2 -> 0.01, 3 -> 0.001

        # Build metadata
        metadata = {
            **data,
            "clobTokenIds": token_ids,
            "token_ids": token_ids,
            "isNegRisk": data.get("isNegRisk", False),
            "isYieldBearing": data.get("isYieldBearing", False),
            "conditionId": data.get("conditionId", ""),
            "feeRateBps": data.get("feeRateBps", 0),
            "categorySlug": data.get("categorySlug", ""),
            "closed": is_closed,
            "minimum_tick_size": tick_size,
        }

        return Market(
            id=market_id,
            question=question,
            outcomes=outcomes,
            close_time=None,  # Predict.fun doesn't expose close time in basic API
            volume=0,  # Need to call statistics endpoint for volume
            liquidity=0,
            prices={},  # Need to call last sale or orderbook for prices
            metadata=metadata,
            tick_size=tick_size,
            description=description,
        )

    def get_orderbook(self, market_id: str) -> Dict[str, Any]:
        """
        Fetch orderbook for a specific market.

        Note: Orderbook stores prices based on the Yes outcome.
        For No outcome, use: No price = 1 - Yes price

        Args:
            market_id: Market ID

        Returns:
            Dictionary with 'bids' and 'asks' arrays
        """
        try:
            response = self._request("GET", f"/v1/markets/{market_id}/orderbook")
            data = response.get("data", {})

            # API returns asks/bids as [[price, size], [price, size], ...]
            raw_bids = data.get("bids", [])
            raw_asks = data.get("asks", [])

            bids = []
            asks = []

            for entry in raw_bids:
                if len(entry) >= 2:
                    bids.append({"price": str(entry[0]), "size": str(entry[1])})

            for entry in raw_asks:
                if len(entry) >= 2:
                    asks.append({"price": str(entry[0]), "size": str(entry[1])})

            # Sort: bids descending, asks ascending
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
            market_id: Market ID

        Returns:
            List of token IDs (onChainId for each outcome)
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
    ) -> Order:
        """
        Create a new order on Predict.fun.

        Args:
            market_id: Market ID
            outcome: Outcome name (e.g., "Yes" or "No")
            side: OrderSide.BUY or OrderSide.SELL
            price: Price per share (0-1)
            size: Size in collateral units
            params: Additional parameters:
                - token_id: Token ID (optional if outcome provided)
                - strategy: "LIMIT" or "MARKET" (default: "LIMIT")
                - expiration: Order expiration timestamp (optional)

        Returns:
            Order object
        """
        self._ensure_authenticated()

        extra_params = params or {}
        token_id = extra_params.get("token_id")
        strategy = extra_params.get("strategy", "LIMIT").upper()

        # Get market data
        market = self.fetch_market(market_id)

        if not token_id:
            # Map outcome to token_id
            outcomes = market.metadata.get("outcomes", [])
            token_ids = market.metadata.get("clobTokenIds", [])

            try:
                outcome_names = [o.get("name", "") if isinstance(o, dict) else o for o in outcomes]
                outcome_index = outcome_names.index(outcome)
                if outcome_index < len(token_ids):
                    token_id = token_ids[outcome_index]
            except (ValueError, IndexError):
                pass

            if not token_id:
                raise InvalidOrder(f"Could not find token_id for outcome '{outcome}'")

        if price < 0 or price > 1:
            raise InvalidOrder(f"Price must be between 0 and 1 (inclusive), got: {price}")

        # Get fee rate from market
        fee_rate_bps = market.metadata.get("feeRateBps", 0)

        # Determine exchange address based on isYieldBearing and isNegRisk
        is_yield_bearing = market.metadata.get("isYieldBearing", True)
        is_neg_risk = market.metadata.get("isNegRisk", False)

        if is_yield_bearing:
            if is_neg_risk:
                exchange_address = self.yield_bearing_neg_risk_ctf_exchange
            else:
                exchange_address = self.yield_bearing_ctf_exchange
        else:
            if is_neg_risk:
                exchange_address = self.neg_risk_ctf_exchange
            else:
                exchange_address = self.ctf_exchange

        # Build and sign the order
        try:
            signed_order = self._build_signed_order(
                token_id=str(token_id),
                price=price,
                size=size,
                side=side,
                fee_rate_bps=fee_rate_bps,
                exchange_address=exchange_address,
                expiration=extra_params.get("expiration", 0),
            )

            # Build payload - price in wei (1e18)
            price_per_share_wei = int(price * 10**18)

            payload = {
                "data": {
                    "pricePerShare": str(price_per_share_wei),
                    "strategy": strategy,
                    "order": signed_order,
                }
            }

            result = self._request("POST", "/v1/orders", data=payload, require_auth=True)

            order_data = result.get("data", result)
            order_hash = order_data.get("orderHash", "")

            return Order(
                id=order_hash,
                market_id=market_id,
                outcome=outcome,
                side=side,
                price=price,
                size=size,
                filled=0,
                status=OrderStatus.OPEN,
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
        fee_rate_bps: int,
        exchange_address: str,
        expiration: int = 0,
    ) -> Dict[str, Any]:
        """Build and sign an order using EIP-712."""
        # Generate salt
        salt = int(time.time() * 1000000)

        # Calculate amounts (all in wei, 18 decimals for this exchange)
        # size is the number of shares, price is 0-1
        shares_wei = int(size * 10**18)
        price_wei = int(price * 10**18)

        # side: 0 = BUY, 1 = SELL
        side_int = 0 if side == OrderSide.BUY else 1

        if side == OrderSide.BUY:
            # BUY: maker provides collateral, receives shares
            # makerAmount = price * shares
            maker_amount = (shares_wei * price_wei) // (10**18)
            taker_amount = shares_wei
        else:
            # SELL: maker provides shares, receives collateral
            maker_amount = shares_wei
            taker_amount = (shares_wei * price_wei) // (10**18)

        # Build order for signing
        order = {
            "salt": str(salt),
            "maker": self._address,
            "signer": self._address,
            "taker": "0x0000000000000000000000000000000000000000",
            "tokenId": str(token_id),
            "makerAmount": str(maker_amount),
            "takerAmount": str(taker_amount),
            "expiration": str(expiration) if expiration else "0",
            "nonce": "0",
            "feeRateBps": str(fee_rate_bps),
            "side": side_int,
            "signatureType": 0,
        }

        # Sign with EIP-712
        signature = self._sign_order_eip712(order, exchange_address)
        order["signature"] = signature

        # Compute order hash (for reference)
        # Note: actual hash is computed server-side

        return order

    def _sign_order_eip712(self, order: Dict[str, Any], exchange_address: str) -> str:
        """Sign order using EIP-712 typed data."""
        domain = {
            "name": self.PROTOCOL_NAME,
            "version": self.PROTOCOL_VERSION,
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

        # Convert string values to int for signing
        message = {
            "salt": int(order["salt"]),
            "maker": order["maker"],
            "signer": order["signer"],
            "taker": order["taker"],
            "tokenId": int(order["tokenId"]),
            "makerAmount": int(order["makerAmount"]),
            "takerAmount": int(order["takerAmount"]),
            "expiration": int(order["expiration"]),
            "nonce": int(order["nonce"]),
            "feeRateBps": int(order["feeRateBps"]),
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
            order_id: Order hash
            market_id: Market ID (optional)

        Returns:
            Updated Order object
        """
        self._ensure_authenticated()

        try:
            # Predict.fun uses POST /v1/orders/cancel with order hashes
            payload = {"data": {"orderHashes": [order_id]}}
            self._request("POST", "/v1/orders/cancel", data=payload, require_auth=True)

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
        Fetch order details by hash.

        Args:
            order_id: Order hash
            market_id: Market ID (optional)

        Returns:
            Order object
        """
        self._ensure_authenticated()

        try:
            data = self._request("GET", f"/v1/orders/{order_id}", require_auth=True)
            order_data = data.get("data", data)
            return self._parse_order(order_data)
        except Exception as e:
            raise ExchangeError(f"Failed to fetch order {order_id}: {e}")

    def fetch_open_orders(
        self, market_id: Optional[str] = None, params: Optional[Dict[str, Any]] = None
    ) -> List[Order]:
        """
        Fetch all open orders.

        Args:
            market_id: Optional market filter
            params: Additional parameters

        Returns:
            List of Order objects
        """
        self._ensure_authenticated()

        query_params = params or {}
        query_params["status"] = "OPEN"

        try:
            response = self._request("GET", "/v1/orders", params=query_params, require_auth=True)
            orders_data = response.get("data", [])

            orders = [self._parse_order(o) for o in orders_data]

            # Filter by market_id if specified
            if market_id:
                orders = [o for o in orders if o.market_id == market_id]

            return orders

        except Exception as e:
            if self.verbose:
                print(f"Failed to fetch open orders: {e}")
            return []

    def _parse_order(self, data: Dict[str, Any]) -> Order:
        """Parse order data from API response."""
        order_data = data.get("order", data)
        order_id = data.get("id", order_data.get("hash", ""))
        market_id = str(data.get("marketId", ""))

        # Parse side
        side_raw = order_data.get("side", 0)
        side = OrderSide.BUY if side_raw == 0 else OrderSide.SELL

        # Parse status
        status_str = data.get("status", "OPEN")
        status = self._parse_order_status(status_str)

        # Parse amounts
        maker_amount = int(order_data.get("makerAmount", 0) or 0)
        taker_amount = int(order_data.get("takerAmount", 0) or 0)

        # Calculate price and size from amounts
        if side == OrderSide.BUY and taker_amount > 0:
            size = taker_amount / 10**18
            price = maker_amount / taker_amount if taker_amount else 0
        elif side == OrderSide.SELL and maker_amount > 0:
            size = maker_amount / 10**18
            price = taker_amount / maker_amount if maker_amount else 0
        else:
            size = 0
            price = 0

        # Parse filled amount
        amount_filled = int(data.get("amountFilled", 0) or 0)
        filled = amount_filled / 10**18 if amount_filled else 0

        return Order(
            id=str(order_id),
            market_id=market_id,
            outcome="",  # Not directly available in order response
            side=side,
            price=price,
            size=size,
            filled=filled,
            status=status,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

    def _parse_order_status(self, status: Any) -> OrderStatus:
        """Convert string status to OrderStatus enum."""
        if status is None:
            return OrderStatus.OPEN

        status_str = str(status).upper()
        status_map = {
            "OPEN": OrderStatus.OPEN,
            "FILLED": OrderStatus.FILLED,
            "EXPIRED": OrderStatus.CANCELLED,
            "CANCELLED": OrderStatus.CANCELLED,
            "INVALIDATED": OrderStatus.CANCELLED,
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

        query_params = params or {}

        try:
            response = self._request("GET", "/v1/positions", params=query_params, require_auth=True)
            positions_data = response.get("data", [])

            positions = []
            for pos_data in positions_data:
                parsed = self._parse_position(pos_data)
                if market_id and parsed.market_id != market_id:
                    continue
                positions.append(parsed)

            return positions

        except Exception as e:
            if self.verbose:
                print(f"Failed to fetch positions: {e}")
            return []

    def _parse_position(self, data: Dict[str, Any]) -> Position:
        """Parse position data from API response."""
        market_data = data.get("market", {})
        market_id = str(market_data.get("id", ""))

        # Position data includes outcome info
        outcome = data.get("outcome", {})
        outcome_name = outcome.get("name", "") if isinstance(outcome, dict) else str(outcome)

        # Parse size (balance)
        size_raw = data.get("size", data.get("balance", "0"))
        size = int(size_raw) / 10**18 if size_raw else 0

        # Parse average price
        avg_price_raw = data.get("avgPrice", data.get("averagePrice", "0"))
        avg_price = int(avg_price_raw) / 10**18 if avg_price_raw else 0

        return Position(
            market_id=market_id,
            outcome=outcome_name,
            size=size,
            average_price=avg_price,
            current_price=0,  # Would need to fetch from orderbook/last sale
        )

    def fetch_balance(self) -> Dict[str, float]:
        """
        Fetch account balance.

        Note: Predict.fun balance is managed through the Vault contract on-chain.
        This method returns the account info which may include balance data.

        Returns:
            Dictionary with balance info
        """
        self._ensure_authenticated()

        try:
            response = self._request("GET", "/v1/accounts/me", require_auth=True)
            account_data = response.get("data", {})

            # Balance info might be in account data
            balance = float(account_data.get("balance", 0) or 0)

            return {"USDT": balance}  # Predict.fun uses USDT on BNB Chain

        except Exception as e:
            if self.verbose:
                print(f"Failed to fetch balance: {e}")
            return {"USDT": 0}

    def describe(self) -> Dict[str, Any]:
        """Return exchange metadata and capabilities."""
        return {
            "id": self.id,
            "name": self.name,
            "chain_id": self.chain_id,
            "host": self.host,
            "testnet": self.testnet,
            "has": {
                "fetch_markets": True,
                "fetch_market": True,
                "create_order": True,
                "cancel_order": True,
                "fetch_order": True,
                "fetch_open_orders": True,
                "fetch_positions": True,
                "fetch_balance": True,
                "get_orderbook": True,
                "fetch_token_ids": True,
            },
        }
