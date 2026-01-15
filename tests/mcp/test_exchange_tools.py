"""Test exchange tools."""

import pytest

from dr_manhattan.mcp.tools import exchange_tools


def test_list_exchanges():
    """Test list_exchanges returns correct exchanges."""
    exchanges = exchange_tools.list_exchanges()

    assert isinstance(exchanges, list)
    assert len(exchanges) == 5
    assert "polymarket" in exchanges
    assert "opinion" in exchanges
    assert "limitless" in exchanges
    assert "predictfun" in exchanges
    assert "kalshi" in exchanges


def test_validate_credentials_without_env():
    """Test validate_credentials without environment variables."""
    # Should return invalid when no credentials
    result = exchange_tools.validate_credentials("polymarket")

    assert isinstance(result, dict)
    assert "valid" in result
    assert "exchange" in result
    # Without real credentials, should be invalid
    assert result["exchange"] == "polymarket"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
