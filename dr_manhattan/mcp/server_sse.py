"""
Dr. Manhattan MCP Server - SSE Transport for Remote Access

HTTP-based MCP server using Server-Sent Events (SSE) transport.
Allows remote Claude Desktop/Code connections without local installation.

Usage:
    python -m dr_manhattan.mcp.server_sse

Environment:
    PORT: Server port (default: 8080)
    LOG_LEVEL: Logging level (default: INFO)

Security:
    - Credentials passed via HTTP headers (X-{Exchange}-{Credential})
    - Sensitive headers never logged
    - HTTPS required in production (handled by Railway/hosting)
"""

import asyncio
import contextvars
import json
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# =============================================================================
# CRITICAL: Logger patching MUST happen BEFORE importing dr_manhattan modules
# =============================================================================


def _mcp_setup_logger(name: str = None, level: int = logging.INFO):
    """MCP-compatible logger that outputs to stderr without colors."""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.handlers = []

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(handler)
    logger.propagate = False

    return logger


# Configure root logging to use stderr BEFORE any imports
log_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
logging.basicConfig(
    level=log_level,
    format="[%(asctime)s] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
    force=True,
)

# Patch the logger module BEFORE importing dr_manhattan.utils
import dr_manhattan.utils.logger as logger_module  # noqa: E402

logger_module.setup_logger = _mcp_setup_logger
logger_module.default_logger = _mcp_setup_logger("dr_manhattan")

import dr_manhattan.utils  # noqa: E402

dr_manhattan.utils.setup_logger = _mcp_setup_logger

# Third-party imports after patching
from dotenv import load_dotenv  # noqa: E402
from mcp.server import Server  # noqa: E402
from mcp.server.sse import SseServerTransport  # noqa: E402
from mcp.types import TextContent, Tool  # noqa: E402
from starlette.applications import Starlette  # noqa: E402
from starlette.middleware import Middleware  # noqa: E402
from starlette.middleware.cors import CORSMiddleware  # noqa: E402
from starlette.requests import Request  # noqa: E402
from starlette.responses import JSONResponse, Response  # noqa: E402
from starlette.routing import Route  # noqa: E402

# Load environment variables
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(env_path)


def fix_all_loggers():
    """Remove ALL handlers and configure only root logger with stderr."""
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    for name in logging.Logger.manager.loggerDict:
        logger_obj = logging.getLogger(name)
        if not isinstance(logger_obj, logging.Logger):
            continue
        for handler in logger_obj.handlers[:]:
            logger_obj.removeHandler(handler)
        logger_obj.propagate = True

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%H:%M:%S"))
    root_logger.addHandler(stderr_handler)
    root_logger.setLevel(log_level)


# Import modules after logger monkey-patching
from .session import (  # noqa: E402
    ExchangeSessionManager,
    StrategySessionManager,
    set_context_credentials_getter,
)
from .tools import (  # noqa: E402
    account_tools,
    exchange_tools,
    market_tools,
    strategy_tools,
    trading_tools,
)
from .utils import (  # noqa: E402
    check_rate_limit,
    get_credentials_from_headers,
    sanitize_headers_for_logging,
    translate_error,
)

# Fix loggers immediately after imports
fix_all_loggers()

# Get logger for this module
logger = logging.getLogger(__name__)

# Context variable to store current request credentials
_request_credentials: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar(
    "request_credentials", default=None
)


def get_current_credentials() -> Optional[Dict[str, Any]]:
    """Get credentials from current request context."""
    return _request_credentials.get()


# Register the credentials getter with exchange manager
set_context_credentials_getter(get_current_credentials)

# Initialize MCP server
mcp_app = Server("dr-manhattan")

# SSE transport
sse_transport = SseServerTransport("/messages/")

# Session managers
exchange_manager = ExchangeSessionManager()
strategy_manager = StrategySessionManager()


# =============================================================================
# Tool Registration (same as server.py)
# =============================================================================


@mcp_app.list_tools()
async def list_tools() -> List[Tool]:
    """List all available MCP tools."""
    return [
        # Exchange tools (3)
        Tool(
            name="list_exchanges",
            description="List all available prediction market exchanges",
            inputSchema={"type": "object", "properties": {}},
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
                "properties": {"exchange": {"type": "string", "description": "Exchange name"}},
                "required": ["exchange"],
            },
        ),
        # Market tools (10)
        Tool(
            name="fetch_markets",
            description="Fetch ALL markets with pagination (slow, 100+ results). Use search_markets instead to find specific markets by name.",
            inputSchema={
                "type": "object",
                "properties": {
                    "exchange": {"type": "string", "description": "Exchange name"},
                    "limit": {
                        "type": "integer",
                        "description": "Max markets to return (default: 100, max: 500)",
                        "default": 100,
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Pagination offset (default: 0)",
                        "default": 0,
                    },
                    "params": {"type": "object", "description": "Optional filters"},
                },
                "required": ["exchange"],
            },
        ),
        Tool(
            name="search_markets",
            description="RECOMMENDED: Search markets by keyword (fast). Use this first when user asks about specific topics.",
            inputSchema={
                "type": "object",
                "properties": {
                    "exchange": {"type": "string", "description": "Exchange name"},
                    "query": {"type": "string", "description": "Search keyword"},
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default: 20)",
                        "default": 20,
                    },
                },
                "required": ["exchange", "query"],
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
            description="Get best bid and ask prices",
            inputSchema={
                "type": "object",
                "properties": {
                    "exchange": {"type": "string"},
                    "token_id": {"type": "string"},
                },
                "required": ["exchange", "token_id"],
            },
        ),
        Tool(
            name="fetch_token_ids",
            description="Get token IDs for a market",
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
            description="Find a tradeable market for an outcome",
            inputSchema={
                "type": "object",
                "properties": {
                    "exchange": {"type": "string"},
                    "market_id": {"type": "string"},
                    "outcome": {"type": "string"},
                },
                "required": ["exchange", "market_id", "outcome"],
            },
        ),
        Tool(
            name="find_crypto_hourly_market",
            description="Find hourly crypto prediction markets",
            inputSchema={
                "type": "object",
                "properties": {
                    "exchange": {"type": "string"},
                    "symbol": {"type": "string", "description": "Crypto symbol (BTC, ETH)"},
                },
                "required": ["exchange", "symbol"],
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
        # Trading tools (5)
        Tool(
            name="create_order",
            description="Create a new order (requires credentials in headers)",
            inputSchema={
                "type": "object",
                "properties": {
                    "exchange": {"type": "string"},
                    "market_id": {"type": "string"},
                    "outcome": {"type": "string", "description": "Outcome (Yes, No, etc.)"},
                    "side": {"type": "string", "enum": ["buy", "sell"]},
                    "price": {"type": "number", "minimum": 0, "maximum": 1},
                    "size": {"type": "number", "minimum": 0},
                    "params": {"type": "object"},
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
                    "market_id": {"type": "string"},
                },
                "required": ["exchange"],
            },
        ),
        Tool(
            name="fetch_open_orders",
            description="Fetch open orders",
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
            description="Fetch a specific order by ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "exchange": {"type": "string"},
                    "order_id": {"type": "string"},
                },
                "required": ["exchange", "order_id"],
            },
        ),
        # Account tools (4)
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
            description="Fetch all positions",
            inputSchema={
                "type": "object",
                "properties": {"exchange": {"type": "string"}},
                "required": ["exchange"],
            },
        ),
        Tool(
            name="calculate_nav",
            description="Calculate Net Asset Value",
            inputSchema={
                "type": "object",
                "properties": {"exchange": {"type": "string"}},
                "required": ["exchange"],
            },
        ),
        Tool(
            name="fetch_positions_for_market",
            description="Fetch positions for a specific market",
            inputSchema={
                "type": "object",
                "properties": {
                    "exchange": {"type": "string"},
                    "market_id": {"type": "string"},
                },
                "required": ["exchange", "market_id"],
            },
        ),
        # Strategy tools (7)
        Tool(
            name="create_strategy_session",
            description="Create a new strategy session",
            inputSchema={
                "type": "object",
                "properties": {
                    "exchange": {"type": "string"},
                    "strategy_name": {"type": "string"},
                    "market_id": {"type": "string"},
                    "params": {"type": "object"},
                },
                "required": ["exchange", "strategy_name", "market_id"],
            },
        ),
        Tool(
            name="get_strategy_status",
            description="Get strategy session status",
            inputSchema={
                "type": "object",
                "properties": {"session_id": {"type": "string"}},
                "required": ["session_id"],
            },
        ),
        Tool(
            name="stop_strategy",
            description="Stop a strategy session",
            inputSchema={
                "type": "object",
                "properties": {"session_id": {"type": "string"}},
                "required": ["session_id"],
            },
        ),
        Tool(
            name="list_strategy_sessions",
            description="List all strategy sessions",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="pause_strategy",
            description="Pause a strategy session",
            inputSchema={
                "type": "object",
                "properties": {"session_id": {"type": "string"}},
                "required": ["session_id"],
            },
        ),
        Tool(
            name="resume_strategy",
            description="Resume a paused strategy session",
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
    ]


# Tool dispatch table
TOOL_DISPATCH = {
    # Exchange tools
    "list_exchanges": (exchange_tools.list_exchanges, False),
    "get_exchange_info": (exchange_tools.get_exchange_info, True),
    "validate_credentials": (exchange_tools.validate_credentials, True),
    # Market tools
    "fetch_markets": (market_tools.fetch_markets, True),
    "search_markets": (market_tools.search_markets, True),
    "fetch_market": (market_tools.fetch_market, True),
    "fetch_markets_by_slug": (market_tools.fetch_markets_by_slug, True),
    "get_orderbook": (market_tools.get_orderbook, True),
    "get_best_bid_ask": (market_tools.get_best_bid_ask, True),
    "fetch_token_ids": (market_tools.fetch_token_ids, True),
    "find_tradeable_market": (market_tools.find_tradeable_market, True),
    "find_crypto_hourly_market": (market_tools.find_crypto_hourly_market, True),
    "parse_market_identifier": (market_tools.parse_market_identifier, True),
    "get_tag_by_slug": (market_tools.get_tag_by_slug, True),
    # Trading tools
    "create_order": (trading_tools.create_order, True),
    "cancel_order": (trading_tools.cancel_order, True),
    "cancel_all_orders": (trading_tools.cancel_all_orders, True),
    "fetch_open_orders": (trading_tools.fetch_open_orders, True),
    "fetch_order": (trading_tools.fetch_order, True),
    # Account tools
    "fetch_balance": (account_tools.fetch_balance, True),
    "fetch_positions": (account_tools.fetch_positions, True),
    "calculate_nav": (account_tools.calculate_nav, True),
    "fetch_positions_for_market": (account_tools.fetch_positions_for_market, True),
    # Strategy tools
    "create_strategy_session": (strategy_tools.create_strategy_session, True),
    "get_strategy_status": (strategy_tools.get_strategy_status, True),
    "stop_strategy": (strategy_tools.stop_strategy, True),
    "list_strategy_sessions": (strategy_tools.list_strategy_sessions, False),
    "pause_strategy": (strategy_tools.pause_strategy, True),
    "resume_strategy": (strategy_tools.resume_strategy, True),
    "get_strategy_metrics": (strategy_tools.get_strategy_metrics, True),
}


@mcp_app.call_tool()
async def call_tool(name: str, arguments: Any) -> List[TextContent]:
    """Handle tool execution with rate limiting."""
    try:
        if not check_rate_limit():
            raise ValueError(
                "Rate limit exceeded. Please wait before making more requests."
            )

        if name not in TOOL_DISPATCH:
            raise ValueError(f"Unknown tool: {name}")

        handler, requires_args = TOOL_DISPATCH[name]
        result = handler(**arguments) if requires_args else handler()

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    except Exception as e:
        mcp_error = translate_error(e, {"tool": name, "arguments": arguments})
        error_response = {"error": mcp_error.to_dict()}
        return [TextContent(type="text", text=json.dumps(error_response, indent=2))]


# =============================================================================
# HTTP Handlers
# =============================================================================


async def handle_sse(request: Request) -> Response:
    """Handle SSE connection for MCP."""
    # Extract and log headers (sanitized)
    headers = dict(request.headers)
    logger.info(f"SSE connection from {request.client.host if request.client else 'unknown'}")
    logger.debug(f"Headers (sanitized): {sanitize_headers_for_logging(headers)}")

    # Extract credentials from headers and store in context
    credentials = get_credentials_from_headers(headers)
    token = _request_credentials.set(credentials)

    try:
        async with sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await mcp_app.run(
                streams[0], streams[1], mcp_app.create_initialization_options()
            )
    finally:
        _request_credentials.reset(token)

    return Response()


async def handle_messages(request: Request) -> Response:
    """Handle POST messages for SSE transport."""
    # Extract credentials for this request
    headers = dict(request.headers)
    credentials = get_credentials_from_headers(headers)
    token = _request_credentials.set(credentials)

    try:
        return await sse_transport.handle_post_message(request.scope, request.receive, request._send)
    finally:
        _request_credentials.reset(token)


async def health_check(request: Request) -> JSONResponse:
    """Health check endpoint."""
    return JSONResponse({
        "status": "healthy",
        "service": "dr-manhattan-mcp",
        "transport": "sse",
        "version": "0.0.2",
    })


async def root(request: Request) -> JSONResponse:
    """Root endpoint with usage info."""
    return JSONResponse({
        "service": "Dr. Manhattan MCP Server",
        "transport": "SSE",
        "endpoints": {
            "/sse": "MCP SSE connection endpoint",
            "/messages/": "MCP message handling",
            "/health": "Health check",
        },
        "usage": {
            "claude_config": {
                "url": "https://<your-domain>/sse",
                "headers": {
                    "X-Polymarket-Private-Key": "<your-private-key>",
                    "X-Polymarket-Funder": "<your-funder-address>",
                },
            }
        },
    })


# =============================================================================
# Starlette App
# =============================================================================

middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
]

routes = [
    Route("/", endpoint=root, methods=["GET"]),
    Route("/health", endpoint=health_check, methods=["GET"]),
    Route("/sse", endpoint=handle_sse, methods=["GET"]),
    Route("/messages/", endpoint=handle_messages, methods=["POST"]),
]

app = Starlette(routes=routes, middleware=middleware)


# =============================================================================
# Cleanup and Main
# =============================================================================

_shutdown_requested = False


def cleanup_handler(signum, frame):
    """Handle shutdown signal."""
    global _shutdown_requested
    _shutdown_requested = True
    sys.stderr.write("[SIGNAL] Shutdown requested, cleaning up...\n")
    sys.stderr.flush()


async def cleanup():
    """Cleanup resources on shutdown."""
    logger.info("Shutting down MCP SSE server...")
    await asyncio.to_thread(strategy_manager.cleanup)
    await asyncio.to_thread(exchange_manager.cleanup)
    logger.info("Cleanup complete")


def run_sse():
    """Run the SSE server."""
    import uvicorn

    signal.signal(signal.SIGINT, cleanup_handler)
    signal.signal(signal.SIGTERM, cleanup_handler)

    port = int(os.getenv("PORT", "8080"))
    host = os.getenv("HOST", "0.0.0.0")

    logger.info(f"Starting Dr. Manhattan MCP SSE Server on {host}:{port}")

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=True,
    )


if __name__ == "__main__":
    run_sse()
