"""Tests for Limitless exchange implementation"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from dr_manhattan.exchanges.limitless import Limitless
from dr_manhattan.models.order import OrderSide, OrderStatus
from dr_manhattan.base.errors import ExchangeError, MarketNotFound


def test_limitless_properties():
    """Test Limitless exchange properties"""
    exchange = Limitless()

    assert exchange.id == "limitless"
    assert exchange.name == "Limitless"
    assert exchange.BASE_URL == "https://limitless.exchange/api"


def test_limitless_initialization():
    """Test Limitless initialization without private key"""
    config = {'timeout': 45}
    exchange = Limitless(config)

    assert exchange.timeout == 45
    assert exchange.auth_manager is None


def test_limitless_initialization_with_private_key():
    """Test Limitless initialization with private key fails gracefully"""
    config = {'private_key': 'test_key'}

    # Should raise error if limitless-mm not available
    with pytest.raises(ExchangeError, match="limitless-mm package not available"):
        exchange = Limitless(config)


def test_request_without_auth():
    """Test making request without authentication"""
    exchange = Limitless()

    with pytest.raises(ExchangeError, match="Not authenticated"):
        exchange._request("GET", "/markets")


@patch('dr_manhattan.exchanges.limitless.LIMITLESS_MM_AVAILABLE', True)
@patch('dr_manhattan.exchanges.limitless.AuthManager')
def test_fetch_markets(mock_auth_manager):
    """Test fetching markets"""
    # Mock auth manager
    mock_auth = Mock()
    mock_session = Mock()
    mock_response = Mock()
    mock_response.json.return_value = [
        {
            "id": "market_1",
            "title": "Will it rain tomorrow?",
            "outcomes": ["Yes", "No"],
            "closeDate": "2025-12-31T23:59:59Z",
            "volume": 10000,
            "liquidity": 5000,
            "yesPrice": 0.6,
            "noPrice": 0.4
        }
    ]
    mock_response.raise_for_status = Mock()
    mock_session.request.return_value = mock_response
    mock_auth.session = mock_session
    mock_auth.login.return_value = True
    mock_auth_manager.return_value = mock_auth

    exchange = Limitless({'private_key': 'test_key'})
    markets = exchange.fetch_markets()

    assert len(markets) == 1
    assert markets[0].id == "market_1"
    assert markets[0].question == "Will it rain tomorrow?"
    assert markets[0].volume == 10000
    assert markets[0].prices["Yes"] == 0.6


@patch('dr_manhattan.exchanges.limitless.LIMITLESS_MM_AVAILABLE', True)
@patch('dr_manhattan.exchanges.limitless.AuthManager')
def test_fetch_market(mock_auth_manager):
    """Test fetching a specific market"""
    mock_auth = Mock()
    mock_session = Mock()
    mock_response = Mock()
    mock_response.json.return_value = {
        "id": "market_123",
        "title": "Test question?",
        "outcomes": ["Yes", "No"],
        "closeDate": None,
        "volume": 5000,
        "liquidity": 2500,
        "yesPrice": 0.5,
        "noPrice": 0.5
    }
    mock_response.raise_for_status = Mock()
    mock_session.request.return_value = mock_response
    mock_auth.session = mock_session
    mock_auth.login.return_value = True
    mock_auth_manager.return_value = mock_auth

    exchange = Limitless({'private_key': 'test_key'})
    market = exchange.fetch_market("market_123")

    assert market.id == "market_123"
    assert market.question == "Test question?"
    assert market.volume == 5000


@patch('dr_manhattan.exchanges.limitless.LIMITLESS_MM_AVAILABLE', True)
@patch('dr_manhattan.exchanges.limitless.AuthManager')
def test_fetch_market_not_found(mock_auth_manager):
    """Test fetching non-existent market"""
    mock_auth = Mock()
    mock_session = Mock()
    mock_session.request.side_effect = Exception("Not found")
    mock_auth.session = mock_session
    mock_auth.login.return_value = True
    mock_auth_manager.return_value = mock_auth

    exchange = Limitless({'private_key': 'test_key'})

    with pytest.raises(MarketNotFound):
        exchange.fetch_market("invalid_market")


@patch('dr_manhattan.exchanges.limitless.LIMITLESS_MM_AVAILABLE', True)
@patch('dr_manhattan.exchanges.limitless.AuthManager')
def test_create_order(mock_auth_manager):
    """Test creating an order"""
    mock_auth = Mock()
    mock_session = Mock()
    mock_response = Mock()
    mock_response.json.return_value = {
        "id": "order_123",
        "marketId": "market_123",
        "outcome": "Yes",
        "side": "buy",
        "price": 0.65,
        "amount": 100,
        "filled": 0,
        "status": "open",
        "createdAt": "2025-01-01T00:00:00Z",
        "updatedAt": "2025-01-01T00:00:00Z"
    }
    mock_response.raise_for_status = Mock()
    mock_session.request.return_value = mock_response
    mock_auth.session = mock_session
    mock_auth.login.return_value = True
    mock_auth_manager.return_value = mock_auth

    exchange = Limitless({'private_key': 'test_key'})
    order = exchange.create_order(
        market_id="market_123",
        outcome="Yes",
        side=OrderSide.BUY,
        price=0.65,
        size=100
    )

    assert order.id == "order_123"
    assert order.market_id == "market_123"
    assert order.outcome == "Yes"
    assert order.side == OrderSide.BUY
    assert order.price == 0.65
    assert order.size == 100


@patch('dr_manhattan.exchanges.limitless.LIMITLESS_MM_AVAILABLE', True)
@patch('dr_manhattan.exchanges.limitless.AuthManager')
def test_fetch_balance(mock_auth_manager):
    """Test fetching account balance"""
    mock_auth = Mock()
    mock_session = Mock()
    mock_response = Mock()
    mock_response.json.return_value = {"balance": 1000.50}
    mock_response.raise_for_status = Mock()
    mock_session.request.return_value = mock_response
    mock_auth.session = mock_session
    mock_auth.login.return_value = True
    mock_auth_manager.return_value = mock_auth

    exchange = Limitless({'private_key': 'test_key'})
    balance = exchange.fetch_balance()

    assert "USD" in balance
    assert balance["USD"] == 1000.50


@patch('dr_manhattan.exchanges.limitless.LIMITLESS_MM_AVAILABLE', True)
@patch('dr_manhattan.exchanges.limitless.AuthManager')
def test_cancel_order(mock_auth_manager):
    """Test canceling an order"""
    mock_auth = Mock()
    mock_session = Mock()
    mock_response = Mock()
    mock_response.json.return_value = {
        "id": "order_123",
        "marketId": "market_123",
        "outcome": "Yes",
        "side": "buy",
        "price": 0.65,
        "amount": 100,
        "filled": 0,
        "status": "cancelled",
        "createdAt": "2025-01-01T00:00:00Z",
        "updatedAt": "2025-01-01T00:00:01Z"
    }
    mock_response.raise_for_status = Mock()
    mock_session.request.return_value = mock_response
    mock_auth.session = mock_session
    mock_auth.login.return_value = True
    mock_auth_manager.return_value = mock_auth

    exchange = Limitless({'private_key': 'test_key'})
    order = exchange.cancel_order("order_123")

    assert order.id == "order_123"
    assert order.status == OrderStatus.CANCELLED


@patch('dr_manhattan.exchanges.limitless.LIMITLESS_MM_AVAILABLE', True)
@patch('dr_manhattan.exchanges.limitless.AuthManager')
def test_fetch_open_orders(mock_auth_manager):
    """Test fetching open orders"""
    mock_auth = Mock()
    mock_session = Mock()
    mock_response = Mock()
    mock_response.json.return_value = [
        {
            "id": "order_1",
            "marketId": "market_123",
            "outcome": "Yes",
            "side": "buy",
            "price": 0.60,
            "amount": 50,
            "filled": 0,
            "status": "open",
            "createdAt": "2025-01-01T00:00:00Z",
            "updatedAt": "2025-01-01T00:00:00Z"
        }
    ]
    mock_response.raise_for_status = Mock()
    mock_session.request.return_value = mock_response
    mock_auth.session = mock_session
    mock_auth.login.return_value = True
    mock_auth_manager.return_value = mock_auth

    exchange = Limitless({'private_key': 'test_key'})
    orders = exchange.fetch_open_orders()

    assert len(orders) == 1
    assert orders[0].id == "order_1"


@patch('dr_manhattan.exchanges.limitless.LIMITLESS_MM_AVAILABLE', True)
@patch('dr_manhattan.exchanges.limitless.AuthManager')
def test_fetch_positions(mock_auth_manager):
    """Test fetching positions"""
    mock_auth = Mock()
    mock_session = Mock()
    mock_response = Mock()
    mock_response.json.return_value = [
        {
            "marketId": "market_123",
            "outcome": "Yes",
            "size": 100,
            "averagePrice": 0.60,
            "currentPrice": 0.65
        }
    ]
    mock_response.raise_for_status = Mock()
    mock_session.request.return_value = mock_response
    mock_auth.session = mock_session
    mock_auth.login.return_value = True
    mock_auth_manager.return_value = mock_auth

    exchange = Limitless({'private_key': 'test_key'})
    positions = exchange.fetch_positions()

    assert len(positions) == 1
    assert positions[0].market_id == "market_123"
    assert positions[0].size == 100


def test_parse_order_status():
    """Test order status parsing"""
    exchange = Limitless()

    assert exchange._parse_order_status("pending") == OrderStatus.PENDING
    assert exchange._parse_order_status("open") == OrderStatus.OPEN
    assert exchange._parse_order_status("filled") == OrderStatus.FILLED
    assert exchange._parse_order_status("cancelled") == OrderStatus.CANCELLED
    assert exchange._parse_order_status("unknown") == OrderStatus.OPEN


def test_parse_datetime():
    """Test datetime parsing"""
    exchange = Limitless()

    # Test ISO format
    dt = exchange._parse_datetime("2025-01-01T00:00:00Z")
    assert dt is not None

    # Test None
    dt = exchange._parse_datetime(None)
    assert dt is None

    # Test timestamp
    dt = exchange._parse_datetime(1735689600)
    assert dt is not None

    # Test invalid
    dt = exchange._parse_datetime("invalid")
    assert dt is None
