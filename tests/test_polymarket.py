"""Tests for Polymarket exchange implementation"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from dr_manhattan.exchanges.polymarket import Polymarket
from dr_manhattan.models.order import OrderSide, OrderStatus
from dr_manhattan.base.errors import ExchangeError, MarketNotFound


def test_polymarket_properties():
    """Test Polymarket exchange properties"""
    exchange = Polymarket()

    assert exchange.id == "polymarket"
    assert exchange.name == "Polymarket"
    assert exchange.BASE_URL == "https://gamma-api.polymarket.com"


def test_polymarket_initialization():
    """Test Polymarket initialization without private key"""
    config = {'timeout': 45}
    exchange = Polymarket(config)

    assert exchange.timeout == 45
    assert exchange.poly_client is None


def test_polymarket_initialization_with_private_key():
    """Test Polymarket initialization with private key fails gracefully"""
    config = {
        'private_key': 'test_key',
        'condition_id': 'test_condition',
        'yes_token_id': 'yes_token',
        'no_token_id': 'no_token'
    }

    # Should raise error if poly-mm not available
    with pytest.raises(ExchangeError, match="poly-mm package not available"):
        exchange = Polymarket(config)


@patch('requests.request')
def test_fetch_markets(mock_request):
    """Test fetching markets"""
    mock_response = Mock()
    mock_response.json.return_value = [
        {
            "id": "market_1",
            "question": "Will it rain tomorrow?",
            "outcomes": ["Yes", "No"],
            "end_date": "2025-12-31T23:59:59Z",
            "volume": 10000,
            "liquidity": 5000,
            "prices": {"Yes": 0.6, "No": 0.4}
        }
    ]
    mock_response.raise_for_status = Mock()
    mock_request.return_value = mock_response

    exchange = Polymarket()
    markets = exchange.fetch_markets()

    assert len(markets) == 1
    assert markets[0].id == "market_1"
    assert markets[0].question == "Will it rain tomorrow?"
    assert markets[0].volume == 10000
    assert markets[0].prices == {"Yes": 0.6, "No": 0.4}


@patch('requests.request')
def test_fetch_market(mock_request):
    """Test fetching a specific market"""
    mock_response = Mock()
    mock_response.json.return_value = {
        "id": "market_123",
        "question": "Test question?",
        "outcomes": ["Yes", "No"],
        "end_date": None,
        "volume": 5000,
        "liquidity": 2500,
        "prices": {"Yes": 0.5, "No": 0.5}
    }
    mock_response.raise_for_status = Mock()
    mock_request.return_value = mock_response

    exchange = Polymarket()
    market = exchange.fetch_market("market_123")

    assert market.id == "market_123"
    assert market.question == "Test question?"
    assert market.volume == 5000


@patch('requests.request')
def test_fetch_market_not_found(mock_request):
    """Test fetching non-existent market"""
    from dr_manhattan.base.errors import ExchangeError
    mock_request.side_effect = ExchangeError("Not found")

    exchange = Polymarket()

    with pytest.raises(MarketNotFound):
        exchange.fetch_market("invalid_market")


@patch('requests.request')
def test_create_order_without_client(mock_request):
    """Test creating order without authenticated client"""
    mock_response = Mock()
    mock_response.json.return_value = {
        "id": "order_123",
        "market_id": "market_123",
        "outcome": "Yes",
        "side": "buy",
        "price": 0.65,
        "size": 100,
        "filled": 0,
        "status": "open",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z"
    }
    mock_response.raise_for_status = Mock()
    mock_request.return_value = mock_response

    exchange = Polymarket()
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


@patch('requests.request')
def test_fetch_balance_without_client(mock_request):
    """Test fetching balance without authenticated client"""
    mock_response = Mock()
    mock_response.json.return_value = {"balance": 1000.50}
    mock_response.raise_for_status = Mock()
    mock_request.return_value = mock_response

    exchange = Polymarket()
    balance = exchange.fetch_balance()

    assert "USDC" in balance
    assert balance["USDC"] == 1000.50


@patch('requests.request')
def test_cancel_order(mock_request):
    """Test canceling an order"""
    mock_response = Mock()
    mock_response.json.return_value = {
        "id": "order_123",
        "market_id": "market_123",
        "outcome": "Yes",
        "side": "buy",
        "price": 0.65,
        "size": 100,
        "filled": 0,
        "status": "cancelled",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:01Z"
    }
    mock_response.raise_for_status = Mock()
    mock_request.return_value = mock_response

    exchange = Polymarket()
    order = exchange.cancel_order("order_123")

    assert order.id == "order_123"
    assert order.status == OrderStatus.CANCELLED


@patch('requests.request')
def test_fetch_open_orders(mock_request):
    """Test fetching open orders"""
    mock_response = Mock()
    mock_response.json.return_value = [
        {
            "id": "order_1",
            "market_id": "market_123",
            "outcome": "Yes",
            "side": "buy",
            "price": 0.60,
            "size": 50,
            "filled": 0,
            "status": "open",
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z"
        },
        {
            "id": "order_2",
            "market_id": "market_456",
            "outcome": "No",
            "side": "sell",
            "price": 0.40,
            "size": 75,
            "filled": 0,
            "status": "open",
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z"
        }
    ]
    mock_response.raise_for_status = Mock()
    mock_request.return_value = mock_response

    exchange = Polymarket()
    orders = exchange.fetch_open_orders()

    assert len(orders) == 2
    assert orders[0].id == "order_1"
    assert orders[1].id == "order_2"


@patch('requests.request')
def test_fetch_positions(mock_request):
    """Test fetching positions"""
    mock_response = Mock()
    mock_response.json.return_value = [
        {
            "market_id": "market_123",
            "outcome": "Yes",
            "size": 100,
            "average_price": 0.60,
            "current_price": 0.65
        }
    ]
    mock_response.raise_for_status = Mock()
    mock_request.return_value = mock_response

    exchange = Polymarket()
    positions = exchange.fetch_positions()

    assert len(positions) == 1
    assert positions[0].market_id == "market_123"
    assert positions[0].size == 100
    assert positions[0].average_price == 0.60


def test_parse_order_status():
    """Test order status parsing"""
    exchange = Polymarket()

    assert exchange._parse_order_status("pending") == OrderStatus.PENDING
    assert exchange._parse_order_status("open") == OrderStatus.OPEN
    assert exchange._parse_order_status("filled") == OrderStatus.FILLED
    assert exchange._parse_order_status("cancelled") == OrderStatus.CANCELLED
    assert exchange._parse_order_status("unknown") == OrderStatus.OPEN


def test_parse_datetime():
    """Test datetime parsing"""
    exchange = Polymarket()

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
