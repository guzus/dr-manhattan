import json

import pytest

from dr_manhattan.base.websocket import WebSocketState
from dr_manhattan.exchanges.polymarket.polymarket_ws import PolymarketWebSocket
from dr_manhattan.marketdata import PolymarketOrderbookRelay


class FakeClient:
    def __init__(self):
        self.sent = []

    async def send(self, message):
        self.sent.append(json.loads(message))


class FakeSource:
    def __init__(self):
        self.subscriptions = {}
        self.connected = False
        self.disconnected = False

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.disconnected = True

    async def _receive_loop(self):
        return None

    async def watch_orderbooks_by_assets(self, callbacks):
        self.subscriptions.update(callbacks)


class FakeWire:
    def __init__(self):
        self.sent = []

    async def send(self, message):
        self.sent.append(json.loads(message))


@pytest.mark.asyncio
async def test_polymarket_relay_subscribes_union_of_client_assets():
    source = FakeSource()
    relay = PolymarketOrderbookRelay(
        source_factory=lambda: source,
        refresh_on_client_subscribe=False,
        stats_interval_sec=0,
    )
    client = FakeClient()

    await relay.handle_client_message(
        client,
        json.dumps({"type": "subscribe", "assets": ["asset-b", "asset-a"]}),
    )

    assert set(source.subscriptions) == {"asset-a", "asset-b"}
    assert client.sent[0]["type"] == "subscribed"
    assert client.sent[0]["assets"] == 2


@pytest.mark.asyncio
async def test_polymarket_relay_broadcasts_only_to_subscribed_clients():
    relay = PolymarketOrderbookRelay(source_factory=FakeSource, stats_interval_sec=0)
    subscribed = FakeClient()
    other = FakeClient()
    relay.clients = {subscribed, other}
    relay.assets_by_client = {subscribed: {"asset-1"}, other: {"asset-2"}}

    await relay.broadcast("asset-1", {"type": "book", "asset_id": "asset-1", "book": {}})

    assert len(subscribed.sent) == 1
    assert subscribed.sent[0]["asset_id"] == "asset-1"
    assert "relay_sent_ms" in subscribed.sent[0]
    assert other.sent == []


@pytest.mark.asyncio
async def test_polymarket_ws_sends_full_asset_subscription_batch():
    ws = PolymarketWebSocket()
    ws.ws = FakeWire()
    ws.state = WebSocketState.CONNECTED

    await ws.watch_orderbooks_by_assets({"asset-2": lambda *_: None, "asset-1": lambda *_: None})

    message = ws.ws.sent[-1]
    assert set(message["assets_ids"]) == {"asset-1", "asset-2"}
    assert message["custom_feature_enabled"] is True
    assert message["type"] == "market"


def test_polymarket_ws_price_change_updates_cached_depth_for_multiple_assets():
    ws = PolymarketWebSocket()
    ws._parse_book_message(
        {
            "event_type": "book",
            "market": "m1",
            "asset_id": "asset-1",
            "timestamp": 1,
            "bids": [{"price": "0.40", "size": "10"}],
            "asks": [{"price": "0.42", "size": "12"}],
        }
    )

    updates = ws._parse_price_change_message(
        {
            "event_type": "price_change",
            "market": "m1",
            "timestamp": 2,
            "price_changes": [
                {"asset_id": "asset-1", "side": "BUY", "price": "0.41", "size": "3"},
                {"asset_id": "asset-2", "side": "SELL", "price": "0.61", "size": "4"},
            ],
        }
    )

    assert [update["asset_id"] for update in updates] == ["asset-1", "asset-2"]
    assert updates[0]["bids"][0] == (0.41, 3.0)
    assert updates[1]["asks"] == [(0.61, 4.0)]
