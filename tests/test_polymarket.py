"""Tests for Polymarket exchange implementation"""

from unittest.mock import Mock, patch

import pytest

from dr_manhattan.base.errors import AuthenticationError, MarketNotFound
from dr_manhattan.exchanges.polymarket import Polymarket
from dr_manhattan.models.market import Market
from dr_manhattan.models.order import OrderSide, OrderStatus


def _market(**overrides):
    data = dict(
        id="0xmarket123",
        question="Test?",
        outcomes=["Yes", "No"],
        close_time=None,
        volume=0.0,
        liquidity=0.0,
        prices={"Yes": 0.6, "No": 0.4},
        metadata={"clobTokenIds": ["token1", "token2"]},
        tick_size=0.01,
    )
    data.update(overrides)
    return Market(**data)


def test_polymarket_properties():
    """Test Polymarket exchange properties"""
    exchange = Polymarket()

    assert exchange.id == "polymarket"
    assert exchange.name == "Polymarket"
    assert exchange.BASE_URL == "https://gamma-api.polymarket.com"


def test_polymarket_initialization():
    """Test Polymarket initialization without private key"""
    config = {"timeout": 45}
    exchange = Polymarket(config)

    assert exchange.timeout == 45
    assert exchange._clob_client is None


def test_polymarket_initialization_with_private_key():
    """Test Polymarket initialization with private key fails with invalid key"""
    config = {
        "private_key": "test_key",
        "condition_id": "test_condition",
        "yes_token_id": "yes_token",
        "no_token_id": "no_token",
    }

    # Should raise error with invalid private key format
    with pytest.raises(AuthenticationError, match="Failed to initialize CLOB client"):
        Polymarket(config)


@patch("requests.get")
def test_fetch_markets(mock_get):
    """Test fetching markets from CLOB API"""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [
            {
                "condition_id": "0xabc123",
                "question_id": "0xdef456",
                "tokens": [
                    {"token_id": "token1", "outcome": "Yes", "price": 0.6},
                    {"token_id": "token2", "outcome": "No", "price": 0.4},
                ],
                "active": True,
                "closed": False,
                "accepting_orders": True,
                "minimum_tick_size": 0.01,
            }
        ]
    }
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response

    exchange = Polymarket()
    markets = exchange.fetch_markets()

    assert len(markets) == 1
    assert markets[0].id == "0xabc123"
    assert markets[0].prices == {"Yes": 0.6, "No": 0.4}


@patch.object(Polymarket, "fetch_token_ids", return_value=["token1", "token2"])
@patch("requests.get")
def test_fetch_market(mock_get, mock_fetch_token_ids):
    """Test fetching a specific market"""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {
            "id": "0xmarket123",
            "question": "Test question?",
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["0.5", "0.5"]',
            "clobTokenIds": '["token1", "token2"]',
            "active": True,
            "closed": False,
            "minimum_tick_size": 0.01,
        }
    ]
    mock_get.return_value = mock_response

    exchange = Polymarket()
    market = exchange.fetch_market("0xmarket123")

    assert market.id == "0xmarket123"
    assert market.question == "Test question?"
    mock_fetch_token_ids.assert_called_once_with("0xmarket123")


@patch("requests.get")
def test_fetch_market_not_found(mock_get):
    """Test fetching non-existent market"""
    mock_response = Mock()
    mock_response.status_code = 404
    mock_response.json.return_value = []
    mock_get.return_value = mock_response

    exchange = Polymarket()

    with pytest.raises(MarketNotFound):
        exchange.fetch_market("invalid_market")


def test_create_order_without_client():
    """Test creating order without authenticated client raises error"""
    exchange = Polymarket()

    with pytest.raises(AuthenticationError, match="CLOB client not initialized"):
        exchange.create_order(
            market_id="market_123",
            outcome="Yes",
            side=OrderSide.BUY,
            price=0.65,
            size=100,
        )


def test_fetch_balance_without_client():
    """Test fetching balance without authenticated client raises error"""
    exchange = Polymarket()

    with pytest.raises(AuthenticationError, match="CLOB client not initialized"):
        exchange.fetch_balance()


def test_cancel_order_without_client():
    """Test canceling order without authenticated client raises error"""
    exchange = Polymarket()

    with pytest.raises(AuthenticationError, match="CLOB client not initialized"):
        exchange.cancel_order("order_123")


def test_fetch_open_orders_without_client():
    """Test fetching open orders without authenticated client raises error"""
    exchange = Polymarket()

    with pytest.raises(AuthenticationError, match="CLOB client not initialized"):
        exchange.fetch_open_orders()


def test_fetch_positions_without_client():
    """Test fetching positions without authenticated client raises error"""
    exchange = Polymarket()

    with pytest.raises(AuthenticationError, match="CLOB client not initialized"):
        exchange.fetch_positions()


def test_fetch_positions_without_market_id_returns_empty():
    """Without a market_id there is no token context, so an empty list is correct."""
    exchange = Polymarket()
    exchange._clob_client = Mock()

    assert exchange.fetch_positions() == []


@patch.object(Polymarket, "fetch_market")
def test_fetch_positions_delegates_to_market_lookup(mock_fetch_market):
    """fetch_positions(market_id) resolves the market and returns real token balances."""
    # #given an authenticated client holding 5 YES shares and no NO shares
    exchange = Polymarket()
    exchange._clob_client = Mock()
    exchange._clob_client.get_balance_allowance.side_effect = [
        {"balance": "5000000"},  # token1 (Yes): 5.0 shares at 6 decimals
        {"balance": "0"},  # token2 (No): flat
    ]
    mock_fetch_market.return_value = _market()

    # #when
    positions = exchange.fetch_positions(market_id="0xmarket123")

    # #then the market is resolved once and the wei balance becomes a real position
    mock_fetch_market.assert_called_once_with("0xmarket123")
    assert len(positions) == 1
    assert positions[0].outcome == "Yes"
    assert positions[0].size == 5.0
    assert positions[0].current_price == 0.6


@patch.object(Polymarket, "fetch_market", side_effect=MarketNotFound("nope"))
def test_fetch_positions_propagates_lookup_error(mock_fetch_market):
    """A lookup failure must raise, not be silently reported as a flat book."""
    exchange = Polymarket()
    exchange._clob_client = Mock()

    with pytest.raises(MarketNotFound):
        exchange.fetch_positions(market_id="0xmarket123")


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
