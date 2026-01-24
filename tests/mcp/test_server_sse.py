"""Tests for MCP SSE server.

Tests cover:
- Credential extraction from headers
- Health check endpoint
- Credential masking in logs
- Credential validation

Note: Tests that require the 'mcp' package are skipped if not installed.
"""

from unittest.mock import patch

import pytest


# Check if mcp package is available
try:
    import mcp  # noqa: F401

    HAS_MCP = True
except ImportError:
    HAS_MCP = False


class TestCredentialExtraction:
    """Tests for extracting credentials from HTTP headers."""

    def test_extract_polymarket_credentials(self):
        """Test extraction of Polymarket credentials from headers."""
        from dr_manhattan.mcp.utils.security import get_credentials_from_headers

        headers = {
            "X-Polymarket-Private-Key": "0x1234567890abcdef",
            "X-Polymarket-Funder": "0xfunder123",
            "X-Polymarket-Proxy-Wallet": "0xproxy456",
        }

        credentials = get_credentials_from_headers(headers)

        assert "polymarket" in credentials
        assert credentials["polymarket"]["private_key"] == "0x1234567890abcdef"
        assert credentials["polymarket"]["funder"] == "0xfunder123"
        assert credentials["polymarket"]["proxy_wallet"] == "0xproxy456"

    def test_extract_limitless_credentials(self):
        """Test extraction of Limitless credentials from headers."""
        from dr_manhattan.mcp.utils.security import get_credentials_from_headers

        headers = {"X-Limitless-Private-Key": "0xprivatekey"}

        credentials = get_credentials_from_headers(headers)

        assert "limitless" in credentials
        assert credentials["limitless"]["private_key"] == "0xprivatekey"

    def test_extract_multiple_exchanges(self):
        """Test extraction of credentials for multiple exchanges."""
        from dr_manhattan.mcp.utils.security import get_credentials_from_headers

        headers = {
            "X-Polymarket-Private-Key": "0xpoly",
            "X-Polymarket-Funder": "0xfunder",
            "X-Limitless-Private-Key": "0xlimitless",
            "X-Opinion-Private-Key": "0xopinion",
        }

        credentials = get_credentials_from_headers(headers)

        assert len(credentials) == 3
        assert "polymarket" in credentials
        assert "limitless" in credentials
        assert "opinion" in credentials

    def test_case_insensitive_headers(self):
        """Test that header extraction is case-insensitive."""
        from dr_manhattan.mcp.utils.security import get_credentials_from_headers

        headers = {
            "x-polymarket-private-key": "0xkey",
            "X-POLYMARKET-FUNDER": "0xfunder",
        }

        credentials = get_credentials_from_headers(headers)

        assert credentials["polymarket"]["private_key"] == "0xkey"
        assert credentials["polymarket"]["funder"] == "0xfunder"

    def test_empty_headers(self):
        """Test extraction with no credential headers."""
        from dr_manhattan.mcp.utils.security import get_credentials_from_headers

        headers = {"Content-Type": "application/json", "Accept": "*/*"}

        credentials = get_credentials_from_headers(headers)

        assert credentials == {}

    def test_signature_type_conversion(self):
        """Test that signature_type is converted to int."""
        from dr_manhattan.mcp.utils.security import get_credentials_from_headers

        headers = {
            "X-Polymarket-Private-Key": "0xkey",
            "X-Polymarket-Funder": "0xfunder",
            "X-Polymarket-Signature-Type": "1",
        }

        credentials = get_credentials_from_headers(headers)

        assert credentials["polymarket"]["signature_type"] == 1

    def test_invalid_signature_type_defaults_to_zero(self):
        """Test that invalid signature_type defaults to 0."""
        from dr_manhattan.mcp.utils.security import get_credentials_from_headers

        headers = {
            "X-Polymarket-Private-Key": "0xkey",
            "X-Polymarket-Funder": "0xfunder",
            "X-Polymarket-Signature-Type": "invalid",
        }

        credentials = get_credentials_from_headers(headers)

        assert credentials["polymarket"]["signature_type"] == 0


class TestCredentialMasking:
    """Tests for credential masking in logs."""

    def test_sensitive_headers_fully_masked(self):
        """Test that sensitive headers are fully masked (no partial exposure)."""
        from dr_manhattan.mcp.utils.security import sanitize_headers_for_logging

        headers = {
            "X-Polymarket-Private-Key": "0x1234567890abcdef1234567890abcdef",
            "Content-Type": "application/json",
        }

        sanitized = sanitize_headers_for_logging(headers)

        # Should be fully redacted, not showing first/last chars
        assert sanitized["X-Polymarket-Private-Key"] == "[REDACTED]"
        assert sanitized["Content-Type"] == "application/json"

    def test_empty_sensitive_header_marked(self):
        """Test that empty sensitive headers are marked as empty."""
        from dr_manhattan.mcp.utils.security import sanitize_headers_for_logging

        headers = {"X-Polymarket-Private-Key": "", "Content-Type": "application/json"}

        sanitized = sanitize_headers_for_logging(headers)

        assert sanitized["X-Polymarket-Private-Key"] == "[EMPTY]"

    def test_all_sensitive_headers_masked(self):
        """Test that all known sensitive headers are masked."""
        from dr_manhattan.mcp.utils.security import (
            SENSITIVE_HEADERS,
            sanitize_headers_for_logging,
        )

        headers = {h: "secret_value_123" for h in SENSITIVE_HEADERS}
        headers["safe-header"] = "visible"

        sanitized = sanitize_headers_for_logging(headers)

        for header in SENSITIVE_HEADERS:
            assert sanitized[header] == "[REDACTED]"
        assert sanitized["safe-header"] == "visible"


class TestCredentialValidation:
    """Tests for credential validation."""

    def test_validate_polymarket_credentials_valid(self):
        """Test validation passes with all required Polymarket credentials."""
        from dr_manhattan.mcp.utils.security import validate_credentials_present

        credentials = {"private_key": "0xkey", "funder": "0xfunder"}

        is_valid, error = validate_credentials_present(credentials, "polymarket")

        assert is_valid is True
        assert error is None

    def test_validate_polymarket_credentials_missing_key(self):
        """Test validation fails when private_key is missing."""
        from dr_manhattan.mcp.utils.security import validate_credentials_present

        credentials = {"funder": "0xfunder"}

        is_valid, error = validate_credentials_present(credentials, "polymarket")

        assert is_valid is False
        assert "private_key" in error

    def test_validate_polymarket_credentials_missing_funder(self):
        """Test validation fails when funder is missing."""
        from dr_manhattan.mcp.utils.security import validate_credentials_present

        credentials = {"private_key": "0xkey"}

        is_valid, error = validate_credentials_present(credentials, "polymarket")

        assert is_valid is False
        assert "funder" in error

    def test_validate_limitless_credentials(self):
        """Test validation for Limitless (only needs private_key)."""
        from dr_manhattan.mcp.utils.security import validate_credentials_present

        credentials = {"private_key": "0xkey"}

        is_valid, error = validate_credentials_present(credentials, "limitless")

        assert is_valid is True
        assert error is None

    def test_error_message_transport_agnostic(self):
        """Test that error messages don't contain HTTP-specific references."""
        from dr_manhattan.mcp.utils.security import validate_credentials_present

        credentials = {}

        is_valid, error = validate_credentials_present(credentials, "polymarket")

        assert is_valid is False
        # Should NOT contain HTTP header names like X-Polymarket-Private-Key
        assert "X-" not in error
        assert "header" not in error.lower()


@pytest.mark.skipif(not HAS_MCP, reason="MCP package not installed")
class TestHealthCheck:
    """Tests for health check endpoint (requires mcp package)."""

    def test_health_check_returns_healthy(self):
        """Test that health check returns healthy status."""
        from starlette.testclient import TestClient

        from dr_manhattan.mcp.server_sse import app

        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "dr-manhattan-mcp"
        assert data["transport"] == "sse"


@pytest.mark.skipif(not HAS_MCP, reason="MCP package not installed")
class TestRootEndpoint:
    """Tests for root endpoint (requires mcp package)."""

    def test_root_returns_usage_info(self):
        """Test that root endpoint returns usage information."""
        from starlette.testclient import TestClient

        from dr_manhattan.mcp.server_sse import app

        client = TestClient(app)
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert "service" in data
        assert "endpoints" in data
        assert "/sse" in data["endpoints"]
        assert "/health" in data["endpoints"]


@pytest.mark.skipif(not HAS_MCP, reason="MCP package not installed")
class TestEnvironmentValidation:
    """Tests for environment variable validation (requires mcp package)."""

    def test_invalid_port_raises_error(self):
        """Test that invalid PORT causes error."""
        from dr_manhattan.mcp.server_sse import _validate_env

        with patch.dict("os.environ", {"PORT": "invalid"}, clear=False):
            with pytest.raises(SystemExit):
                _validate_env()

    def test_port_out_of_range_raises_error(self):
        """Test that PORT outside valid range causes error."""
        from dr_manhattan.mcp.server_sse import _validate_env

        with patch.dict("os.environ", {"PORT": "99999"}, clear=False):
            with pytest.raises(SystemExit):
                _validate_env()

    def test_valid_port_returns_config(self):
        """Test that valid PORT returns correct config."""
        from dr_manhattan.mcp.server_sse import _validate_env

        with patch.dict("os.environ", {"PORT": "3000", "HOST": "127.0.0.1"}, clear=False):
            host, port = _validate_env()

            assert host == "127.0.0.1"
            assert port == 3000


@pytest.mark.skipif(not HAS_MCP, reason="MCP package not installed")
class TestToolDefinitions:
    """Tests for shared tool definitions (requires mcp package)."""

    def test_tool_definitions_not_empty(self):
        """Test that tool definitions are loaded."""
        from dr_manhattan.mcp.tools import get_tool_definitions

        tools = get_tool_definitions()

        assert len(tools) > 0

    def test_tool_dispatch_matches_definitions(self):
        """Test that dispatch table has entry for each tool."""
        from dr_manhattan.mcp.tools import TOOL_DISPATCH, get_tool_definitions

        tools = get_tool_definitions()
        tool_names = {t.name for t in tools}

        assert set(TOOL_DISPATCH.keys()) == tool_names

    def test_required_tools_present(self):
        """Test that essential tools are defined."""
        from dr_manhattan.mcp.tools import get_tool_definitions

        tools = get_tool_definitions()
        tool_names = {t.name for t in tools}

        required = [
            "list_exchanges",
            "search_markets",
            "fetch_balance",
            "create_order",
        ]

        for name in required:
            assert name in tool_names, f"Missing required tool: {name}"
