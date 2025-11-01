import json
from typing import Dict, Any, Optional
from ..base.websocket import OrderBookWebSocket


class PolymarketWebSocket(OrderBookWebSocket):
    """
    Polymarket WebSocket implementation for real-time orderbook updates.

    Uses CLOB WebSocket API for market channel subscriptions.
    Documentation: https://docs.polymarket.com/developers/CLOB/websocket/
    """

    WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)

        # Market ID to asset ID mapping
        self.market_to_asset: Dict[str, str] = {}

        # Track subscribed asset IDs
        self.subscribed_assets = set()

    @property
    def ws_url(self) -> str:
        """WebSocket endpoint URL for Polymarket CLOB market channel"""
        return self.WS_URL

    async def _authenticate(self):
        """
        Market channel is public, no authentication required.
        """
        if self.verbose:
            print("Market channel is public - no authentication required")

    async def _subscribe_orderbook(self, market_id: str):
        """
        Subscribe to orderbook updates for a market.

        For Polymarket, we need to subscribe using asset_id (token ID).
        The market_id is the condition_id, and we need to map it to asset_ids.

        Args:
            market_id: Market condition ID or asset ID
        """
        # Store the market_id as asset_id for subscription
        asset_id = market_id

        # Mark as subscribed
        self.subscribed_assets.add(asset_id)

        # Send subscription message
        subscribe_message = {
            "auth": {},
            "markets": [],
            "assets_ids": [asset_id],
            "type": "market"
        }

        await self.ws.send(json.dumps(subscribe_message))

        if self.verbose:
            print(f"Subscribed to market/asset: {asset_id}")

    async def _unsubscribe_orderbook(self, market_id: str):
        """
        Unsubscribe from orderbook updates.

        Args:
            market_id: Market condition ID or asset ID
        """
        asset_id = market_id

        # Remove from subscribed set
        self.subscribed_assets.discard(asset_id)

        # Send unsubscription (resubscribe with remaining assets)
        subscribe_message = {
            "auth": {},
            "markets": [],
            "assets_ids": list(self.subscribed_assets),
            "type": "market"
        }

        await self.ws.send(json.dumps(subscribe_message))

        if self.verbose:
            print(f"Unsubscribed from market/asset: {asset_id}")

    def _parse_orderbook_message(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Parse incoming WebSocket message into standardized orderbook format.

        Handles two message types:
        1. book - Full orderbook snapshot (bids/asks arrays)
        2. price_change - Price updates with best bid/ask

        Args:
            message: Raw message from WebSocket

        Returns:
            Standardized orderbook data or None if not an orderbook message
        """
        event_type = message.get("event_type")

        if event_type == "book":
            return self._parse_book_message(message)
        elif event_type == "price_change":
            return self._parse_price_change_message(message)

        return None

    def _parse_book_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse book message (full orderbook snapshot).

        Message format:
        {
            "event_type": "book",
            "asset_id": "token_id",
            "market": "condition_id",
            "timestamp": 1234567890,
            "hash": "...",
            "bids": [{"price": "0.52", "size": "100"}, ...],
            "asks": [{"price": "0.53", "size": "100"}, ...]
        }
        """
        asset_id = message.get("asset_id", "")
        market_id = message.get("market", asset_id)

        # Parse bids and asks
        bids = []
        for bid in message.get("bids", []):
            try:
                price = float(bid.get("price", 0))
                size = float(bid.get("size", 0))
                if price > 0 and size > 0:
                    bids.append((price, size))
            except (ValueError, TypeError):
                continue

        asks = []
        for ask in message.get("asks", []):
            try:
                price = float(ask.get("price", 0))
                size = float(ask.get("size", 0))
                if price > 0 and size > 0:
                    asks.append((price, size))
            except (ValueError, TypeError):
                continue

        # Sort bids descending, asks ascending
        bids.sort(reverse=True)
        asks.sort()

        return {
            "market_id": market_id,
            "asset_id": asset_id,
            "bids": bids,
            "asks": asks,
            "timestamp": message.get("timestamp", 0),
            "hash": message.get("hash", "")
        }

    def _parse_price_change_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse price_change message (incremental updates).

        Message format:
        {
            "event_type": "price_change",
            "market": "condition_id",
            "timestamp": 1234567890,
            "price_changes": [{
                "asset_id": "token_id",
                "price": "0.52",
                "size": "100",
                "side": "BUY",
                "hash": "...",
                "best_bid": "0.52",
                "best_ask": "0.53"
            }]
        }
        """
        market_id = message.get("market", "")
        timestamp = message.get("timestamp", 0)

        price_changes = message.get("price_changes", [])
        if not price_changes:
            return None

        # Use first price change (usually one per message)
        change = price_changes[0]
        asset_id = change.get("asset_id", "")

        # Build orderbook from best bid/ask
        bids = []
        asks = []

        try:
            best_bid = change.get("best_bid")
            best_ask = change.get("best_ask")

            if best_bid:
                price = float(best_bid)
                if price > 0:
                    # We don't get size from price_change, use placeholder
                    bids.append((price, 0.0))

            if best_ask:
                price = float(best_ask)
                if price > 0:
                    asks.append((price, 0.0))
        except (ValueError, TypeError):
            pass

        return {
            "market_id": market_id,
            "asset_id": asset_id,
            "bids": bids,
            "asks": asks,
            "timestamp": timestamp,
            "hash": change.get("hash", ""),
            "side": change.get("side"),
            "price": float(change.get("price", 0)) if change.get("price") else None,
            "size": float(change.get("size", 0)) if change.get("size") else None
        }

    async def watch_orderbook_by_asset(self, asset_id: str, callback):
        """
        Subscribe to orderbook updates for a specific asset (token).

        Args:
            asset_id: Token ID to watch
            callback: Function to call with orderbook updates
        """
        await self.watch_orderbook(asset_id, callback)

    async def watch_orderbook_by_market(self, market_id: str, asset_ids: list[str], callback):
        """
        Subscribe to orderbook updates for a market with multiple assets.

        For binary markets, there are typically two assets (YES/NO tokens).

        Args:
            market_id: Market condition ID
            asset_ids: List of asset (token) IDs for this market
            callback: Function to call with orderbook updates
        """
        # Store mapping
        for asset_id in asset_ids:
            self.market_to_asset[market_id] = asset_id
            await self.watch_orderbook(asset_id, callback)

    async def _process_message_item(self, data: dict):
        """
        Process a single message item.
        Override to handle both market_id and asset_id lookups.
        """
        try:
            # Parse orderbook data
            orderbook = self._parse_orderbook_message(data)
            if not orderbook:
                return

            # Try both market_id and asset_id as subscription keys
            market_id = orderbook.get('market_id')
            asset_id = orderbook.get('asset_id')

            # Check which key is in subscriptions
            callback = None
            callback_key = None

            if asset_id and asset_id in self.subscriptions:
                callback = self.subscriptions[asset_id]
                callback_key = asset_id
            elif market_id and market_id in self.subscriptions:
                callback = self.subscriptions[market_id]
                callback_key = market_id

            if callback and callback_key:
                # Call callback in a non-blocking way
                import asyncio
                if asyncio.iscoroutinefunction(callback):
                    await callback(callback_key, orderbook)
                else:
                    callback(callback_key, orderbook)
        except Exception as e:
            if self.verbose:
                print(f"Error processing message item: {e}")
