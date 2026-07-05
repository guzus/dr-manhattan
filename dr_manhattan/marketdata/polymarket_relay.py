"""Polymarket orderbook relay utilities.

The relay keeps one upstream Polymarket CLOB websocket connection and fans
orderbook messages out to local websocket clients. Clients subscribe with:

    {"type": "subscribe", "assets": ["<clob token id>", "..."]}

Book messages are forwarded as compact JSON with relay receive/send timestamps.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

try:
    from dr_manhattan.exchanges.polymarket.polymarket_ws import PolymarketWebSocket
except ModuleNotFoundError:  # pragma: no cover - compatibility for older private deploys
    from dr_manhattan.exchanges.polymarket_ws import PolymarketWebSocket


def now_ms() -> int:
    return time.time_ns() // 1_000_000


@dataclass(frozen=True)
class RelayStats:
    clients: int
    source_assets: int
    cached_books: int
    books_received: int
    books_sent: int
    books_dropped: int


class PolymarketOrderbookRelay:
    """Fan out one Polymarket orderbook feed to many local clients."""

    def __init__(
        self,
        *,
        verbose: bool = False,
        refresh_on_client_subscribe: bool = True,
        stats_interval_sec: float = 30.0,
        max_client_write_buffer_bytes: int = 512 * 1024,
        source_factory: Callable[[], PolymarketWebSocket] | None = None,
    ) -> None:
        self.verbose = verbose
        self.refresh_on_client_subscribe = refresh_on_client_subscribe
        self.stats_interval_sec = max(0.0, stats_interval_sec)
        self.source_factory = source_factory or self._default_source_factory
        self.max_client_write_buffer_bytes = max(0, int(max_client_write_buffer_bytes))
        self.source = self.source_factory()
        self.clients: set[Any] = set()
        self.assets_by_client: dict[Any, set[str]] = {}
        self.last_book_by_asset: dict[str, dict[str, Any]] = {}
        self._source_receive_task: asyncio.Task | None = None
        self._stats_task: asyncio.Task | None = None
        self._source_lock = asyncio.Lock()
        self.books_received = 0
        self.books_sent = 0
        self.books_dropped = 0

    @property
    def stats(self) -> RelayStats:
        return RelayStats(
            clients=len(self.clients),
            source_assets=len(self.source.subscriptions),
            cached_books=len(self.last_book_by_asset),
            books_received=self.books_received,
            books_sent=self.books_sent,
            books_dropped=self.books_dropped,
        )

    async def start(self) -> None:
        await self.source.connect()
        self._source_receive_task = asyncio.create_task(self.source._receive_loop())
        if self.stats_interval_sec > 0:
            self._stats_task = asyncio.create_task(self._stats_loop())
        print("polymarket_relay_source_connected", file=sys.stderr, flush=True)

    async def stop(self) -> None:
        if self._stats_task:
            self._stats_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._stats_task
            self._stats_task = None
        await self._close_source()

    async def handle_client(self, websocket: Any) -> None:
        self.clients.add(websocket)
        self.assets_by_client[websocket] = set()
        peer = getattr(websocket, "remote_address", None)
        print(f"client_connected peer={peer}", file=sys.stderr, flush=True)
        try:
            async for message in websocket:
                await self.handle_client_message(websocket, message)
        finally:
            self.clients.discard(websocket)
            self.assets_by_client.pop(websocket, None)
            print(f"client_disconnected peer={peer}", file=sys.stderr, flush=True)

    async def handle_client_message(self, websocket: Any, message: str) -> None:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            return
        if payload.get("type") != "subscribe":
            return
        assets = {str(asset) for asset in payload.get("assets", []) if asset}
        self.assets_by_client[websocket] = assets
        await self._subscribe_client_assets()
        await websocket.send(
            json.dumps({"type": "subscribed", "assets": len(assets), "ts_ms": now_ms()})
        )
        for asset in sorted(assets):
            cached = self.last_book_by_asset.get(asset)
            if cached is not None:
                await websocket.send(
                    json.dumps(
                        {**cached, "replay": True, "relay_sent_ms": now_ms()},
                        separators=(",", ":"),
                    )
                )
        print(f"client_subscribed assets={len(assets)}", file=sys.stderr, flush=True)

    def _default_source_factory(self) -> PolymarketWebSocket:
        return PolymarketWebSocket(config={"verbose": self.verbose, "auto_reconnect": True})

    async def _close_source(self) -> None:
        if self._source_receive_task:
            self._source_receive_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._source_receive_task
            self._source_receive_task = None
        await self.source.disconnect()

    async def _subscribe_client_assets(self) -> None:
        assets = set().union(*self.assets_by_client.values()) if self.assets_by_client else set()
        current_assets = set(self.source.subscriptions)
        if not assets:
            return
        if current_assets == assets and not self.refresh_on_client_subscribe:
            return

        callbacks = {asset: self._make_callback(asset) for asset in sorted(assets)}
        async with self._source_lock:
            if self.refresh_on_client_subscribe:
                await self._refresh_source(callbacks)
            else:
                new_callbacks = {
                    asset: callbacks[asset]
                    for asset in sorted(assets)
                    if asset not in self.source.subscriptions
                }
                if new_callbacks:
                    await self.source.watch_orderbooks_by_assets(new_callbacks)
        print(
            "source_subscribed "
            f"assets={len(assets)} refreshed={self.refresh_on_client_subscribe} "
            f"total_assets={len(self.source.subscriptions)}",
            file=sys.stderr,
            flush=True,
        )

    async def _refresh_source(self, callbacks: dict[str, Any]) -> None:
        await self._close_source()
        self.source = self.source_factory()
        self.last_book_by_asset.clear()
        await self.source.connect()
        self._source_receive_task = asyncio.create_task(self.source._receive_loop())
        await self.source.watch_orderbooks_by_assets(callbacks)

    def _make_callback(self, asset: str) -> Callable[[str, dict[str, Any]], None]:
        def callback(_asset_id: str, orderbook: dict[str, Any]) -> None:
            payload = {
                "type": "book",
                "asset_id": asset,
                "relay_received_ms": now_ms(),
                "book": orderbook,
            }
            self.last_book_by_asset[asset] = payload
            self.books_received += 1
            asyncio.create_task(self.broadcast(asset, payload))

        return callback

    async def broadcast(self, asset: str, payload: dict[str, Any]) -> None:
        if not self.clients:
            return
        message = json.dumps({**payload, "relay_sent_ms": now_ms()}, separators=(",", ":"))
        stale_clients = []
        for client in list(self.clients):
            if asset not in self.assets_by_client.get(client, set()):
                continue
            try:
                if self._client_write_buffer_size(client) > self.max_client_write_buffer_bytes:
                    self.books_dropped += 1
                    continue
                await client.send(message)
                self.books_sent += 1
            except Exception:
                stale_clients.append(client)
        for client in stale_clients:
            self.clients.discard(client)
            self.assets_by_client.pop(client, None)

    @staticmethod
    def _client_write_buffer_size(client: Any) -> int:
        transport = getattr(client, "transport", None)
        get_size = getattr(transport, "get_write_buffer_size", None)
        if not callable(get_size):
            return 0
        try:
            return int(get_size())
        except Exception:
            return 0

    async def _stats_loop(self) -> None:
        while True:
            await asyncio.sleep(self.stats_interval_sec)
            stats = self.stats
            print(
                "polymarket_relay_stats "
                f"clients={stats.clients} "
                f"source_assets={stats.source_assets} "
                f"cached_books={stats.cached_books} "
                f"books_received={stats.books_received} "
                f"books_sent={stats.books_sent} "
                f"books_dropped={stats.books_dropped}",
                file=sys.stderr,
                flush=True,
            )
