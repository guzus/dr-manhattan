"""
Predict.fun Exchange implementation for dr-manhattan.

Predict.fun is a prediction market on BNB Chain with CLOB-style orderbook.
Uses REST API for communication and EIP-712 for order signing.

API Documentation: https://dev.predict.fun/
"""

import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
from eth_abi import encode as eth_abi_encode
from eth_account import Account
from eth_account.messages import _hash_eip191_message, encode_defunct, encode_typed_data
from web3 import Web3

from ..base.errors import (
    AuthenticationError,
    ExchangeError,
    InsufficientFunds,
    InvalidOrder,
    MarketNotFound,
    NetworkError,
    RateLimitError,
)
from ..base.exchange import Exchange
from ..models.market import Market
from ..models.order import Order, OrderSide, OrderStatus
from ..models.position import Position
from .predictfun_ws import PredictFunUserWebSocket, PredictFunWebSocket

__all__ = ["PredictFun"]

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

# Collateral token (USDT on BNB Chain)
USDT_ADDRESS_MAINNET = "0x55d398326f99059fF775485246999027B3197955"
USDT_ADDRESS_TESTNET = "0xB32171ecD878607FFc4F8FC0bCcE6852BB3149E0"  # Testnet USDT

# ECDSA Validator address (same for mainnet and testnet)
ECDSA_VALIDATOR_ADDRESS = "0x845ADb2C711129d4f3966735eD98a9F09fC4cE57"

# Kernel domain for smart wallet signing
KERNEL_DOMAIN_NAME = "Kernel"
KERNEL_DOMAIN_VERSION = "0.3.1"

# Order expiration timestamp for no-expiry orders (year 2100)
NO_EXPIRY_TIMESTAMP = 4102444800

# BNB Chain RPC endpoints
BNB_RPC_MAINNET = "https://bsc-dataseed.binance.org/"
BNB_RPC_TESTNET = "https://data-seed-prebsc-1-s1.binance.org:8545/"

# ERC-20 ABI for balanceOf, allowance, and approve
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_spender", "type": "address"},
        ],
        "name": "allowance",
        "outputs": [{"name": "remaining", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_spender", "type": "address"},
            {"name": "_value", "type": "uint256"},
        ],
        "name": "approve",
        "outputs": [{"name": "success", "type": "bool"}],
        "type": "function",
    },
]


class PredictFun(Exchange):
    """
    Predict.fun exchange implementation for BNB Chain prediction markets.

    Supports both public API (market data) and authenticated operations (trading).
    Uses EIP-712 message signing for order creation and authentication.
    """

    @property
    def id(self) -> str:
        return "predict.fun"

    @property
    def name(self) -> str:
        return "Predict.fun"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize Predict.fun exchange.

        Args:
            config: Configuration dictionary with:
                - api_key: API key for authentication (required for trading)
                - private_key: Private key for signing transactions (required for trading)
                - testnet: Use testnet API (default: False)
                - host: Custom API host URL (optional)
        """
        super().__init__(config)

        self.api_key = self.config.get("api_key", "")
        self.private_key = self.config.get("private_key", "")
        self.smart_wallet_owner_private_key = self.config.get("smart_wallet_owner_private_key", "")
        self.use_smart_wallet = self.config.get("use_smart_wallet", False)
        self.smart_wallet_address = self.config.get("smart_wallet_address", "")
        self.testnet = self.config.get("testnet", False)

        if self.testnet:
            self.host = self.config.get("host", TESTNET_URL)
            self.chain_id = TESTNET_CHAIN_ID
            self._yield_bearing_ctf_exchange = YIELD_BEARING_CTF_EXCHANGE_TESTNET
            self._yield_bearing_neg_risk_ctf_exchange = YIELD_BEARING_NEG_RISK_CTF_EXCHANGE_TESTNET
            self._ctf_exchange = CTF_EXCHANGE_TESTNET
            self._neg_risk_ctf_exchange = NEG_RISK_CTF_EXCHANGE_TESTNET
            self._usdt_address = USDT_ADDRESS_TESTNET
            self._rpc_url = BNB_RPC_TESTNET
        else:
            self.host = self.config.get("host", BASE_URL)
            self.chain_id = CHAIN_ID
            self._yield_bearing_ctf_exchange = YIELD_BEARING_CTF_EXCHANGE_MAINNET
            self._yield_bearing_neg_risk_ctf_exchange = YIELD_BEARING_NEG_RISK_CTF_EXCHANGE_MAINNET
            self._ctf_exchange = CTF_EXCHANGE_MAINNET
            self._neg_risk_ctf_exchange = NEG_RISK_CTF_EXCHANGE_MAINNET
            self._usdt_address = USDT_ADDRESS_MAINNET
            self._rpc_url = BNB_RPC_MAINNET

        self._session = requests.Session()
        self._account = None
        self._address = None
        self._owner_account = None  # Smart wallet owner account for signing
        self._jwt_token = None
        self._authenticated = False

        # Token ID to market ID mapping (for orderbook lookups)
        self._token_to_market: Dict[str, str] = {}
        # Token ID to outcome index (0=Yes, 1=No for binary markets)
        self._token_to_index: Dict[str, int] = {}

        # Web3 connection for on-chain balance queries and approvals
        self._web3 = Web3(Web3.HTTPProvider(self._rpc_url))
        self._usdt_contract = self._web3.eth.contract(
            address=Web3.to_checksum_address(self._usdt_address),
            abi=ERC20_ABI,
        )

        # Track if approvals have been checked this session
        self._approvals_checked = False

        # WebSocket instances
        self._websocket: Optional[PredictFunWebSocket] = None
        self._user_websocket: Optional[PredictFunUserWebSocket] = None

        # Mid-price cache for orderbook updates
        self._mid_price_cache: Dict[str, float] = {}

        # Initialize account if private key provided (skip in smart wallet mode)
        if self.private_key and not self.use_smart_wallet:
            self._account = Account.from_key(self.private_key)
            self._address = self._account.address

        # Initialize owner account for smart wallet mode
        if self.smart_wallet_owner_private_key:
            self._owner_account = Account.from_key(self.smart_wallet_owner_private_key)

        # Set _address for smart wallet mode (required by _is_using_smart_wallet)
        if self.use_smart_wallet and self.smart_wallet_address:
            self._address = self.smart_wallet_address

    def _get_headers(self, require_auth: bool = False) -> Dict[str, str]:
        """Get headers for API requests."""
        headers = {"Content-Type": "application/json"}

        if self.api_key:
            headers["x-api-key"] = self.api_key

        if require_auth and self._jwt_token:
            headers["Authorization"] = f"Bearer {self._jwt_token}"

        return headers

    def _authenticate(self) -> None:
        """Authenticate with Predict.fun using EIP-191 signing.

        For Smart Wallet mode: authenticates as the smart wallet address,
        using the owner's private key to sign with Kernel domain wrapping.
        For EOA mode: authenticates as the EOA address with standard EIP-191.
        """
        if not self.api_key:
            raise AuthenticationError("API key required for authentication")

        # Determine signer based on mode
        if self._is_using_smart_wallet():
            if not self._owner_account or not self.smart_wallet_address:
                raise AuthenticationError(
                    "Smart wallet owner private key and smart wallet address required"
                )
            signer_address = self.smart_wallet_address
            signing_account = self._owner_account
        else:
            if not self._account or not self._address:
                raise AuthenticationError("Private key required for authentication")
            signer_address = self._address
            signing_account = self._account

        try:
            # Get signing message
            msg_response = self._session.get(
                f"{self.host}/v1/auth/message",
                headers={"x-api-key": self.api_key},
                timeout=self.timeout,
            )
            msg_response.raise_for_status()

            msg_data = msg_response.json()
            message = msg_data.get("data", {}).get("message", "")

            if not message:
                raise AuthenticationError("Empty signing message")

            # Sign the message
            if self._is_using_smart_wallet():
                # Smart wallet: use Kernel domain wrapping
                signature = self._sign_auth_message_for_smart_wallet(message)
            else:
                # EOA: standard EIP-191 personal sign
                signable = encode_defunct(text=message)
                signed = signing_account.sign_message(signable)
                signature = signed.signature.hex()
                if not signature.startswith("0x"):
                    signature = f"0x{signature}"

            # Get JWT token
            jwt_response = self._session.post(
                f"{self.host}/v1/auth",
                headers={"Content-Type": "application/json", "x-api-key": self.api_key},
                json={"signer": signer_address, "message": message, "signature": signature},
                timeout=self.timeout,
            )
            jwt_response.raise_for_status()

            jwt_data = jwt_response.json()
            self._jwt_token = jwt_data.get("data", {}).get("token")

            if not self._jwt_token:
                raise AuthenticationError("Failed to get JWT token")

            self._authenticated = True

            if self.verbose:
                mode = "Smart Wallet" if self._is_using_smart_wallet() else "EOA"
                print(f"Authenticated as {signer_address} ({mode} mode)")

        except requests.RequestException as e:
            raise AuthenticationError(f"Authentication failed: {e}")

    def _sign_auth_message_for_smart_wallet(self, message: str) -> str:
        """Sign auth message for Smart Wallet using Kernel domain wrapping."""
        if not self._owner_account or not self.smart_wallet_address:
            raise AuthenticationError("Owner account and smart_wallet_address required")

        # Use EIP-191 prefix hash (same as SDK's hashMessage)
        signable = encode_defunct(text=message)
        message_hash = "0x" + _hash_eip191_message(signable).hex()

        # Use Kernel domain wrapping and sign
        return self._sign_predict_account_message(message_hash)

    def _ensure_authenticated(self) -> None:
        """Ensure user is authenticated for operations requiring auth."""
        # Check for Smart Wallet requirements
        if self._is_using_smart_wallet():
            if not self._owner_account:
                raise AuthenticationError(
                    "Smart Wallet mode requires PREDICTFUN_SMART_WALLET_OWNER_PRIVATE_KEY.\n"
                    "This is the private key of the EOA that owns the Smart Wallet."
                )
            if not self.smart_wallet_address:
                raise AuthenticationError(
                    "Smart Wallet mode requires PREDICTFUN_SMART_WALLET_ADDRESS.\n"
                    "This is your Predict Account (deposit address)."
                )

        if not self._authenticated:
            if not self.api_key:
                raise AuthenticationError("API key required for this operation")
            # For smart wallet mode, we need owner account; for EOA mode, we need _account
            if self._is_using_smart_wallet():
                if not self._owner_account:
                    raise AuthenticationError(
                        "Smart wallet owner private key required for this operation"
                    )
            else:
                if not self._account:
                    raise AuthenticationError("Private key required for this operation")
            self._authenticate()

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
                if method == "GET":
                    response = self._session.get(
                        url, params=params, headers=headers, timeout=self.timeout
                    )
                elif method == "POST":
                    response = self._session.post(
                        url, json=data, headers=headers, timeout=self.timeout
                    )
                elif method == "DELETE":
                    response = self._session.delete(
                        url, json=data, headers=headers, timeout=self.timeout
                    )
                else:
                    response = self._session.request(
                        method, url, params=params, json=data, headers=headers, timeout=self.timeout
                    )

                if response.status_code == 429:
                    raise RateLimitError("Rate limited")

                if response.status_code == 401:
                    # Try to get error message from response body
                    error_msg = "API key required"
                    try:
                        error_body = response.json()
                        error_msg = error_body.get("message", error_msg)
                    except Exception:
                        pass

                    # Try to re-authenticate if we have credentials
                    if self.api_key and (self._account or self._owner_account):
                        self._jwt_token = None
                        self._authenticated = False
                        self._authenticate()

                        # Retry the request
                        headers = self._get_headers(require_auth)
                        if method == "GET":
                            response = self._session.get(
                                url, params=params, headers=headers, timeout=self.timeout
                            )
                        elif method == "POST":
                            response = self._session.post(
                                url, json=data, headers=headers, timeout=self.timeout
                            )
                        elif method == "DELETE":
                            response = self._session.delete(
                                url, json=data, headers=headers, timeout=self.timeout
                            )

                        if not response.ok:
                            raise AuthenticationError("Authentication failed after retry")
                    else:
                        raise AuthenticationError(
                            f"{error_msg}. Predict.fun requires api_key for all API calls."
                        )

                if response.status_code == 403:
                    raise AuthenticationError("Access forbidden")

                if response.status_code == 404:
                    raise ExchangeError(f"Resource not found: {endpoint}")

                # Check for insufficient funds error (400 Bad Request)
                if response.status_code == 400:
                    try:
                        error_body = response.json()
                        error_tag = error_body.get("error", {}).get("_tag", "")
                        error_desc = error_body.get("error", {}).get("description", "")
                        if "Collateral" in error_tag or "Insufficient" in error_desc:
                            raise InsufficientFunds(f"Insufficient funds: {error_desc}")
                    except InsufficientFunds:
                        raise
                    except Exception:
                        pass  # Let raise_for_status handle other 400 errors

                response.raise_for_status()

                result = response.json()

                # API returns {"success": false, "message": "..."} for errors
                if isinstance(result, dict) and result.get("success") is False:
                    error_msg = result.get("message", "Unknown error")
                    if "invalid api key" in error_msg.lower():
                        raise AuthenticationError(f"Invalid API key: {error_msg}")
                    raise ExchangeError(f"API error: {error_msg}")

                return result

            except requests.Timeout as e:
                raise NetworkError(f"Request timeout: {e}")
            except requests.ConnectionError as e:
                raise NetworkError(f"Connection error: {e}")
            except requests.HTTPError as e:
                error_detail = ""
                try:
                    error_body = response.json()
                    # Show full error body for debugging
                    error_detail = str(error_body)
                except Exception:
                    error_detail = response.text[:500] if response.text else ""
                raise ExchangeError(f"HTTP error: {e} - {error_detail}")
            except requests.RequestException as e:
                raise ExchangeError(f"Request failed: {e}")

        return _make_request()

    def _parse_market(self, data: Dict[str, Any]) -> Market:
        """Parse market data from Predict.fun API response."""
        market_id = str(data.get("id", ""))
        title = data.get("title", "")
        question = data.get("question", title)
        description = data.get("description", "")

        outcomes_data = data.get("outcomes", [])
        outcomes = [o.get("name", "") for o in outcomes_data if o.get("name")]
        token_ids = [str(o.get("onChainId", "")) for o in outcomes_data if o.get("onChainId")]

        if not outcomes:
            outcomes = ["Yes", "No"]

        status = data.get("status", "")
        # REGISTERED = active, RESOLVED/PAUSED = closed
        closed = status not in ("REGISTERED", "ACTIVE", "OPEN", "")

        decimal_precision = data.get("decimalPrecision", 2)
        tick_size = 10 ** (-decimal_precision)

        # Volume and liquidity
        volume = float(data.get("volume", 0) or 0)
        liquidity = float(data.get("liquidity", 0) or 0)

        # Prices (empty by default, can be fetched from orderbook)
        prices: Dict[str, float] = {}

        metadata = {
            **data,
            "clobTokenIds": token_ids,
            "token_ids": token_ids,
            "isNegRisk": data.get("isNegRisk", False),
            "isYieldBearing": data.get("isYieldBearing", True),
            "conditionId": data.get("conditionId", ""),
            "feeRateBps": data.get("feeRateBps", 0),
            "categorySlug": data.get("categorySlug", ""),
            "closed": closed,
            "minimum_tick_size": tick_size,
        }

        # Cache token_id -> market_id and index mapping for orderbook lookups
        for idx, token_id in enumerate(token_ids):
            if token_id:
                self._token_to_market[token_id] = market_id
                self._token_to_index[token_id] = idx

        return Market(
            id=market_id,
            question=question,
            outcomes=outcomes,
            close_time=None,
            volume=volume,
            liquidity=liquidity,
            prices=prices,
            metadata=metadata,
            tick_size=tick_size,
            description=description,
        )

    def _parse_order(self, data: Dict[str, Any], outcome: str = "") -> Order:
        """Parse order data from API response."""
        # Handle nested order structure from GET /v1/orders
        nested_order = data.get("order", {})

        # Use database ID for cancellation (API requires ID, not hash)
        # Fallback to hash if ID not available
        order_id = str(
            data.get("id", "")
            or nested_order.get("hash", "")
            or data.get("hash", "")
            or data.get("orderHash", "")
        )
        market_id = str(data.get("marketId", ""))

        # Parse side from nested order or top level
        side_raw = nested_order.get("side") if nested_order else data.get("side", "buy")
        if side_raw is None:
            side_raw = data.get("side", "buy")
        if isinstance(side_raw, int):
            side = OrderSide.BUY if side_raw == 0 else OrderSide.SELL
        else:
            side = OrderSide.BUY if str(side_raw).lower() == "buy" else OrderSide.SELL

        status = self._parse_order_status(data.get("status"))

        # Price from makerAmount/takerAmount (nested) or pricePerShare
        price = 0.0
        if nested_order:
            maker_amount = int(nested_order.get("makerAmount", 0) or 0)
            taker_amount = int(nested_order.get("takerAmount", 0) or 0)
            # For BUY: price = makerAmount / takerAmount
            # For SELL: price = takerAmount / makerAmount
            if side == OrderSide.BUY and taker_amount > 0:
                price = maker_amount / taker_amount
            elif side == OrderSide.SELL and maker_amount > 0:
                price = taker_amount / maker_amount
        elif data.get("pricePerShare"):
            price_wei = int(str(data["pricePerShare"]))
            price = price_wei / 1e18
        elif data.get("price"):
            price = float(data["price"])

        # Amount in shares (takerAmount for BUY, makerAmount for SELL)
        amount_wei = int(data.get("amount", 0) or 0)
        if amount_wei == 0 and nested_order:
            if side == OrderSide.BUY:
                amount_wei = int(nested_order.get("takerAmount", 0) or 0)
            else:
                amount_wei = int(nested_order.get("makerAmount", 0) or 0)
        amount = amount_wei / 1e18 if amount_wei > 0 else 0.0

        filled_wei = int(data.get("amountFilled", 0) or 0)
        filled = filled_wei / 1e18 if filled_wei > 0 else 0.0

        created_at = self._parse_datetime(data.get("createdAt"))
        updated_at = self._parse_datetime(data.get("updatedAt"))

        if not created_at:
            created_at = datetime.now(timezone.utc)

        return Order(
            id=order_id,
            market_id=market_id,
            outcome=outcome,
            side=side,
            price=price,
            size=amount,
            filled=filled,
            status=status,
            created_at=created_at,
            updated_at=updated_at,
        )

    def _parse_order_status(self, status: Any) -> OrderStatus:
        """Convert string status to OrderStatus enum."""
        if not status:
            return OrderStatus.OPEN

        status_str = str(status).upper()
        status_map = {
            "PENDING": OrderStatus.PENDING,
            "OPEN": OrderStatus.OPEN,
            "LIVE": OrderStatus.OPEN,
            "ACTIVE": OrderStatus.OPEN,
            "FILLED": OrderStatus.FILLED,
            "MATCHED": OrderStatus.FILLED,
            "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
            "CANCELLED": OrderStatus.CANCELLED,
            "CANCELED": OrderStatus.CANCELLED,
            "EXPIRED": OrderStatus.CANCELLED,
            "INVALIDATED": OrderStatus.REJECTED,
        }
        return status_map.get(status_str, OrderStatus.OPEN)

    def _parse_position(self, data: Dict[str, Any]) -> Position:
        """Parse position data from API response."""
        # Handle nested structure from API
        market_data = data.get("market", {})
        outcome_data = data.get("outcome", {})

        market_id = str(market_data.get("id", "") or data.get("marketId", ""))
        outcome = (
            outcome_data.get("name", "") if isinstance(outcome_data, dict) else str(outcome_data)
        )

        # Amount is in wei (18 decimals)
        amount_wei = int(data.get("amount", 0) or 0)
        size = amount_wei / 1e18 if amount_wei > 0 else float(data.get("size", 0) or 0)

        average_price = float(data.get("avgPrice", 0) or 0)
        current_price = float(data.get("currentPrice", 0) or 0)

        return Position(
            market_id=market_id,
            outcome=outcome,
            size=size,
            average_price=average_price,
            current_price=current_price,
        )

    def _parse_datetime(self, timestamp: Any) -> Optional[datetime]:
        """Parse datetime from various formats."""
        if not timestamp:
            return None

        if isinstance(timestamp, datetime):
            return timestamp

        try:
            if isinstance(timestamp, (int, float)):
                return datetime.fromtimestamp(timestamp, tz=timezone.utc)
            ts_str = str(timestamp).replace("Z", "+00:00")
            return datetime.fromisoformat(ts_str)
        except (ValueError, TypeError):
            return None

    def fetch_markets(self, params: Optional[Dict[str, Any]] = None) -> List[Market]:
        """
        Fetch active markets from Predict.fun.

        Args:
            params: Optional parameters:
                - limit: Maximum number of markets to return
                - active: If True (default), filter out closed markets
                - all: If True, fetch all pages (default False)

        Returns:
            List of Market objects
        """
        query_params = params or {}
        limit = query_params.get("limit", 100)
        fetch_all = query_params.get("all", False)

        all_markets: List[Market] = []
        cursor = None
        max_pages = 10 if fetch_all else 1

        for _ in range(max_pages):
            api_params = {"first": min(limit, 100)}
            if cursor:
                api_params["after"] = cursor

            response = self._request("GET", "/v1/markets", params=api_params)

            markets_data = response if isinstance(response, list) else response.get("data", [])
            markets = [self._parse_market(m) for m in markets_data]
            all_markets.extend(markets)

            # Get cursor for next page
            cursor = response.get("cursor") if isinstance(response, dict) else None
            if not cursor or len(markets_data) < 100:
                break

        # Filter closed markets by default
        if query_params.get("active", True):
            all_markets = [m for m in all_markets if not m.metadata.get("closed")]

        # Apply limit
        if limit and len(all_markets) > limit:
            all_markets = all_markets[:limit]

        return all_markets

    def fetch_market(self, market_id: str) -> Market:
        """
        Fetch a specific market by ID.

        Args:
            market_id: Market ID

        Returns:
            Market object
        """

        @self._retry_on_failure
        def _fetch():
            try:
                response = self._request("GET", f"/v1/markets/{market_id}")
                market_data = response.get("data", response)
                return self._parse_market(market_data)
            except ExchangeError as e:
                if "not found" in str(e).lower():
                    raise MarketNotFound(f"Market {market_id} not found")
                raise

        return _fetch()

    def fetch_markets_by_slug(self, slug_or_url: str) -> List[Market]:
        """
        Fetch markets by category slug or URL.

        First tries to fetch from /v1/categories/{slug} API.
        Falls back to keyword search if category not found.

        Args:
            slug_or_url: Category slug or predict.fun URL
                Examples:
                - "will-gold-be-above-4400-on-january-30th-2026"
                - "https://predict.fun/markets/will-gold-be-above-4400-on-january-30th-2026"

        Returns:
            List of Market objects
        """
        # Parse slug from URL if needed
        slug = self._parse_slug(slug_or_url)

        if not slug:
            raise ValueError("Empty slug provided")

        markets: List[Market] = []

        # Try to fetch from /v1/categories/{slug} API
        try:
            response = self._request("GET", f"/v1/categories/{slug}")
            data = response.get("data", {})

            if data:
                # Category found - parse markets from it
                markets_data = data.get("markets", [])
                if markets_data:
                    markets = [self._parse_market(m) for m in markets_data]
                else:
                    # If no nested markets, create market from category itself
                    markets = [self._parse_category_as_market(data)]

        except ExchangeError:
            pass  # Category not found, fall back to keyword search

        # Fallback: keyword search
        if not markets:
            markets = self._search_markets_by_keywords(slug)

        # Enrich markets with orderbook prices
        self._enrich_markets_with_prices(markets)

        return markets

    def _enrich_markets_with_prices(self, markets: List[Market]) -> None:
        """Fetch orderbook prices and populate market.prices for display."""
        if self.verbose and markets:
            print(f"Fetching prices for {len(markets)} markets...")

        for market in markets:
            if market.prices.get("Yes"):
                continue  # Already has prices

            token_ids = market.metadata.get("clobTokenIds", [])
            if not token_ids:
                continue

            try:
                orderbook = self.get_orderbook(token_ids[0])
                bids = orderbook.get("bids", [])
                asks = orderbook.get("asks", [])

                best_bid = float(bids[0]["price"]) if bids else 0
                best_ask = float(asks[0]["price"]) if asks else 0

                if best_bid and best_ask:
                    mid_price = (best_bid + best_ask) / 2
                elif best_bid:
                    mid_price = best_bid
                elif best_ask:
                    mid_price = best_ask
                else:
                    continue

                market.prices["Yes"] = mid_price
                market.prices["No"] = 1 - mid_price
            except Exception:
                pass

    def _parse_slug(self, slug_or_url: str) -> str:
        """Parse slug from URL or return as-is."""
        slug = slug_or_url.strip()

        # Handle predict.fun URLs
        if "predict.fun" in slug:
            # Extract slug from URL like https://predict.fun/markets/slug-here
            parts = slug.rstrip("/").split("/")
            slug = parts[-1] if parts else ""

        return slug

    def _parse_category_as_market(self, data: Dict[str, Any]) -> Market:
        """Parse category data as a Market when it contains a single market."""
        market_id = str(data.get("id", ""))

        # Try to get the actual market from the category
        markets = data.get("markets", [])
        if markets:
            return self._parse_market(markets[0])

        # Otherwise create market from category data
        title = data.get("title", "")
        slug = data.get("slug", "")
        outcomes_data = data.get("outcomes", [])

        outcomes = [o.get("name", "") for o in outcomes_data] if outcomes_data else ["Yes", "No"]
        token_ids = [str(o.get("onChainId", "")) for o in outcomes_data if o.get("onChainId")]

        return Market(
            id=market_id,
            question=title,
            outcomes=outcomes,
            description=data.get("description", ""),
            volume=data.get("volume", 0),
            liquidity=data.get("liquidity", 0),
            metadata={
                "slug": slug,
                "clobTokenIds": token_ids,
                "token_ids": token_ids,
                "isNegRisk": data.get("isNegRisk", False),
                "isYieldBearing": data.get("isYieldBearing", True),
                "conditionId": data.get("conditionId", ""),
                "feeRateBps": data.get("feeRateBps", 0),
            },
        )

    def _search_markets_by_keywords(self, slug: str) -> List[Market]:
        """Fallback: search markets by keywords from slug."""
        keywords = slug.replace("-", " ").lower().split()
        keywords = [k for k in keywords if len(k) > 2]

        if not keywords:
            return []

        all_markets = self.fetch_markets({"all": True})

        matches = []
        for market in all_markets:
            text = market.question.lower()
            if all(k in text for k in keywords):
                matches.append(market)

        return matches

    def get_orderbook(self, market_id_or_token_id: str) -> Dict[str, Any]:
        """
        Fetch orderbook for a specific market or token.

        For binary markets, the API returns orderbook for the first outcome (Yes).
        If token_id is for the second outcome (No), prices are inverted (1 - price).

        Args:
            market_id_or_token_id: Market ID or token ID

        Returns:
            Dictionary with 'bids' and 'asks' arrays
        """
        # Check if this is a token_id and if it's the second outcome (No)
        is_second_outcome = False
        market_id = market_id_or_token_id

        if market_id_or_token_id in self._token_to_market:
            market_id = self._token_to_market[market_id_or_token_id]
            # Check if this token is the second outcome by looking at cached market data
            is_second_outcome = self._is_second_outcome_token(market_id_or_token_id, market_id)

        @self._retry_on_failure
        def _fetch():
            try:
                response = self._request("GET", f"/v1/markets/{market_id}/orderbook")
                data = response.get("data", {})

                raw_bids = data.get("bids", [])
                raw_asks = data.get("asks", [])

                bids = []
                asks = []

                if is_second_outcome:
                    # For second outcome (No), invert prices: No bid = 1 - Yes ask
                    for entry in raw_asks:
                        if len(entry) >= 2:
                            inverted_price = 1.0 - float(entry[0])
                            if inverted_price > 0:
                                bids.append({"price": str(inverted_price), "size": str(entry[1])})

                    for entry in raw_bids:
                        if len(entry) >= 2:
                            inverted_price = 1.0 - float(entry[0])
                            if inverted_price > 0:
                                asks.append({"price": str(inverted_price), "size": str(entry[1])})
                else:
                    # First outcome (Yes) - use as-is
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
                    print(f"Failed to fetch orderbook for {market_id}: {e}")
                return {"bids": [], "asks": []}

        return _fetch()

    def _is_second_outcome_token(self, token_id: str, market_id: str) -> bool:
        """Check if token_id is the second outcome (No) for a binary market."""
        # Use the cached index mapping (0=Yes, 1=No)
        return self._token_to_index.get(token_id, 0) == 1

    def fetch_token_ids(self, market_id: str) -> List[str]:
        """
        Fetch token IDs for a specific market.

        Args:
            market_id: Market ID

        Returns:
            List of token IDs
        """
        market = self.fetch_market(market_id)
        token_ids = market.metadata.get("clobTokenIds", [])
        if not token_ids:
            raise ExchangeError(f"No token IDs found for market {market_id}")
        return token_ids

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
            outcome: Outcome to bet on
            side: OrderSide.BUY or OrderSide.SELL
            price: Price per share (0-1)
            size: Size in shares
            params: Additional parameters:
                - token_id: Token ID (optional if outcome provided)
                - strategy: "LIMIT" or "MARKET" (default: "LIMIT")
                - slippageBps: Slippage in basis points (default: "0")

        Returns:
            Order object
        """
        self._ensure_authenticated()

        # Check and set approvals for EOA mode (only once per session)
        if not self._is_using_smart_wallet() and not self._approvals_checked:
            if not self.check_and_set_approvals():
                raise ExchangeError("Failed to set USDT approvals for exchange contracts")

        if self._is_using_smart_wallet():
            if not self._owner_account or not self._address:
                raise AuthenticationError("Smart wallet not initialized")
        else:
            if not self._account or not self._address:
                raise AuthenticationError("Wallet not initialized")

        market = self.fetch_market(market_id)
        outcomes = market.outcomes
        token_ids = market.metadata.get("clobTokenIds", [])

        extra_params = params or {}
        token_id = extra_params.get("token_id")

        if not token_id:
            outcome_index = outcomes.index(outcome) if outcome in outcomes else -1
            if outcome_index != -1 and outcome_index < len(token_ids):
                token_id = token_ids[outcome_index]

        if not token_id:
            raise InvalidOrder(f"Could not find token_id for outcome '{outcome}'")

        if price <= 0 or price > 1:
            raise InvalidOrder(f"Price must be between 0 and 1, got: {price}")

        if size <= 0:
            raise InvalidOrder(f"Size must be greater than 0, got: {size}")

        fee_rate_bps = market.metadata.get("feeRateBps", 0)
        is_yield_bearing = market.metadata.get("isYieldBearing", True)
        is_neg_risk = market.metadata.get("isNegRisk", False)

        # Select appropriate exchange contract
        if is_yield_bearing:
            exchange_address = (
                self._yield_bearing_neg_risk_ctf_exchange
                if is_neg_risk
                else self._yield_bearing_ctf_exchange
            )
        else:
            exchange_address = self._neg_risk_ctf_exchange if is_neg_risk else self._ctf_exchange

        strategy = (extra_params.get("strategy", "LIMIT")).upper()

        signed_order = self._build_signed_order(
            token_id=str(token_id),
            price=price,
            size=size,
            side=side,
            fee_rate_bps=fee_rate_bps,
            exchange_address=exchange_address,
        )

        # Price in wei (1e18), rounded to 1e13 precision
        precision = int(1e13)
        price_per_share_wei = (int(price * 1e18) // precision) * precision

        payload = {
            "data": {
                "pricePerShare": str(price_per_share_wei),
                "strategy": strategy,
                "slippageBps": extra_params.get("slippageBps", "0"),
                "order": signed_order,
            }
        }

        @self._retry_on_failure
        def _create():
            result = self._request("POST", "/v1/orders", data=payload, require_auth=True)
            order_data = result.get("data", result)
            order_id = order_data.get("hash", "") or order_data.get("orderHash", "")

            return Order(
                id=str(order_id),
                market_id=market_id,
                outcome=outcome,
                side=side,
                price=price,
                size=size,
                filled=0,
                status=OrderStatus.OPEN,
                created_at=datetime.now(timezone.utc),
            )

        return _create()

    def _is_using_smart_wallet(self) -> bool:
        """Check if using a Predict smart wallet."""
        return bool(self.use_smart_wallet and self.smart_wallet_address and self._address)

    def _get_maker_address(self) -> str:
        """Get the maker address (smart wallet if configured, otherwise EOA)."""
        if self._is_using_smart_wallet():
            return self.smart_wallet_address
        return self._address

    def check_and_set_approvals(self) -> bool:
        """
        Check and set USDT approvals for CTF exchange contracts (EOA mode only).

        In EOA mode, the EOA wallet must approve the CTF exchange contracts to spend USDT.
        This checks allowance and sends approve transactions if needed.

        Returns:
            True if approvals are set (or already sufficient), False on failure.
        """
        if self._is_using_smart_wallet():
            return True

        if not self._account or not self._address:
            if self.verbose:
                print("Cannot check approvals: wallet not initialized")
            return False

        # All exchange contracts that need approval
        exchange_contracts = [
            self._yield_bearing_ctf_exchange,
            self._yield_bearing_neg_risk_ctf_exchange,
            self._ctf_exchange,
            self._neg_risk_ctf_exchange,
        ]

        # Max uint256 for unlimited approval
        max_approval = 2**256 - 1
        # Threshold: approve if allowance is below 1M USDT (1e24 wei)
        approval_threshold = int(1e24)

        try:
            for exchange_addr in exchange_contracts:
                exchange_checksum = Web3.to_checksum_address(exchange_addr)
                owner_checksum = Web3.to_checksum_address(self._address)

                # Check current allowance
                allowance = self._usdt_contract.functions.allowance(
                    owner_checksum, exchange_checksum
                ).call()

                if allowance < approval_threshold:
                    if self.verbose:
                        print(f"Approving USDT for {exchange_addr}...")

                    # Build and send approve transaction
                    nonce = self._web3.eth.get_transaction_count(owner_checksum)
                    gas_price = self._web3.eth.gas_price

                    tx = self._usdt_contract.functions.approve(
                        exchange_checksum, max_approval
                    ).build_transaction(
                        {
                            "from": owner_checksum,
                            "nonce": nonce,
                            "gas": 100000,
                            "gasPrice": gas_price,
                            "chainId": self.chain_id,
                        }
                    )

                    signed_tx = self._account.sign_transaction(tx)
                    tx_hash = self._web3.eth.send_raw_transaction(signed_tx.raw_transaction)

                    # Wait for confirmation
                    receipt = self._web3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

                    if receipt["status"] == 1:
                        if self.verbose:
                            print(f"Approved USDT for {exchange_addr}: {tx_hash.hex()}")
                    else:
                        if self.verbose:
                            print(f"Approval failed for {exchange_addr}")
                        return False

            self._approvals_checked = True
            return True

        except Exception as e:
            if self.verbose:
                print(f"Failed to set approvals: {e}")
            return False

    def _hash_kernel_message(self, message_hash: str) -> str:
        """Hash a message for Kernel smart wallet."""
        kernel_type_hash = Web3.keccak(text="Kernel(bytes32 hash)")
        message_hash_bytes = bytes.fromhex(
            message_hash[2:] if message_hash.startswith("0x") else message_hash
        )
        encoded = eth_abi_encode(["bytes32", "bytes32"], [kernel_type_hash, message_hash_bytes])
        return "0x" + Web3.keccak(encoded).hex()

    def _hash_eip712_domain(self, domain: Dict[str, Any]) -> bytes:
        """Hash an EIP-712 domain."""
        domain_type = (
            "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
        )
        domain_type_hash = Web3.keccak(text=domain_type)
        name_hash = Web3.keccak(text=domain["name"])
        version_hash = Web3.keccak(text=domain["version"])
        chain_id = int(domain["chainId"])
        verifying_contract = Web3.to_checksum_address(domain["verifyingContract"])
        encoded = eth_abi_encode(
            ["bytes32", "bytes32", "bytes32", "uint256", "address"],
            [domain_type_hash, name_hash, version_hash, chain_id, verifying_contract],
        )
        return Web3.keccak(encoded)

    def _eip712_wrap_hash(self, message_hash: str, domain: Dict[str, Any]) -> str:
        """Wrap a message hash with EIP-712 domain separator for Kernel signing."""
        domain_separator = self._hash_eip712_domain(domain)
        final_message_hash = self._hash_kernel_message(message_hash)
        final_hash_bytes = bytes.fromhex(
            final_message_hash[2:] if final_message_hash.startswith("0x") else final_message_hash
        )
        data = b"\x19\x01" + domain_separator + final_hash_bytes
        return "0x" + Web3.keccak(data).hex()

    def _sign_predict_account_message(self, message_hash: str) -> str:
        """Sign a message for Predict smart wallet using Kernel domain wrapping."""
        if not self._owner_account or not self.smart_wallet_address:
            raise AuthenticationError(
                "Owner account and smart_wallet_address required for smart wallet signing"
            )

        kernel_domain = {
            "name": KERNEL_DOMAIN_NAME,
            "version": KERNEL_DOMAIN_VERSION,
            "chainId": self.chain_id,
            "verifyingContract": self.smart_wallet_address,
        }

        digest = self._eip712_wrap_hash(message_hash, kernel_domain)

        message_bytes = bytes.fromhex(digest[2:] if digest.startswith("0x") else digest)
        signable_msg = encode_defunct(primitive=message_bytes)
        signed = self._owner_account.sign_message(signable_msg)

        # Format: 0x01 + validator_address (without 0x) + signature
        return "0x01" + ECDSA_VALIDATOR_ADDRESS[2:] + signed.signature.hex()

    def _build_signed_order(
        self,
        token_id: str,
        price: float,
        size: float,
        side: OrderSide,
        fee_rate_bps: int,
        exchange_address: str,
    ) -> Dict[str, Any]:
        """Build and sign an order using EIP-712."""
        if self._is_using_smart_wallet():
            if not self._owner_account or not self._address:
                raise AuthenticationError("Smart wallet not initialized")
        else:
            if not self._account or not self._address:
                raise AuthenticationError("Wallet not initialized")

        # Generate salt (must be between 0 and 2147483648)
        max_salt = 2147483648
        salt = secrets.randbelow(max_salt)

        # Calculate amounts (all in wei, 18 decimals)
        # API requires amounts to be multiples of 1e13 (precision = 5 decimals)
        precision = int(1e13)

        def round_to_precision(value: int) -> int:
            """Round down to nearest multiple of 1e13."""
            return (value // precision) * precision

        shares_wei = round_to_precision(int(size * 1e18))
        price_wei = round_to_precision(int(price * 1e18))

        # side: 0 = BUY, 1 = SELL
        side_int = 0 if side == OrderSide.BUY else 1

        if side == OrderSide.BUY:
            # BUY: maker provides collateral, receives shares
            maker_amount = round_to_precision((shares_wei * price_wei) // int(1e18))
            taker_amount = shares_wei
        else:
            # SELL: maker provides shares, receives collateral
            maker_amount = shares_wei
            taker_amount = round_to_precision((shares_wei * price_wei) // int(1e18))

        # When using smart wallet, maker and signer are both the smart wallet address
        maker_address = self._get_maker_address()

        expiration = NO_EXPIRY_TIMESTAMP

        order = {
            "salt": str(salt),
            "maker": maker_address,
            "signer": maker_address,
            "taker": "0x0000000000000000000000000000000000000000",
            "tokenId": token_id,
            "makerAmount": str(maker_amount),
            "takerAmount": str(taker_amount),
            "expiration": str(expiration),
            "nonce": "0",
            "feeRateBps": str(fee_rate_bps),
            "side": side_int,
            "signatureType": 0,
        }

        # Sign with EIP-712 (using appropriate method for smart wallet or EOA)
        signature = self._sign_order_eip712(order, exchange_address)

        return {**order, "signature": signature}

    def _sign_order_eip712(self, order: Dict[str, Any], exchange_address: str) -> str:
        """Sign order using EIP-712 typed data."""
        if self._is_using_smart_wallet():
            if not self._owner_account:
                raise AuthenticationError("Owner account not initialized for smart wallet")
        else:
            if not self._account:
                raise AuthenticationError("Wallet not initialized")

        domain = {
            "name": PROTOCOL_NAME,
            "version": PROTOCOL_VERSION,
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

        # For smart wallet, use Kernel domain wrapping
        if self._is_using_smart_wallet():
            encoded = encode_typed_data(full_message=typed_data)
            order_hash = "0x" + _hash_eip191_message(encoded).hex()
            signature = self._sign_predict_account_message(order_hash)
        else:
            # Standard EOA signing
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
            order_id: Order ID (hash) to cancel
            market_id: Market ID (optional)

        Returns:
            Updated Order object
        """
        self._ensure_authenticated()

        @self._retry_on_failure
        def _cancel():
            self._request(
                "POST",
                "/v1/orders/remove",
                data={"data": {"ids": [order_id]}},
                require_auth=True,
            )

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
            )

        return _cancel()

    def fetch_order(self, order_id: str, market_id: Optional[str] = None) -> Order:
        """
        Fetch order details by ID.

        Args:
            order_id: Order ID
            market_id: Market ID (optional)

        Returns:
            Order object
        """
        self._ensure_authenticated()

        @self._retry_on_failure
        def _fetch():
            response = self._request("GET", f"/v1/orders/{order_id}", require_auth=True)
            order_data = response.get("data", response)
            return self._parse_order(order_data)

        return _fetch()

    def fetch_open_orders(self, market_id: Optional[str] = None) -> List[Order]:
        """
        Fetch all open orders.

        Args:
            market_id: Optional market filter

        Returns:
            List of Order objects
        """
        self._ensure_authenticated()

        query_params = {"status": "OPEN"}
        if market_id:
            query_params["marketId"] = market_id

        @self._retry_on_failure
        def _fetch():
            response = self._request("GET", "/v1/orders", params=query_params, require_auth=True)
            orders_data = response if isinstance(response, list) else response.get("data", [])
            return [self._parse_order(o) for o in orders_data]

        return _fetch()

    def fetch_positions(self, market_id: Optional[str] = None) -> List[Position]:
        """
        Fetch current positions.

        Args:
            market_id: Optional market filter

        Returns:
            List of Position objects
        """
        self._ensure_authenticated()

        query_params = {}
        if market_id:
            query_params["marketId"] = market_id

        @self._retry_on_failure
        def _fetch():
            response = self._request("GET", "/v1/positions", params=query_params, require_auth=True)
            positions_data = response if isinstance(response, list) else response.get("data", [])
            # Filter by amount (wei) or size
            return [
                self._parse_position(p)
                for p in positions_data
                if int(p.get("amount", 0) or 0) > 0 or float(p.get("size", 0) or 0) > 0
            ]

        return _fetch()

    def fetch_balance(self) -> Dict[str, float]:
        """
        Fetch account USDT balance from on-chain.

        Returns:
            Dictionary with balance info (e.g., {'USDT': 1000.0})

        Note:
            Queries USDT balance directly from BNB Chain smart contract.
            Uses smart_wallet_address if configured, otherwise EOA address.
        """
        # Use smart wallet if configured, otherwise EOA
        if self._is_using_smart_wallet():
            balance_address = self.smart_wallet_address
        else:
            balance_address = self._address
        if not balance_address:
            return {"USDT": 0.0}

        try:
            # Query USDT balance from on-chain
            balance_wei = self._usdt_contract.functions.balanceOf(
                Web3.to_checksum_address(balance_address)
            ).call()

            # USDT on BNB has 18 decimals
            balance_usdt = balance_wei / 1e18

            return {"USDT": balance_usdt}
        except Exception as e:
            if self.verbose:
                print(f"Failed to fetch on-chain balance: {e}")
            return {"USDT": 0.0}

    @property
    def wallet_address(self) -> Optional[str]:
        """Get the wallet address."""
        return self._address

    def get_websocket(self) -> PredictFunWebSocket:
        """Get WebSocket for real-time orderbook updates."""
        if self._websocket is None:
            self._websocket = PredictFunWebSocket(
                config={"api_key": self.api_key, "verbose": self.verbose},
                exchange=self,
            )
        return self._websocket

    def get_user_websocket(self) -> PredictFunUserWebSocket:
        """Get User WebSocket for wallet event notifications."""
        self._ensure_authenticated()
        if not self._jwt_token:
            raise AuthenticationError("Cannot create user websocket: not authenticated")
        if self._user_websocket is None:
            self._user_websocket = PredictFunUserWebSocket(
                jwt_token=self._jwt_token,
                api_key=self.api_key,
                verbose=self.verbose,
            )
        return self._user_websocket

    def update_mid_price_from_orderbook(self, token_id: str, orderbook: Dict[str, Any]) -> None:
        """Update mid-price cache from orderbook data (called by WebSocket)."""
        bids = orderbook.get("bids", [])
        asks = orderbook.get("asks", [])
        if not bids and not asks:
            return
        best_bid = bids[0][0] if bids else 0
        best_ask = asks[0][0] if asks else 0
        if best_bid and best_ask:
            mid_price = (best_bid + best_ask) / 2
        elif best_bid:
            mid_price = best_bid
        elif best_ask:
            mid_price = best_ask
        else:
            return
        self._mid_price_cache[token_id] = mid_price

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
                "websocket": True,
            },
            "notes": {
                "smart_wallet": (
                    "Smart Wallet (Predict Account) is supported for API trading. "
                    "Set PREDICTFUN_USE_SMART_WALLET=true and provide "
                    "PREDICTFUN_SMART_WALLET_OWNER_PRIVATE_KEY and PREDICTFUN_SMART_WALLET_ADDRESS."
                ),
            },
        }
