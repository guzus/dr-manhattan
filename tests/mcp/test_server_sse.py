"""Tests for MCP SSE server.

Tests cover:
- Credential extraction from headers (Polymarket Builder profile only)
- Health check endpoint
- Credential masking in logs
- Credential validation
- Write operation restrictions

Note: Tests that require the 'mcp' package are skipped if not installed.
"""

# isort: skip_file
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
        """Test extraction of Polymarket Builder profile credentials."""
        from dr_manhattan.mcp.utils.security import get_credentials_from_headers

        headers = {
            "X-Polymarket-Api-Key": "api_key_123",
            "X-Polymarket-Api-Secret": "api_secret_456",
            "X-Polymarket-Passphrase": "passphrase_789",
        }

        credentials = get_credentials_from_headers(headers)

        assert "polymarket" in credentials
        assert credentials["polymarket"]["api_key"] == "api_key_123"
        assert credentials["polymarket"]["api_secret"] == "api_secret_456"
        assert credentials["polymarket"]["api_passphrase"] == "passphrase_789"

    def test_case_insensitive_headers(self):
        """Test that header extraction is case-insensitive."""
        from dr_manhattan.mcp.utils.security import get_credentials_from_headers

        headers = {
            "x-polymarket-api-key": "key",
            "X-POLYMARKET-API-SECRET": "secret",
            "X-Polymarket-Passphrase": "pass",
        }

        credentials = get_credentials_from_headers(headers)

        assert credentials["polymarket"]["api_key"] == "key"
        assert credentials["polymarket"]["api_secret"] == "secret"
        assert credentials["polymarket"]["api_passphrase"] == "pass"

    def test_empty_headers(self):
        """Test extraction with no credential headers."""
        from dr_manhattan.mcp.utils.security import get_credentials_from_headers

        headers = {"Content-Type": "application/json", "Accept": "*/*"}

        credentials = get_credentials_from_headers(headers)

        assert credentials == {}

    def test_partial_credentials(self):
        """Test extraction with only some Polymarket headers."""
        from dr_manhattan.mcp.utils.security import get_credentials_from_headers

        headers = {"X-Polymarket-Api-Key": "key_only"}

        credentials = get_credentials_from_headers(headers)

        # Should still extract partial credentials
        assert "polymarket" in credentials
        assert credentials["polymarket"]["api_key"] == "key_only"
        assert "api_secret" not in credentials["polymarket"]


class TestCredentialMasking:
    """Tests for credential masking in logs."""

    def test_sensitive_headers_fully_masked(self):
        """Test that sensitive headers are fully masked (no partial exposure)."""
        from dr_manhattan.mcp.utils.security import sanitize_headers_for_logging

        headers = {
            "X-Polymarket-Api-Key": "api_key_1234567890",
            "Content-Type": "application/json",
        }

        sanitized = sanitize_headers_for_logging(headers)

        # Should be fully redacted, not showing first/last chars
        assert sanitized["X-Polymarket-Api-Key"] == "[REDACTED]"
        assert sanitized["Content-Type"] == "application/json"

    def test_empty_sensitive_header_marked(self):
        """Test that empty sensitive headers are marked as empty."""
        from dr_manhattan.mcp.utils.security import sanitize_headers_for_logging

        headers = {"X-Polymarket-Api-Key": "", "Content-Type": "application/json"}

        sanitized = sanitize_headers_for_logging(headers)

        assert sanitized["X-Polymarket-Api-Key"] == "[EMPTY]"

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

        credentials = {
            "api_key": "key",
            "api_secret": "secret",
            "api_passphrase": "pass",
        }

        is_valid, error = validate_credentials_present(credentials, "polymarket")

        assert is_valid is True
        assert error is None

    def test_validate_polymarket_credentials_missing_key(self):
        """Test validation fails when api_key is missing."""
        from dr_manhattan.mcp.utils.security import validate_credentials_present

        credentials = {"api_secret": "secret", "api_passphrase": "pass"}

        is_valid, error = validate_credentials_present(credentials, "polymarket")

        assert is_valid is False
        assert "api_key" in error

    def test_validate_polymarket_credentials_missing_secret(self):
        """Test validation fails when api_secret is missing."""
        from dr_manhattan.mcp.utils.security import validate_credentials_present

        credentials = {"api_key": "key", "api_passphrase": "pass"}

        is_valid, error = validate_credentials_present(credentials, "polymarket")

        assert is_valid is False
        assert "api_secret" in error

    def test_validate_unknown_exchange(self):
        """Test validation for unknown exchange (no required fields)."""
        from dr_manhattan.mcp.utils.security import validate_credentials_present

        credentials = {"some_key": "value"}

        # Unknown exchanges have no requirements in SSE mode
        is_valid, error = validate_credentials_present(credentials, "limitless")

        assert is_valid is True
        assert error is None

    def test_error_message_transport_agnostic(self):
        """Test that error messages don't contain HTTP-specific references."""
        from dr_manhattan.mcp.utils.security import validate_credentials_present

        credentials = {}

        is_valid, error = validate_credentials_present(credentials, "polymarket")

        assert is_valid is False
        # Should NOT contain HTTP header names like X-Polymarket-Api-Key
        assert "X-" not in error
        assert "header" not in error.lower()


class TestWriteOperationValidation:
    """Tests for write operation restrictions."""

    def test_write_operation_allowed_for_polymarket(self):
        """Test that write operations are allowed for Polymarket."""
        from dr_manhattan.mcp.utils.security import validate_write_operation

        is_allowed, error = validate_write_operation("create_order", "polymarket")

        assert is_allowed is True
        assert error is None

    def test_write_operation_blocked_for_other_exchanges(self):
        """Test that write operations are blocked for non-Polymarket exchanges."""
        from dr_manhattan.mcp.utils.security import validate_write_operation

        for exchange in ["limitless", "opinion", "kalshi", "predictfun"]:
            is_allowed, error = validate_write_operation("create_order", exchange)

            assert is_allowed is False
            assert "not supported" in error
            assert "Builder profile" in error

    def test_read_operation_allowed_for_all_exchanges(self):
        """Test that read operations are allowed for all exchanges."""
        from dr_manhattan.mcp.utils.security import validate_write_operation

        for exchange in ["polymarket", "limitless", "opinion", "kalshi"]:
            is_allowed, error = validate_write_operation("fetch_markets", exchange)

            assert is_allowed is True
            assert error is None

    def test_all_write_operations_blocked_for_other_exchanges(self):
        """Test that all write operations are blocked for non-Polymarket."""
        from dr_manhattan.mcp.utils.security import WRITE_OPERATIONS, validate_write_operation

        for op in WRITE_OPERATIONS:
            is_allowed, error = validate_write_operation(op, "limitless")

            assert is_allowed is False
            assert error is not None

    def test_write_operation_without_exchange(self):
        """Test write operation without exchange parameter."""
        from dr_manhattan.mcp.utils.security import validate_write_operation

        is_allowed, error = validate_write_operation("create_order", None)

        assert is_allowed is False
        assert "requires an exchange" in error


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

    def test_root_shows_security_model(self):
        """Test that root endpoint shows security model."""
        from starlette.testclient import TestClient

        from dr_manhattan.mcp.server_sse import app

        client = TestClient(app)
        response = client.get("/")

        data = response.json()
        assert "security" in data
        assert "Polymarket" in data["security"]["write_operations"]


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
