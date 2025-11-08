"""Tests for base Exchange class"""

import pytest
from dr_manhattan.base.exchange import Exchange
from dr_manhattan.models.market import Market
from dr_manhattan.models.order import Order, OrderSide
from dr_manhattan.models.position import Position


class MockExchange(Exchange):
    """Mock exchange for testing base class"""

    @property
    def id(self) -> str:
        return "mock"

    @property
    def name(self) -> str:
        return "Mock Exchange"

    def fetch_markets(self, params=None):
        return []

    def fetch_market(self, market_id: str):
        return Market(
            id=market_id,
            question="Test question?",
            outcomes=["Yes", "No"],
            close_time=None,
            volume=0,
            liquidity=0,
            prices={"Yes": 0.5, "No": 0.5},
            metadata={}
        )

    def create_order(self, market_id, outcome, side, price, size, params=None):
        return Order(
            id="test_order",
            market_id=market_id,
            outcome=outcome,
            side=side,
            price=price,
            size=size,
            filled=0,
            status=None,
            created_at=None,
            updated_at=None
        )

    def cancel_order(self, order_id, market_id=None):
        return Order(
            id=order_id,
            market_id=market_id or "",
            outcome="",
            side=OrderSide.BUY,
            price=0,
            size=0,
            filled=0,
            status=None,
            created_at=None,
            updated_at=None
        )

    def fetch_order(self, order_id, market_id=None):
        return Order(
            id=order_id,
            market_id=market_id or "",
            outcome="",
            side=OrderSide.BUY,
            price=0,
            size=0,
            filled=0,
            status=None,
            created_at=None,
            updated_at=None
        )

    def fetch_open_orders(self, market_id=None, params=None):
        return []

    def fetch_positions(self, market_id=None, params=None):
        return []

    def fetch_balance(self):
        return {"USDC": 1000.0}


def test_exchange_initialization():
    """Test exchange initialization with config"""
    config = {
        'api_key': 'test_key',
        'api_secret': 'test_secret',
        'timeout': 60,
        'verbose': True
    }
    exchange = MockExchange(config)

    assert exchange.api_key == 'test_key'
    assert exchange.api_secret == 'test_secret'
    assert exchange.timeout == 60
    assert exchange.verbose is True


def test_exchange_default_config():
    """Test exchange initialization with default config"""
    exchange = MockExchange()

    assert exchange.api_key is None
    assert exchange.api_secret is None
    assert exchange.timeout == 30
    assert exchange.verbose is False


def test_exchange_properties():
    """Test exchange properties"""
    exchange = MockExchange()

    assert exchange.id == "mock"
    assert exchange.name == "Mock Exchange"


def test_exchange_describe():
    """Test exchange describe method"""
    exchange = MockExchange()
    desc = exchange.describe()

    assert desc['id'] == "mock"
    assert desc['name'] == "Mock Exchange"
    assert 'has' in desc
    assert desc['has']['fetch_markets'] is True
    assert desc['has']['create_order'] is True
    assert desc['has']['fetch_balance'] is True


def test_fetch_market():
    """Test fetching a single market"""
    exchange = MockExchange()
    market = exchange.fetch_market("test_market")

    assert market.id == "test_market"
    assert market.question == "Test question?"
    assert market.outcomes == ["Yes", "No"]


def test_create_order():
    """Test creating an order"""
    exchange = MockExchange()
    order = exchange.create_order(
        market_id="test_market",
        outcome="Yes",
        side=OrderSide.BUY,
        price=0.65,
        size=100
    )

    assert order.id == "test_order"
    assert order.market_id == "test_market"
    assert order.outcome == "Yes"
    assert order.side == OrderSide.BUY
    assert order.price == 0.65
    assert order.size == 100


def test_fetch_balance():
    """Test fetching account balance"""
    exchange = MockExchange()
    balance = exchange.fetch_balance()

    assert "USDC" in balance
    assert balance["USDC"] == 1000.0


def test_fetch_markets():
    """Test fetching markets"""
    exchange = MockExchange()
    markets = exchange.fetch_markets()

    assert isinstance(markets, list)
    assert len(markets) == 0


def test_fetch_open_orders():
    """Test fetching open orders"""
    exchange = MockExchange()
    orders = exchange.fetch_open_orders()

    assert isinstance(orders, list)
    assert len(orders) == 0


def test_fetch_positions():
    """Test fetching positions"""
    exchange = MockExchange()
    positions = exchange.fetch_positions()

    assert isinstance(positions, list)
    assert len(positions) == 0
