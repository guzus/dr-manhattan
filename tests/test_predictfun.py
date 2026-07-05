"""Tests for Predict.fun exchange implementation."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from dr_manhattan.base.errors import AuthenticationError, ExchangeError, InvalidOrder
from dr_manhattan.exchanges.predictfun import PredictFun
from dr_manhattan.exchanges.predictfun_ws import PredictFunWebSocket
from dr_manhattan.models.order import OrderSide, OrderStatus


class TestPredictFunProperties:
    def test_properties(self):
        exchange = PredictFun()
        assert exchange.id == "predict.fun"
        assert exchange.name == "Predict.fun"

    def test_initialization_defaults_to_mainnet(self):
        exchange = PredictFun()
        assert exchange.testnet is False
        assert exchange.host

    def test_initialization_testnet(self):
        exchange = PredictFun({"testnet": True})
        assert exchange.testnet is True


class TestPredictFunAuthGuards:
    def test_create_order_without_auth_raises(self):
        exchange = PredictFun()
        with pytest.raises(AuthenticationError):
            exchange.create_order(
                market_id="m", outcome="Yes", side=OrderSide.BUY, price=0.5, size=10
            )


class TestPredictFunParsing:
    def test_parse_order_status(self):
        exchange = PredictFun()
        assert exchange._parse_order_status("FILLED") == OrderStatus.FILLED
        assert exchange._parse_order_status("matched") == OrderStatus.FILLED
        assert exchange._parse_order_status("CANCELED") == OrderStatus.CANCELLED
        assert exchange._parse_order_status("EXPIRED") == OrderStatus.CANCELLED
        assert exchange._parse_order_status("INVALIDATED") == OrderStatus.REJECTED
        assert exchange._parse_order_status("") == OrderStatus.OPEN
        assert exchange._parse_order_status("something-else") == OrderStatus.OPEN

    def test_parse_position_converts_wei_to_shares(self):
        exchange = PredictFun()
        data = {
            "marketId": "42",
            "outcome": {"name": "Yes"},
            "amount": str(3 * 10**18),  # 3 shares in 18-decimal wei
            "avgPrice": "0.5",
            "currentPrice": "0.55",
        }

        pos = exchange._parse_position(data)

        assert pos.market_id == "42"
        assert pos.outcome == "Yes"
        assert pos.size == 3.0
        assert pos.average_price == 0.5
        assert pos.current_price == 0.55

    def test_parse_datetime(self):
        exchange = PredictFun()
        assert exchange._parse_datetime(None) is None
        assert exchange._parse_datetime("invalid") is None
        assert exchange._parse_datetime("2025-01-01T00:00:00Z") is not None

        existing = datetime(2025, 1, 1, tzinfo=timezone.utc)
        assert exchange._parse_datetime(existing) == existing


def test_parse_market_sets_normalized_times():
    """Test Predict.fun parser maps API time fields to Market accessors."""
    exchange = PredictFun({})

    market = exchange._parse_market(
        {
            "id": 483522,
            "title": "World Cup match?",
            "outcomes": [
                {"name": "Team A", "onChainId": "1"},
                {"name": "Team B", "onChainId": "2"},
            ],
            "startTime": "2026-06-21T16:00:00Z",
            "expirationTimestamp": 1782144000000,
            "status": "REGISTERED",
            "decimalPrecision": 2,
        }
    )

    assert market.start_time == datetime(2026, 6, 21, 16, 0, tzinfo=timezone.utc)
    assert market.end_time == datetime.fromtimestamp(1782144000, timezone.utc)
    assert market.close_time == market.end_time


def test_parse_category_as_market_sets_normalized_times():
    """Test Predict.fun category fallback builds a complete Market with timing."""
    exchange = PredictFun({})

    market = exchange._parse_category_as_market(
        {
            "id": 1,
            "title": "World Cup category market?",
            "slug": "world-cup-category",
            "outcomes": [
                {"name": "Yes", "onChainId": "1"},
                {"name": "No", "onChainId": "2"},
            ],
            "endTime": "2026-06-22T00:00:00Z",
            "decimalPrecision": 3,
        }
    )

    assert market.id == "1"
    assert market.end_time == datetime(2026, 6, 22, 0, 0, tzinfo=timezone.utc)
    assert market.tick_size == 0.001


def test_parse_market_current_schema_metadata_and_tokens():
    exchange = PredictFun({"api_key": "test"})

    market = exchange._parse_market(
        {
            "id": 1518,
            "title": "Spain",
            "question": "Will Spain win the 2026 FIFA World Cup?",
            "description": "Resolves to Yes if Spain wins.",
            "tradingStatus": "OPEN",
            "status": "REGISTERED",
            "isNegRisk": False,
            "isYieldBearing": True,
            "feeRateBps": 0,
            "conditionId": "0xabc",
            "categorySlug": "2026-fifa-world-cup-winner",
            "decimalPrecision": 3,
            "marketVariant": "SPORTS_TEAM_MATCH",
            "outcomes": [
                {"name": "Yes", "indexSet": 1, "onChainId": "111"},
                {"name": "No", "indexSet": 2, "onChainId": "222"},
            ],
        }
    )

    assert market.id == "1518"
    assert market.outcomes == ["Yes", "No"]
    assert market.tick_size == 0.001
    assert market.is_open is True
    assert market.metadata["clobTokenIds"] == ["111", "222"]
    assert market.metadata["tokens"] == {"Yes": "111", "No": "222"}
    assert market.metadata["marketVariant"] == "SPORTS_TEAM_MATCH"
    assert exchange._token_to_market["111"] == "1518"
    assert exchange._token_to_index["222"] == 1


def test_parse_market_treats_cancel_only_as_closed():
    exchange = PredictFun({"api_key": "test"})

    market = exchange._parse_market(
        {
            "id": 1,
            "title": "Closed market",
            "tradingStatus": "CANCEL_ONLY",
            "status": "REGISTERED",
            "outcomes": [],
        }
    )

    assert market.is_open is False


def test_parse_position_current_schema_uses_value_usd():
    exchange = PredictFun({"api_key": "test"})

    position = exchange._parse_position(
        {
            "amount": "100000000000000000000",
            "averageBuyPriceUsd": "0.12",
            "valueUsd": "1",
            "market": {"id": 374798},
            "outcome": {"name": "Yes"},
        }
    )

    assert position.market_id == "374798"
    assert position.outcome == "Yes"
    assert position.size == 100
    assert position.average_price == 0.12
    assert position.current_price == 0.01
    assert position.current_value == 1
    assert position.unrealized_pnl == -11


def test_fetch_markets_forwards_current_filters(monkeypatch):
    exchange = PredictFun({"api_key": "test"})
    captured = {}

    def fake_request(method, endpoint, params=None, data=None, require_auth=False):
        captured.update({"method": method, "endpoint": endpoint, "params": params})
        return {"success": True, "cursor": None, "data": []}

    monkeypatch.setattr(exchange, "_request", fake_request)

    markets = exchange.fetch_markets(
        {
            "limit": 250,
            "active": False,
            "categorySlug": "fifwc-nld-mar-2026-06-29",
            "marketVariant": "SPORTS_TEAM_MATCH",
            "sort": "VOLUME_TOTAL_DESC",
            "tagIds": "1,2",
            "hasActiveRewards": True,
        }
    )

    assert markets == []
    assert captured["endpoint"] == "/v1/markets"
    assert captured["params"] == {
        "first": 100,
        "categorySlug": "fifwc-nld-mar-2026-06-29",
        "marketVariant": "SPORTS_TEAM_MATCH",
        "sort": "VOLUME_TOTAL_DESC",
        "tagIds": "1,2",
        "hasActiveRewards": True,
    }


def test_search_markets_expands_category_markets_before_direct_hits(monkeypatch):
    exchange = PredictFun({"api_key": "test"})

    def fake_request(method, endpoint, params=None, data=None, require_auth=False):
        assert endpoint == "/v1/search"
        assert params["query"] == "2026 fifa world cup winner"
        assert params["limit"] == "25"
        return {
            "success": True,
            "data": {
                "categories": [
                    {
                        "slug": "2026-fifa-world-cup-winner",
                        "markets": [
                            {
                                "id": 1518,
                                "question": "Will Spain win the 2026 FIFA World Cup?",
                                "tradingStatus": "OPEN",
                                "status": "REGISTERED",
                                "outcomes": [{"name": "Yes", "onChainId": "111"}],
                            }
                        ],
                    }
                ],
                "markets": [
                    {
                        "id": 1518,
                        "question": "Duplicate direct hit",
                        "tradingStatus": "OPEN",
                        "status": "REGISTERED",
                        "outcomes": [{"name": "Yes", "onChainId": "111"}],
                    },
                    {
                        "id": 440853,
                        "question": "Will a first-time winner win the World Cup?",
                        "tradingStatus": "OPEN",
                        "status": "REGISTERED",
                        "outcomes": [{"name": "Yes", "onChainId": "333"}],
                    },
                ],
            },
        }

    monkeypatch.setattr(exchange, "_request", fake_request)

    markets = exchange.search_markets("2026 fifa world cup winner")

    assert [market.id for market in markets] == ["1518", "440853"]
    assert markets[0].question == "Will Spain win the 2026 FIFA World Cup?"


def test_search_categories_returns_raw_category_hits(monkeypatch):
    exchange = PredictFun({"api_key": "test"})

    def fake_request(method, endpoint, params=None, data=None, require_auth=False):
        assert endpoint == "/v1/search"
        assert params["query"] == "Netherlands Morocco"
        return {
            "success": True,
            "data": {
                "categories": [
                    {
                        "slug": "fifwc-nld-mar-2026-06-29-first-to-score",
                        "parentSlug": "fifwc-nld-mar-2026-06-29",
                        "markets": [],
                    }
                ],
                "markets": [],
            },
        }

    monkeypatch.setattr(exchange, "_request", fake_request)

    categories = exchange.search_categories("Netherlands Morocco")

    assert categories == [
        {
            "slug": "fifwc-nld-mar-2026-06-29-first-to-score",
            "parentSlug": "fifwc-nld-mar-2026-06-29",
            "markets": [],
        }
    ]


def test_fetch_category_markets_by_slug_does_not_keyword_fallback(monkeypatch):
    exchange = PredictFun({"api_key": "test"})

    def fake_request(method, endpoint, params=None, data=None, require_auth=False):
        assert endpoint == "/v1/categories/fifwc-nld-mar-2026-06-29-first-to-score"
        return {
            "success": True,
            "data": {
                "slug": "fifwc-nld-mar-2026-06-29-first-to-score",
                "markets": [
                    {
                        "id": 593908,
                        "title": "NLD",
                        "question": "Netherlands to score first vs. Morocco?",
                        "categorySlug": "fifwc-nld-mar-2026-06-29-first-to-score",
                        "marketType": "SPORTS_FIRST_TO_SCORE",
                        "tradingStatus": "OPEN",
                        "status": "REGISTERED",
                        "outcomes": [{"name": "Yes", "onChainId": "111"}],
                    }
                ],
            },
        }

    monkeypatch.setattr(exchange, "_request", fake_request)

    markets = exchange.fetch_category_markets_by_slug(
        "fifwc-nld-mar-2026-06-29-first-to-score", enrich=False
    )

    assert [market.id for market in markets] == ["593908"]
    assert markets[0].metadata["categorySlug"] == "fifwc-nld-mar-2026-06-29-first-to-score"


def test_fetch_markets_by_slug_falls_back_when_search_fails(monkeypatch):
    exchange = PredictFun({"api_key": "test"})

    def fake_request(method, endpoint, params=None, data=None, require_auth=False):
        if endpoint == "/v1/categories/not-a-category":
            raise ExchangeError("not found")
        if endpoint == "/v1/search":
            raise ExchangeError("search unavailable")
        if endpoint == "/v1/markets":
            return {
                "success": True,
                "cursor": None,
                "data": [
                    {
                        "id": 1,
                        "question": "Will a not category market resolve?",
                        "tradingStatus": "OPEN",
                        "status": "REGISTERED",
                        "outcomes": [{"name": "Yes", "onChainId": "111"}],
                    }
                ],
            }
        raise AssertionError(endpoint)

    monkeypatch.setattr(exchange, "_request", fake_request)

    markets = exchange.fetch_markets_by_slug("not-a-category")

    assert [market.id for market in markets] == ["1"]


def test_get_orderbook_normalizes_tuples_and_inverts_no_token(monkeypatch):
    exchange = PredictFun({"api_key": "test"})
    exchange._token_to_market["no-token"] = "1518"
    exchange._token_to_index["no-token"] = 1
    exchange._market_decimal_precision["1518"] = 3

    def fake_request(method, endpoint, params=None, data=None, require_auth=False):
        assert endpoint == "/v1/markets/1518/orderbook"
        return {
            "success": True,
            "data": {
                "marketId": 1518,
                "updateTimestampMs": 123456,
                "bids": [[0.14, 100.0]],
                "asks": [[0.141, 200.0]],
            },
        }

    monkeypatch.setattr(exchange, "_request", fake_request)

    orderbook = exchange.get_orderbook("no-token")

    assert orderbook["market_id"] == "1518"
    assert orderbook["timestamp"] == 123456
    assert orderbook["bids"] == [{"price": "0.859", "size": "200.0"}]
    assert orderbook["asks"] == [{"price": "0.86", "size": "100.0"}]


def test_create_order_options_passthrough_for_market():
    data = {"pricePerShare": "100000000000000000", "strategy": "MARKET", "order": {}}

    PredictFun._apply_create_order_options(
        data,
        {
            "post_only": True,
            "fill_or_kill": False,
            "reserved_balance_policy": "SKIP_RESERVED_BALANCE_CHECKS",
            "is_min_amount_out": True,
            "self_trade_prevention": "CANCEL_BOTH",
        },
    )

    assert data["isPostOnly"] is True
    assert data["isFillOrKill"] is False
    assert data["reservedBalancePolicy"] == "SKIP_RESERVED_BALANCE_CHECKS"
    assert data["isMinAmountOut"] is True
    assert data["selfTradePrevention"] == "CANCEL_BOTH"


def test_create_order_options_reject_reserved_policy_on_limit():
    data = {"pricePerShare": "100000000000000000", "strategy": "LIMIT", "order": {}}

    with pytest.raises(InvalidOrder, match="reservedBalancePolicy"):
        PredictFun._apply_create_order_options(
            data,
            {"reserved_balance_policy": "SKIP_RESERVED_BALANCE_CHECKS"},
        )


def test_order_strategy_requires_explicit_market_opt_in():
    with pytest.raises(InvalidOrder, match="allow_market_order"):
        PredictFun._normalize_order_strategy({"strategy": "MARKET"})

    assert (
        PredictFun._normalize_order_strategy({"strategy": "MARKET", "allow_market_order": True})
        == "MARKET"
    )
    assert PredictFun._normalize_order_strategy({}) == "LIMIT"


def test_create_order_limit_payload_matches_signed_amounts(monkeypatch):
    exchange = PredictFun({"api_key": "test"})
    market = exchange._parse_market(
        {
            "id": 1520,
            "title": "Will France win the 2026 FIFA World Cup?",
            "feeRateBps": 0,
            "isNegRisk": False,
            "isYieldBearing": True,
            "outcomes": [
                {"name": "Yes", "onChainId": "yes-token"},
                {"name": "No", "onChainId": "no-token"},
            ],
        }
    )
    captured = {}

    def fake_signed_order(**kwargs):
        amounts = PredictFun._quantized_limit_amounts(
            kwargs["price"], kwargs["size"], kwargs["side"]
        )
        return {
            "makerAmount": str(amounts["maker"]),
            "takerAmount": str(amounts["taker"]),
        }

    def fake_request(method, endpoint, params=None, data=None, require_auth=False):
        captured.update({"method": method, "endpoint": endpoint, "data": data})
        return {"success": True, "data": {"orderId": "123"}}

    monkeypatch.setattr(exchange, "_ensure_authenticated", lambda: None)
    monkeypatch.setattr(exchange, "_is_using_smart_wallet", lambda: True)
    monkeypatch.setattr(exchange, "fetch_market", lambda market_id: market)
    monkeypatch.setattr(exchange, "_build_signed_order", fake_signed_order)
    monkeypatch.setattr(exchange, "_request", fake_request)
    exchange._owner_account = object()
    exchange._address = "0xabc"

    order = exchange.create_order("1520", "Yes", OrderSide.BUY, 0.358, 2.793)

    data = captured["data"]["data"]
    assert order.id == "123"
    assert data["strategy"] == "LIMIT"
    assert data["pricePerShare"] == str(
        PredictFun._quantized_limit_amounts(0.358, 2.793, OrderSide.BUY)["price_per_share"]
    )
    assert data["amount"] == data["order"]["takerAmount"]
    assert data["pricePaid"] == data["order"]["makerAmount"]


def test_quantized_limit_amounts_match_signed_bid_for_fractional_buy():
    amounts = PredictFun._quantized_limit_amounts(
        price=0.33,
        size=96.969697,
        side=OrderSide.BUY,
    )

    assert amounts["maker"] == amounts["notional"]
    assert amounts["taker"] == amounts["shares"]
    assert amounts["shares"] == 96969000000000000000
    assert amounts["maker"] % 10**13 == 0
    assert amounts["taker"] % 10**15 == 0


def test_quantized_limit_amounts_match_signed_ask_for_fractional_sell():
    amounts = PredictFun._quantized_limit_amounts(
        price=0.83,
        size=38.554217,
        side=OrderSide.SELL,
    )

    assert amounts["maker"] == amounts["shares"]
    assert amounts["taker"] == amounts["notional"]
    assert amounts["shares"] == 38554000000000000000
    assert amounts["maker"] % 10**15 == 0
    assert amounts["taker"] % 10**13 == 0


def test_merge_positions_uses_market_metadata_and_18_decimal_amount(monkeypatch):
    exchange = PredictFun({"api_key": "test"})
    market = exchange._parse_market(
        {
            "id": 607092,
            "title": "Will Norway win?",
            "conditionId": "0xabc",
            "isNegRisk": False,
            "isYieldBearing": True,
            "outcomes": [
                {"name": "Yes", "onChainId": "1"},
                {"name": "No", "onChainId": "2"},
            ],
        }
    )
    calls = []

    class FakeBuilder:
        def merge_positions(self, condition_id, amount, *, is_neg_risk, is_yield_bearing):
            calls.append(
                {
                    "condition_id": condition_id,
                    "amount": amount,
                    "is_neg_risk": is_neg_risk,
                    "is_yield_bearing": is_yield_bearing,
                }
            )
            return SimpleNamespace(
                success=True,
                receipt={"transactionHash": bytes.fromhex("12" * 32)},
            )

    monkeypatch.setattr(exchange, "_ensure_authenticated", lambda: None)
    monkeypatch.setattr(exchange, "fetch_market", lambda market_id: market)
    monkeypatch.setattr(exchange, "_get_order_builder", lambda: FakeBuilder())

    result = exchange.merge_positions("607092", 19.720855)

    assert calls == [
        {
            "condition_id": "0xabc",
            "amount": 19720000000000000000,
            "is_neg_risk": False,
            "is_yield_bearing": True,
        }
    ]
    assert result["amount"] == 19.72
    assert result["tx_hash"] == "12" * 32


def test_predictfun_web3_injects_poa_middleware():
    exchange = PredictFun({"api_key": "test"})

    middleware_names = [name for _, name in exchange._web3.middleware_onion.middleware]

    assert any("FormattingMiddlewareBuilder" in name for name in middleware_names)


def test_merge_positions_raises_when_builder_fails(monkeypatch):
    exchange = PredictFun({"api_key": "test"})

    class FakeBuilder:
        def merge_positions(self, *args, **kwargs):
            return SimpleNamespace(success=False, cause=RuntimeError("revert"))

    monkeypatch.setattr(exchange, "_ensure_authenticated", lambda: None)
    monkeypatch.setattr(exchange, "_get_order_builder", lambda: FakeBuilder())

    with pytest.raises(ExchangeError, match="revert"):
        exchange.merge_positions(
            "607092",
            1,
            {"condition_id": "0xabc", "is_neg_risk": False, "is_yield_bearing": True},
        )


def test_extract_created_order_id_prefers_cancelable_order_id():
    assert (
        PredictFun._extract_created_order_id(
            {"orderId": "123", "orderHash": "0xabc", "hash": "0xdef"}
        )
        == "123"
    )
    assert PredictFun._extract_created_order_id({"orderHash": "0xabc"}) == "0xabc"


def test_fetch_open_orders_filters_market_id_client_side(monkeypatch):
    exchange = PredictFun({"api_key": "test"})
    exchange._authenticated = True

    def fake_request(method, endpoint, params=None, data=None, require_auth=False):
        assert endpoint == "/v1/orders"
        assert params["marketId"] == "1519"
        return {
            "success": True,
            "data": [
                {
                    "id": "1",
                    "marketId": 1519,
                    "status": "OPEN",
                    "side": "buy",
                    "amount": "100000000000000000000",
                    "price": "0.1",
                },
                {
                    "id": "2",
                    "marketId": 1523,
                    "status": "OPEN",
                    "side": "buy",
                    "amount": "100000000000000000000",
                    "price": "0.1",
                },
            ],
        }

    monkeypatch.setattr(exchange, "_request", fake_request)

    orders = exchange.fetch_open_orders(market_id="1519")

    assert [order.id for order in orders] == ["1"]


def test_fetch_orders_forwards_history_filters(monkeypatch):
    exchange = PredictFun({"api_key": "test"})
    exchange._authenticated = True
    captured = {}

    def fake_request(method, endpoint, params=None, data=None, require_auth=False):
        captured.update(
            {
                "method": method,
                "endpoint": endpoint,
                "params": params,
                "require_auth": require_auth,
            }
        )
        return {
            "success": True,
            "data": [
                {
                    "id": "1",
                    "marketId": 1519,
                    "status": "FILLED",
                    "side": "buy",
                    "amount": "100000000000000000000",
                    "amountFilled": "100000000000000000000",
                    "price": "0.1",
                },
                {
                    "id": "2",
                    "marketId": 1523,
                    "status": "FILLED",
                    "side": "buy",
                    "amount": "100000000000000000000",
                    "amountFilled": "100000000000000000000",
                    "price": "0.1",
                },
            ],
        }

    monkeypatch.setattr(exchange, "_request", fake_request)

    orders = exchange.fetch_orders(
        market_id="1519",
        status=OrderStatus.FILLED,
        limit=25,
        params={"after": "cursor-1"},
    )

    assert [order.id for order in orders] == ["1"]
    assert captured == {
        "method": "GET",
        "endpoint": "/v1/orders",
        "params": {
            "after": "cursor-1",
            "first": 25,
            "status": "FILLED",
            "marketId": "1519",
        },
        "require_auth": True,
    }


def test_fetch_order_matches_forwards_filters(monkeypatch):
    exchange = PredictFun({"api_key": "test"})
    captured = {}

    def fake_request(method, endpoint, params=None, data=None, require_auth=False):
        captured.update(
            {
                "method": method,
                "endpoint": endpoint,
                "params": params,
                "require_auth": require_auth,
            }
        )
        return {
            "success": True,
            "data": [{"transactionHash": "0xabc", "executedAt": "2026-06-17T00:00:00Z"}],
        }

    monkeypatch.setattr(exchange, "_request", fake_request)

    matches = exchange.fetch_order_matches(
        market_id="1519",
        signer_address="0x123",
        limit=20,
        params={"isSignerMaker": True},
    )

    assert matches == [{"transactionHash": "0xabc", "executedAt": "2026-06-17T00:00:00Z"}]
    assert captured == {
        "method": "GET",
        "endpoint": "/v1/orders/matches",
        "params": {
            "isSignerMaker": True,
            "first": 20,
            "marketId": "1519",
            "signerAddress": "0x123",
        },
        "require_auth": False,
    }


def test_predictfun_websocket_preserves_update_timestamp():
    ws = PredictFunWebSocket()

    parsed = ws._parse_orderbook_message(
        {
            "type": "M",
            "topic": "predictOrderbook/1518",
            "data": {
                "updateTimestampMs": 1782098035543,
                "bids": [{"price": "0.12", "size": "10"}],
                "asks": [{"price": "0.13", "size": "20"}],
            },
        }
    )

    assert parsed["timestamp"] == 1782098035543
    assert parsed["updateTimestampMs"] == 1782098035543


def test_parse_position_normalizes_outcome_to_market_label():
    exchange = PredictFun({"api_key": "test"})
    exchange._parse_market(
        {
            "id": 633385,
            "title": "Team to Advance",
            "question": "Canada vs. Morocco: Team to Advance",
            "tradingStatus": "OPEN",
            "status": "REGISTERED",
            "outcomes": [
                {"name": "CAN", "onChainId": "111"},
                {"name": "MAR", "onChainId": "222"},
            ],
        }
    )

    position = exchange._parse_position(
        {
            "market": {"id": 633385},
            "outcome": {"name": "Canada", "onChainId": "111"},
            "amount": int(5e18),
            "averageBuyPriceUsd": 0.33,
            "currentPrice": 0.4,
        }
    )

    assert position.outcome == "CAN"
    assert position.market_id == "633385"


def test_parse_position_keeps_label_when_market_unknown():
    exchange = PredictFun({"api_key": "test"})

    position = exchange._parse_position(
        {
            "market": {"id": 999999},
            "outcome": {"name": "Canada", "onChainId": "does-not-exist"},
            "amount": int(1e18),
            "currentPrice": 0.5,
        }
    )

    assert position.outcome == "Canada"
