"""Polymarket exchange implementation using Builder profile.

This module provides a Polymarket exchange that uses Builder profile
credentials (api_key, api_secret, passphrase) instead of private keys.

Security Benefits:
- No private key exposure to the server
- Users can revoke API credentials at any time from Polymarket
- Credentials are scoped to trading operations only
"""

from datetime import datetime
from typing import Any, Dict, Optional

from py_builder_signing_sdk.config import BuilderApiKeyCreds, BuilderConfig
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import AssetType, BalanceAllowanceParams, OrderArgs, OrderType

from ...base.errors import AuthenticationError, InvalidOrder
from ...models.order import Order, OrderSide, OrderStatus, OrderTimeInForce
from . import Polymarket


class PolymarketBuilder(Polymarket):
    """Polymarket exchange using Builder profile for authentication.

    This class extends Polymarket to use Builder API credentials instead of
    private keys. This is the recommended approach for remote/server deployments
    where storing private keys is undesirable.

    Config:
        api_key: Polymarket Builder API key
        api_secret: Polymarket Builder API secret
        api_passphrase: Polymarket Builder passphrase
        chain_id: Polygon chain ID (default: 137)

    Example:
        exchange = PolymarketBuilder({
            'api_key': 'your_api_key',
            'api_secret': 'your_api_secret',
            'api_passphrase': 'your_passphrase',
        })
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize Polymarket with Builder profile credentials."""
        # Don't call parent __init__ directly - it tries to use private_key
        # Instead, do minimal Exchange init and our own setup
        from ...base.exchange import Exchange

        Exchange.__init__(self, config)
        self._ws = None
        self._user_ws = None
        self.private_key = None
        self.funder = None
        self._clob_client = None
        self._address = None

        # Extract Builder credentials
        self._api_key = self.config.get("api_key")
        self._api_secret = self.config.get("api_secret")
        self._api_passphrase = self.config.get("api_passphrase")

        if not all([self._api_key, self._api_secret, self._api_passphrase]):
            raise AuthenticationError(
                "Builder profile requires api_key, api_secret, and api_passphrase"
            )

        self._initialize_builder_client()

    def _initialize_builder_client(self):
        """Initialize CLOB client with Builder profile credentials."""
        try:
            # Create Builder credentials
            builder_creds = BuilderApiKeyCreds(
                key=self._api_key,
                secret=self._api_secret,
                passphrase=self._api_passphrase,
            )

            # Create Builder config
            builder_config = BuilderConfig(local_builder_creds=builder_creds)

            if not builder_config.is_valid():
                raise AuthenticationError("Invalid Builder profile credentials")

            # Initialize CLOB client with Builder config
            chain_id = self.config.get("chain_id", 137)
            self._clob_client = ClobClient(
                host=self.CLOB_URL,
                chain_id=chain_id,
                builder_config=builder_config,
            )

            # Verify Builder auth is available
            if not self._clob_client.can_builder_auth():
                raise AuthenticationError("Builder authentication not available")

        except AuthenticationError:
            raise
        except Exception as e:
            raise AuthenticationError(f"Failed to initialize Builder client: {e}")

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
        """Create order on Polymarket CLOB using Builder profile."""
        if not self._clob_client:
            raise AuthenticationError("CLOB client not initialized.")

        if not self._clob_client.can_builder_auth():
            raise AuthenticationError("Builder authentication not available.")

        token_id = params.get("token_id") if params else None
        if not token_id:
            raise InvalidOrder("token_id required in params")

        # Map our OrderTimeInForce to py_clob_client OrderType
        order_type_map = {
            OrderTimeInForce.GTC: OrderType.GTC,
            OrderTimeInForce.FOK: OrderType.FOK,
            OrderTimeInForce.IOC: OrderType.GTD,
        }
        clob_order_type = order_type_map.get(time_in_force, OrderType.GTC)

        try:
            # Create and sign order using Builder
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
        """Cancel order on Polymarket using Builder profile."""
        if not self._clob_client:
            raise AuthenticationError("CLOB client not initialized.")

        if not self._clob_client.can_builder_auth():
            raise AuthenticationError("Builder authentication not available.")

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
        """Fetch account balance from Polymarket using Builder profile."""
        if not self._clob_client:
            raise AuthenticationError("CLOB client not initialized.")

        if not self._clob_client.can_builder_auth():
            raise AuthenticationError("Builder authentication not available.")

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
            raise AuthenticationError(f"Failed to fetch balance: {str(e)}")

    def fetch_open_orders(
        self, market_id: Optional[str] = None, params: Optional[Dict[str, Any]] = None
    ) -> list[Order]:
        """Fetch open orders using Builder profile."""
        if not self._clob_client:
            raise AuthenticationError("CLOB client not initialized.")

        if not self._clob_client.can_builder_auth():
            raise AuthenticationError("Builder authentication not available.")

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

            # Filter by market_id if provided
            if market_id:
                orders = [o for o in orders if o.get("market") == market_id]

            return [self._parse_order(order) for order in orders]
        except Exception as e:
            if self.verbose:
                print(f"Warning: Failed to fetch open orders: {e}")
            return []
