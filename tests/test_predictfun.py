"""Tests for Predict.fun exchange implementation."""

from datetime import datetime, timezone

import pytest

from dr_manhattan.base.errors import AuthenticationError
from dr_manhattan.exchanges.predictfun import PredictFun
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
