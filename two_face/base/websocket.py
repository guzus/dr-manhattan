from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, Callable
import asyncio
import json
from enum import Enum


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
        self.max_reconnect_attempts = self.config.get('max_reconnect_attempts', 10)
        self.reconnect_delay = self.config.get('reconnect_delay', 5.0)
        self.reconnect_attempts = 0

        # Subscriptions
        self.subscriptions: Dict[str, Callable] = {}

        # Event loop
        self.loop = None
        self.tasks = []

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
        """Establish WebSocket connection"""
        try:
            import websockets
        except ImportError:
            raise ImportError("websockets library required. Install with: uv add websockets")

        if self.state == WebSocketState.CONNECTED:
            if self.verbose:
                print("WebSocket already connected")
            return

        self.state = WebSocketState.CONNECTING

        try:
            self.ws = await websockets.connect(self.ws_url)
            self.state = WebSocketState.CONNECTED
            self.reconnect_attempts = 0

            if self.verbose:
                print(f"WebSocket connected to {self.ws_url}")

            # Authenticate if needed
            await self._authenticate()

            # Resubscribe to all markets
            for market_id in list(self.subscriptions.keys()):
                await self._subscribe_orderbook(market_id)

        except Exception as e:
            self.state = WebSocketState.DISCONNECTED
            if self.verbose:
                print(f"WebSocket connection failed: {e}")
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
            print("WebSocket disconnected")

    async def _handle_message(self, message: str):
        """
        Handle incoming WebSocket message.

        Args:
            message: Raw message string from WebSocket
        """
        try:
            if self.verbose:
                # Log first 200 chars of message
                msg_preview = message[:200] + "..." if len(message) > 200 else message
                print(f"[WS] Received: {msg_preview}")

            data = json.loads(message)

            # Handle messages that come as arrays
            if isinstance(data, list):
                for item in data:
                    await self._process_message_item(item)
            else:
                await self._process_message_item(data)

        except json.JSONDecodeError as e:
            if self.verbose:
                print(f"Failed to parse message: {e}")
        except Exception as e:
            if self.verbose:
                print(f"Error handling message: {e}")

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
                print(f"Error processing message item: {e}")

    async def _receive_loop(self):
        """Main loop for receiving WebSocket messages"""
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

            except Exception as e:
                if self.verbose:
                    print(f"WebSocket receive error: {e}")

                if self.auto_reconnect and self.state != WebSocketState.CLOSED:
                    await self._reconnect()
                else:
                    break

    async def _reconnect(self):
        """Handle reconnection with exponential backoff"""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            if self.verbose:
                print("Max reconnection attempts reached")
            self.state = WebSocketState.CLOSED
            return

        self.state = WebSocketState.RECONNECTING
        self.reconnect_attempts += 1

        delay = self.reconnect_delay * (2 ** (self.reconnect_attempts - 1))
        if self.verbose:
            print(f"Reconnecting in {delay}s (attempt {self.reconnect_attempts}/{self.max_reconnect_attempts})")

        await asyncio.sleep(delay)

        try:
            await self.connect()
        except Exception as e:
            if self.verbose:
                print(f"Reconnection failed: {e}")

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
            print(f"Subscribed to orderbook for market: {market_id}")

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
            print(f"Unsubscribed from orderbook for market: {market_id}")

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
