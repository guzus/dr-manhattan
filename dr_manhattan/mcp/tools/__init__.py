"""MCP Tools for dr-manhattan."""

from . import account_tools, exchange_tools, market_tools, strategy_tools, trading_tools

# Lazy imports for MCP-specific definitions (requires mcp package)
# These are only imported when explicitly accessed to avoid breaking
# tests that don't have the mcp package installed
_definitions_loaded = False
_TOOL_DISPATCH = None
_get_tool_definitions = None


def get_tool_definitions():
    """Get tool definitions (lazy import)."""
    global _definitions_loaded, _get_tool_definitions
    if not _definitions_loaded:
        from .definitions import get_tool_definitions as _gtd

        _get_tool_definitions = _gtd
        _definitions_loaded = True
    return _get_tool_definitions()


def _get_dispatch():
    """Get tool dispatch table (lazy import)."""
    global _definitions_loaded, _TOOL_DISPATCH
    if not _definitions_loaded:
        from .definitions import TOOL_DISPATCH

        _TOOL_DISPATCH = TOOL_DISPATCH
        _definitions_loaded = True
    return _TOOL_DISPATCH


# For backwards compatibility, expose TOOL_DISPATCH as a property-like access
class _ToolDispatchProxy:
    """Proxy for lazy loading TOOL_DISPATCH."""

    def __getitem__(self, key):
        return _get_dispatch()[key]

    def __contains__(self, key):
        return key in _get_dispatch()

    def keys(self):
        return _get_dispatch().keys()

    def items(self):
        return _get_dispatch().items()

    def values(self):
        return _get_dispatch().values()


TOOL_DISPATCH = _ToolDispatchProxy()

__all__ = [
    "account_tools",
    "exchange_tools",
    "market_tools",
    "strategy_tools",
    "trading_tools",
    "get_tool_definitions",
    "TOOL_DISPATCH",
]
