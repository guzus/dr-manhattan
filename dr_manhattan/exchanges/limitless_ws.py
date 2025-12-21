"""
Limitless WebSocket implementation for real-time market data.

Uses Socket.IO for communication with the Limitless WebSocket API.
Documentation: https://api.limitless.exchange/api-v1
"""

import asyncio
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

import socketio

from ..models.orderbook import OrderbookManager

logger = logging.getLogger(__name__)


class WebSocketState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    CLOSED = "closed"


@dataclass
class OrderbookUpdate:
    """Represents an orderbook update from WebSocket"""

    slug: str
    bids: List[tuple]  # [(price, size), ...]
    asks: List[tuple]  # [(price, size), ...]
    timestamp: datetime


@dataclass
class PriceUpdate:
    """Represents a price update from WebSocket (AMM markets)"""

    market_address: str
    yes_price: float
    no_price: float
    block_number: int
    timestamp: datetime


@dataclass
class PositionUpdate:
    """Represents a position update from WebSocket"""

    account: str
    market_address: str
    token_id: str
    balance: float
    outcome_index: int
    market_type: str  # "AMM" or "CLOB"


@dataclass
class Trade:
    """Represents a trade/fill event (compatible with Polymarket Trade)"""

    id: str
    order_id: str
    market_id: str
    asset_id: str
    side: str
    price: float
    size: float
    fee: float
    timestamp: datetime
    outcome: str = ""
    taker: str = ""
    maker: str = ""
    transaction_hash: str = ""


TradeCallback = Callable[["Trade"], None]


class LimitlessWebSocket:
    """
    Limitless WebSocket client for real-time market data.

    Supports:
    - Price updates (AMM markets)
    - Orderbook updates (CLOB markets)
    - Position updates (authenticated)

    Usage:
        ws = LimitlessWebSocket()
        ws.on_orderbook(callback)
        ws.subscribe_market("market-slug")
        ws.start()
    """

    WS_URL = "wss://ws.limitless.exchange"
    NAMESPACE = "/markets"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.verbose = self.config.get("verbose", False)
        self.session_cookie = self.config.get("session_cookie")

        # Socket.IO client
        self.sio = socketio.AsyncClient(
            reconnection=True,
            reconnection_attempts=0,  # Infinite
            reconnection_delay=1,
            reconnection_delay_max=30,
            logger=False,
            engineio_logger=False,
        )

        # State
        self.state = WebSocketState.DISCONNECTED
        self._subscribed_slugs: List[str] = []
        self._subscribed_addresses: List[str] = []

        # Callbacks
        self._orderbook_callbacks: List[Callable[[OrderbookUpdate], None]] = []
        self._price_callbacks: List[Callable[[PriceUpdate], None]] = []
        self._position_callbacks: List[Callable[[PositionUpdate], None]] = []
        self._error_callbacks: List[Callable[[str], None]] = []

        # Event loop (public for compatibility with exchange_client)
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()  # Signals when connection is ready

        # Orderbook manager for compatibility with exchange_client
        self.orderbook_manager = OrderbookManager()

        # Token ID to slug mapping for watch_orderbook_by_market
        self._token_to_slug: Dict[str, str] = {}

        # Register event handlers
        self._setup_handlers()

    def _setup_handlers(self):
        """Setup Socket.IO event handlers"""

        @self.sio.on("connect", namespace=self.NAMESPACE)
        async def on_connect():
            self.state = WebSocketState.CONNECTED
            if self.verbose:
                logger.info("Connected to Limitless WebSocket")

            # Resubscribe after reconnection
            await self._resubscribe()

        @self.sio.on("disconnect", namespace=self.NAMESPACE)
        async def on_disconnect():
            self.state = WebSocketState.DISCONNECTED
            if self.verbose:
                logger.info("Disconnected from Limitless WebSocket")

        @self.sio.on("orderbookUpdate", namespace=self.NAMESPACE)
        async def on_orderbook_update(data):
            try:
                update = self._parse_orderbook_update(data)
                if update:
                    for callback in self._orderbook_callbacks:
                        try:
                            if asyncio.iscoroutinefunction(callback):
                                await callback(update)
                            else:
                                callback(update)
                        except Exception as e:
                            if self.verbose:
                                logger.error(f"Orderbook callback error: {e}")
            except Exception as e:
                if self.verbose:
                    logger.error(f"Error parsing orderbook update: {e}")

        @self.sio.on("newPriceData", namespace=self.NAMESPACE)
        async def on_price_update(data):
            try:
                update = self._parse_price_update(data)
                if update:
                    for callback in self._price_callbacks:
                        try:
                            if asyncio.iscoroutinefunction(callback):
                                await callback(update)
                            else:
                                callback(update)
                        except Exception as e:
                            if self.verbose:
                                logger.error(f"Price callback error: {e}")
            except Exception as e:
                if self.verbose:
                    logger.error(f"Error parsing price update: {e}")

        @self.sio.on("positions", namespace=self.NAMESPACE)
        async def on_position_update(data):
            try:
                updates = self._parse_position_updates(data)
                for update in updates:
                    for callback in self._position_callbacks:
                        try:
                            if asyncio.iscoroutinefunction(callback):
                                await callback(update)
                            else:
                                callback(update)
                        except Exception as e:
                            if self.verbose:
                                logger.error(f"Position callback error: {e}")
            except Exception as e:
                if self.verbose:
                    logger.error(f"Error parsing position update: {e}")

        @self.sio.on("authenticated", namespace=self.NAMESPACE)
        async def on_authenticated(data):
            if self.verbose:
                logger.info("Authenticated with Limitless WebSocket")

        @self.sio.on("exception", namespace=self.NAMESPACE)
        async def on_exception(data):
            error_msg = str(data)
            if self.verbose:
                logger.error(f"WebSocket exception: {error_msg}")
            for callback in self._error_callbacks:
                try:
                    callback(error_msg)
                except Exception:
                    pass

        @self.sio.on("system", namespace=self.NAMESPACE)
        async def on_system(data):
            if self.verbose:
                logger.debug(f"System message: {data}")

    def _parse_orderbook_update(self, data: Dict[str, Any]) -> Optional[OrderbookUpdate]:
        """Parse orderbook update from WebSocket"""
        try:
            market_slug = data.get("marketSlug", data.get("slug", ""))
            if not market_slug:
                return None

            # Handle nested orderbook structure
            orderbook_data = data.get("orderbook", data)

            # Parse bids
            bids = []
            for bid in orderbook_data.get("bids", []):
                try:
                    price = float(bid.get("price", 0))
                    size = float(bid.get("size", 0))
                    if price > 0:
                        bids.append((price, size))
                except (ValueError, TypeError):
                    continue

            # Parse asks
            asks = []
            for ask in orderbook_data.get("asks", []):
                try:
                    price = float(ask.get("price", 0))
                    size = float(ask.get("size", 0))
                    if price > 0:
                        asks.append((price, size))
                except (ValueError, TypeError):
                    continue

            # Sort bids descending, asks ascending
            bids.sort(reverse=True)
            asks.sort()

            # Parse timestamp
            ts = data.get("timestamp")
            if isinstance(ts, str):
                timestamp = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            elif isinstance(ts, (int, float)):
                timestamp = datetime.fromtimestamp(ts / 1000 if ts > 1e12 else ts, tz=timezone.utc)
            else:
                timestamp = datetime.now(timezone.utc)

            return OrderbookUpdate(
                slug=market_slug,
                bids=bids,
                asks=asks,
                timestamp=timestamp,
            )
        except Exception as e:
            if self.verbose:
                logger.error(f"Error parsing orderbook: {e}")
            return None

    def _parse_price_update(self, data: Dict[str, Any]) -> Optional[PriceUpdate]:
        """Parse price update from WebSocket (AMM markets)"""
        try:
            market_address = data.get("marketAddress", "")
            if not market_address:
                return None

            prices = data.get("updatedPrices", {})
            yes_price = float(prices.get("yes", 0))
            no_price = float(prices.get("no", 0))

            block_number = int(data.get("blockNumber", 0))

            ts = data.get("timestamp")
            if isinstance(ts, str):
                timestamp = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            else:
                timestamp = datetime.now(timezone.utc)

            return PriceUpdate(
                market_address=market_address,
                yes_price=yes_price,
                no_price=no_price,
                block_number=block_number,
                timestamp=timestamp,
            )
        except Exception as e:
            if self.verbose:
                logger.error(f"Error parsing price update: {e}")
            return None

    def _parse_position_updates(self, data: Dict[str, Any]) -> List[PositionUpdate]:
        """Parse position updates from WebSocket"""
        updates = []
        try:
            account = data.get("account", "")
            market_address = data.get("marketAddress", "")
            market_type = data.get("type", "CLOB")

            for pos in data.get("positions", []):
                try:
                    updates.append(
                        PositionUpdate(
                            account=account,
                            market_address=market_address,
                            token_id=str(pos.get("tokenId", "")),
                            balance=float(pos.get("balance", 0)),
                            outcome_index=int(pos.get("outcomeIndex", 0)),
                            market_type=market_type,
                        )
                    )
                except (ValueError, TypeError):
                    continue
        except Exception as e:
            if self.verbose:
                logger.error(f"Error parsing position updates: {e}")
        return updates

    async def _resubscribe(self):
        """Resubscribe to markets after reconnection"""
        if self._subscribed_slugs or self._subscribed_addresses:
            await self._send_subscription()

    async def _send_subscription(self):
        """Send subscription message to server"""
        payload = {}
        if self._subscribed_addresses:
            payload["marketAddresses"] = self._subscribed_addresses
        if self._subscribed_slugs:
            payload["marketSlugs"] = self._subscribed_slugs

        if payload:
            await self.sio.emit("subscribe_market_prices", payload, namespace=self.NAMESPACE)
            if self.verbose:
                logger.debug(f"Subscribed to markets: {payload}")

    async def connect(self):
        """Connect to Limitless WebSocket"""
        if self.state == WebSocketState.CONNECTED:
            return

        self.state = WebSocketState.CONNECTING

        headers = {}
        if self.session_cookie:
            headers["Cookie"] = f"limitless_session={self.session_cookie}"

        try:
            await self.sio.connect(
                self.WS_URL,
                namespaces=[self.NAMESPACE],
                transports=["websocket"],
                headers=headers,
            )
            self._ready.set()  # Signal that connection is ready
        except Exception as e:
            self.state = WebSocketState.DISCONNECTED
            raise ConnectionError(f"Failed to connect to Limitless WebSocket: {e}")

    async def disconnect(self):
        """Disconnect from Limitless WebSocket"""
        self.state = WebSocketState.CLOSED
        if self.sio.connected:
            await self.sio.disconnect()

    async def close(self):
        """Alias for disconnect"""
        await self.disconnect()

    async def _receive_loop(self):
        """Wait for Socket.IO events (Socket.IO handles receiving internally)"""
        while self.state == WebSocketState.CONNECTED and self.sio.connected:
            await asyncio.sleep(0.1)

    async def subscribe_market(self, market_slug: str):
        """
        Subscribe to orderbook updates for a CLOB market.

        Args:
            market_slug: Market slug (e.g., "btc-above-100k")
        """
        if market_slug not in self._subscribed_slugs:
            self._subscribed_slugs.append(market_slug)

        if self.state == WebSocketState.CONNECTED:
            await self._send_subscription()

    async def subscribe_market_address(self, market_address: str):
        """
        Subscribe to price updates for an AMM market.

        Args:
            market_address: Market contract address
        """
        if market_address not in self._subscribed_addresses:
            self._subscribed_addresses.append(market_address)

        if self.state == WebSocketState.CONNECTED:
            await self._send_subscription()

    async def unsubscribe_market(self, market_slug: str):
        """Unsubscribe from a CLOB market"""
        if market_slug in self._subscribed_slugs:
            self._subscribed_slugs.remove(market_slug)

        if self.state == WebSocketState.CONNECTED:
            await self._send_subscription()

    async def unsubscribe_market_address(self, market_address: str):
        """Unsubscribe from an AMM market"""
        if market_address in self._subscribed_addresses:
            self._subscribed_addresses.remove(market_address)

        if self.state == WebSocketState.CONNECTED:
            await self._send_subscription()

    def on_orderbook(self, callback: Callable[[OrderbookUpdate], None]) -> "LimitlessWebSocket":
        """Register callback for orderbook updates"""
        self._orderbook_callbacks.append(callback)
        return self

    def on_price(self, callback: Callable[[PriceUpdate], None]) -> "LimitlessWebSocket":
        """Register callback for price updates (AMM)"""
        self._price_callbacks.append(callback)
        return self

    def on_position(self, callback: Callable[[PositionUpdate], None]) -> "LimitlessWebSocket":
        """Register callback for position updates"""
        self._position_callbacks.append(callback)
        return self

    def on_error(self, callback: Callable[[str], None]) -> "LimitlessWebSocket":
        """Register callback for errors"""
        self._error_callbacks.append(callback)
        return self

    def start(self, timeout: float = 5.0) -> threading.Thread:
        """
        Start WebSocket connection in background thread.

        Args:
            timeout: Seconds to wait for connection to establish

        Returns:
            Background thread running the WebSocket

        Raises:
            ConnectionError: If connection is not established within timeout
        """
        self.loop = asyncio.new_event_loop()
        self._ready.clear()

        async def _run():
            await self.connect()
            # Keep running until disconnected
            while self.state != WebSocketState.CLOSED:
                await asyncio.sleep(1)

        def _thread_target():
            asyncio.set_event_loop(self.loop)
            try:
                self.loop.run_until_complete(_run())
            except Exception as e:
                if self.verbose:
                    logger.error(f"WebSocket thread error: {e}")
            finally:
                self.loop.close()

        self._thread = threading.Thread(target=_thread_target, daemon=True)
        self._thread.start()

        # Wait for connection to be ready
        if not self._ready.wait(timeout=timeout):
            raise ConnectionError(f"WebSocket connection not established within {timeout}s")

        return self._thread

    def get_orderbook_manager(self) -> OrderbookManager:
        """
        Get the orderbook manager for compatibility with exchange_client.

        Returns:
            OrderbookManager instance
        """
        return self.orderbook_manager

    async def watch_orderbook_by_market(
        self, market_id: str, asset_ids: List[str], callback: Optional[Callable] = None
    ):
        """
        Subscribe to orderbook updates for a market.

        Compatible with Polymarket's watch_orderbook_by_market interface.

        Args:
            market_id: Market slug
            asset_ids: List of token IDs (used for orderbook_manager keys)
            callback: Optional function to call with orderbook updates
        """
        # Store token_id -> slug mapping
        for asset_id in asset_ids:
            self._token_to_slug[asset_id] = market_id

        # Limitless: first token is Yes, second is No
        yes_token = asset_ids[0] if asset_ids else None
        no_token = asset_ids[1] if len(asset_ids) > 1 else None

        # Create callback that updates orderbook_manager
        def on_orderbook_update(update: OrderbookUpdate):
            ts = int(update.timestamp.timestamp() * 1000)

            # Yes token gets original orderbook
            if yes_token:
                yes_orderbook = {
                    "bids": update.bids,
                    "asks": update.asks,
                    "timestamp": ts,
                    "market_id": update.slug,
                }
                self.orderbook_manager.update(yes_token, yes_orderbook)

            # No token gets inverted orderbook
            # No bids = 1 - Yes asks, No asks = 1 - Yes bids
            if no_token:
                no_bids = [(round(1 - price, 3), size) for price, size in update.asks]
                no_asks = [(round(1 - price, 3), size) for price, size in update.bids]
                # Re-sort after inversion
                no_bids.sort(reverse=True)
                no_asks.sort()
                no_orderbook = {
                    "bids": no_bids,
                    "asks": no_asks,
                    "timestamp": ts,
                    "market_id": update.slug,
                }
                self.orderbook_manager.update(no_token, no_orderbook)

            if callback:
                callback(market_id, {"bids": update.bids, "asks": update.asks})

        self.on_orderbook(on_orderbook_update)
        await self.subscribe_market(market_id)

    def stop(self, timeout: float = 5.0):
        """
        Stop WebSocket connection and wait for cleanup.

        Args:
            timeout: Seconds to wait for disconnect and thread cleanup
        """
        if self.loop and self.sio.connected:
            future = asyncio.run_coroutine_threadsafe(self.disconnect(), self.loop)
            try:
                future.result(timeout=timeout)
            except Exception:
                pass  # Ignore timeout/errors during shutdown

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    @property
    def connected(self) -> bool:
        """Check if connected"""
        return self.state == WebSocketState.CONNECTED and self.sio.connected


class LimitlessUserWebSocket(LimitlessWebSocket):
    """
    Authenticated Limitless WebSocket for user-specific updates.

    Extends LimitlessWebSocket with position tracking for authenticated users.
    """

    def __init__(self, session_cookie: str, config: Optional[Dict[str, Any]] = None):
        """
        Initialize authenticated WebSocket.

        Args:
            session_cookie: Session cookie from authentication
            config: Additional configuration
        """
        config = config or {}
        config["session_cookie"] = session_cookie
        super().__init__(config)

        # Trade callbacks for compatibility with exchange_client
        self._trade_callbacks: List[TradeCallback] = []

    def on_trade(self, callback: TradeCallback) -> "LimitlessUserWebSocket":
        """
        Register callback for trade/fill events.

        Compatible with Polymarket's on_trade interface.

        Args:
            callback: Function to call with Trade object on fills

        Returns:
            Self for chaining
        """
        self._trade_callbacks.append(callback)
        return self

    def _emit_trade(self, trade: Trade):
        """Emit trade to all callbacks."""
        for callback in self._trade_callbacks:
            try:
                callback(trade)
            except Exception as e:
                if self.verbose:
                    logger.warning(f"Trade callback error: {e}")

    async def subscribe_positions(self, market_addresses: Optional[List[str]] = None):
        """
        Subscribe to position updates.

        Args:
            market_addresses: Optional list of market addresses to filter
        """
        payload = {}
        if market_addresses:
            payload["marketAddresses"] = market_addresses

        await self.sio.emit("subscribe_positions", payload, namespace=self.NAMESPACE)
        if self.verbose:
            logger.debug(f"Subscribed to position updates: {payload}")
