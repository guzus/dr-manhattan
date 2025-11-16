from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, Callable
import asyncio
import json
import time
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class WebSocketState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    CLOSED = "closed"


class OrderBookWebSocket(ABC):
    """
    Base WebSocket class for real-time orderbook updates.
    Interrupt-driven approach using asyncio and websockets.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.verbose = self.config.get('verbose', False)

        # WebSocket connection
        self.ws = None
        self.state = WebSocketState.DISCONNECTED

        # Reconnection settings
        self.auto_reconnect = self.config.get('auto_reconnect', True)
        self.max_reconnect_attempts = self.config.get('max_reconnect_attempts', 999)  # Essentially infinite
        self.reconnect_delay = self.config.get('reconnect_delay', 3.0)
        self.reconnect_attempts = 0

        # Connection timeout settings
        self.ping_interval = self.config.get('ping_interval', 20.0)  # Send ping every 20s
        self.ping_timeout = self.config.get('ping_timeout', 10.0)   # Wait 10s for pong
        self.close_timeout = self.config.get('close_timeout', 10.0)

        # Subscriptions
        self.subscriptions: Dict[str, Callable] = {}

        # Event loop
        self.loop = None
        self.tasks = []

        # Last activity tracking
        self.last_message_time = 0

    @property
    @abstractmethod
    def ws_url(self) -> str:
        """WebSocket endpoint URL"""
        pass

    @abstractmethod
    async def _authenticate(self):
        """
        Authenticate WebSocket connection if required.
        Should send auth message through self.ws
        """
        pass

    @abstractmethod
    async def _subscribe_orderbook(self, market_id: str):
        """
        Send subscription message for orderbook updates.

        Args:
            market_id: Market identifier to subscribe to
        """
        pass

    @abstractmethod
    async def _unsubscribe_orderbook(self, market_id: str):
        """
        Send unsubscription message for orderbook updates.

        Args:
            market_id: Market identifier to unsubscribe from
        """
        pass

    @abstractmethod
    def _parse_orderbook_message(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Parse incoming WebSocket message into standardized orderbook format.

        Args:
            message: Raw message from WebSocket

        Returns:
            Parsed orderbook data or None if not an orderbook message
            Format: {
                'market_id': str,
                'bids': [(price, size), ...],
                'asks': [(price, size), ...],
                'timestamp': int
            }
        """
        pass

    async def connect(self):
        """Establish WebSocket connection with improved settings"""
        try:
            import websockets
        except ImportError:
            raise ImportError("websockets library required. Install with: uv add websockets")

        if self.state == WebSocketState.CONNECTED:
            if self.verbose:
                logger.debug("WebSocket already connected")
            return

        self.state = WebSocketState.CONNECTING

        try:
            # Connect with ping/pong heartbeat
            self.ws = await websockets.connect(
                self.ws_url,
                ping_interval=self.ping_interval,
                ping_timeout=self.ping_timeout,
                close_timeout=self.close_timeout,
                max_size=10 * 1024 * 1024,  # 10MB max message size
                compression=None  # Disable compression for lower latency
            )
            self.state = WebSocketState.CONNECTED
            self.reconnect_attempts = 0
            self.last_message_time = time.time()

            if self.verbose:
                logger.debug(f"WebSocket connected to {self.ws_url}")
                logger.debug(f"  Ping interval: {self.ping_interval}s")
                logger.debug(f"  Ping timeout: {self.ping_timeout}s")

            # Authenticate if needed
            await self._authenticate()

            # Resubscribe to all markets
            for market_id in list(self.subscriptions.keys()):
                await self._subscribe_orderbook(market_id)

        except Exception as e:
            self.state = WebSocketState.DISCONNECTED
            if self.verbose:
                logger.debug(f"WebSocket connection failed: {e}")
            raise

    async def disconnect(self):
        """Close WebSocket connection"""
        self.state = WebSocketState.CLOSED
        self.auto_reconnect = False

        if self.ws:
            await self.ws.close()
            self.ws = None

        # Cancel all tasks
        for task in self.tasks:
            task.cancel()
        self.tasks.clear()

        if self.verbose:
            logger.debug("WebSocket disconnected")

    async def _handle_message(self, message: str):
        """
        Handle incoming WebSocket message.

        Args:
            message: Raw message string from WebSocket
        """
        try:
            # Update last message time
            self.last_message_time = time.time()

            # Skip non-JSON messages (like PONG heartbeats)
            if message in ('PONG', 'PING', ''):
                return

            if self.verbose:
                # Log first 200 chars of message
                msg_preview = message[:200] + "..." if len(message) > 200 else message
                logger.debug(f"[WS] Received: {msg_preview}")

            data = json.loads(message)

            # Handle messages that come as arrays
            if isinstance(data, list):
                for item in data:
                    await self._process_message_item(item)
            else:
                await self._process_message_item(data)

        except json.JSONDecodeError as e:
            # Only log JSON errors if verbose and not a known non-JSON message
            if self.verbose and message not in ('PONG', 'PING'):
                logger.debug(f"Failed to parse message as JSON: {message[:100]}")
        except Exception as e:
            if self.verbose:
                logger.debug(f"Error handling message: {e}")

    async def _process_message_item(self, data: dict):
        """Process a single message item"""
        try:
            # Parse orderbook data
            orderbook = self._parse_orderbook_message(data)
            if not orderbook:
                return

            market_id = orderbook.get('market_id')
            if market_id in self.subscriptions:
                callback = self.subscriptions[market_id]

                # Call callback in a non-blocking way
                if asyncio.iscoroutinefunction(callback):
                    await callback(market_id, orderbook)
                else:
                    callback(market_id, orderbook)
        except Exception as e:
            if self.verbose:
                logger.debug(f"Error processing message item: {e}")

    async def _receive_loop(self):
        """Main loop for receiving WebSocket messages with improved error handling"""
        import websockets.exceptions

        while self.state != WebSocketState.CLOSED:
            try:
                if self.ws is None or self.state != WebSocketState.CONNECTED:
                    if self.auto_reconnect:
                        await self._reconnect()
                    else:
                        break
                    continue

                async for message in self.ws:
                    await self._handle_message(message)

                # If loop exits normally, connection was closed
                if self.verbose:
                    logger.debug("WebSocket connection closed normally")

                if self.auto_reconnect and self.state != WebSocketState.CLOSED:
                    await self._reconnect()
                else:
                    break

            except websockets.exceptions.ConnectionClosed as e:
                if self.verbose:
                    logger.debug(f"WebSocket connection closed: {e.code} {e.reason}")

                if self.auto_reconnect and self.state != WebSocketState.CLOSED:
                    await self._reconnect()
                else:
                    break

            except asyncio.TimeoutError:
                if self.verbose:
                    logger.debug("WebSocket timeout - reconnecting...")

                if self.auto_reconnect and self.state != WebSocketState.CLOSED:
                    await self._reconnect()
                else:
                    break

            except Exception as e:
                if self.verbose:
                    logger.debug(f"WebSocket receive error: {type(e).__name__}: {e}")

                if self.auto_reconnect and self.state != WebSocketState.CLOSED:
                    await self._reconnect()
                else:
                    break

    async def _reconnect(self):
        """Handle reconnection with exponential backoff (capped)"""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            if self.verbose:
                logger.debug("Max reconnection attempts reached")
            self.state = WebSocketState.CLOSED
            return

        self.state = WebSocketState.RECONNECTING
        self.reconnect_attempts += 1

        # Exponential backoff with max delay of 60s
        delay = min(60.0, self.reconnect_delay * (1.5 ** (self.reconnect_attempts - 1)))

        if self.verbose:
            logger.debug(f"Reconnecting in {delay:.1f}s (attempt {self.reconnect_attempts})")

        await asyncio.sleep(delay)

        try:
            # Close old connection if exists
            if self.ws:
                try:
                    await self.ws.close()
                except:
                    pass
                self.ws = None

            await self.connect()

            if self.verbose:
                logger.debug(f"✓ Reconnected successfully")

        except Exception as e:
            if self.verbose:
                logger.debug(f"Reconnection failed: {e}")

    async def watch_orderbook(self, market_id: str, callback: Callable):
        """
        Subscribe to orderbook updates for a market.

        Args:
            market_id: Market identifier
            callback: Function to call with orderbook updates
                      Signature: callback(market_id: str, orderbook: Dict)
        """
        # Store subscription
        self.subscriptions[market_id] = callback

        # Connect if not already connected
        if self.state != WebSocketState.CONNECTED:
            await self.connect()

        # Subscribe to orderbook
        await self._subscribe_orderbook(market_id)

        if self.verbose:
            logger.debug(f"Subscribed to orderbook for market: {market_id}")

    async def unwatch_orderbook(self, market_id: str):
        """
        Unsubscribe from orderbook updates.

        Args:
            market_id: Market identifier
        """
        if market_id not in self.subscriptions:
            return

        # Remove subscription
        del self.subscriptions[market_id]

        # Unsubscribe from orderbook
        if self.state == WebSocketState.CONNECTED:
            await self._unsubscribe_orderbook(market_id)

        if self.verbose:
            logger.debug(f"Unsubscribed from orderbook for market: {market_id}")

    def start(self):
        """
        Start WebSocket connection and message loop.
        Non-blocking - runs in background.
        """
        if self.loop is None:
            self.loop = asyncio.new_event_loop()

        async def _start():
            await self.connect()
            await self._receive_loop()

        import threading

        def _run_loop():
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(_start())

        thread = threading.Thread(target=_run_loop, daemon=True)
        thread.start()
        return thread

    def stop(self):
        """Stop WebSocket connection"""
        if self.loop:
            asyncio.run_coroutine_threadsafe(self.disconnect(), self.loop)
