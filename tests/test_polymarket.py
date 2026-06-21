"""Tests for Polymarket exchange implementation"""

from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest

from dr_manhattan.base.errors import AuthenticationError, MarketNotFound
from dr_manhattan.exchanges.polymarket import Polymarket
from dr_manhattan.models.order import OrderSide, OrderStatus


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
                "game_start_time": "2026-06-21T16:00:00Z",
                "end_date_iso": "2026-06-21T18:00:00Z",
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
    assert markets[0].start_time == datetime(2026, 6, 21, 16, 0, tzinfo=timezone.utc)
    assert markets[0].end_time == datetime(2026, 6, 21, 18, 0, tzinfo=timezone.utc)
    assert markets[0].close_time == markets[0].end_time


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


def test_parse_gamma_market_normalizes_event_times():
    """Test Gamma parser normalizes endDate but does not treat startDate as kickoff."""
    exchange = Polymarket()

    market = exchange._parse_market(
        {
            "id": "540817",
            "question": "New Rihanna Album before GTA VI?",
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["0.515", "0.485"]',
            "startDate": "2025-05-02T15:48:10.582Z",
            "endDate": "2026-07-31T12:00:00Z",
            "active": True,
            "closed": False,
        }
    )

    assert market.start_time is None
    assert market.end_time == datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
    assert market.event_time == market.end_time


def test_parse_gamma_market_uses_game_start_time():
    """Test Gamma parser maps game_start_time to normalized start_time."""
    exchange = Polymarket()

    market = exchange._parse_market(
        {
            "id": "sports-market",
            "question": "World Cup: Team A vs Team B",
            "outcomes": '["Team A", "Team B"]',
            "outcomePrices": '["0.5", "0.5"]',
            "startDate": "2026-06-01T00:00:00Z",
            "game_start_time": "2026-06-21T16:00:00Z",
            "endDate": "2026-06-22T00:00:00Z",
            "active": True,
            "closed": False,
        }
    )

    assert market.start_time == datetime(2026, 6, 21, 16, 0, tzinfo=timezone.utc)
    assert market.end_time == datetime(2026, 6, 22, 0, 0, tzinfo=timezone.utc)


def test_parse_gamma_market_normalizes_snake_case_end_date():
    """Test Gamma parser accepts snake_case end_date from API responses."""
    exchange = Polymarket()

    market = exchange._parse_market(
        {
            "id": "snake-case-end-date",
            "question": "Snake case end date?",
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["0.5", "0.5"]',
            "end_date": "2026-06-22T00:00:00Z",
            "active": True,
            "closed": False,
        }
    )

    assert market.end_time == datetime(2026, 6, 22, 0, 0, tzinfo=timezone.utc)


def test_parse_gamma_market_extracts_clob_token_ids_from_token_objects():
    """Test Gamma parser exposes clobTokenIds as strings when tokens are objects."""
    exchange = Polymarket()

    market = exchange._parse_market(
        {
            "id": "token-object-market",
            "question": "Token objects?",
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["0.6", "0.4"]',
            "tokens": [
                {"token_id": "token_yes", "outcome": "Yes"},
                {"token_id": "token_no", "outcome": "No"},
            ],
            "active": True,
            "closed": False,
        }
    )

    assert market.metadata["clobTokenIds"] == ["token_yes", "token_no"]
    assert market.metadata["tokens"][0]["token_id"] == "token_yes"
