"""Tests for error handling"""

import pytest
from dr_manhattan.base.errors import (
    DrManhattanError,
    ExchangeError,
    NetworkError,
    RateLimitError,
    AuthenticationError,
    InsufficientFunds,
    InvalidOrder,
    MarketNotFound
)


class TestErrorHierarchy:
    """Test error class hierarchy"""

    def test_base_error(self):
        """Test DrManhattanError base class"""
        error = DrManhattanError("Test error")
        assert str(error) == "Test error"
        assert isinstance(error, Exception)

    def test_exchange_error(self):
        """Test ExchangeError"""
        error = ExchangeError("Exchange error")
        assert str(error) == "Exchange error"
        assert isinstance(error, DrManhattanError)
        assert isinstance(error, Exception)

    def test_network_error(self):
        """Test NetworkError"""
        error = NetworkError("Network error")
        assert str(error) == "Network error"
        assert isinstance(error, DrManhattanError)

    def test_rate_limit_error(self):
        """Test RateLimitError"""
        error = RateLimitError("Rate limit exceeded")
        assert str(error) == "Rate limit exceeded"
        assert isinstance(error, DrManhattanError)

    def test_authentication_error(self):
        """Test AuthenticationError"""
        error = AuthenticationError("Auth failed")
        assert str(error) == "Auth failed"
        assert isinstance(error, DrManhattanError)

    def test_insufficient_funds(self):
        """Test InsufficientFunds"""
        error = InsufficientFunds("Not enough balance")
        assert str(error) == "Not enough balance"
        assert isinstance(error, DrManhattanError)

    def test_invalid_order(self):
        """Test InvalidOrder"""
        error = InvalidOrder("Invalid order parameters")
        assert str(error) == "Invalid order parameters"
        assert isinstance(error, DrManhattanError)

    def test_market_not_found(self):
        """Test MarketNotFound"""
        error = MarketNotFound("Market not found")
        assert str(error) == "Market not found"
        assert isinstance(error, DrManhattanError)


class TestErrorRaising:
    """Test error raising in context"""

    def test_raise_exchange_error(self):
        """Test raising ExchangeError"""
        with pytest.raises(ExchangeError) as exc_info:
            raise ExchangeError("Test exchange error")

        assert "Test exchange error" in str(exc_info.value)

    def test_raise_network_error(self):
        """Test raising NetworkError"""
        with pytest.raises(NetworkError) as exc_info:
            raise NetworkError("Connection timeout")

        assert "Connection timeout" in str(exc_info.value)

    def test_raise_authentication_error(self):
        """Test raising AuthenticationError"""
        with pytest.raises(AuthenticationError) as exc_info:
            raise AuthenticationError("Invalid credentials")

        assert "Invalid credentials" in str(exc_info.value)

    def test_raise_market_not_found(self):
        """Test raising MarketNotFound"""
        with pytest.raises(MarketNotFound) as exc_info:
            raise MarketNotFound("Market ID: 123 not found")

        assert "Market ID: 123 not found" in str(exc_info.value)

    def test_catch_base_error(self):
        """Test catching DrManhattanError catches all subclasses"""
        with pytest.raises(DrManhattanError):
            raise ExchangeError("Test")

        with pytest.raises(DrManhattanError):
            raise NetworkError("Test")

        with pytest.raises(DrManhattanError):
            raise AuthenticationError("Test")


class TestErrorMessages:
    """Test error messages and formatting"""

    def test_error_with_details(self):
        """Test error with detailed message"""
        details = {"code": 400, "message": "Bad request"}
        error = ExchangeError(f"Request failed: {details}")
        assert "400" in str(error)
        assert "Bad request" in str(error)

    def test_error_chaining(self):
        """Test error chaining"""
        try:
            try:
                raise ValueError("Original error")
            except ValueError as e:
                raise ExchangeError("Exchange error") from e
        except ExchangeError as exc:
            assert exc.__cause__ is not None
            assert isinstance(exc.__cause__, ValueError)

    def test_multiple_error_types(self):
        """Test distinguishing between error types"""
        network_err = NetworkError("Network issue")
        auth_err = AuthenticationError("Auth issue")

        assert type(network_err) != type(auth_err)
        assert isinstance(network_err, DrManhattanError)
        assert isinstance(auth_err, DrManhattanError)


class TestErrorContext:
    """Test errors in realistic contexts"""

    def test_api_request_error(self):
        """Test handling API request errors"""
        def make_request():
            raise NetworkError("Connection timeout after 30s")

        with pytest.raises(NetworkError) as exc_info:
            make_request()

        assert "timeout" in str(exc_info.value).lower()

    def test_authentication_failure(self):
        """Test authentication failure"""
        def authenticate(api_key):
            if not api_key:
                raise AuthenticationError("API key required")
            if api_key == "invalid":
                raise AuthenticationError("Invalid API key")
            return True

        with pytest.raises(AuthenticationError, match="API key required"):
            authenticate(None)

        with pytest.raises(AuthenticationError, match="Invalid API key"):
            authenticate("invalid")

        assert authenticate("valid_key") is True

    def test_insufficient_balance_error(self):
        """Test insufficient balance error"""
        def place_order(balance, order_cost):
            if balance < order_cost:
                raise InsufficientFunds(
                    f"Insufficient balance: {balance} < {order_cost}"
                )
            return True

        with pytest.raises(InsufficientFunds) as exc_info:
            place_order(100, 200)

        assert "100" in str(exc_info.value)
        assert "200" in str(exc_info.value)

    def test_invalid_order_parameters(self):
        """Test invalid order parameters"""
        def validate_order(price, size):
            if price <= 0 or price > 1:
                raise InvalidOrder("Price must be between 0 and 1")
            if size <= 0:
                raise InvalidOrder("Size must be positive")
            return True

        with pytest.raises(InvalidOrder, match="Price must be between 0 and 1"):
            validate_order(1.5, 100)

        with pytest.raises(InvalidOrder, match="Size must be positive"):
            validate_order(0.5, -10)

        assert validate_order(0.65, 100) is True

    def test_market_not_found_with_id(self):
        """Test market not found with market ID"""
        def get_market(market_id, available_markets):
            if market_id not in available_markets:
                raise MarketNotFound(f"Market {market_id} not found")
            return available_markets[market_id]

        markets = {"market_1": "Data 1"}

        with pytest.raises(MarketNotFound, match="market_2 not found"):
            get_market("market_2", markets)

        assert get_market("market_1", markets) == "Data 1"
