from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Sequence

import requests
from py_clob_client.client import ClobClient

from ...base.errors import (
    AuthenticationError,
    ExchangeError,
    MarketNotFound,
    NetworkError,
    RateLimitError,
)
from ...models.market import Market


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


class PolymarketCore:
    """Common infrastructure mixin: constants, init, HTTP, parsing helpers."""

    BASE_URL = "https://gamma-api.polymarket.com"
    CLOB_URL = "https://clob.polymarket.com"
    PRICES_HISTORY_URL = f"{CLOB_URL}/prices-history"
    DATA_API_URL = "https://data-api.polymarket.com"
    SUPPORTED_INTERVALS: Sequence[str] = ("1m", "1h", "6h", "1d", "1w", "max")

    # CTF (Conditional Token Framework) constants
    CTF_CONTRACT = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
    USDC_E = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    RELAYER_URL = "https://relayer-v2.polymarket.com"
    ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
    POLYGON_RPC_URL = "https://polygon-rpc.com"
    CHAIN_ID = 137

    # Safe ABI for nonce
    SAFE_ABI = [
        {
            "inputs": [],
            "name": "nonce",
            "outputs": [{"type": "uint256"}],
            "stateMutability": "view",
            "type": "function",
        }
    ]

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
        return PolymarketCore.TOKEN_ALIASES.get(token_upper, token_upper)

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
        self._w3 = None

        # Builder API credentials for CTF operations (split/merge/redeem)
        self.builder_api_key = self.config.get("builder_api_key")
        self.builder_secret = self.config.get("builder_secret")
        self.builder_passphrase = self.config.get("builder_passphrase")

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

    def _ensure_market(self, market: Market | str) -> Market:
        if isinstance(market, Market):
            return market
        fetched = self.fetch_market(market)
        if not fetched:
            raise MarketNotFound(f"Market {market} not found")
        return fetched

    # ------------------------------------------------------------------
    # ID resolvers: Market | str → specific ID type
    # ------------------------------------------------------------------

    def _resolve_condition_id(self, market: Market | str) -> str:
        """Extract condition_id from Market object or pass through str."""
        if isinstance(market, Market):
            # Try both key formats (Gamma uses conditionId, CLOB uses condition_id)
            cid = (
                market.metadata.get("conditionId")
                or market.metadata.get("condition_id")
                or market.id
            )
            return str(cid)
        return market

    def _resolve_gamma_id(self, market: Market | str) -> str:
        """Extract Gamma numeric ID from Market object or pass through str.

        If Market has no Gamma ID, fetches it via Gamma API.
        """
        if isinstance(market, Market):
            # Gamma API stores numeric id under "id" key (not always present in CLOB data)
            gid = market.metadata.get("id")
            if gid and str(gid).isdigit():
                return str(gid)
            # Fallback: fetch from Gamma via condition_id → need to resolve
            cid = self._resolve_condition_id(market)
            fetched = self.fetch_market(cid)
            gid = fetched.metadata.get("id")
            if gid and str(gid).isdigit():
                return str(gid)
            raise ExchangeError("Could not resolve Gamma numeric ID for this market")
        return market

    def _resolve_token_id(self, market: Market | str, outcome: int | str = 0) -> str:
        """Extract token_id for a given outcome from Market object or pass through str.

        Args:
            market: Market object or raw token_id/condition_id string.
                    If a condition_id (0x...) is passed, token_ids are fetched via CLOB.
            outcome: 0/"Yes" for first token, 1/"No" for second token.
                     Ignored if a raw token_id string is passed.
        """
        if isinstance(market, str):
            # If it looks like a condition_id, resolve to token_id
            if market.startswith("0x") and len(market) == 66:
                token_ids = self.fetch_token_ids(market)
                idx = 0
                if isinstance(outcome, int):
                    idx = outcome
                elif isinstance(outcome, str) and outcome.lower() in ("no", "1"):
                    idx = 1
                if idx >= len(token_ids):
                    raise ExchangeError(f"Token index {idx} out of range")
                return str(token_ids[idx])
            # Otherwise assume it's already a token_id
            return market
        # Market object
        token_ids = market.metadata.get("clobTokenIds", [])
        if not token_ids:
            token_ids = self._extract_token_ids(market)
        if not token_ids:
            raise ExchangeError("Market object has no token IDs")
        idx = 0
        if isinstance(outcome, int):
            idx = outcome
        elif isinstance(outcome, str):
            if outcome.lower() in ("no", "1"):
                idx = 1
        if idx >= len(token_ids):
            raise ExchangeError(f"Token index {idx} out of range (have {len(token_ids)} tokens)")
        return str(token_ids[idx])
