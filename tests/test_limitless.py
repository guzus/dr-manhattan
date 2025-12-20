"""Tests for Limitless exchange implementation."""

from unittest.mock import MagicMock, Mock, patch

import pytest

from dr_manhattan import Limitless, OrderSide, OrderStatus
from dr_manhattan.base.errors import (
    AuthenticationError,
    ExchangeError,
    InvalidOrder,
    MarketNotFound,
)


class TestLimitlessBasic:
    """Basic Limitless exchange tests."""

    def test_exchange_properties(self):
        """Test exchange id and name properties."""
        exchange = Limitless({})
        assert exchange.id == "limitless"
        assert exchange.name == "Limitless"
        assert exchange.BASE_URL == "https://api.limitless.exchange"
        assert exchange.CHAIN_ID == 8453

    def test_describe(self):
        """Test describe method returns correct capabilities."""
        exchange = Limitless({})
        info = exchange.describe()

        assert info["id"] == "limitless"
        assert info["name"] == "Limitless"
        assert info["chain_id"] == 8453
        assert info["has"]["fetch_markets"] is True
        assert info["has"]["create_order"] is True
        assert info["has"]["cancel_order"] is True
        assert info["has"]["fetch_positions"] is True
        assert info["has"]["fetch_balance"] is True
        assert info["has"]["get_orderbook"] is True
        assert info["has"]["search_markets"] is True
        assert info["has"]["fetch_price_history"] is True

    def test_initialization_without_credentials(self):
        """Test that exchange initializes without credentials."""
        exchange = Limitless({})
        assert exchange._authenticated is False
        assert exchange._account is None
        assert exchange._address is None

    def test_ensure_authenticated_raises_without_credentials(self):
        """Test that operations requiring auth raise AuthenticationError."""
        exchange = Limitless({})

        with pytest.raises(AuthenticationError):
            exchange._ensure_authenticated()

        with pytest.raises(AuthenticationError):
            exchange.fetch_balance()

        with pytest.raises(AuthenticationError):
            exchange.fetch_positions()


class TestLimitlessMarketParsing:
    """Test market parsing logic."""

    def test_parse_market_basic(self):
        """Test parsing basic market data."""
        exchange = Limitless({})

        mock_data = {
            "slug": "will-btc-reach-100k",
            "title": "Will BTC reach $100k?",
            "tokens": {"yes": "token_yes_123", "no": "token_no_456"},
            "yesPrice": 0.65,
            "noPrice": 0.35,
            "volume": 10000.0,
            "liquidity": 5000.0,
            "deadline": 1735689600,
            "status": "active",
        }

        market = exchange._parse_market(mock_data)

        assert market.id == "will-btc-reach-100k"
        assert market.question == "Will BTC reach $100k?"
        assert market.outcomes == ["Yes", "No"]
        assert market.volume == 10000.0
        assert market.liquidity == 5000.0
        assert market.prices["Yes"] == 0.65
        assert market.prices["No"] == 0.35
        assert market.metadata["clobTokenIds"] == ["token_yes_123", "token_no_456"]
        assert market.metadata["tokens"]["Yes"] == "token_yes_123"
        assert market.metadata["tokens"]["No"] == "token_no_456"

    def test_parse_market_with_nested_prices(self):
        """Test parsing market with nested price structure."""
        exchange = Limitless({})

        mock_data = {
            "slug": "test-market",
            "title": "Test Market?",
            "tokens": {"yes": "yes_token", "no": "no_token"},
            "prices": {"yes": 0.50, "no": 0.50},
            "volume": 1000,
            "liquidity": 500,
            "status": "active",
        }

        market = exchange._parse_market(mock_data)

        assert market.prices["Yes"] == 0.50
        assert market.prices["No"] == 0.50

    def test_parse_market_resolved(self):
        """Test parsing resolved market."""
        exchange = Limitless({})

        mock_data = {
            "slug": "resolved-market",
            "title": "Resolved Market?",
            "tokens": {},
            "status": "resolved",
        }

        market = exchange._parse_market(mock_data)

        assert market.metadata["closed"] is True


class TestLimitlessOrderParsing:
    """Test order parsing logic."""

    def test_parse_order_buy(self):
        """Test parsing buy order."""
        exchange = Limitless({})

        mock_data = {
            "id": "order_123",
            "marketSlug": "test-market",
            "outcome": "Yes",
            "side": "buy",
            "price": 0.55,
            "size": 100.0,
            "filled": 25.0,
            "status": "open",
            "createdAt": "2025-01-01T00:00:00Z",
            "updatedAt": "2025-01-01T00:00:00Z",
        }

        order = exchange._parse_order(mock_data)

        assert order.id == "order_123"
        assert order.market_id == "test-market"
        assert order.outcome == "Yes"
        assert order.side == OrderSide.BUY
        assert order.price == 0.55
        assert order.size == 100.0
        assert order.filled == 25.0
        assert order.status == OrderStatus.OPEN

    def test_parse_order_sell(self):
        """Test parsing sell order."""
        exchange = Limitless({})

        mock_data = {
            "id": "order_456",
            "marketSlug": "test-market",
            "side": "sell",
            "price": 0.45,
            "size": 50.0,
            "status": "filled",
        }

        order = exchange._parse_order(mock_data)

        assert order.id == "order_456"
        assert order.side == OrderSide.SELL
        assert order.status == OrderStatus.FILLED

    def test_parse_order_status_variants(self):
        """Test parsing various order status values."""
        exchange = Limitless({})

        assert exchange._parse_order_status("pending") == OrderStatus.PENDING
        assert exchange._parse_order_status("open") == OrderStatus.OPEN
        assert exchange._parse_order_status("live") == OrderStatus.OPEN
        assert exchange._parse_order_status("active") == OrderStatus.OPEN
        assert exchange._parse_order_status("filled") == OrderStatus.FILLED
        assert exchange._parse_order_status("matched") == OrderStatus.FILLED
        assert exchange._parse_order_status("partially_filled") == OrderStatus.PARTIALLY_FILLED
        assert exchange._parse_order_status("partial") == OrderStatus.PARTIALLY_FILLED
        assert exchange._parse_order_status("cancelled") == OrderStatus.CANCELLED
        assert exchange._parse_order_status("canceled") == OrderStatus.CANCELLED
        assert exchange._parse_order_status("rejected") == OrderStatus.REJECTED
        assert exchange._parse_order_status("unknown") == OrderStatus.OPEN
        assert exchange._parse_order_status(None) == OrderStatus.OPEN


class TestLimitlessPositionParsing:
    """Test position parsing logic."""

    def test_parse_position_basic(self):
        """Test parsing basic position data."""
        exchange = Limitless({})

        mock_data = {
            "market": {"slug": "test-market"},
            "outcome": "Yes",
            "size": 100.0,
            "avgEntryPrice": 0.50,
            "currentPrice": 0.65,
        }

        position = exchange._parse_position(mock_data)

        assert position.market_id == "test-market"
        assert position.outcome == "Yes"
        assert position.size == 100.0
        assert position.average_price == 0.50
        assert position.current_price == 0.65
        assert position.unrealized_pnl == 15.0  # (0.65 - 0.50) * 100

    def test_parse_position_flat_structure(self):
        """Test parsing position with flat structure."""
        exchange = Limitless({})

        mock_data = {
            "marketSlug": "flat-market",
            "tokenName": "No",
            "balance": 50.0,
            "averagePrice": 0.30,
            "price": 0.40,
        }

        position = exchange._parse_position(mock_data)

        assert position.market_id == "flat-market"
        assert position.outcome == "No"
        assert position.size == 50.0


class TestLimitlessDatetimeParsing:
    """Test datetime parsing logic."""

    def test_parse_datetime_iso_format(self):
        """Test parsing ISO format datetime."""
        exchange = Limitless({})

        dt = exchange._parse_datetime("2025-01-01T00:00:00Z")
        assert dt is not None
        assert dt.year == 2025
        assert dt.month == 1
        assert dt.day == 1

    def test_parse_datetime_timestamp(self):
        """Test parsing unix timestamp."""
        exchange = Limitless({})

        dt = exchange._parse_datetime(1735689600)
        assert dt is not None

    def test_parse_datetime_none(self):
        """Test parsing None returns None."""
        exchange = Limitless({})

        dt = exchange._parse_datetime(None)
        assert dt is None

    def test_parse_datetime_invalid(self):
        """Test parsing invalid format returns None."""
        exchange = Limitless({})

        dt = exchange._parse_datetime("invalid")
        assert dt is None


class TestLimitlessWithMockedSession:
    """Tests with mocked HTTP session."""

    @pytest.fixture
    def mock_session(self):
        """Create a mocked requests session."""
        return MagicMock()

    @pytest.fixture
    def exchange_with_mock(self, mock_session):
        """Create exchange with mocked session."""
        exchange = Limitless({})
        exchange._session = mock_session
        return exchange

    def test_fetch_markets_success(self, exchange_with_mock, mock_session):
        """Test successful fetch_markets."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": [
                {
                    "slug": "market-1",
                    "title": "Test Market 1?",
                    "tokens": {"yes": "yes_1", "no": "no_1"},
                    "yesPrice": 0.60,
                    "noPrice": 0.40,
                    "volume": 1000,
                    "liquidity": 500,
                    "status": "active",
                }
            ]
        }
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        mock_session.request.return_value = mock_response

        markets = exchange_with_mock.fetch_markets()

        assert len(markets) == 1
        assert markets[0].id == "market-1"
        assert markets[0].question == "Test Market 1?"
        assert markets[0].prices["Yes"] == 0.60

    def test_fetch_market_success(self, exchange_with_mock, mock_session):
        """Test successful fetch_market."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "slug": "specific-market",
            "title": "Specific Market?",
            "tokens": {"yes": "yes_token", "no": "no_token"},
            "yesPrice": 0.70,
            "noPrice": 0.30,
            "volume": 5000,
            "liquidity": 2500,
            "status": "active",
        }
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        mock_session.request.return_value = mock_response

        market = exchange_with_mock.fetch_market("specific-market")

        assert market.id == "specific-market"
        assert market.question == "Specific Market?"
        assert market.volume == 5000

    def test_fetch_market_not_found(self, exchange_with_mock, mock_session):
        """Test fetch_market when market not found."""
        from requests import HTTPError

        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = HTTPError("404 Not Found")
        mock_session.request.return_value = mock_response

        with pytest.raises(MarketNotFound):
            exchange_with_mock.fetch_market("nonexistent-market")

    def test_get_orderbook_success(self, exchange_with_mock, mock_session):
        """Test successful orderbook fetch."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "bids": [{"price": 0.50, "size": 100}],
            "asks": [{"price": 0.52, "size": 150}],
        }
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        mock_session.request.return_value = mock_response

        orderbook = exchange_with_mock.get_orderbook("test-market")

        assert len(orderbook["bids"]) == 1
        assert len(orderbook["asks"]) == 1
        assert float(orderbook["bids"][0]["price"]) == 0.50
        assert float(orderbook["asks"][0]["price"]) == 0.52

    def test_get_orderbook_with_orders_format(self, exchange_with_mock, mock_session):
        """Test orderbook parsing with orders array format."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "orders": [
                {"side": "buy", "price": 0.48, "size": 50},
                {"side": "sell", "price": 0.55, "size": 75},
            ]
        }
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        mock_session.request.return_value = mock_response

        orderbook = exchange_with_mock.get_orderbook("test-market")

        assert len(orderbook["bids"]) == 1
        assert len(orderbook["asks"]) == 1


class TestLimitlessAuthenticated:
    """Tests for authenticated operations."""

    @pytest.fixture
    def authenticated_exchange(self):
        """Create an exchange with mocked authentication."""
        from eth_account import Account

        # Use a valid test private key
        test_private_key = "0x" + "a" * 64
        test_account = Account.from_key(test_private_key)

        exchange = Limitless({})
        exchange._authenticated = True
        exchange._session = MagicMock()
        exchange._account = test_account
        exchange._address = test_account.address
        exchange._owner_id = 12345
        return exchange

    def test_create_order_success(self, authenticated_exchange):
        """Test successful order creation."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "id": "order_123",
            "status": "open",
            "filled": 0,
        }
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200

        # Mock fetch_market for token lookup (needs venue.exchange for signing)
        market_response = Mock()
        market_response.json.return_value = {
            "slug": "test-market",
            "title": "Test?",
            "tokens": {"yes": "123456789", "no": "987654321"},
            "status": "active",
            "venue": {"exchange": "0x05c748E2f4DcDe0ec9Fa8DDc40DE6b867f923fa5"},
        }
        market_response.raise_for_status = Mock()
        market_response.status_code = 200

        authenticated_exchange._session.request.side_effect = [market_response, mock_response]

        order = authenticated_exchange.create_order(
            market_id="test-market",
            outcome="Yes",
            side=OrderSide.BUY,
            price=0.65,
            size=100,
        )

        assert order.id == "order_123"
        assert order.market_id == "test-market"
        assert order.outcome == "Yes"
        assert order.side == OrderSide.BUY
        assert order.price == 0.65
        assert order.size == 100
        assert order.status == OrderStatus.OPEN

    def test_create_order_with_token_id(self, authenticated_exchange):
        """Test order creation with token_id provided."""
        order_response = Mock()
        order_response.json.return_value = {
            "id": "order_456",
            "status": "open",
        }
        order_response.raise_for_status = Mock()
        order_response.status_code = 200

        # Still need market for venue.exchange
        market_response = Mock()
        market_response.json.return_value = {
            "slug": "test-market",
            "title": "Test?",
            "tokens": {"yes": "123456789", "no": "987654321"},
            "status": "active",
            "venue": {"exchange": "0x05c748E2f4DcDe0ec9Fa8DDc40DE6b867f923fa5"},
        }
        market_response.raise_for_status = Mock()
        market_response.status_code = 200

        authenticated_exchange._session.request.side_effect = [market_response, order_response]

        order = authenticated_exchange.create_order(
            market_id="test-market",
            outcome="No",
            side=OrderSide.SELL,
            price=0.40,
            size=50,
            params={"token_id": "987654321"},  # numeric string for EIP-712
        )

        assert order.id == "order_456"
        assert order.side == OrderSide.SELL

    def test_create_order_invalid_price(self, authenticated_exchange):
        """Test order creation with invalid price."""
        with pytest.raises(InvalidOrder, match="Price must be between 0 and 1"):
            authenticated_exchange.create_order(
                market_id="test-market",
                outcome="Yes",
                side=OrderSide.BUY,
                price=1.5,
                size=100,
                params={"token_id": "yes_token"},
            )

        with pytest.raises(InvalidOrder, match="Price must be between 0 and 1"):
            authenticated_exchange.create_order(
                market_id="test-market",
                outcome="Yes",
                side=OrderSide.BUY,
                price=0,
                size=100,
                params={"token_id": "yes_token"},
            )

    def test_cancel_order_success(self, authenticated_exchange):
        """Test successful order cancellation."""
        mock_response = Mock()
        mock_response.json.return_value = {"success": True}
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        authenticated_exchange._session.request.return_value = mock_response

        order = authenticated_exchange.cancel_order("order_123", market_id="test-market")

        assert order.id == "order_123"
        assert order.status == OrderStatus.CANCELLED

    def test_fetch_balance_success(self, authenticated_exchange):
        """Test successful balance fetch via on-chain RPC."""
        import requests

        # Balance uses RPC, not session. Mock requests.post
        with patch.object(requests, "post") as mock_post:
            mock_response = Mock()
            # 1000.5 USDC = 1000500000 in 6 decimals = 0x3B9ACA00 + ~500k
            # Let's use 1000000000 = 1000 USDC = 0x3B9ACA00
            mock_response.json.return_value = {"result": "0x3B9ACA00"}
            mock_post.return_value = mock_response

            balance = authenticated_exchange.fetch_balance()

            assert "USDC" in balance
            assert balance["USDC"] == 1000.0

    def test_fetch_positions_success(self, authenticated_exchange):
        """Test successful positions fetch."""
        mock_api_response = {
            "clob": [
                {
                    "market": {"slug": "test-market"},
                    "tokensBalance": {"yes": "100000000", "no": "0"},
                    "positions": {
                        "yes": {"fillPrice": "600000", "cost": "60000000"},
                        "no": {"fillPrice": "0", "cost": "0"},
                    },
                    "latestTrade": {"latestYesPrice": 0.70, "latestNoPrice": 0.30},
                }
            ]
        }
        with patch.object(authenticated_exchange, "_request", return_value=mock_api_response):
            positions = authenticated_exchange.fetch_positions()

        assert len(positions) == 1
        assert positions[0].market_id == "test-market"
        assert positions[0].outcome == "Yes"
        assert positions[0].size == 100.0

    def test_fetch_open_orders_success(self, authenticated_exchange):
        """Test successful open orders fetch."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "order_1",
                    "marketSlug": "test-market",
                    "side": "buy",
                    "price": 0.60,
                    "size": 50,
                    "status": "open",
                }
            ]
        }
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        authenticated_exchange._session.request.return_value = mock_response

        orders = authenticated_exchange.fetch_open_orders()

        assert len(orders) == 1
        assert orders[0].id == "order_1"
        assert orders[0].status == OrderStatus.OPEN

    def test_cancel_all_orders_requires_market_id(self, authenticated_exchange):
        """Test cancel_all_orders requires market_id."""
        with pytest.raises(InvalidOrder, match="market_id required"):
            authenticated_exchange.cancel_all_orders()


class TestLimitlessHelperMethods:
    """Test helper methods."""

    def test_extract_token_ids(self):
        """Test extracting token IDs from market metadata."""
        from dr_manhattan.models.market import Market

        market = Market(
            id="test",
            question="Test?",
            outcomes=["Yes", "No"],
            close_time=None,
            volume=0,
            liquidity=0,
            prices={},
            metadata={"clobTokenIds": ["token_yes", "token_no"]},
            tick_size=0.01,
        )

        token_ids = Limitless._extract_token_ids(market)
        assert token_ids == ["token_yes", "token_no"]

    def test_extract_token_ids_from_json_string(self):
        """Test extracting token IDs from JSON string."""
        from dr_manhattan.models.market import Market

        market = Market(
            id="test",
            question="Test?",
            outcomes=["Yes", "No"],
            close_time=None,
            volume=0,
            liquidity=0,
            prices={},
            metadata={"clobTokenIds": '["token_1", "token_2"]'},
            tick_size=0.01,
        )

        token_ids = Limitless._extract_token_ids(market)
        assert token_ids == ["token_1", "token_2"]

    def test_lookup_token_id_by_outcome_name(self):
        """Test looking up token ID by outcome name."""
        from dr_manhattan.models.market import Market

        exchange = Limitless({})
        market = Market(
            id="test",
            question="Test?",
            outcomes=["Yes", "No"],
            close_time=None,
            volume=0,
            liquidity=0,
            prices={},
            metadata={"clobTokenIds": ["yes_token", "no_token"]},
            tick_size=0.01,
        )

        assert exchange._lookup_token_id(market, "Yes") == "yes_token"
        assert exchange._lookup_token_id(market, "No") == "no_token"
        assert exchange._lookup_token_id(market, 0) == "yes_token"
        assert exchange._lookup_token_id(market, 1) == "no_token"

    def test_lookup_token_id_invalid_outcome(self):
        """Test looking up token ID with invalid outcome."""
        from dr_manhattan.models.market import Market

        exchange = Limitless({})
        market = Market(
            id="test",
            question="Test?",
            outcomes=["Yes", "No"],
            close_time=None,
            volume=0,
            liquidity=0,
            prices={},
            metadata={"clobTokenIds": ["yes_token", "no_token"]},
            tick_size=0.01,
        )

        with pytest.raises(ExchangeError, match="Outcome Maybe not found"):
            exchange._lookup_token_id(market, "Maybe")

    def test_build_search_text(self):
        """Test building search text from market."""
        from dr_manhattan.models.market import Market

        market = Market(
            id="test",
            question="Will BTC reach $100k?",
            outcomes=["Yes", "No"],
            close_time=None,
            volume=0,
            liquidity=0,
            prices={},
            metadata={
                "description": "Bitcoin price prediction",
                "slug": "btc-100k",
                "category": "Crypto",
            },
            tick_size=0.01,
        )

        text = Limitless._build_search_text(market)

        assert "will btc reach $100k?" in text
        assert "bitcoin price prediction" in text
        assert "btc-100k" in text
        assert "crypto" in text


class TestLimitlessPriceHistory:
    """Test price history functionality."""

    def test_parse_history(self):
        """Test parsing price history data."""
        history = [
            {"timestamp": 1735689600, "price": 0.50},
            {"timestamp": 1735693200, "price": 0.55},
            {"t": 1735696800, "p": 0.60},
        ]

        points = Limitless._parse_history(history)

        assert len(points) == 3
        assert points[0].price == 0.50
        assert points[1].price == 0.55
        assert points[2].price == 0.60
        # Should be sorted by timestamp
        assert points[0].timestamp < points[1].timestamp < points[2].timestamp

    def test_fetch_price_history_invalid_interval(self):
        """Test fetch_price_history with invalid interval."""
        exchange = Limitless({})

        with pytest.raises(ValueError, match="Unsupported interval"):
            exchange.fetch_price_history("test-market", interval="5m")


class TestLimitlessSearchMarkets:
    """Test market search functionality."""

    @pytest.fixture
    def exchange_with_markets(self):
        """Create exchange with mock markets."""
        exchange = Limitless({})
        exchange._session = MagicMock()

        mock_response = Mock()
        mock_response.json.return_value = {
            "data": [
                {
                    "slug": "btc-100k",
                    "title": "Will BTC reach $100k?",
                    "tokens": {"yes": "y1", "no": "n1"},
                    "volume": 10000,
                    "liquidity": 5000,
                    "status": "active",
                },
                {
                    "slug": "eth-5k",
                    "title": "Will ETH reach $5k?",
                    "tokens": {"yes": "y2", "no": "n2"},
                    "volume": 5000,
                    "liquidity": 2000,
                    "status": "active",
                },
            ]
        }
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        exchange._session.request.return_value = mock_response

        return exchange

    def test_search_markets_with_query(self, exchange_with_markets):
        """Test searching markets with query."""
        results = exchange_with_markets.search_markets(query="btc")

        assert len(results) == 1
        assert results[0].id == "btc-100k"

    def test_search_markets_with_min_liquidity(self, exchange_with_markets):
        """Test searching markets with minimum liquidity."""
        results = exchange_with_markets.search_markets(min_liquidity=3000)

        assert len(results) == 1
        assert results[0].id == "btc-100k"

    def test_search_markets_with_predicate(self, exchange_with_markets):
        """Test searching markets with custom predicate."""
        results = exchange_with_markets.search_markets(predicate=lambda m: m.volume > 7000)

        assert len(results) == 1
        assert results[0].id == "btc-100k"

    def test_search_markets_empty_result(self, exchange_with_markets):
        """Test searching with no matches."""
        results = exchange_with_markets.search_markets(query="nonexistent")

        assert len(results) == 0

    def test_search_markets_limit_zero(self, exchange_with_markets):
        """Test searching with limit=0 returns empty."""
        results = exchange_with_markets.search_markets(limit=0)

        assert len(results) == 0
