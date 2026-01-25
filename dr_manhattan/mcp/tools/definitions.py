"""Shared tool definitions for MCP servers.

This module contains tool definitions and dispatch tables used by both
stdio (server.py) and SSE (server_sse.py) transports.

Consolidating definitions here avoids code duplication and ensures
consistency between transport implementations.
"""

from typing import Callable, Dict, List, Tuple

from mcp.types import Tool

from . import account_tools, exchange_tools, market_tools, strategy_tools, trading_tools


def get_tool_definitions() -> List[Tool]:
    """
    Get all MCP tool definitions.

    Returns:
        List of Tool objects for MCP registration
    """
    return [
        # =================================================================
        # Exchange tools (3)
        # =================================================================
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
        # =================================================================
        # Market tools (11)
        # =================================================================
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
        # =================================================================
        # Trading tools (5)
        # =================================================================
        Tool(
            name="create_order",
            description="Create a new order (requires credentials)",
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
        # =================================================================
        # Account tools (4)
        # =================================================================
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
        # =================================================================
        # Strategy tools (7)
        # =================================================================
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
# Format: tool_name -> (handler_function, requires_arguments)
TOOL_DISPATCH: Dict[str, Tuple[Callable, bool]] = {
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
