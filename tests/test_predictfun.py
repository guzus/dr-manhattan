"""Tests for PredictFun exchange implementation."""

from unittest.mock import MagicMock, Mock, patch

import pytest

from dr_manhattan import OrderSide, OrderStatus, PredictFun
from dr_manhattan.base.errors import (
    AuthenticationError,
    ExchangeError,
    InvalidOrder,
    MarketNotFound,
)


class TestPredictFunBasic:
    """Basic PredictFun exchange tests."""

    def test_exchange_properties(self):
        """Test exchange id and name properties."""
        exchange = PredictFun({"testnet": True})
        assert exchange.id == "predictfun"
        assert exchange.name == "Predict.fun"
        assert exchange.testnet is True
        assert exchange.host == "https://api-testnet.predict.fun"
        assert exchange.chain_id == 97

    def test_exchange_properties_mainnet(self):
        """Test exchange properties for mainnet."""
        exchange = PredictFun({})
        assert exchange.testnet is False
        assert exchange.host == "https://api.predict.fun"
        assert exchange.chain_id == 56

    def test_describe(self):
        """Test describe method returns correct capabilities."""
        exchange = PredictFun({"testnet": True})
        info = exchange.describe()

        assert info["id"] == "predictfun"
        assert info["name"] == "Predict.fun"
        assert info["chain_id"] == 97
        assert info["testnet"] is True
        assert info["has"]["fetch_markets"] is True
        assert info["has"]["fetch_market"] is True
        assert info["has"]["create_order"] is True
        assert info["has"]["cancel_order"] is True
        assert info["has"]["fetch_order"] is True
        assert info["has"]["fetch_open_orders"] is True
        assert info["has"]["fetch_positions"] is True
        assert info["has"]["fetch_balance"] is True
        assert info["has"]["get_orderbook"] is True
        assert info["has"]["fetch_token_ids"] is True

    def test_initialization_without_credentials(self):
        """Test that exchange initializes without credentials."""
        exchange = PredictFun({"testnet": True})
        assert exchange._authenticated is False
        assert exchange._account is None
        assert exchange._address is None
        assert exchange._jwt_token is None

    def test_initialization_with_private_key(self):
        """Test initialization with private key."""
        # Valid test private key
        test_key = "0x" + "1" * 64
        exchange = PredictFun({"testnet": True, "private_key": test_key})
        assert exchange._account is not None
        assert exchange._address is not None

    def test_initialization_with_invalid_private_key(self):
        """Test initialization with invalid private key raises error."""
        with pytest.raises(AuthenticationError):
            PredictFun({"testnet": True, "private_key": "invalid_key"})

    def test_ensure_authenticated_raises_without_credentials(self):
        """Test that operations requiring auth raise AuthenticationError."""
        exchange = PredictFun({"testnet": True})

        with pytest.raises(AuthenticationError):
            exchange._ensure_authenticated()

    def test_contract_addresses_testnet(self):
        """Test correct contract addresses for testnet."""
        exchange = PredictFun({"testnet": True})
        assert exchange.yield_bearing_ctf_exchange == "0x8a6B4Fa700A1e310b106E7a48bAFa29111f66e89"
        assert (
            exchange.yield_bearing_neg_risk_ctf_exchange
            == "0x95D5113bc50eD201e319101bbca3e0E250662fCC"
        )
        assert exchange.ctf_exchange == "0x2A6413639BD3d73a20ed8C95F634Ce198ABbd2d7"
        assert exchange.neg_risk_ctf_exchange == "0xd690b2bd441bE36431F6F6639D7Ad351e7B29680"

    def test_contract_addresses_mainnet(self):
        """Test correct contract addresses for mainnet."""
        exchange = PredictFun({})
        assert exchange.yield_bearing_ctf_exchange == "0x6bEb5a40C032AFc305961162d8204CDA16DECFa5"
        assert (
            exchange.yield_bearing_neg_risk_ctf_exchange
            == "0x8A289d458f5a134bA40015085A8F50Ffb681B41d"
        )
        assert exchange.ctf_exchange == "0x8BC070BEdAB741406F4B1Eb65A72bee27894B689"
        assert exchange.neg_risk_ctf_exchange == "0x365fb81bd4A24D6303cd2F19c349dE6894D8d58A"


class TestPredictFunMarketParsing:
    """Test market parsing logic."""

    def test_parse_market_basic(self):
        """Test parsing basic market data."""
        exchange = PredictFun({"testnet": True})

        mock_data = {
            "id": 123,
            "title": "Test Market",
            "question": "Will test pass?",
            "description": "Test description",
            "status": "REGISTERED",
            "isNegRisk": False,
            "isYieldBearing": True,
            "feeRateBps": 200,
            "conditionId": "0xabc123",
            "categorySlug": "test",
            "decimalPrecision": 2,
            "outcomes": [
                {"name": "Yes", "indexSet": 1, "onChainId": "12345", "status": None},
                {"name": "No", "indexSet": 2, "onChainId": "67890", "status": None},
            ],
        }

        market = exchange._parse_market(mock_data)

        assert market.id == "123"
        assert market.question == "Will test pass?"
        assert market.description == "Test description"
        assert market.outcomes == ["Yes", "No"]
        assert market.tick_size == 0.01
        assert market.metadata["clobTokenIds"] == ["12345", "67890"]
        assert market.metadata["isNegRisk"] is False
        assert market.metadata["isYieldBearing"] is True
        assert market.metadata["feeRateBps"] == 200
        assert market.metadata["closed"] is False

    def test_parse_market_closed_status(self):
        """Test parsing market with closed status."""
        exchange = PredictFun({"testnet": True})

        mock_data = {
            "id": 456,
            "title": "Closed Market",
            "question": "Is this closed?",
            "description": "",
            "status": "RESOLVED",
            "decimalPrecision": 3,
            "outcomes": [],
        }

        market = exchange._parse_market(mock_data)

        assert market.id == "456"
        assert market.outcomes == ["Yes", "No"]  # Default for binary
        assert market.tick_size == 0.001
        assert market.metadata["closed"] is True

    def test_parse_market_paused_status(self):
        """Test parsing market with paused status."""
        exchange = PredictFun({"testnet": True})

        mock_data = {
            "id": 789,
            "title": "Paused Market",
            "question": "Is this paused?",
            "description": "",
            "status": "PAUSED",
            "decimalPrecision": 2,
            "outcomes": [],
        }

        market = exchange._parse_market(mock_data)
        assert market.metadata["closed"] is True


class TestPredictFunOrderParsing:
    """Test order parsing logic."""

    def test_parse_order_status(self):
        """Test order status parsing."""
        exchange = PredictFun({"testnet": True})

        assert exchange._parse_order_status("OPEN") == OrderStatus.OPEN
        assert exchange._parse_order_status("FILLED") == OrderStatus.FILLED
        assert exchange._parse_order_status("EXPIRED") == OrderStatus.CANCELLED
        assert exchange._parse_order_status("CANCELLED") == OrderStatus.CANCELLED
        assert exchange._parse_order_status("INVALIDATED") == OrderStatus.CANCELLED
        assert exchange._parse_order_status(None) == OrderStatus.OPEN

    def test_parse_order_buy(self):
        """Test parsing buy order."""
        exchange = PredictFun({"testnet": True})

        mock_data = {
            "id": "order_123",
            "marketId": 456,
            "status": "OPEN",
            "amountFilled": "0",
            "order": {
                "hash": "0xabc",
                "side": 0,  # BUY
                "makerAmount": "550000000000000000",  # 0.55 * shares
                "takerAmount": "1000000000000000000",  # 1.0 share
            },
        }

        order = exchange._parse_order(mock_data)

        assert order.id == "order_123"
        assert order.market_id == "456"
        assert order.side == OrderSide.BUY
        assert order.status == OrderStatus.OPEN
        assert order.size == 1.0
        assert order.price == 0.55
        assert order.filled == 0

    def test_parse_order_sell(self):
        """Test parsing sell order."""
        exchange = PredictFun({"testnet": True})

        mock_data = {
            "id": "order_456",
            "marketId": 789,
            "status": "FILLED",
            "amountFilled": "2000000000000000000",  # 2.0
            "order": {
                "hash": "0xdef",
                "side": 1,  # SELL
                "makerAmount": "2000000000000000000",  # 2.0 shares
                "takerAmount": "1300000000000000000",  # 0.65 * 2
            },
        }

        order = exchange._parse_order(mock_data)

        assert order.id == "order_456"
        assert order.market_id == "789"
        assert order.side == OrderSide.SELL
        assert order.status == OrderStatus.FILLED
        assert order.size == 2.0
        assert order.price == 0.65
        assert order.filled == 2.0


class TestPredictFunOrderCreation:
    """Test order creation logic."""

    def test_create_order_price_validation(self):
        """Test price validation in create_order."""
        test_key = "0x" + "1" * 64
        exchange = PredictFun({"testnet": True, "api_key": "test", "private_key": test_key})

        # Mock fetch_market
        with patch.object(exchange, "fetch_market") as mock_fetch:
            mock_market = Mock()
            mock_market.metadata = {
                "outcomes": [{"name": "Yes"}, {"name": "No"}],
                "clobTokenIds": ["123", "456"],
                "feeRateBps": 200,
                "isYieldBearing": True,
                "isNegRisk": False,
            }
            mock_fetch.return_value = mock_market

            # Price too low
            with pytest.raises(InvalidOrder, match="must be between 0 and 1"):
                exchange.create_order("1", "Yes", OrderSide.BUY, -0.1, 10)

            # Price too high
            with pytest.raises(InvalidOrder, match="must be between 0 and 1"):
                exchange.create_order("1", "Yes", OrderSide.BUY, 1.5, 10)

    def test_create_order_boundary_prices(self):
        """Test that boundary prices (0.0 and 1.0) are allowed."""
        test_key = "0x" + "1" * 64
        exchange = PredictFun({"testnet": True, "api_key": "test", "private_key": test_key})

        with patch.object(exchange, "fetch_market") as mock_fetch:
            with patch.object(exchange, "_request") as mock_request:
                mock_market = Mock()
                mock_market.metadata = {
                    "outcomes": [{"name": "Yes"}, {"name": "No"}],
                    "clobTokenIds": ["123", "456"],
                    "feeRateBps": 200,
                    "isYieldBearing": True,
                    "isNegRisk": False,
                }
                mock_fetch.return_value = mock_market
                mock_request.return_value = {"data": {"orderHash": "0xabc"}}

                # Price 0.0 should be valid
                order = exchange.create_order("1", "Yes", OrderSide.BUY, 0.0, 10)
                assert order.price == 0.0

                # Price 1.0 should be valid
                order = exchange.create_order("1", "Yes", OrderSide.BUY, 1.0, 10)
                assert order.price == 1.0

    def test_create_order_missing_token_id(self):
        """Test error when token_id cannot be found."""
        test_key = "0x" + "1" * 64
        exchange = PredictFun({"testnet": True, "api_key": "test", "private_key": test_key})

        with patch.object(exchange, "fetch_market") as mock_fetch:
            mock_market = Mock()
            mock_market.metadata = {
                "outcomes": [{"name": "Yes"}],
                "clobTokenIds": [],
                "feeRateBps": 200,
            }
            mock_fetch.return_value = mock_market

            with pytest.raises(InvalidOrder, match="Could not find token_id"):
                exchange.create_order("1", "Maybe", OrderSide.BUY, 0.5, 10)

    def test_build_signed_order_buy(self):
        """Test building signed order for BUY side."""
        test_key = "0x" + "1" * 64
        exchange = PredictFun({"testnet": True, "api_key": "test", "private_key": test_key})

        # Use valid testnet exchange address
        order = exchange._build_signed_order(
            token_id="12345",
            price=0.6,
            size=10.0,
            side=OrderSide.BUY,
            fee_rate_bps=200,
            exchange_address=exchange.yield_bearing_ctf_exchange,
            expiration=0,
        )

        assert order["tokenId"] == "12345"
        assert order["side"] == 0  # BUY
        assert order["maker"] == exchange._address
        assert order["signer"] == exchange._address
        assert order["taker"] == "0x0000000000000000000000000000000000000000"
        assert "signature" in order
        assert order["signatureType"] == 0
        assert int(order["feeRateBps"]) == 200

        # For BUY: makerAmount = price * shares, takerAmount = shares
        shares_wei = 10 * 10**18
        price_wei = int(0.6 * 10**18)
        expected_maker = (shares_wei * price_wei) // (10**18)
        assert int(order["makerAmount"]) == expected_maker
        assert int(order["takerAmount"]) == shares_wei

    def test_build_signed_order_sell(self):
        """Test building signed order for SELL side."""
        test_key = "0x" + "1" * 64
        exchange = PredictFun({"testnet": True, "api_key": "test", "private_key": test_key})

        # Use valid testnet exchange address
        order = exchange._build_signed_order(
            token_id="67890",
            price=0.4,
            size=5.0,
            side=OrderSide.SELL,
            fee_rate_bps=150,
            exchange_address=exchange.yield_bearing_ctf_exchange,
            expiration=123456,
        )

        assert order["tokenId"] == "67890"
        assert order["side"] == 1  # SELL
        assert int(order["expiration"]) == 123456
        assert int(order["feeRateBps"]) == 150

        # For SELL: makerAmount = shares, takerAmount = price * shares
        shares_wei = 5 * 10**18
        price_wei = int(0.4 * 10**18)
        expected_taker = (shares_wei * price_wei) // (10**18)
        assert int(order["makerAmount"]) == shares_wei
        assert int(order["takerAmount"]) == expected_taker

    def test_exchange_address_selection(self):
        """Test correct exchange address selection based on market type."""
        test_key = "0x" + "1" * 64
        exchange = PredictFun({"testnet": True, "api_key": "test", "private_key": test_key})

        with patch.object(exchange, "_request") as mock_request:
            mock_request.return_value = {"data": {"orderHash": "0xabc"}}

            # Test yield-bearing, non-neg-risk
            with patch.object(exchange, "fetch_market") as mock_fetch:
                mock_market = Mock()
                mock_market.metadata = {
                    "outcomes": [{"name": "Yes"}],
                    "clobTokenIds": ["123"],
                    "feeRateBps": 200,
                    "isYieldBearing": True,
                    "isNegRisk": False,
                }
                mock_fetch.return_value = mock_market

                with patch.object(exchange, "_build_signed_order") as mock_build:
                    mock_build.return_value = {"signature": "0x"}
                    exchange.create_order("1", "Yes", OrderSide.BUY, 0.5, 10)

                    # Check the exchange_address passed to _build_signed_order
                    assert (
                        mock_build.call_args[1]["exchange_address"]
                        == exchange.yield_bearing_ctf_exchange
                    )

            # Test yield-bearing, neg-risk
            with patch.object(exchange, "fetch_market") as mock_fetch:
                mock_market = Mock()
                mock_market.metadata = {
                    "outcomes": [{"name": "Yes"}],
                    "clobTokenIds": ["123"],
                    "feeRateBps": 200,
                    "isYieldBearing": True,
                    "isNegRisk": True,
                }
                mock_fetch.return_value = mock_market

                with patch.object(exchange, "_build_signed_order") as mock_build:
                    mock_build.return_value = {"signature": "0x"}
                    exchange.create_order("1", "Yes", OrderSide.BUY, 0.5, 10)

                    assert (
                        mock_build.call_args[1]["exchange_address"]
                        == exchange.yield_bearing_neg_risk_ctf_exchange
                    )


class TestPredictFunOrderbook:
    """Test orderbook functionality."""

    def test_get_orderbook_parsing(self):
        """Test orderbook parsing."""
        exchange = PredictFun({"testnet": True})

        mock_response = {
            "data": {
                "marketId": 123,
                "updateTimestampMs": 1234567890,
                "bids": [[0.65, 100], [0.64, 50], [0.63, 200]],
                "asks": [[0.67, 150], [0.68, 75], [0.69, 100]],
            }
        }

        with patch.object(exchange, "_request") as mock_request:
            mock_request.return_value = mock_response

            orderbook = exchange.get_orderbook("123")

            assert len(orderbook["bids"]) == 3
            assert len(orderbook["asks"]) == 3

            # Check sorting: bids descending
            assert float(orderbook["bids"][0]["price"]) == 0.65
            assert float(orderbook["bids"][1]["price"]) == 0.64
            assert float(orderbook["bids"][2]["price"]) == 0.63

            # Check sorting: asks ascending
            assert float(orderbook["asks"][0]["price"]) == 0.67
            assert float(orderbook["asks"][1]["price"]) == 0.68
            assert float(orderbook["asks"][2]["price"]) == 0.69

    def test_get_orderbook_error_handling(self):
        """Test orderbook error handling."""
        exchange = PredictFun({"testnet": True})

        with patch.object(exchange, "_request") as mock_request:
            mock_request.side_effect = Exception("API error")

            orderbook = exchange.get_orderbook("123")

            # Should return empty orderbook on error
            assert orderbook == {"bids": [], "asks": []}


class TestPredictFunAuthentication:
    """Test authentication functionality."""

    def test_get_headers_no_auth(self):
        """Test headers without authentication."""
        exchange = PredictFun({"testnet": True, "api_key": "test_key"})
        headers = exchange._get_headers(require_auth=False)

        assert headers["Content-Type"] == "application/json"
        assert headers["x-api-key"] == "test_key"
        assert "Authorization" not in headers

    def test_get_headers_with_auth(self):
        """Test headers with authentication."""
        exchange = PredictFun({"testnet": True, "api_key": "test_key"})
        exchange._jwt_token = "test_jwt_token"
        headers = exchange._get_headers(require_auth=True)

        assert headers["Content-Type"] == "application/json"
        assert headers["x-api-key"] == "test_key"
        assert headers["Authorization"] == "Bearer test_jwt_token"


class TestPredictFunProtocol:
    """Test EIP-712 protocol constants."""

    def test_protocol_constants(self):
        """Test that protocol constants match official SDK."""
        exchange = PredictFun({"testnet": True})
        assert exchange.PROTOCOL_NAME == "predict.fun CTF Exchange"
        assert exchange.PROTOCOL_VERSION == "1"
