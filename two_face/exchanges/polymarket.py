from typing import Optional, Dict, Any
from datetime import datetime
from decimal import Decimal
import json

import requests
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType, AssetType, BalanceAllowanceParams

from ..base.exchange import Exchange
from ..base.errors import NetworkError, ExchangeError, MarketNotFound, RateLimitError
from ..models.market import Market
from ..models.order import Order, OrderSide, OrderStatus
from ..models.position import Position
from .polymarket_ws import PolymarketWebSocket


class Polymarket(Exchange):
    """Polymarket exchange implementation"""

    BASE_URL = "https://gamma-api.polymarket.com"
    CLOB_URL = "https://clob.polymarket.com"

    # Market type tags (Polymarket-specific)
    TAG_1H = "102175"  # 1-hour crypto price markets

    # Token normalization mapping
    TOKEN_ALIASES = {
        'BITCOIN': 'BTC',
        'ETHEREUM': 'ETH',
        'SOLANA': 'SOL',
    }

    @staticmethod
    def normalize_token(token: str) -> str:
        """Normalize token symbol to standard format (e.g., BITCOIN -> BTC)"""
        token_upper = token.upper()
        return Polymarket.TOKEN_ALIASES.get(token_upper, token_upper)

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
        self._clob_client = None
        self._address = None
        
        # Initialize CLOB client if private key is provided
        if self.private_key:
            self._initialize_clob_client()

    def _initialize_clob_client(self):
        """Initialize CLOB client with authentication."""
        try:
            chain_id = self.config.get('chain_id', 137)
            signature_type = self.config.get('signature_type', 2)
            
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
                raise ExchangeError("Failed to derive API credentials")
            
            self._clob_client.set_api_creds(api_creds)
            
            # Verify L2 mode
            if self._clob_client.mode < 2:
                raise ExchangeError(f"Client not in L2 mode (current mode: {self._clob_client.mode})")
            
            # Store address
            try:
                self._address = self._clob_client.get_address()
            except:
                self._address = None
                
        except Exception as e:
            raise ExchangeError(f"Failed to initialize CLOB client: {e}")
    
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
        """
        Fetch all markets from Polymarket
        
        Uses CLOB API instead of Gamma API because CLOB includes token IDs
        which are required for trading.
        """
        @self._retry_on_failure
        def _fetch():
            # Fetch from CLOB API /sampling-markets (includes token IDs and live markets)
            try:
                response = requests.get(
                    f"{self.CLOB_URL}/sampling-markets",
                    timeout=self.timeout
                )
                
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
                    if query_params.get('active') or (not query_params.get('closed', True)):
                        markets = [m for m in markets if m.is_open]
                    
                    # Apply limit if provided
                    limit = query_params.get('limit')
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

    def _parse_sampling_market(self, data: Dict[str, Any]) -> Optional[Market]:
        """Parse market data from CLOB sampling-markets API response"""
        try:
            # sampling-markets includes more fields than simplified-markets
            condition_id = data.get("condition_id")
            if not condition_id:
                return None
            
            # Extract question and description
            question = data.get("question", "")
            
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
            
            # Determine if market is open
            is_open = data.get("active", False) and data.get("accepting_orders", False) and not data.get("closed", False)
            
            # Build metadata with token IDs already included
            metadata = {
                **data,
                "clobTokenIds": token_ids,
                "condition_id": condition_id
            }
            
            return Market(
                id=condition_id,
                question=question,
                outcomes=outcomes if outcomes else ["Yes", "No"],
                close_time=None,  # Can parse if needed
                volume=0,  # Not in sampling-markets
                liquidity=0,  # Not in sampling-markets
                prices=prices,
                metadata=metadata
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
            
            # Determine if market is open
            # A market is tradeable if it's active and accepting orders (even if "closed")
            is_open = data.get("active", False) and data.get("accepting_orders", False)
            
            # Build metadata with token IDs already included
            metadata = {
                **data,
                "clobTokenIds": token_ids,
                "condition_id": condition_id
            }
            
            return Market(
                id=condition_id,
                question="",  # CLOB API doesn't include question text
                outcomes=outcomes if outcomes else ["Yes", "No"],
                close_time=None,  # CLOB API doesn't include end date
                volume=0,  # CLOB API doesn't include volume
                liquidity=0,  # CLOB API doesn't include liquidity
                prices=prices,
                metadata=metadata
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
        if 'tokens' in data and data['tokens']:
            metadata['clobTokenIds'] = data['tokens']
        elif 'clobTokenIds' not in metadata and 'tokenID' in data:
            # Single token ID - might be a simplified response
            metadata['clobTokenIds'] = [data['tokenID']]

        return Market(
            id=data.get("id", ""),
            question=data.get("question", ""),
            outcomes=outcomes,
            close_time=close_time,
            volume=volume,
            liquidity=liquidity,
            prices=prices,
            metadata=metadata
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
            import requests
            
            # Try simplified-markets endpoint
            # Response structure: {"data": [{"condition_id": ..., "tokens": [{"token_id": ..., "outcome": ...}]}]}
            try:
                response = requests.get(
                    f"{self.CLOB_URL}/simplified-markets",
                    timeout=self.timeout
                )
                
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
                                        print(f"✓ Found {len(token_ids)} token IDs via simplified-markets")
                                        for i, tid in enumerate(token_ids):
                                            outcome = tokens[i].get("outcome", f"outcome_{i}") if isinstance(tokens[i], dict) else f"outcome_{i}"
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
                    f"{self.CLOB_URL}/sampling-simplified-markets",
                    timeout=self.timeout
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
                                        print(f"✓ Found token IDs via sampling-simplified-markets: {len(token_ids)} tokens")
                                    return token_ids
            except Exception as e:
                if self.verbose:
                    print(f"sampling-simplified-markets failed: {e}")
            
            # Try markets endpoint
            try:
                response = requests.get(
                    f"{self.CLOB_URL}/markets",
                    timeout=self.timeout
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
                                        print(f"✓ Found token IDs via markets endpoint: {len(token_ids)} tokens")
                                    return token_ids
            except Exception as e:
                if self.verbose:
                    print(f"markets endpoint failed: {e}")
            
            raise ExchangeError(f"Could not fetch token IDs for market {condition_id} from any CLOB endpoint")
            
        except requests.RequestException as e:
            raise ExchangeError(f"Network error fetching token IDs: {e}")

    def create_order(
        self,
        market_id: str,
        outcome: str,
        side: OrderSide,
        price: float,
        size: float,
        params: Optional[Dict[str, Any]] = None
    ) -> Order:
        """Create order on Polymarket CLOB"""
        if not self._clob_client:
            raise ExchangeError("CLOB client not initialized. Private key required.")
        
        token_id = params.get('token_id') if params else None
        if not token_id:
            raise ExchangeError("token_id required in params")
        
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
                updated_at=datetime.now()
            )
            
        except Exception as e:
            raise ExchangeError(f"Order placement failed: {str(e)}")

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
        """
        Fetch current positions from Polymarket.

        Note: On Polymarket, positions are represented by conditional token balances.
        This method queries token balances for the specified market.
        Since positions require market-specific token data, we can't query positions
        without a market context. Returns empty list if no market_id is provided.
        """
        if not self._clob_client:
            raise ExchangeError("CLOB client not initialized. Private key required.")

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
            raise ExchangeError("CLOB client not initialized. Private key required.")

        try:
            positions = []
            token_ids_raw = market.metadata.get('clobTokenIds', [])

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
                        asset_type=AssetType.CONDITIONAL,
                        token_id=token_id
                    )
                    balance_data = self._clob_client.get_balance_allowance(params=params_obj)

                    if isinstance(balance_data, dict) and 'balance' in balance_data:
                        balance_raw = balance_data['balance']
                        # Convert from wei (6 decimals)
                        size = float(balance_raw) / 1e6 if balance_raw else 0.0

                        if size > 0:
                            # Determine outcome from market.outcomes
                            outcome = market.outcomes[i] if i < len(market.outcomes) else ('Yes' if i == 0 else 'No')

                            # Get current price from market.prices
                            current_price = market.prices.get(outcome, 0.0)

                            position = Position(
                                market_id=market.id,
                                outcome=outcome,
                                size=size,
                                average_price=0.0,  # Not available from balance query
                                current_price=current_price
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
        params: Optional[Dict[str, Any]] = None
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
        from datetime import datetime, timedelta
        from ..models import CryptoHourlyMarket
        from ..utils import setup_logger

        logger = setup_logger(__name__)

        # Use tag-based filtering for efficiency
        tag_id = (params or {}).get('tag_id', self.TAG_1H)

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
        import re

        # Pattern for "Up or Down" markets (e.g., "Bitcoin Up or Down - November 2, 7AM ET")
        up_down_pattern = re.compile(
            r'(?P<token>Bitcoin|Ethereum|Solana|BTC|ETH|SOL|XRP)\s+Up or Down',
            re.IGNORECASE
        )

        # Pattern for strike price markets (e.g., "Will BTC be above $95,000 at 5:00 PM ET?")
        strike_pattern = re.compile(
            r'(?:(?P<token1>BTC|ETH|SOL|BITCOIN|ETHEREUM|SOLANA)\s+.*?'
            r'(?P<direction>above|below|over|under|reach)\s+'
            r'[\$]?(?P<price1>[\d,]+(?:\.\d+)?))|'
            r'(?:[\$]?(?P<price2>[\d,]+(?:\.\d+)?)\s+.*?'
            r'(?P<token2>BTC|ETH|SOL|BITCOIN|ETHEREUM|SOLANA))',
            re.IGNORECASE
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
                    from datetime import timezone
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
                parsed_token = self.normalize_token(up_down_match.group('token'))

                # Apply token filter
                if token_symbol and parsed_token != self.normalize_token(token_symbol):
                    continue

                expiry = market.close_time if market.close_time else datetime.now() + timedelta(hours=1)

                crypto_market = CryptoHourlyMarket(
                    token_symbol=parsed_token,
                    expiry_time=expiry,
                    strike_price=None,
                    market_type="up_down"
                )

                return (market, crypto_market)

            # Try strike price pattern
            strike_match = strike_pattern.search(market.question)
            if strike_match:
                parsed_token = self.normalize_token(
                    strike_match.group('token1') or strike_match.group('token2') or ''
                )
                parsed_price_str = strike_match.group('price1') or strike_match.group('price2') or '0'
                parsed_price = float(parsed_price_str.replace(',', ''))

                # Apply filters
                if token_symbol and parsed_token != self.normalize_token(token_symbol):
                    continue

                expiry = market.close_time if market.close_time else datetime.now() + timedelta(hours=1)

                crypto_market = CryptoHourlyMarket(
                    token_symbol=parsed_token,
                    expiry_time=expiry,
                    strike_price=parsed_price,
                    market_type="strike_price"
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
            raise ExchangeError("CLOB client not initialized. Private key required.")

        try:
            # Fetch USDC (collateral) balance
            params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            balance_data = self._clob_client.get_balance_allowance(params=params)

            # Extract balance from response
            usdc_balance = 0.0
            if isinstance(balance_data, dict) and 'balance' in balance_data:
                try:
                    # Balance is returned as a string in wei (6 decimals for USDC)
                    usdc_balance = float(balance_data['balance']) / 1e6
                except (ValueError, TypeError):
                    usdc_balance = 0.0

            return {'USDC': usdc_balance}

        except Exception as e:
            raise ExchangeError(f"Failed to fetch balance: {str(e)}")

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
