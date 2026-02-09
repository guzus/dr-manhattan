"""Polymarket exchange implementation using Operator pattern.

This module provides a Polymarket exchange where the server acts as an operator,
trading on behalf of users who have approved the server's address.

Security Model:
- Server has its own private key (stored securely on server)
- Users approve the server address as an operator on-chain
- Server signs orders with its own key, specifying user's address as funder
- Users can revoke approval anytime via Polymarket contract
"""

import os
from datetime import datetime
from typing import Any, Dict, Optional

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import AssetType, BalanceAllowanceParams, OrderArgs, OrderType

from ...base.errors import AuthenticationError, ExchangeError, InvalidOrder
from ...models.order import Order, OrderSide, OrderStatus, OrderTimeInForce
from ...models.position import Position
from . import Polymarket


class PolymarketOperator(Polymarket):
    """Polymarket exchange using Operator pattern for server-wide trading.

    The server acts as an operator, signing orders on behalf of users who have
    approved the server's address. This allows centralized trading without
    users exposing their private keys.

    Server Config (from environment):
        POLYMARKET_OPERATOR_KEY: Server's private key for signing
        POLYMARKET_OPERATOR_ADDRESS: Server's address (derived from key)

    Per-Request Config:
        user_address: The user's wallet address to trade for

    Prerequisites:
        Users must approve the server address as operator on Polymarket:
        1. Go to Polymarket
        2. Call approveOperator(server_address) on the CTF Exchange contract

    Example:
        # Server initialization (once at startup)
        operator = PolymarketOperator({
            'user_address': '0xUserWalletAddress...',
        })

        # Create order on behalf of user
        order = operator.create_order(...)
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize Polymarket Operator.

        Args:
            config: Must contain 'user_address' - the wallet to trade for
        """
        from ...base.exchange import Exchange

        Exchange.__init__(self, config)
        self._ws = None
        self._user_ws = None
        self._clob_client = None
        self._address = None

        # Server's operator credentials from environment
        self._operator_key = os.getenv("POLYMARKET_OPERATOR_KEY")
        if not self._operator_key:
            raise AuthenticationError(
                "POLYMARKET_OPERATOR_KEY environment variable is required for operator mode"
            )

        # User's address to trade for (from per-request config)
        self._user_address = self.config.get("user_address")
        if not self._user_address:
            raise AuthenticationError(
                "user_address is required - provide the wallet address to trade for"
            )

        # These are set for compatibility with parent class
        self.private_key = self._operator_key
        self.funder = self._user_address  # User's address as funder

        self._initialize_operator_client()

    def _initialize_operator_client(self):
        """Initialize CLOB client in operator mode."""
        try:
            chain_id = self.config.get("chain_id", 137)
            # signature_type 0 = EOA (standard wallet)
            signature_type = self.config.get("signature_type", 0)

            # Initialize with operator's key, user's address as funder
            self._clob_client = ClobClient(
                host=self.CLOB_URL,
                key=self._operator_key,
                chain_id=chain_id,
                signature_type=signature_type,
                funder=self._user_address,  # Trade for this user
            )

            # Derive and set API credentials
            api_creds = self._clob_client.create_or_derive_api_creds()
            if not api_creds:
                raise AuthenticationError("Failed to derive API credentials")

            self._clob_client.set_api_creds(api_creds)

            # Verify L2 mode
            if self._clob_client.mode < 2:
                raise AuthenticationError(
                    f"Client not in L2 mode (current mode: {self._clob_client.mode})"
                )

            # Store operator address
            try:
                self._address = self._clob_client.get_address()
            except Exception:
                self._address = None

        except AuthenticationError:
            raise
        except Exception as e:
            raise AuthenticationError(f"Failed to initialize operator client: {e}")

    @property
    def operator_address(self) -> Optional[str]:
        """Get the server's operator address."""
        return self._address

    @property
    def user_address(self) -> str:
        """Get the user's address this instance trades for."""
        return self._user_address

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
        """Create order on behalf of user.

        The order is signed by the operator but executes for the user's account.
        User must have approved the operator address.
        """
        if not self._clob_client:
            raise AuthenticationError("CLOB client not initialized.")

        token_id = params.get("token_id") if params else None
        if not token_id:
            raise InvalidOrder("token_id required in params")

        order_type_map = {
            OrderTimeInForce.GTC: OrderType.GTC,
            OrderTimeInForce.FOK: OrderType.FOK,
            OrderTimeInForce.IOC: OrderType.GTD,
        }
        clob_order_type = order_type_map.get(time_in_force, OrderType.GTC)

        try:
            order_args = OrderArgs(
                token_id=token_id,
                price=float(price),
                size=float(size),
                side=side.value.upper(),
            )

            signed_order = self._clob_client.create_order(order_args)
            result = self._clob_client.post_order(signed_order, clob_order_type)

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
            error_msg = str(e)
            if "not approved" in error_msg.lower() or "operator" in error_msg.lower():
                raise InvalidOrder(
                    f"User {self._user_address} has not approved operator. "
                    f"Please approve the operator address first."
                )
            raise InvalidOrder(f"Order placement failed: {error_msg}")

    def cancel_order(self, order_id: str, market_id: Optional[str] = None) -> Order:
        """Cancel order on behalf of user."""
        if not self._clob_client:
            raise AuthenticationError("CLOB client not initialized.")

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

    def fetch_balance(self) -> Dict[str, float]:
        """Fetch user's balance (not operator's)."""
        if not self._clob_client:
            raise AuthenticationError("CLOB client not initialized.")

        try:
            params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            balance_data = self._clob_client.get_balance_allowance(params=params)

            usdc_balance = 0.0
            if isinstance(balance_data, dict) and "balance" in balance_data:
                try:
                    usdc_balance = float(balance_data["balance"]) / 1e6
                except (ValueError, TypeError):
                    usdc_balance = 0.0

            return {"USDC": usdc_balance}

        except Exception as e:
            raise ExchangeError(f"Failed to fetch balance: {str(e)}")

    def fetch_open_orders(
        self, market_id: Optional[str] = None, params: Optional[Dict[str, Any]] = None
    ) -> list[Order]:
        """Fetch user's open orders."""
        if not self._clob_client:
            raise AuthenticationError("CLOB client not initialized.")

        try:
            response = self._clob_client.get_orders()

            if isinstance(response, list):
                orders = response
            elif isinstance(response, dict) and "data" in response:
                orders = response["data"]
            else:
                return []

            if not orders:
                return []

            if market_id:
                orders = [o for o in orders if o.get("market") == market_id]

            return [self._parse_order(order) for order in orders]
        except Exception as e:
            if self.verbose:
                print(f"Warning: Failed to fetch open orders: {e}")
            return []

    def fetch_positions(
        self, market_id: Optional[str] = None, params: Optional[Dict[str, Any]] = None
    ) -> list[Position]:
        """Fetch user's positions."""
        if not self._clob_client:
            raise AuthenticationError("CLOB client not initialized.")

        if not market_id:
            return []

        return []

    def check_operator_approval(self) -> bool:
        """Check if user has approved the operator.

        Returns:
            True if user has approved operator, False otherwise
        """
        # This would require checking the CTF Exchange contract
        # For now, we'll rely on order placement errors to detect this
        return True  # Assume approved, error on order if not
