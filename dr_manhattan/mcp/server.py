"""
Dr. Manhattan MCP Server

Main entry point for the Model Context Protocol server.

Logging Architecture:
    MCP uses stdout for JSON-RPC communication, so all logging MUST go to stderr.
    This module patches the dr_manhattan logging system before any other imports
    to ensure all log output is redirected to stderr. The patching strategy:

    1. Replace setup_logger in dr_manhattan.utils before importing other modules
    2. Configure root logger with stderr handler
    3. After imports, fix_all_loggers() cleans up any handlers that slipped through

    This approach is necessary because dr_manhattan modules create loggers at
    import time. Any stdout output would corrupt the JSON-RPC protocol.
"""

import asyncio
import json
import logging
import signal
import sys
from pathlib import Path
from typing import Any, List

# =============================================================================
# CRITICAL: Logger patching MUST happen BEFORE importing dr_manhattan modules
# =============================================================================
# MCP uses stdout exclusively for JSON-RPC communication. Any text output to
# stdout (logs, debug prints, ANSI colors) corrupts the protocol and causes
# parsing errors like "Unexpected token '✓'" or "Unexpected token '←[90m'".
#
# The dr_manhattan base project uses stdout for logging (with ANSI colors).
# We must patch the logging system BEFORE any module imports to ensure:
# 1. All loggers use stderr instead of stdout
# 2. No ANSI color codes are used (they appear as garbage in JSON)
# =============================================================================


def _mcp_setup_logger(name: str = None, level: int = logging.INFO):
    """MCP-compatible logger that outputs to stderr without colors."""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.handlers = []

    # Use stderr instead of stdout, no ANSI colors
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(handler)
    logger.propagate = False

    return logger


# Configure root logging to use stderr BEFORE any imports
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
    force=True,
)

# Patch the logger module BEFORE importing dr_manhattan.utils
# This prevents default_logger from being created with stdout handler
import dr_manhattan.utils.logger as logger_module  # noqa: E402

logger_module.setup_logger = _mcp_setup_logger
# Also recreate default_logger with the patched function
logger_module.default_logger = _mcp_setup_logger("dr_manhattan")

# Now we can safely import dr_manhattan.utils (it will use the patched logger)
import dr_manhattan.utils  # noqa: E402

dr_manhattan.utils.setup_logger = _mcp_setup_logger

# Third-party imports after patching
from dotenv import load_dotenv  # noqa: E402
from mcp.server import Server  # noqa: E402
from mcp.server.stdio import stdio_server  # noqa: E402
from mcp.types import TextContent, Tool  # noqa: E402

# Load environment variables from .env file
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(env_path)


def fix_all_loggers():
    """Remove ALL handlers and configure only root logger with stderr."""
    # Remove all handlers from all loggers
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    for name in logging.Logger.manager.loggerDict:
        logger_obj = logging.getLogger(name)
        if not isinstance(logger_obj, logging.Logger):
            continue
        for handler in logger_obj.handlers[:]:
            logger_obj.removeHandler(handler)
        # Enable propagation so it uses root logger
        logger_obj.propagate = True

    # Add single stderr handler to root logger
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%H:%M:%S"))
    root_logger.addHandler(stderr_handler)
    root_logger.setLevel(logging.INFO)


# Import modules after logger monkey-patching (they will create loggers with stderr)
from .session import ExchangeSessionManager, StrategySessionManager  # noqa: E402
from .tools import (  # noqa: E402
    account_tools,
    exchange_tools,
    market_tools,
    strategy_tools,
    trading_tools,
)
from .utils import check_rate_limit, translate_error  # noqa: E402

# Fix loggers immediately after imports
fix_all_loggers()

# Get logger for this module
logger = logging.getLogger(__name__)

# Initialize server
app = Server("dr-manhattan")

# Session managers (now loggers are fixed)
exchange_manager = ExchangeSessionManager()
strategy_manager = StrategySessionManager()


# Tool registration
@app.list_tools()
async def list_tools() -> List[Tool]:
    """List all available MCP tools."""
    return [
        # Exchange tools (3)
        Tool(
            name="list_exchanges",
            description="List all available prediction market exchanges",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="get_exchange_info",
            description="Get exchange metadata and capabilities",
            inputSchema={
                "type": "object",
                "properties": {
                    "exchange": {
                        "type": "string",
                        "description": "Exchange name (polymarket, opinion, limitless)",
                    }
                },
                "required": ["exchange"],
            },
        ),
        Tool(
            name="validate_credentials",
            description="Validate exchange credentials without trading",
            inputSchema={
                "type": "object",
                "properties": {
                    "exchange": {
                        "type": "string",
                        "description": "Exchange name",
                    }
                },
                "required": ["exchange"],
            },
        ),
        # Market tools (10)
        Tool(
            name="fetch_markets",
            description="Fetch all available markets from an exchange",
            inputSchema={
                "type": "object",
                "properties": {
                    "exchange": {"type": "string", "description": "Exchange name"},
                    "params": {
                        "type": "object",
                        "description": "Optional filters (limit, offset, closed, active)",
                    },
                },
                "required": ["exchange"],
            },
        ),
        Tool(
            name="fetch_market",
            description="Fetch a specific market by ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "exchange": {"type": "string"},
                    "market_id": {"type": "string", "description": "Market identifier"},
                },
                "required": ["exchange", "market_id"],
            },
        ),
        Tool(
            name="fetch_markets_by_slug",
            description="Fetch markets by slug or URL (Polymarket, Limitless)",
            inputSchema={
                "type": "object",
                "properties": {
                    "exchange": {"type": "string"},
                    "slug": {"type": "string", "description": "Market slug or full URL"},
                },
                "required": ["exchange", "slug"],
            },
        ),
        Tool(
            name="get_orderbook",
            description="Get orderbook for a token",
            inputSchema={
                "type": "object",
                "properties": {
                    "exchange": {"type": "string"},
                    "token_id": {"type": "string", "description": "Token ID"},
                },
                "required": ["exchange", "token_id"],
            },
        ),
        Tool(
            name="get_best_bid_ask",
            description="Get best bid and ask prices (uses WebSocket cache if available)",
            inputSchema={
                "type": "object",
                "properties": {
                    "exchange": {"type": "string"},
                    "token_id": {"type": "string"},
                },
                "required": ["exchange", "token_id"],
            },
        ),
        # Trading tools (5)
        Tool(
            name="create_order",
            description="Create a new order",
            inputSchema={
                "type": "object",
                "properties": {
                    "exchange": {"type": "string"},
                    "market_id": {"type": "string"},
                    "outcome": {"type": "string", "description": "Outcome (Yes, No, etc.)"},
                    "side": {"type": "string", "enum": ["buy", "sell"]},
                    "price": {"type": "number", "minimum": 0, "maximum": 1},
                    "size": {"type": "number", "minimum": 0},
                    "params": {"type": "object", "description": "Additional parameters"},
                },
                "required": ["exchange", "market_id", "outcome", "side", "price", "size"],
            },
        ),
        Tool(
            name="cancel_order",
            description="Cancel an existing order",
            inputSchema={
                "type": "object",
                "properties": {
                    "exchange": {"type": "string"},
                    "order_id": {"type": "string"},
                    "market_id": {"type": "string"},
                },
                "required": ["exchange", "order_id"],
            },
        ),
        Tool(
            name="cancel_all_orders",
            description="Cancel all open orders",
            inputSchema={
                "type": "object",
                "properties": {
                    "exchange": {"type": "string"},
                    "market_id": {"type": "string", "description": "Optional market filter"},
                },
                "required": ["exchange"],
            },
        ),
        Tool(
            name="fetch_open_orders",
            description="Fetch all open orders",
            inputSchema={
                "type": "object",
                "properties": {
                    "exchange": {"type": "string"},
                    "market_id": {"type": "string"},
                },
                "required": ["exchange"],
            },
        ),
        Tool(
            name="fetch_order",
            description="Fetch order details by ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "exchange": {"type": "string"},
                    "order_id": {"type": "string"},
                    "market_id": {"type": "string"},
                },
                "required": ["exchange", "order_id"],
            },
        ),
        # Account tools (5)
        Tool(
            name="fetch_balance",
            description="Fetch account balance",
            inputSchema={
                "type": "object",
                "properties": {"exchange": {"type": "string"}},
                "required": ["exchange"],
            },
        ),
        Tool(
            name="fetch_positions",
            description="Fetch current positions",
            inputSchema={
                "type": "object",
                "properties": {
                    "exchange": {"type": "string"},
                    "market_id": {"type": "string"},
                },
                "required": ["exchange"],
            },
        ),
        Tool(
            name="calculate_nav",
            description="Calculate Net Asset Value",
            inputSchema={
                "type": "object",
                "properties": {
                    "exchange": {"type": "string"},
                    "market_id": {"type": "string"},
                },
                "required": ["exchange"],
            },
        ),
        Tool(
            name="fetch_positions_for_market",
            description="Fetch positions for a specific market with token IDs",
            inputSchema={
                "type": "object",
                "properties": {
                    "exchange": {"type": "string"},
                    "market_id": {"type": "string"},
                },
                "required": ["exchange", "market_id"],
            },
        ),
        # Strategy tools (9)
        Tool(
            name="create_strategy_session",
            description="Start market making strategy in background",
            inputSchema={
                "type": "object",
                "properties": {
                    "strategy_type": {"type": "string", "enum": ["market_making"]},
                    "exchange": {"type": "string"},
                    "market_id": {"type": "string"},
                    "max_position": {"type": "number", "default": 100.0},
                    "order_size": {"type": "number", "default": 5.0},
                    "max_delta": {"type": "number", "default": 20.0},
                    "check_interval": {"type": "number", "default": 5.0},
                    "duration_minutes": {"type": "number"},
                },
                "required": ["strategy_type", "exchange", "market_id"],
            },
        ),
        Tool(
            name="get_strategy_status",
            description="Get real-time strategy status",
            inputSchema={
                "type": "object",
                "properties": {"session_id": {"type": "string"}},
                "required": ["session_id"],
            },
        ),
        Tool(
            name="stop_strategy",
            description="Stop strategy and optionally cleanup",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "cleanup": {"type": "boolean", "default": True},
                },
                "required": ["session_id"],
            },
        ),
        Tool(
            name="list_strategy_sessions",
            description="List all active strategy sessions",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="pause_strategy",
            description="Pause strategy execution",
            inputSchema={
                "type": "object",
                "properties": {"session_id": {"type": "string"}},
                "required": ["session_id"],
            },
        ),
        Tool(
            name="resume_strategy",
            description="Resume paused strategy",
            inputSchema={
                "type": "object",
                "properties": {"session_id": {"type": "string"}},
                "required": ["session_id"],
            },
        ),
        Tool(
            name="get_strategy_metrics",
            description="Get strategy performance metrics",
            inputSchema={
                "type": "object",
                "properties": {"session_id": {"type": "string"}},
                "required": ["session_id"],
            },
        ),
        # Market discovery tools (6)
        Tool(
            name="fetch_token_ids",
            description="Fetch token IDs for a market",
            inputSchema={
                "type": "object",
                "properties": {
                    "exchange": {"type": "string"},
                    "market_id": {"type": "string"},
                },
                "required": ["exchange", "market_id"],
            },
        ),
        Tool(
            name="find_tradeable_market",
            description="Find a suitable market for trading",
            inputSchema={
                "type": "object",
                "properties": {
                    "exchange": {"type": "string"},
                    "binary": {"type": "boolean", "default": True},
                    "limit": {"type": "integer", "default": 100},
                    "min_liquidity": {"type": "number", "default": 0.0},
                },
                "required": ["exchange"],
            },
        ),
        Tool(
            name="find_crypto_hourly_market",
            description="Find crypto hourly price market (Polymarket)",
            inputSchema={
                "type": "object",
                "properties": {
                    "exchange": {"type": "string"},
                    "token_symbol": {"type": "string"},
                    "min_liquidity": {"type": "number", "default": 0.0},
                    "is_active": {"type": "boolean", "default": True},
                },
                "required": ["exchange"],
            },
        ),
        Tool(
            name="parse_market_identifier",
            description="Parse market slug from URL",
            inputSchema={
                "type": "object",
                "properties": {"identifier": {"type": "string"}},
                "required": ["identifier"],
            },
        ),
        Tool(
            name="get_tag_by_slug",
            description="Get Polymarket tag information",
            inputSchema={
                "type": "object",
                "properties": {"slug": {"type": "string"}},
                "required": ["slug"],
            },
        ),
    ]


# Tool dispatch table (replaces long if-elif chain)
# Format: tool_name -> (handler_function, requires_arguments)
TOOL_DISPATCH = {
    # Exchange tools (3)
    "list_exchanges": (exchange_tools.list_exchanges, False),
    "get_exchange_info": (exchange_tools.get_exchange_info, True),
    "validate_credentials": (exchange_tools.validate_credentials, True),
    # Market tools (10)
    "fetch_markets": (market_tools.fetch_markets, True),
    "fetch_market": (market_tools.fetch_market, True),
    "fetch_markets_by_slug": (market_tools.fetch_markets_by_slug, True),
    "get_orderbook": (market_tools.get_orderbook, True),
    "get_best_bid_ask": (market_tools.get_best_bid_ask, True),
    "fetch_token_ids": (market_tools.fetch_token_ids, True),
    "find_tradeable_market": (market_tools.find_tradeable_market, True),
    "find_crypto_hourly_market": (market_tools.find_crypto_hourly_market, True),
    "parse_market_identifier": (market_tools.parse_market_identifier, True),
    "get_tag_by_slug": (market_tools.get_tag_by_slug, True),
    # Trading tools (5)
    "create_order": (trading_tools.create_order, True),
    "cancel_order": (trading_tools.cancel_order, True),
    "cancel_all_orders": (trading_tools.cancel_all_orders, True),
    "fetch_open_orders": (trading_tools.fetch_open_orders, True),
    "fetch_order": (trading_tools.fetch_order, True),
    # Account tools (4)
    "fetch_balance": (account_tools.fetch_balance, True),
    "fetch_positions": (account_tools.fetch_positions, True),
    "calculate_nav": (account_tools.calculate_nav, True),
    "fetch_positions_for_market": (account_tools.fetch_positions_for_market, True),
    # Strategy tools (7)
    "create_strategy_session": (strategy_tools.create_strategy_session, True),
    "get_strategy_status": (strategy_tools.get_strategy_status, True),
    "stop_strategy": (strategy_tools.stop_strategy, True),
    "list_strategy_sessions": (strategy_tools.list_strategy_sessions, False),
    "pause_strategy": (strategy_tools.pause_strategy, True),
    "resume_strategy": (strategy_tools.resume_strategy, True),
    "get_strategy_metrics": (strategy_tools.get_strategy_metrics, True),
}


@app.call_tool()
async def call_tool(name: str, arguments: Any) -> List[TextContent]:
    """Handle tool execution with rate limiting."""
    try:
        # Check rate limit before processing
        if not check_rate_limit():
            raise ValueError(
                "Rate limit exceeded. Please wait before making more requests. "
                "The MCP server limits requests to prevent overload."
            )

        # Route to appropriate tool function using dispatch table
        if name not in TOOL_DISPATCH:
            raise ValueError(f"Unknown tool: {name}")

        handler, requires_args = TOOL_DISPATCH[name]
        result = handler(**arguments) if requires_args else handler()

        # Return result as text content
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    except Exception as e:
        # Translate error
        mcp_error = translate_error(e, {"tool": name, "arguments": arguments})
        error_response = {"error": mcp_error.to_dict()}
        return [TextContent(type="text", text=json.dumps(error_response, indent=2))]


# Shutdown flag for signal handler (avoids complex operations in signal context)
# False = running normally, True = shutdown requested (set by signal handler)
_shutdown_requested = False


def cleanup_handler(signum, frame):
    """
    Handle shutdown signal.

    IMPORTANT: Signal handlers must be minimal to avoid deadlock.
    Only sets a flag here; actual cleanup done in main loop.
    """
    global _shutdown_requested
    _shutdown_requested = True
    # Log to stderr directly (avoid any locking in logger)
    sys.stderr.write("[SIGNAL] Shutdown requested, cleaning up...\n")
    sys.stderr.flush()


async def _do_cleanup():
    """
    Perform actual cleanup (called from main context, not signal handler).

    Async-aware: runs blocking cleanup operations in thread pool
    to avoid blocking the event loop during shutdown.
    """
    logger.info("Shutting down MCP server...")

    # Run blocking cleanup operations in thread pool
    await asyncio.to_thread(strategy_manager.cleanup)
    await asyncio.to_thread(exchange_manager.cleanup)

    logger.info("Cleanup complete")


async def main():
    """Main entry point."""
    # Register signal handlers (only set flag, no complex operations)
    signal.signal(signal.SIGINT, cleanup_handler)
    signal.signal(signal.SIGTERM, cleanup_handler)

    logger.info("Starting Dr. Manhattan MCP Server...")

    try:
        # Run stdio server
        async with stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())
    finally:
        # Cleanup in main context (safe from deadlock, async-aware)
        await _do_cleanup()


def run():
    """Run the server."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
