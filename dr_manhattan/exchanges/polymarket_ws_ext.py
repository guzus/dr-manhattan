from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

import websockets
import websockets.exceptions

logger = logging.getLogger(__name__)


class PolymarketSportsWebSocket:
    """
    Sports market real-time WebSocket.

    Connects to the Polymarket CLOB WebSocket for sports market updates.
    Follows the same pattern as PolymarketWebSocket from polymarket_ws.py.
    """

    WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.ws = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._callbacks: Dict[str, List[Callable]] = {}
        self._subscribed_markets: List[str] = []

    def on_update(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Register a callback for market updates."""
        self._callbacks.setdefault("update", []).append(callback)

    def on_error(self, callback: Callable[[Exception], None]) -> None:
        """Register a callback for errors."""
        self._callbacks.setdefault("error", []).append(callback)

    def subscribe(self, market_ids: List[str]) -> None:
        """
        Subscribe to sports market updates.

        Args:
            market_ids: List of asset IDs (token IDs) to subscribe to
        """
        self._subscribed_markets.extend(market_ids)
        if self.ws and self._running:
            asyncio.run_coroutine_threadsafe(
                self._send_subscribe(market_ids), self._loop
            )

    async def _send_subscribe(self, market_ids: List[str]) -> None:
        """Send subscription message over WebSocket."""
        msg = {
            "auth": {},
            "markets": [],
            "assets_ids": market_ids,
            "type": "market",
        }
        await self.ws.send(json.dumps(msg))
        if self.verbose:
            logger.info(f"Subscribed to sports markets: {market_ids}")

    async def _listen(self) -> None:
        """Main WebSocket listen loop."""
        while self._running:
            try:
                async with websockets.connect(self.WS_URL) as ws:
                    self.ws = ws
                    if self.verbose:
                        logger.info("Sports WebSocket connected")

                    # Subscribe to any pending markets
                    if self._subscribed_markets:
                        await self._send_subscribe(self._subscribed_markets)

                    async for message in ws:
                        try:
                            data = json.loads(message)
                            for cb in self._callbacks.get("update", []):
                                cb(data)
                        except json.JSONDecodeError:
                            if self.verbose:
                                logger.warning(f"Invalid JSON: {message[:100]}")

            except websockets.exceptions.ConnectionClosed as e:
                if self.verbose:
                    logger.warning(f"Sports WebSocket closed: {e}")
                if self._running:
                    await asyncio.sleep(2)
            except Exception as e:
                for cb in self._callbacks.get("error", []):
                    cb(e)
                if self._running:
                    await asyncio.sleep(5)

    def start(self) -> None:
        """Start the WebSocket in a background thread."""
        if self._running:
            return
        self._running = True
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="sports-ws"
        )
        self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._listen())

    def stop(self) -> None:
        """Stop the WebSocket."""
        self._running = False
        if self.ws:
            asyncio.run_coroutine_threadsafe(self.ws.close(), self._loop)
        if self._thread:
            self._thread.join(timeout=5)


class PolymarketRTDSWebSocket:
    """
    Real-Time Data Stream WebSocket for crypto prices and comments.

    Follows the same pattern as PolymarketWebSocket from polymarket_ws.py.
    """

    WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.ws = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._callbacks: Dict[str, List[Callable]] = {}
        self._subscribed_assets: List[str] = []

    def on_price(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Register a callback for price updates."""
        self._callbacks.setdefault("price", []).append(callback)

    def on_comment(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Register a callback for comment updates."""
        self._callbacks.setdefault("comment", []).append(callback)

    def on_error(self, callback: Callable[[Exception], None]) -> None:
        """Register a callback for errors."""
        self._callbacks.setdefault("error", []).append(callback)

    def subscribe(self, asset_ids: List[str]) -> None:
        """
        Subscribe to real-time data for assets.

        Args:
            asset_ids: List of asset IDs (token IDs) to subscribe to
        """
        self._subscribed_assets.extend(asset_ids)
        if self.ws and self._running:
            asyncio.run_coroutine_threadsafe(
                self._send_subscribe(asset_ids), self._loop
            )

    async def _send_subscribe(self, asset_ids: List[str]) -> None:
        """Send subscription message over WebSocket."""
        msg = {
            "auth": {},
            "markets": [],
            "assets_ids": asset_ids,
            "type": "market",
        }
        await self.ws.send(json.dumps(msg))
        if self.verbose:
            logger.info(f"Subscribed to RTDS assets: {asset_ids}")

    async def _listen(self) -> None:
        """Main WebSocket listen loop."""
        while self._running:
            try:
                async with websockets.connect(self.WS_URL) as ws:
                    self.ws = ws
                    if self.verbose:
                        logger.info("RTDS WebSocket connected")

                    if self._subscribed_assets:
                        await self._send_subscribe(self._subscribed_assets)

                    async for message in ws:
                        try:
                            data = json.loads(message)
                            # Route to appropriate callbacks based on message type
                            msg_type = data.get("type", "")
                            if msg_type == "comment":
                                for cb in self._callbacks.get("comment", []):
                                    cb(data)
                            else:
                                # Default to price callback
                                for cb in self._callbacks.get("price", []):
                                    cb(data)
                        except json.JSONDecodeError:
                            if self.verbose:
                                logger.warning(f"Invalid JSON: {message[:100]}")

            except websockets.exceptions.ConnectionClosed as e:
                if self.verbose:
                    logger.warning(f"RTDS WebSocket closed: {e}")
                if self._running:
                    await asyncio.sleep(2)
            except Exception as e:
                for cb in self._callbacks.get("error", []):
                    cb(e)
                if self._running:
                    await asyncio.sleep(5)

    def start(self) -> None:
        """Start the WebSocket in a background thread."""
        if self._running:
            return
        self._running = True
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="rtds-ws"
        )
        self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._listen())

    def stop(self) -> None:
        """Stop the WebSocket."""
        self._running = False
        if self.ws:
            asyncio.run_coroutine_threadsafe(self.ws.close(), self._loop)
        if self._thread:
            self._thread.join(timeout=5)
