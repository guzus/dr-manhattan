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
    - Write operations only supported for Polymarket (via Builder profile)
    - Other exchanges are read-only (no private keys on server)
    - Polymarket credentials: API key, secret, passphrase (no private key)
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
from .tools import TOOL_DISPATCH, get_tool_definitions  # noqa: E402
from .utils import (  # noqa: E402
    check_rate_limit,
    get_credentials_from_headers,
    sanitize_headers_for_logging,
    translate_error,
    validate_write_operation,
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
# Tool Registration (shared with server.py via tools.definitions)
# =============================================================================


@mcp_app.list_tools()
async def list_tools() -> List[Tool]:
    """List all available MCP tools."""
    return get_tool_definitions()


@mcp_app.call_tool()
async def call_tool(name: str, arguments: Any) -> List[TextContent]:
    """Handle tool execution with rate limiting and write operation validation."""
    try:
        if not check_rate_limit():
            raise ValueError("Rate limit exceeded. Please wait before making more requests.")

        if name not in TOOL_DISPATCH:
            raise ValueError(f"Unknown tool: {name}")

        # Validate write operations - only Polymarket allowed via Builder profile
        exchange = arguments.get("exchange") if isinstance(arguments, dict) else None
        is_allowed, error_msg = validate_write_operation(name, exchange)
        if not is_allowed:
            raise ValueError(error_msg)

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
            await mcp_app.run(streams[0], streams[1], mcp_app.create_initialization_options())
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
        return await sse_transport.handle_post_message(
            request.scope, request.receive, request._send
        )
    finally:
        _request_credentials.reset(token)


async def health_check(request: Request) -> JSONResponse:
    """Health check endpoint."""
    return JSONResponse(
        {
            "status": "healthy",
            "service": "dr-manhattan-mcp",
            "transport": "sse",
            "version": "0.0.2",
        }
    )


async def root(request: Request) -> JSONResponse:
    """Root endpoint with usage info."""
    return JSONResponse(
        {
            "service": "Dr. Manhattan MCP Server",
            "transport": "SSE",
            "endpoints": {
                "/sse": "MCP SSE connection endpoint",
                "/messages/": "MCP message handling",
                "/health": "Health check",
            },
            "security": {
                "write_operations": "Polymarket only (via Builder profile)",
                "other_exchanges": "Read-only (fetch_markets, fetch_orderbook, etc.)",
            },
            "usage": {
                "read_only": {
                    "url": "https://<your-domain>/sse",
                    "note": "No headers needed for read-only access",
                },
                "polymarket_trading": {
                    "url": "https://<your-domain>/sse",
                    "headers": {
                        "X-Polymarket-Api-Key": "<your-api-key>",
                        "X-Polymarket-Api-Secret": "<your-api-secret>",
                        "X-Polymarket-Passphrase": "<your-passphrase>",
                    },
                    "note": "Get credentials from Polymarket Builder profile",
                },
            },
        }
    )


# =============================================================================
# Starlette App
# =============================================================================

# CORS configuration - restrict origins for security
# MCP clients (Claude Desktop/Code) typically don't send Origin headers,
# so we allow specific known origins and handle no-origin requests
_cors_origins_env = os.getenv("CORS_ALLOWED_ORIGINS", "")
ALLOWED_ORIGINS: List[str] = [o.strip() for o in _cors_origins_env.split(",") if o.strip()]
if not ALLOWED_ORIGINS:
    # Default: known MCP client origins
    ALLOWED_ORIGINS = [
        "https://claude.ai",
        "https://console.anthropic.com",
    ]

middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        allow_credentials=True,
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


def _validate_env() -> tuple[str, int]:
    """Validate and return environment configuration."""
    host = os.getenv("HOST", "0.0.0.0")
    port_str = os.getenv("PORT", "8080")

    # Validate port
    try:
        port = int(port_str)
        if not (1 <= port <= 65535):
            raise ValueError(f"Port must be 1-65535, got {port}")
    except ValueError as e:
        logger.error(f"Invalid PORT: {e}")
        raise SystemExit(1)

    # Validate log level
    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    if log_level_str not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        logger.warning(f"Invalid LOG_LEVEL '{log_level_str}', using INFO")

    return host, port


def run_sse():
    """Run the SSE server."""
    import uvicorn

    signal.signal(signal.SIGINT, cleanup_handler)
    signal.signal(signal.SIGTERM, cleanup_handler)

    host, port = _validate_env()

    logger.info(f"Starting Dr. Manhattan MCP SSE Server on {host}:{port}")
    logger.info(f"CORS allowed origins: {ALLOWED_ORIGINS}")

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=True,
    )


if __name__ == "__main__":
    run_sse()
