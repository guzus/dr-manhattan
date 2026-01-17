"""
Predict.fun WebSocket implementation for real-time market data.

Uses raw WebSocket for communication with the Predict.fun WebSocket API.
Documentation: https://dev.predict.fun/

WebSocket Features:
- Orderbook updates: predictOrderbook/{marketId}
- Asset price updates: assetPriceUpdate/{priceFeedId}
- Wallet events: predictWalletEvents/{jwt} (authenticated)
"""

import asyncio
import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

import websockets
import websockets.exceptions

from ..base.websocket import OrderBookWebSocket, WebSocketState
from ..models.orderbook import OrderbookManager

logger = logging.getLogger(__name__)


class WalletEventType(Enum):
    """Wallet event types from user WebSocket"""

    ORDER_ACCEPTED = "orderAccepted"
    ORDER_NOT_ACCEPTED = "orderNotAccepted"
    ORDER_EXPIRED = "orderExpired"
    ORDER_CANCELLED = "orderCancelled"
    ORDER_TRANSACTION_SUBMITTED = "orderTransactionSubmitted"
    ORDER_TRANSACTION_SUCCESS = "orderTransactionSuccess"
    ORDER_TRANSACTION_FAILED = "orderTransactionFailed"


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
    event_type: str = ""


@dataclass
class WalletEvent:
    """Represents a wallet event from Predict.fun WebSocket"""

    event_type: WalletEventType
    order_id: str
    market_id: str
    data: Dict[str, Any]
    timestamp: datetime


TradeCallback = Callable[["Trade"], None]


class PredictFunWebSocket(OrderBookWebSocket):
    """
    Predict.fun WebSocket client for real-time orderbook updates.

    Connects to the public orderbook channel which provides:
    - Live orderbook updates for markets
    - Asset price updates

    Usage:
        ws = PredictFunWebSocket()
        await ws.watch_orderbook_by_market(market_id, token_ids)
        ws.start()
    """

    WS_URL = "wss://ws.predict.fun/ws"
    HEARTBEAT_INTERVAL = 15.0

    def __init__(self, config: Optional[Dict[str, Any]] = None, exchange=None):
        super().__init__(config)

        # Reference to parent exchange for updating mid-price cache
        self.exchange = exchange

        # API key for authentication (optional for public channels)
        self.api_key = self.config.get("api_key", "")

        # Request ID counter for tracking responses
        self._request_id = 0

        # Track subscribed markets
        self._subscribed_markets: Dict[str, str] = {}  # market_id -> topic

        # Market ID to token IDs mapping
        self._market_to_tokens: Dict[str, List[str]] = {}

        # Token ID to market ID mapping
        self._token_to_market: Dict[str, str] = {}

        # Orderbook manager
        self.orderbook_manager = OrderbookManager()

        # Heartbeat task
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._last_heartbeat_ts: int = 0

        # Pending requests (for response tracking)
        self._pending_requests: Dict[int, asyncio.Future] = {}

    @property
    def ws_url(self) -> str:
        """WebSocket endpoint URL"""
        if self.api_key:
            return f"{self.WS_URL}?apiKey={self.api_key}"
        return self.WS_URL

    def _next_request_id(self) -> int:
        """Get next request ID"""
        self._request_id += 1
        return self._request_id

    async def _authenticate(self):
        """
        Public orderbook channel doesn't require authentication.
        API key is passed via query parameter if available.
        """
        if self.verbose:
            logger.debug("Orderbook channel connected (API key in query param if provided)")

    async def _subscribe_orderbook(self, market_id: str):
        """
        Subscribe to orderbook updates for a market.

        Args:
            market_id: Market ID to subscribe to
        """
        topic = f"predictOrderbook/{market_id}"
        request_id = self._next_request_id()

        subscribe_message = {
            "method": "subscribe",
            "requestId": request_id,
            "params": [topic],
        }

        await self.ws.send(json.dumps(subscribe_message))
        self._subscribed_markets[market_id] = topic

        if self.verbose:
            logger.debug(f"Subscribed to orderbook for market: {market_id}")

    async def _unsubscribe_orderbook(self, market_id: str):
        """
        Unsubscribe from orderbook updates.

        Args:
            market_id: Market ID to unsubscribe from
        """
        topic = self._subscribed_markets.get(market_id)
        if not topic:
            return

        request_id = self._next_request_id()

        unsubscribe_message = {
            "method": "unsubscribe",
            "requestId": request_id,
            "params": [topic],
        }

        await self.ws.send(json.dumps(unsubscribe_message))
        del self._subscribed_markets[market_id]

        if self.verbose:
            logger.debug(f"Unsubscribed from orderbook for market: {market_id}")

    def _parse_orderbook_message(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Parse incoming WebSocket message into standardized orderbook format.

        Handles:
        - Type M messages with topic "predictOrderbook/{marketId}"

        Args:
            message: Raw message from WebSocket

        Returns:
            Standardized orderbook data or None if not an orderbook message
        """
        msg_type = message.get("type")

        # Handle push messages (Type M)
        if msg_type == "M":
            topic = message.get("topic", "")

            # Handle heartbeat
            if topic == "heartbeat":
                self._last_heartbeat_ts = message.get("data", 0)
                # Schedule heartbeat response
                asyncio.create_task(self._send_heartbeat_response())
                return None

            # Handle orderbook updates
            if topic.startswith("predictOrderbook/"):
                return self._parse_orderbook_data(topic, message.get("data", {}))

        # Handle response messages (Type R) - just log for now
        elif msg_type == "R":
            request_id = message.get("requestId")
            success = message.get("success", False)
            if self.verbose:
                if success:
                    logger.debug(f"Request {request_id} succeeded")
                else:
                    error = message.get("error", {})
                    logger.warning(f"Request {request_id} failed: {error}")
            return None

        return None

    def _parse_orderbook_data(
        self, topic: str, data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Parse orderbook data from predictOrderbook topic."""
        # Extract market ID from topic
        market_id = topic.replace("predictOrderbook/", "")

        # Parse bids and asks
        bids = []
        for bid in data.get("bids", []):
            try:
                if isinstance(bid, list) and len(bid) >= 2:
                    price = float(bid[0])
                    size = float(bid[1])
                elif isinstance(bid, dict):
                    price = float(bid.get("price", 0))
                    size = float(bid.get("size", 0))
                else:
                    continue

                if price > 0:
                    bids.append((price, size))
            except (ValueError, TypeError):
                continue

        asks = []
        for ask in data.get("asks", []):
            try:
                if isinstance(ask, list) and len(ask) >= 2:
                    price = float(ask[0])
                    size = float(ask[1])
                elif isinstance(ask, dict):
                    price = float(ask.get("price", 0))
                    size = float(ask.get("size", 0))
                else:
                    continue

                if price > 0:
                    asks.append((price, size))
            except (ValueError, TypeError):
                continue

        # Sort bids descending, asks ascending
        bids.sort(reverse=True)
        asks.sort()

        timestamp = data.get("timestamp", int(time.time() * 1000))

        return {
            "market_id": market_id,
            "bids": bids,
            "asks": asks,
            "timestamp": timestamp,
        }

    async def _send_heartbeat_response(self):
        """Send heartbeat response to server."""
        if not self.ws or self.state != WebSocketState.CONNECTED:
            return

        if self._last_heartbeat_ts == 0:
            return

        try:
            heartbeat_msg = {
                "method": "heartbeat",
                "data": self._last_heartbeat_ts,
            }
            await self.ws.send(json.dumps(heartbeat_msg))

            if self.verbose:
                logger.debug(f"Sent heartbeat response: {self._last_heartbeat_ts}")
        except Exception as e:
            if self.verbose:
                logger.warning(f"Failed to send heartbeat: {e}")

    async def watch_orderbook_by_market(
        self, market_id: str, asset_ids: List[str], callback: Optional[Callable] = None
    ):
        """
        Subscribe to orderbook updates for a market.

        Args:
            market_id: Market ID
            asset_ids: List of token IDs for this market (Yes/No tokens)
            callback: Optional function to call with orderbook updates
        """
        # Store mappings
        self._market_to_tokens[market_id] = asset_ids
        for idx, token_id in enumerate(asset_ids):
            self._token_to_market[token_id] = market_id

        # Get Yes/No token IDs
        yes_token = asset_ids[0] if asset_ids else None
        no_token = asset_ids[1] if len(asset_ids) > 1 else None

        def on_orderbook_update(mid: str, orderbook: Dict[str, Any]):
            ts = orderbook.get("timestamp", int(time.time() * 1000))

            # Yes token gets original orderbook
            if yes_token:
                yes_orderbook = {
                    "bids": orderbook["bids"],
                    "asks": orderbook["asks"],
                    "timestamp": ts,
                    "market_id": mid,
                }
                self.orderbook_manager.update(yes_token, yes_orderbook)

                # Update exchange mid-price cache
                if self.exchange:
                    self.exchange.update_mid_price_from_orderbook(yes_token, yes_orderbook)

            # No token gets inverted orderbook
            if no_token:
                no_bids = [(round(1 - price, 4), size) for price, size in orderbook["asks"]]
                no_asks = [(round(1 - price, 4), size) for price, size in orderbook["bids"]]
                no_bids.sort(reverse=True)
                no_asks.sort()
                no_orderbook = {
                    "bids": no_bids,
                    "asks": no_asks,
                    "timestamp": ts,
                    "market_id": mid,
                }
                self.orderbook_manager.update(no_token, no_orderbook)

                # Update exchange mid-price cache
                if self.exchange:
                    self.exchange.update_mid_price_from_orderbook(no_token, no_orderbook)

            if callback:
                callback(mid, orderbook)

        await self.watch_orderbook(market_id, on_orderbook_update)

    def get_orderbook_manager(self) -> OrderbookManager:
        """Get the orderbook manager for compatibility."""
        return self.orderbook_manager


class PredictFunUserWebSocket:
    """
    Predict.fun User WebSocket for real-time wallet event notifications.

    Connects to the authenticated wallet events channel which provides:
    - Order accepted/rejected events
    - Order expiration/cancellation events
    - Transaction submission/success/failure events

    Requires JWT token for authentication.

    Usage:
        ws = PredictFunUserWebSocket(jwt_token, api_key)
        ws.on_trade(callback)
        ws.start()
    """

    WS_URL = "wss://ws.predict.fun/ws"
    HEARTBEAT_INTERVAL = 15.0

    def __init__(
        self,
        jwt_token: str,
        api_key: str = "",
        verbose: bool = False,
    ):
        self.jwt_token = jwt_token
        self.api_key = api_key
        self.verbose = verbose

        self.ws = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._connected = False

        # Request ID counter
        self._request_id = 0

        # Callbacks
        self._trade_callbacks: List[TradeCallback] = []
        self._event_callbacks: List[Callable[[WalletEvent], None]] = []

        # Heartbeat tracking
        self._last_heartbeat_ts: int = 0

    @property
    def ws_url(self) -> str:
        """WebSocket endpoint URL with API key"""
        if self.api_key:
            return f"{self.WS_URL}?apiKey={self.api_key}"
        return self.WS_URL

    def _next_request_id(self) -> int:
        """Get next request ID"""
        self._request_id += 1
        return self._request_id

    def on_trade(self, callback: TradeCallback) -> "PredictFunUserWebSocket":
        """Register a callback for trade/fill events"""
        self._trade_callbacks.append(callback)
        return self

    def on_event(
        self, callback: Callable[[WalletEvent], None]
    ) -> "PredictFunUserWebSocket":
        """Register a callback for all wallet events"""
        self._event_callbacks.append(callback)
        return self

    async def _connect(self):
        """Connect and subscribe to wallet events"""
        self.ws = await websockets.connect(
            self.ws_url,
            ping_interval=None,  # We handle heartbeats manually
            ping_timeout=None,
            close_timeout=10.0,
            max_size=10 * 1024 * 1024,
        )
        self._connected = True

        # Subscribe to wallet events with JWT
        topic = f"predictWalletEvents/{self.jwt_token}"
        request_id = self._next_request_id()

        subscribe_msg = {
            "method": "subscribe",
            "requestId": request_id,
            "params": [topic],
        }
        await self.ws.send(json.dumps(subscribe_msg))

        if self.verbose:
            logger.info("User WebSocket connected and subscribed to wallet events")

    async def _receive_loop(self):
        """Main receive loop"""
        while self._running:
            try:
                if not self._connected:
                    await self._connect()

                async for message in self.ws:
                    if message in ("PONG", "PING", ""):
                        continue

                    try:
                        data = json.loads(message)
                        await self._handle_message(data)
                    except json.JSONDecodeError:
                        pass

            except websockets.exceptions.ConnectionClosed as e:
                if self.verbose:
                    logger.warning(f"User WebSocket closed: {e}")
                self._connected = False
                if self._running:
                    await asyncio.sleep(3)

            except Exception as e:
                if self.verbose:
                    logger.warning(f"User WebSocket error: {e}")
                self._connected = False
                if self._running:
                    await asyncio.sleep(3)

    async def _handle_message(self, data: Dict[str, Any]):
        """Handle incoming WebSocket message"""
        msg_type = data.get("type")

        if msg_type == "M":
            topic = data.get("topic", "")

            # Handle heartbeat
            if topic == "heartbeat":
                self._last_heartbeat_ts = data.get("data", 0)
                await self._send_heartbeat_response()
                return

            # Handle wallet events
            if topic.startswith("predictWalletEvents/"):
                await self._process_wallet_event(data.get("data", {}))

        elif msg_type == "R":
            # Response message - log status
            request_id = data.get("requestId")
            success = data.get("success", False)
            if self.verbose:
                if success:
                    logger.debug(f"Request {request_id} succeeded")
                else:
                    error = data.get("error", {})
                    logger.warning(f"Request {request_id} failed: {error}")

    async def _send_heartbeat_response(self):
        """Send heartbeat response to server."""
        if not self.ws or not self._connected:
            return

        if self._last_heartbeat_ts == 0:
            return

        try:
            heartbeat_msg = {
                "method": "heartbeat",
                "data": self._last_heartbeat_ts,
            }
            await self.ws.send(json.dumps(heartbeat_msg))

            if self.verbose:
                logger.debug(f"Sent heartbeat response: {self._last_heartbeat_ts}")
        except Exception as e:
            if self.verbose:
                logger.warning(f"Failed to send heartbeat: {e}")

    async def _process_wallet_event(self, data: Dict[str, Any]):
        """Process wallet event data"""
        event_type_str = data.get("eventType", "")

        try:
            event_type = WalletEventType(event_type_str)
        except ValueError:
            if self.verbose:
                logger.debug(f"Unknown event type: {event_type_str}")
            return

        # Parse timestamp
        ts = data.get("timestamp", 0)
        if isinstance(ts, str):
            try:
                timestamp = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                timestamp = datetime.now(timezone.utc)
        elif isinstance(ts, (int, float)):
            # Milliseconds to seconds
            if ts > 1e12:
                ts = ts / 1000
            timestamp = datetime.fromtimestamp(ts, tz=timezone.utc)
        else:
            timestamp = datetime.now(timezone.utc)

        # Create wallet event
        wallet_event = WalletEvent(
            event_type=event_type,
            order_id=data.get("orderId", "") or data.get("orderHash", ""),
            market_id=data.get("marketId", ""),
            data=data,
            timestamp=timestamp,
        )

        # Emit to event callbacks
        for callback in self._event_callbacks:
            try:
                callback(wallet_event)
            except Exception as e:
                if self.verbose:
                    logger.warning(f"Event callback error: {e}")

        # Convert to Trade for trade callbacks if it's a fill event
        if event_type == WalletEventType.ORDER_TRANSACTION_SUCCESS:
            trade = self._parse_trade_from_event(data, timestamp)
            if trade:
                self._emit_trade(trade)

    def _parse_trade_from_event(
        self, data: Dict[str, Any], timestamp: datetime
    ) -> Optional[Trade]:
        """Parse Trade from transaction success event."""
        try:
            order_data = data.get("order", {})

            return Trade(
                id=data.get("transactionHash", ""),
                order_id=data.get("orderId", "") or data.get("orderHash", ""),
                market_id=data.get("marketId", ""),
                asset_id=str(order_data.get("tokenId", "")),
                side="buy" if order_data.get("side", 0) == 0 else "sell",
                price=float(order_data.get("price", 0)),
                size=float(order_data.get("size", 0)),
                fee=float(data.get("fee", 0)),
                timestamp=timestamp,
                transaction_hash=data.get("transactionHash", ""),
                event_type=WalletEventType.ORDER_TRANSACTION_SUCCESS.value,
            )
        except Exception as e:
            if self.verbose:
                logger.warning(f"Failed to parse trade: {e}")
            return None

    def _emit_trade(self, trade: Trade):
        """Emit trade to all callbacks"""
        for callback in self._trade_callbacks:
            try:
                callback(trade)
            except Exception as e:
                if self.verbose:
                    logger.warning(f"Trade callback error: {e}")

    def start(self) -> threading.Thread:
        """Start WebSocket in background thread"""
        if self._running:
            return self._thread

        self._running = True
        self._loop = asyncio.new_event_loop()

        def run():
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._receive_loop())

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

        if self.verbose:
            logger.info("User WebSocket started")

        return self._thread

    def stop(self):
        """Stop WebSocket"""
        self._running = False

        if self.ws and self._loop:

            async def close():
                if self.ws:
                    await self.ws.close()

            asyncio.run_coroutine_threadsafe(close(), self._loop)

        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

        if self.verbose:
            logger.info("User WebSocket stopped")
