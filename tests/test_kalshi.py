"""Tests for Kalshi exchange implementation"""

from unittest.mock import Mock, patch

import pytest

from dr_manhattan.base.errors import AuthenticationError, InvalidOrder, MarketNotFound
from dr_manhattan.exchanges.kalshi import Kalshi
from dr_manhattan.models.order import OrderSide, OrderStatus


class TestKalshiProperties:
    def test_kalshi_properties(self):
        # #given
        exchange = Kalshi()

        # #when / #then
        assert exchange.id == "kalshi"
        assert exchange.name == "Kalshi"
        assert exchange.BASE_URL == "https://api.elections.kalshi.com/trade-api/v2"


class TestKalshiInitialization:
    def test_initialization_without_auth(self):
        # #given
        config = {"timeout": 45}

        # #when
        exchange = Kalshi(config)

        # #then
        assert exchange.timeout == 45
        assert not exchange._is_authenticated()

    def test_initialization_with_demo(self):
        # #given
        config = {"demo": True}

        # #when
        exchange = Kalshi(config)

        # #then
        assert exchange._demo is True
        assert exchange._api_url == Kalshi.DEMO_URL


class TestKalshiFetchMarkets:
    @patch("requests.request")
    def test_fetch_markets(self, mock_request):
        # #given
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "markets": [
                {
                    "ticker": "INXD-24DEC31-B5000",
                    "title": "S&P 500 above 5000?",
                    "yes_bid": 65,
                    "yes_ask": 65,
                    "volume": 1000,
                    "status": "open",
                }
            ]
        }
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response

        exchange = Kalshi()

        # #when
        markets = exchange.fetch_markets()

        # #then
        assert len(markets) == 1
        assert markets[0].id == "INXD-24DEC31-B5000"
        assert markets[0].prices["Yes"] == 0.65
        assert markets[0].prices["No"] == 0.35

    @patch("requests.request")
    def test_fetch_market(self, mock_request):
        # #given
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "market": {
                "ticker": "INXD-24DEC31-B5000",
                "title": "S&P 500 above 5000?",
                "yes_bid": 60,
                "volume": 1000,
                "status": "open",
            }
        }
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response

        exchange = Kalshi()

        # #when
        market = exchange.fetch_market("INXD-24DEC31-B5000")

        # #then
        assert market.id == "INXD-24DEC31-B5000"
        assert market.question == "S&P 500 above 5000?"

    @patch("requests.request")
    def test_fetch_market_not_found(self, mock_request):
        # #given
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = Exception("Not found")
        mock_request.return_value = mock_response

        exchange = Kalshi()

        # #when / #then
        with pytest.raises(MarketNotFound):
            exchange.fetch_market("INVALID-TICKER")


class TestKalshiAuthentication:
    def test_create_order_without_auth(self):
        # #given
        exchange = Kalshi()

        # #when / #then
        with pytest.raises(AuthenticationError):
            exchange.create_order(
                market_id="INXD-24DEC31-B5000",
                outcome="Yes",
                side=OrderSide.BUY,
                price=0.65,
                size=10,
            )

    def test_fetch_balance_without_auth(self):
        # #given
        exchange = Kalshi()

        # #when / #then
        with pytest.raises(AuthenticationError):
            exchange.fetch_balance()

    def test_cancel_order_without_auth(self):
        # #given
        exchange = Kalshi()

        # #when / #then
        with pytest.raises(AuthenticationError):
            exchange.cancel_order("order_123")

    def test_fetch_open_orders_without_auth(self):
        # #given
        exchange = Kalshi()

        # #when / #then
        with pytest.raises(AuthenticationError):
            exchange.fetch_open_orders()

    def test_fetch_positions_without_auth(self):
        # #given
        exchange = Kalshi()

        # #when / #then
        with pytest.raises(AuthenticationError):
            exchange.fetch_positions()


class TestKalshiOrderValidation:
    def test_create_order_invalid_price_too_low(self):
        # #given
        exchange = Kalshi({"api_key_id": "test", "private_key_pem": _get_test_rsa_key()})

        # #when / #then
        with pytest.raises(InvalidOrder, match="Price must be between 0 and 1"):
            exchange.create_order(
                market_id="TEST",
                outcome="Yes",
                side=OrderSide.BUY,
                price=0,
                size=10,
            )

    def test_create_order_invalid_price_too_high(self):
        # #given
        exchange = Kalshi({"api_key_id": "test", "private_key_pem": _get_test_rsa_key()})

        # #when / #then
        with pytest.raises(InvalidOrder, match="Price must be between 0 and 1"):
            exchange.create_order(
                market_id="TEST",
                outcome="Yes",
                side=OrderSide.BUY,
                price=1,
                size=10,
            )

    def test_create_order_invalid_outcome(self):
        # #given
        exchange = Kalshi({"api_key_id": "test", "private_key_pem": _get_test_rsa_key()})

        # #when / #then
        with pytest.raises(InvalidOrder, match="Outcome must be 'Yes' or 'No'"):
            exchange.create_order(
                market_id="TEST",
                outcome="Maybe",
                side=OrderSide.BUY,
                price=0.5,
                size=10,
            )


class TestKalshiParsing:
    def test_parse_order_buy_yes(self):
        # #given
        exchange = Kalshi()
        data = {
            "order_id": "order_123",
            "ticker": "TEST-TICKER",
            "action": "buy",
            "side": "yes",
            "status": "resting",
            "yes_price": 55,
            "count": 10,
            "filled_count": 0,
        }

        # #when
        order = exchange._parse_order(data)

        # #then
        assert order.id == "order_123"
        assert order.market_id == "TEST-TICKER"
        assert order.side == OrderSide.BUY
        assert order.outcome == "Yes"
        assert order.status == OrderStatus.OPEN
        assert order.price == 0.55
        assert order.size == 10
        assert order.filled == 0

    def test_parse_order_sell_no(self):
        # #given
        exchange = Kalshi()
        data = {
            "order_id": "order_456",
            "ticker": "TEST-TICKER",
            "action": "sell",
            "side": "no",
            "status": "executed",
            "no_price": 40,
            "count": 5,
            "filled_count": 5,
        }

        # #when
        order = exchange._parse_order(data)

        # #then
        assert order.id == "order_456"
        assert order.side == OrderSide.SELL
        assert order.outcome == "No"
        assert order.status == OrderStatus.FILLED
        assert order.price == 0.40
        assert order.filled == 5

    def test_parse_position_positive(self):
        # #given
        exchange = Kalshi()
        data = {
            "ticker": "TEST-TICKER",
            "position": 100,
        }

        # #when
        position = exchange._parse_position(data)

        # #then
        assert position.market_id == "TEST-TICKER"
        assert position.outcome == "Yes"
        assert position.size == 100

    def test_parse_position_negative(self):
        # #given
        exchange = Kalshi()
        data = {
            "ticker": "TEST-TICKER",
            "position": -50,
        }

        # #when
        position = exchange._parse_position(data)

        # #then
        assert position.outcome == "No"
        assert position.size == 50


class TestKalshiDescribe:
    def test_describe(self):
        # #given
        exchange = Kalshi()

        # #when
        desc = exchange.describe()

        # #then
        assert desc["id"] == "kalshi"
        assert desc["name"] == "Kalshi"
        assert desc["has"]["fetch_markets"] is True
        assert desc["has"]["fetch_market"] is True
        assert desc["has"]["create_order"] is True
        assert desc["has"]["cancel_order"] is True
        assert desc["has"]["fetch_order"] is True
        assert desc["has"]["fetch_open_orders"] is True
        assert desc["has"]["fetch_positions"] is True
        assert desc["has"]["fetch_balance"] is True
        assert desc["has"]["get_websocket"] is False


def _get_test_rsa_key() -> str:
    """Generate a test RSA key for testing authentication initialization."""
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        return pem.decode("utf-8")
    except ImportError:
        pytest.skip("cryptography package not installed")
        return ""
