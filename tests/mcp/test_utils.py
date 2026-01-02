"""Test MCP utilities."""

from datetime import datetime
from enum import Enum

import pytest

from dr_manhattan.base.errors import (
    AuthenticationError,
    MarketNotFound,
    NetworkError,
    RateLimitError,
)
from dr_manhattan.mcp.utils import McpError, serialize_model, translate_error


class TestSerializeModel:
    """Test serialize_model function."""

    def test_primitives(self):
        """Test primitive types."""
        assert serialize_model(123) == 123
        assert serialize_model("test") == "test"
        assert serialize_model(True) is True
        assert serialize_model(None) is None
        assert serialize_model(3.14) == 3.14

    def test_datetime(self):
        """Test datetime serialization."""
        now = datetime(2024, 1, 1, 12, 0, 0)
        result = serialize_model(now)
        assert isinstance(result, str)
        assert "2024-01-01" in result

    def test_enum(self):
        """Test enum serialization."""

        class TestEnum(Enum):
            VALUE1 = "test1"
            VALUE2 = "test2"

        assert serialize_model(TestEnum.VALUE1) == "test1"
        assert serialize_model(TestEnum.VALUE2) == "test2"

    def test_list(self):
        """Test list serialization."""
        data = [1, 2, "three", True]
        result = serialize_model(data)
        assert result == [1, 2, "three", True]

    def test_dict(self):
        """Test dict serialization."""
        data = {"key": "value", "num": 123, "bool": True}
        result = serialize_model(data)
        assert result == data

    def test_nested_structures(self):
        """Test nested data structures."""
        data = {
            "list": [1, 2, 3],
            "dict": {"nested": "value"},
            "mixed": [{"a": 1}, {"b": 2}],
        }
        result = serialize_model(data)
        assert result == data


class TestErrorTranslation:
    """Test error translation."""

    def test_market_not_found(self):
        """Test MarketNotFound translation."""
        error = MarketNotFound("Market not found")
        mcp_error = translate_error(error, {"exchange": "polymarket"})

        assert isinstance(mcp_error, McpError)
        assert mcp_error.code == -32007
        assert "Market not found" in mcp_error.message
        assert mcp_error.data["exchange"] == "polymarket"

    def test_network_error(self):
        """Test NetworkError translation."""
        error = NetworkError("Connection failed")
        mcp_error = translate_error(error)

        assert mcp_error.code == -32002
        assert "Connection failed" in mcp_error.message

    def test_rate_limit_error(self):
        """Test RateLimitError translation."""
        error = RateLimitError("Rate limit exceeded")
        mcp_error = translate_error(error)

        assert mcp_error.code == -32003

    def test_authentication_error(self):
        """Test AuthenticationError translation."""
        error = AuthenticationError("Auth failed")
        mcp_error = translate_error(error)

        assert mcp_error.code == -32004

    def test_error_with_context(self):
        """Test error translation with context."""
        error = MarketNotFound("Market not found")
        context = {
            "exchange": "polymarket",
            "market_id": "0x123",
            "user": "test",
        }
        mcp_error = translate_error(error, context)

        assert mcp_error.data["exchange"] == "polymarket"
        assert mcp_error.data["market_id"] == "0x123"
        assert mcp_error.data["user"] == "test"

    def test_mcp_error_to_dict(self):
        """Test McpError.to_dict()."""
        error = McpError(
            code=-32000,
            message="Test error",
            data={"key": "value"},
        )

        result = error.to_dict()
        assert result["code"] == -32000
        assert result["message"] == "Test error"
        assert result["data"]["key"] == "value"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
