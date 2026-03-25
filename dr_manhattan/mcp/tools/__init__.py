"""MCP Tools for dr-manhattan."""

from . import account_tools, exchange_tools, market_tools, strategy_tools, trading_tools

# Import tool definitions eagerly. The mcp package is always available in the SSE server
# context. Lazy loading caused a shared-flag bug where TOOL_DISPATCH stayed None.
from .definitions import TOOL_DISPATCH, get_tool_definitions

__all__ = [
    "account_tools",
    "exchange_tools",
    "market_tools",
    "strategy_tools",
    "trading_tools",
    "get_tool_definitions",
    "TOOL_DISPATCH",
]
