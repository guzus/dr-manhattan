"""
Predict.fun WebSocket implementation for real-time market data.

WebSocket Features:
- Orderbook updates: predictOrderbook/{marketId}
- Asset price updates: assetPriceUpdate/{priceFeedId}
- Wallet events: predictWalletEvents/{jwt} (authenticated)

Documentation: https://dev.predict.fun/
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
    ORDER_ACCEPTED = "orderAccepted"
    ORDER_NOT_ACCEPTED = "orderNotAccepted"
    ORDER_EXPIRED = "orderExpired"
    ORDER_CANCELLED = "orderCancelled"
    ORDER_TRANSACTION_SUBMITTED = "orderTransactionSubmitted"
    ORDER_TRANSACTION_SUCCESS = "orderTransactionSuccess"
    ORDER_TRANSACTION_FAILED = "orderTransactionFailed"


@dataclass
class Trade:
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
    event_type: WalletEventType
    order_id: str
    market_id: str
    data: Dict[str, Any]
    timestamp: datetime


TradeCallback = Callable[["Trade"], None]


class PredictFunWebSocket(OrderBookWebSocket):
    """
    Predict.fun WebSocket client for real-time orderbook updates.
    """

    WS_URL = "wss://ws.predict.fun/ws"

    def __init__(self, config: Optional[Dict[str, Any]] = None, exchange=None):
        super().__init__(config)
        self.exchange = exchange
        self.api_key = self.config.get("api_key", "")
        self._request_id = 0
        self._subscribed_markets: Dict[str, str] = {}
        self._market_to_tokens: Dict[str, List[str]] = {}
        self._token_to_market: Dict[str, str] = {}
        self.orderbook_manager = OrderbookManager()
        self._last_heartbeat_ts: int = 0

    @property
    def ws_url(self) -> str:
        if self.api_key:
            return f"{self.WS_URL}?apiKey={self.api_key}"
        return self.WS_URL

    def _next_request_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def _authenticate(self):
        if self.verbose:
            logger.debug("Orderbook channel connected")

    async def _subscribe_orderbook(self, market_id: str):
        topic = f"predictOrderbook/{market_id}"
        request_id = self._next_request_id()
        msg = {"method": "subscribe", "requestId": request_id, "params": [topic]}
        await self.ws.send(json.dumps(msg))
        self._subscribed_markets[market_id] = topic
        if self.verbose:
            logger.debug(f"Subscribed to orderbook: {market_id}")

    async def _unsubscribe_orderbook(self, market_id: str):
        topic = self._subscribed_markets.get(market_id)
        if not topic:
            return
        request_id = self._next_request_id()
        msg = {"method": "unsubscribe", "requestId": request_id, "params": [topic]}
        await self.ws.send(json.dumps(msg))
        del self._subscribed_markets[market_id]

    def _parse_orderbook_message(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        msg_type = message.get("type")

        if msg_type == "M":
            topic = message.get("topic", "")
            if topic == "heartbeat":
                self._last_heartbeat_ts = message.get("data", 0)
                asyncio.create_task(self._send_heartbeat_response())
                return None
            if topic.startswith("predictOrderbook/"):
                return self._parse_orderbook_data(topic, message.get("data", {}))

        elif msg_type == "R":
            if self.verbose:
                success = message.get("success", False)
                req_id = message.get("requestId")
                if not success:
                    logger.warning(f"Request {req_id} failed: {message.get('error')}")

        return None

    def _parse_orderbook_data(self, topic: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        market_id = topic.replace("predictOrderbook/", "")
        bids, asks = [], []

        for bid in data.get("bids", []):
            try:
                if isinstance(bid, list) and len(bid) >= 2:
                    price, size = float(bid[0]), float(bid[1])
                elif isinstance(bid, dict):
                    price, size = float(bid.get("price", 0)), float(bid.get("size", 0))
                else:
                    continue
                if price > 0:
                    bids.append((price, size))
            except (ValueError, TypeError):
                continue

        for ask in data.get("asks", []):
            try:
                if isinstance(ask, list) and len(ask) >= 2:
                    price, size = float(ask[0]), float(ask[1])
                elif isinstance(ask, dict):
                    price, size = float(ask.get("price", 0)), float(ask.get("size", 0))
                else:
                    continue
                if price > 0:
                    asks.append((price, size))
            except (ValueError, TypeError):
                continue

        bids.sort(reverse=True)
        asks.sort()

        return {
            "market_id": market_id,
            "bids": bids,
            "asks": asks,
            "timestamp": data.get("timestamp", int(time.time() * 1000)),
        }

    async def _send_heartbeat_response(self):
        if not self.ws or self.state != WebSocketState.CONNECTED or self._last_heartbeat_ts == 0:
            return
        try:
            msg = {"method": "heartbeat", "data": self._last_heartbeat_ts}
            await self.ws.send(json.dumps(msg))
            if self.verbose:
                logger.debug(f"Heartbeat response: {self._last_heartbeat_ts}")
        except Exception as e:
            if self.verbose:
                logger.warning(f"Heartbeat failed: {e}")

    async def watch_orderbook_by_market(
        self, market_id: str, asset_ids: List[str], callback: Optional[Callable] = None
    ):
        self._market_to_tokens[market_id] = asset_ids
        for token_id in asset_ids:
            self._token_to_market[token_id] = market_id

        yes_token = asset_ids[0] if asset_ids else None
        no_token = asset_ids[1] if len(asset_ids) > 1 else None

        def on_update(mid: str, ob: Dict[str, Any]):
            ts = ob.get("timestamp", int(time.time() * 1000))

            if yes_token:
                yes_ob = {"bids": ob["bids"], "asks": ob["asks"], "timestamp": ts, "market_id": mid}
                self.orderbook_manager.update(yes_token, yes_ob)
                if self.exchange:
                    self.exchange.update_mid_price_from_orderbook(yes_token, yes_ob)

            if no_token:
                no_bids = [(round(1 - p, 4), s) for p, s in ob["asks"]]
                no_asks = [(round(1 - p, 4), s) for p, s in ob["bids"]]
                no_bids.sort(reverse=True)
                no_asks.sort()
                no_ob = {"bids": no_bids, "asks": no_asks, "timestamp": ts, "market_id": mid}
                self.orderbook_manager.update(no_token, no_ob)
                if self.exchange:
                    self.exchange.update_mid_price_from_orderbook(no_token, no_ob)

            if callback:
                callback(mid, ob)

        await self.watch_orderbook(market_id, on_update)

    def get_orderbook_manager(self) -> OrderbookManager:
        return self.orderbook_manager


class PredictFunUserWebSocket:
    """
    Predict.fun User WebSocket for wallet event notifications.
    """

    WS_URL = "wss://ws.predict.fun/ws"

    def __init__(self, jwt_token: str, api_key: str = "", verbose: bool = False):
        self.jwt_token = jwt_token
        self.api_key = api_key
        self.verbose = verbose
        self.ws = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._connected = False
        self._request_id = 0
        self._trade_callbacks: List[TradeCallback] = []
        self._event_callbacks: List[Callable[[WalletEvent], None]] = []
        self._last_heartbeat_ts: int = 0

    @property
    def ws_url(self) -> str:
        if self.api_key:
            return f"{self.WS_URL}?apiKey={self.api_key}"
        return self.WS_URL

    def _next_request_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def on_trade(self, callback: TradeCallback) -> "PredictFunUserWebSocket":
        self._trade_callbacks.append(callback)
        return self

    def on_event(self, callback: Callable[[WalletEvent], None]) -> "PredictFunUserWebSocket":
        self._event_callbacks.append(callback)
        return self

    async def _connect(self):
        self.ws = await websockets.connect(self.ws_url, ping_interval=None, ping_timeout=None)
        self._connected = True
        topic = f"predictWalletEvents/{self.jwt_token}"
        msg = {"method": "subscribe", "requestId": self._next_request_id(), "params": [topic]}
        await self.ws.send(json.dumps(msg))
        if self.verbose:
            logger.info("User WebSocket connected")

    async def _receive_loop(self):
        while self._running:
            try:
                if not self._connected:
                    await self._connect()
                async for message in self.ws:
                    if message in ("PONG", "PING", ""):
                        continue
                    try:
                        await self._handle_message(json.loads(message))
                    except json.JSONDecodeError:
                        pass
            except websockets.exceptions.ConnectionClosed:
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
        msg_type = data.get("type")
        if msg_type == "M":
            topic = data.get("topic", "")
            if topic == "heartbeat":
                self._last_heartbeat_ts = data.get("data", 0)
                await self._send_heartbeat_response()
            elif topic.startswith("predictWalletEvents/"):
                await self._process_wallet_event(data.get("data", {}))

    async def _send_heartbeat_response(self):
        if not self.ws or not self._connected or self._last_heartbeat_ts == 0:
            return
        try:
            await self.ws.send(json.dumps({"method": "heartbeat", "data": self._last_heartbeat_ts}))
        except Exception:
            pass

    async def _process_wallet_event(self, data: Dict[str, Any]):
        event_type_str = data.get("eventType", "")
        try:
            event_type = WalletEventType(event_type_str)
        except ValueError:
            return

        ts = data.get("timestamp", 0)
        if isinstance(ts, (int, float)) and ts > 1e12:
            ts = ts / 1000
        timestamp = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else datetime.now(timezone.utc)

        event = WalletEvent(
            event_type=event_type,
            order_id=data.get("orderId", "") or data.get("orderHash", ""),
            market_id=data.get("marketId", ""),
            data=data,
            timestamp=timestamp,
        )

        for cb in self._event_callbacks:
            try:
                cb(event)
            except Exception:
                pass

        if event_type == WalletEventType.ORDER_TRANSACTION_SUCCESS:
            trade = self._parse_trade(data, timestamp)
            if trade:
                for cb in self._trade_callbacks:
                    try:
                        cb(trade)
                    except Exception:
                        pass

    def _parse_trade(self, data: Dict[str, Any], timestamp: datetime) -> Optional[Trade]:
        try:
            order = data.get("order", {})
            return Trade(
                id=data.get("transactionHash", ""),
                order_id=data.get("orderId", ""),
                market_id=data.get("marketId", ""),
                asset_id=str(order.get("tokenId", "")),
                side="buy" if order.get("side", 0) == 0 else "sell",
                price=float(order.get("price", 0)),
                size=float(order.get("size", 0)),
                fee=float(data.get("fee", 0)),
                timestamp=timestamp,
                transaction_hash=data.get("transactionHash", ""),
                event_type=WalletEventType.ORDER_TRANSACTION_SUCCESS.value,
            )
        except Exception:
            return None

    def start(self) -> threading.Thread:
        if self._running:
            return self._thread
        self._running = True
        self._loop = asyncio.new_event_loop()

        def run():
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._receive_loop())

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        return self._thread

    def stop(self):
        self._running = False
        if self.ws and self._loop:
            asyncio.run_coroutine_threadsafe(self.ws.close(), self._loop)
        if self._thread:
            self._thread.join(timeout=5)
