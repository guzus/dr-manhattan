from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Sequence

import pandas as pd
import requests
from py_clob_client.clob_types import AssetType, BalanceAllowanceParams, OrderArgs, OrderType

from ...base.errors import (
    AuthenticationError,
    ExchangeError,
    InvalidOrder,
    MarketNotFound,
)
from ...models.market import Market
from ...models.order import Order, OrderSide, OrderStatus, OrderTimeInForce
from ...models.position import Position
from .polymarket_core import PricePoint
from .polymarket_ws import PolymarketUserWebSocket, PolymarketWebSocket
from .polymarket_ws_ext import PolymarketRTDSWebSocket, PolymarketSportsWebSocket


class PolymarketCLOB:
    """CLOB API mixin: orderbook, orders, positions, balance, price history, websockets."""

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
            # Try simplified-markets endpoint
            # Response structure: {"data": [{"condition_id": ..., "tokens": [{"token_id": ..., "outcome": ...}]}]}
            try:
                response = requests.get(f"{self.CLOB_URL}/simplified-markets", timeout=self.timeout)

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
                                        print(
                                            f"✓ Found {len(token_ids)} token IDs via simplified-markets"
                                        )
                                        for i, tid in enumerate(token_ids):
                                            outcome = (
                                                tokens[i].get("outcome", f"outcome_{i}")
                                                if isinstance(tokens[i], dict)
                                                else f"outcome_{i}"
                                            )
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
                    f"{self.CLOB_URL}/sampling-simplified-markets", timeout=self.timeout
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
                                        print(
                                            f"✓ Found token IDs via sampling-simplified-markets: {len(token_ids)} tokens"
                                        )
                                    return token_ids
            except Exception as e:
                if self.verbose:
                    print(f"sampling-simplified-markets failed: {e}")

            # Try markets endpoint
            try:
                response = requests.get(f"{self.CLOB_URL}/markets", timeout=self.timeout)

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
                                        print(
                                            f"✓ Found token IDs via markets endpoint: {len(token_ids)} tokens"
                                        )
                                    return token_ids
            except Exception as e:
                if self.verbose:
                    print(f"markets endpoint failed: {e}")

            raise ExchangeError(
                f"Could not fetch token IDs for market {condition_id} from any CLOB endpoint"
            )

        except requests.RequestException as e:
            raise ExchangeError(f"Network error fetching token IDs: {e}")

    def get_orderbooks(self, token_ids: List[str]) -> List[Dict[str, Any]]:
        """
        Fetch multiple orderbooks at once.

        Args:
            token_ids: List of token IDs

        Returns:
            List of orderbook dictionaries with 'bids' and 'asks'
        """
        try:
            response = requests.get(
                f"{self.CLOB_URL}/books",
                params={"token_ids": ",".join(token_ids)},
                timeout=self.timeout,
            )
            if response.status_code == 200:
                return response.json()
            return []
        except Exception as e:
            if self.verbose:
                print(f"Failed to fetch orderbooks: {e}")
            return []

    def get_price(self, token_id: str) -> Dict[str, Any]:
        """
        Fetch price for a single token.

        Args:
            token_id: Token ID

        Returns:
            Price dictionary
        """
        try:
            response = requests.get(
                f"{self.CLOB_URL}/price",
                params={"token_id": token_id},
                timeout=self.timeout,
            )
            if response.status_code == 200:
                return response.json()
            return {}
        except Exception as e:
            if self.verbose:
                print(f"Failed to fetch price: {e}")
            return {}

    def get_prices(self, token_ids: List[str]) -> List[Dict[str, Any]]:
        """
        Fetch prices for multiple tokens.

        Args:
            token_ids: List of token IDs

        Returns:
            List of price dictionaries
        """
        try:
            response = requests.get(
                f"{self.CLOB_URL}/prices",
                params={"token_ids": ",".join(token_ids)},
                timeout=self.timeout,
            )
            if response.status_code == 200:
                return response.json()
            return []
        except Exception as e:
            if self.verbose:
                print(f"Failed to fetch prices: {e}")
            return []

    def get_midpoint(self, token_id: str) -> Dict[str, Any]:
        """
        Fetch midpoint price for a token.

        Args:
            token_id: Token ID

        Returns:
            Midpoint price dictionary
        """
        try:
            response = requests.get(
                f"{self.CLOB_URL}/midpoint",
                params={"token_id": token_id},
                timeout=self.timeout,
            )
            if response.status_code == 200:
                return response.json()
            return {}
        except Exception as e:
            if self.verbose:
                print(f"Failed to fetch midpoint: {e}")
            return {}

    def get_spreads(self, token_ids: List[str]) -> List[Dict[str, Any]]:
        """
        Fetch bid-ask spreads for tokens.

        Args:
            token_ids: List of token IDs

        Returns:
            List of spread dictionaries
        """
        try:
            response = requests.get(
                f"{self.CLOB_URL}/spreads",
                params={"token_ids": ",".join(token_ids)},
                timeout=self.timeout,
            )
            if response.status_code == 200:
                return response.json()
            return []
        except Exception as e:
            if self.verbose:
                print(f"Failed to fetch spreads: {e}")
            return []

    def get_orderbook(self, token_id: str) -> Dict[str, Any]:
        """
        Fetch orderbook for a specific token via REST API.

        Args:
            token_id: Token ID to fetch orderbook for

        Returns:
            Dictionary with 'bids' and 'asks' arrays
            Each entry: {'price': str, 'size': str}

        Example:
            >>> orderbook = exchange.get_orderbook(token_id)
            >>> best_bid = float(orderbook['bids'][0]['price'])
            >>> best_ask = float(orderbook['asks'][0]['price'])
        """
        try:
            response = requests.get(
                f"{self.CLOB_URL}/book", params={"token_id": token_id}, timeout=self.timeout
            )

            if response.status_code == 200:
                return response.json()

            return {"bids": [], "asks": []}

        except Exception as e:
            if self.verbose:
                print(f"Failed to fetch orderbook: {e}")
            return {"bids": [], "asks": []}

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
        """Create order on Polymarket CLOB"""
        if not self._clob_client:
            raise AuthenticationError("CLOB client not initialized. Private key required.")

        token_id = params.get("token_id") if params else None
        if not token_id:
            raise InvalidOrder("token_id required in params")

        # Map our OrderTimeInForce to py_clob_client OrderType
        order_type_map = {
            OrderTimeInForce.GTC: OrderType.GTC,
            OrderTimeInForce.FOK: OrderType.FOK,
            OrderTimeInForce.IOC: OrderType.GTD,  # py_clob_client uses GTD for IOC behavior
        }
        clob_order_type = order_type_map.get(time_in_force, OrderType.GTC)

        try:
            # Create and sign order
            order_args = OrderArgs(
                token_id=token_id,
                price=float(price),
                size=float(size),
                side=side.value.upper(),
            )

            signed_order = self._clob_client.create_order(order_args)
            result = self._clob_client.post_order(signed_order, clob_order_type)

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
                updated_at=datetime.now(),
                time_in_force=time_in_force,
            )

        except Exception as e:
            raise InvalidOrder(f"Order placement failed: {str(e)}")

    def cancel_order(self, order_id: str, market_id: Optional[str] = None) -> Order:
        """Cancel order on Polymarket"""
        if not self._clob_client:
            raise AuthenticationError("CLOB client not initialized. Private key required.")

        try:
            result = self._clob_client.cancel(order_id)
            if isinstance(result, dict):
                return self._parse_order(result)
            return Order(
                id=order_id,
                market_id=market_id or "",
                outcome="",
                side=OrderSide.BUY,
                price=0,
                size=0,
                filled=0,
                status=OrderStatus.CANCELLED,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
        except Exception as e:
            raise InvalidOrder(f"Failed to cancel order {order_id}: {str(e)}")

    def fetch_order(self, order_id: str, market_id: Optional[str] = None) -> Order:
        """Fetch order details"""
        data = self._request("GET", f"/orders/{order_id}")
        return self._parse_order(data)

    def fetch_open_orders(
        self, market_id: Optional[str] = None, params: Optional[Dict[str, Any]] = None
    ) -> list[Order]:
        """
        Fetch open orders using CLOB client

        Args:
            market_id: Can be either the numeric market ID or the hex conditionId.
                      If numeric, we filter by exact match. If hex (0x...), we use it directly.
        """
        if not self._clob_client:
            raise AuthenticationError("CLOB client not initialized. Private key required.")

        try:
            # Use CLOB client's get_orders method
            response = self._clob_client.get_orders()

            # Response is a list directly
            if isinstance(response, list):
                orders = response
            elif isinstance(response, dict) and "data" in response:
                orders = response["data"]
            else:
                if self.verbose:
                    print(f"Debug: Unexpected response format: {type(response)}")
                return []

            if not orders:
                return []

            # Filter by market_id if provided
            # Note: CLOB orders use hex conditionId (0x...) in the 'market' field
            if market_id:
                orders = [o for o in orders if o.get("market") == market_id]

            # Debug: Print first order's fields to identify size field
            if orders and self.verbose:
                debug_logger = logging.getLogger(__name__)
                debug_logger.debug(f"Sample order fields: {list(orders[0].keys())}")
                debug_logger.debug(f"Sample order data: {orders[0]}")

            # Parse orders
            return [self._parse_order(order) for order in orders]
        except Exception as e:
            if self.verbose:
                print(f"Warning: Failed to fetch open orders: {e}")
                traceback.print_exc()
            return []

    def fetch_positions(
        self, market_id: Optional[str] = None, params: Optional[Dict[str, Any]] = None
    ) -> list[Position]:
        """
        Fetch current positions from Polymarket.

        Note: On Polymarket, positions are represented by conditional token balances.
        This method queries token balances for the specified market.
        Since positions require market-specific token data, we can't query positions
        without a market context. Returns empty list if no market_id is provided.
        """
        if not self._clob_client:
            raise AuthenticationError("CLOB client not initialized. Private key required.")

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
            raise AuthenticationError("CLOB client not initialized. Private key required.")

        try:
            positions = []
            token_ids_raw = market.metadata.get("clobTokenIds", [])

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
                        asset_type=AssetType.CONDITIONAL, token_id=token_id
                    )
                    balance_data = self._clob_client.get_balance_allowance(params=params_obj)

                    if isinstance(balance_data, dict) and "balance" in balance_data:
                        balance_raw = balance_data["balance"]
                        # Convert from wei (6 decimals)
                        size = float(balance_raw) / 1e6 if balance_raw else 0.0

                        if size > 0:
                            # Determine outcome from market.outcomes
                            outcome = (
                                market.outcomes[i]
                                if i < len(market.outcomes)
                                else ("Yes" if i == 0 else "No")
                            )

                            # Get current price from market.prices
                            current_price = market.prices.get(outcome, 0.0)

                            position = Position(
                                market_id=market.id,
                                outcome=outcome,
                                size=size,
                                average_price=0.0,  # Not available from balance query
                                current_price=current_price,
                            )
                            positions.append(position)
                except Exception as e:
                    if self.verbose:
                        print(f"Failed to fetch balance for token {token_id}: {e}")
                    continue

            return positions

        except Exception as e:
            raise ExchangeError(f"Failed to fetch positions for market: {str(e)}")

    def fetch_balance(self) -> Dict[str, float]:
        """
        Fetch account balance from Polymarket using CLOB client

        Returns:
            Dictionary with balance information including USDC
        """
        if not self._clob_client:
            raise AuthenticationError("CLOB client not initialized. Private key required.")

        try:
            # Fetch USDC (collateral) balance
            params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            balance_data = self._clob_client.get_balance_allowance(params=params)

            # Extract balance from response
            usdc_balance = 0.0
            if isinstance(balance_data, dict) and "balance" in balance_data:
                try:
                    # Balance is returned as a string in wei (6 decimals for USDC)
                    usdc_balance = float(balance_data["balance"]) / 1e6
                except (ValueError, TypeError):
                    usdc_balance = 0.0

            return {"USDC": usdc_balance}

        except Exception as e:
            raise ExchangeError(f"Failed to fetch balance: {str(e)}")

    def fetch_price_history(
        self,
        market: Market | str,
        *,
        outcome: int | str | None = None,
        interval: Literal["1m", "1h", "6h", "1d", "1w", "max"] = "1m",
        fidelity: int = 10,
        as_dataframe: bool = False,
    ) -> List[PricePoint] | pd.DataFrame:
        if interval not in self.SUPPORTED_INTERVALS:
            raise ValueError(
                f"Unsupported interval '{interval}'. Pick from {self.SUPPORTED_INTERVALS}."
            )

        market_obj = self._ensure_market(market)
        token_id = self._lookup_token_id(market_obj, outcome)

        params = {
            "market": token_id,
            "interval": interval,
            "fidelity": fidelity,
        }

        @self._retry_on_failure
        def _fetch() -> List[Dict[str, Any]]:
            resp = requests.get(self.PRICES_HISTORY_URL, params=params, timeout=self.timeout)
            resp.raise_for_status()
            payload = resp.json()
            history = payload.get("history", [])
            if not isinstance(history, list):
                raise ExchangeError("Invalid response: 'history' must be a list.")
            return history

        history = _fetch()
        points = self._parse_history(history)

        if as_dataframe:
            data = {
                "timestamp": [p.timestamp for p in points],
                "price": [p.price for p in points],
            }
            return pd.DataFrame(data).sort_values("timestamp").reset_index(drop=True)

        return points

    def _parse_order(self, data: Dict[str, Any]) -> Order:
        """Parse order data from API response"""
        order_id = data.get("id") or data.get("orderID") or ""

        # Try multiple field names for size (CLOB API may use different names)
        size = float(
            data.get("size")
            or data.get("original_size")
            or data.get("amount")
            or data.get("original_amount")
            or 0
        )
        filled = float(data.get("filled") or data.get("matched") or data.get("matched_amount") or 0)

        return Order(
            id=order_id,
            market_id=data.get("market_id", ""),
            outcome=data.get("outcome", ""),
            side=OrderSide(data.get("side", "buy").lower()),
            price=float(data.get("price", 0)),
            size=size,
            filled=filled,
            status=self._parse_order_status(data.get("status")),
            created_at=self._parse_datetime(data.get("created_at")),
            updated_at=self._parse_datetime(data.get("updated_at")),
        )

    def _parse_position(self, data: Dict[str, Any]) -> Position:
        """Parse position data from API response"""
        return Position(
            market_id=data.get("market_id", ""),
            outcome=data.get("outcome", ""),
            size=float(data.get("size", 0)),
            average_price=float(data.get("average_price", 0)),
            current_price=float(data.get("current_price", 0)),
        )

    def _parse_order_status(self, status: str) -> OrderStatus:
        """Convert string status to OrderStatus enum"""
        status_map = {
            "pending": OrderStatus.PENDING,
            "open": OrderStatus.OPEN,
            "filled": OrderStatus.FILLED,
            "partially_filled": OrderStatus.PARTIALLY_FILLED,
            "cancelled": OrderStatus.CANCELLED,
            "rejected": OrderStatus.REJECTED,
        }
        return status_map.get(status, OrderStatus.OPEN)

    @staticmethod
    def _extract_token_ids(market: Market) -> List[str]:
        raw_ids = market.metadata.get("clobTokenIds", [])
        if isinstance(raw_ids, str):
            try:
                raw_ids = json.loads(raw_ids)
            except json.JSONDecodeError:
                raw_ids = [raw_ids]
        return [str(token_id) for token_id in raw_ids if token_id]

    def _lookup_token_id(self, market: Market, outcome: int | str | None) -> str:
        token_ids = self._extract_token_ids(market)
        if not token_ids:
            raise ExchangeError("Cannot fetch price history without token IDs in metadata.")

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

    def get_websocket(self) -> PolymarketWebSocket:
        """
        Get WebSocket instance for real-time orderbook updates.

        The WebSocket automatically updates the exchange's mid-price cache
        when orderbook data is received.

        Returns:
            PolymarketWebSocket instance

        Example:
            ws = exchange.get_websocket()
            await ws.watch_orderbook(asset_id, callback)
            ws.start()
        """
        if self._ws is None:
            self._ws = PolymarketWebSocket(
                config={"verbose": self.verbose, "auto_reconnect": True}, exchange=self
            )
        return self._ws

    def get_user_websocket(self) -> PolymarketUserWebSocket:
        """
        Get User WebSocket instance for real-time trade/fill notifications.

        Requires CLOB client to be initialized (private key required).

        Returns:
            PolymarketUserWebSocket instance

        Example:
            user_ws = exchange.get_user_websocket()
            user_ws.on_trade(lambda trade: print(f"Fill: {trade.size} @ {trade.price}"))
            user_ws.start()
        """
        if not self._clob_client:
            raise AuthenticationError(
                "CLOB client not initialized. Private key required for user WebSocket."
            )

        if self._user_ws is None:
            # Get API credentials from CLOB client
            creds = self._clob_client.creds
            if not creds:
                raise AuthenticationError("API credentials not available")

            self._user_ws = PolymarketUserWebSocket(
                api_key=creds.api_key,
                api_secret=creds.api_secret,
                api_passphrase=creds.api_passphrase,
                verbose=self.verbose,
            )
        return self._user_ws

    def get_sports_websocket(self) -> PolymarketSportsWebSocket:
        """
        Get a Sports WebSocket instance for real-time sports market updates.

        Returns:
            PolymarketSportsWebSocket instance
        """
        return PolymarketSportsWebSocket(verbose=self.verbose)

    def get_rtds_websocket(self) -> PolymarketRTDSWebSocket:
        """
        Get a Real-Time Data Stream WebSocket for crypto prices and comments.

        Returns:
            PolymarketRTDSWebSocket instance
        """
        return PolymarketRTDSWebSocket(verbose=self.verbose)
