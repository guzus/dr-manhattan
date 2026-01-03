#!/usr/bin/env python3
"""Basic MCP server functionality test."""

import sys


def test_imports():
    """Test all imports work."""
    print("Testing imports...")

    # Test session imports
    from dr_manhattan.mcp.session import (  # noqa: F401
        ExchangeSessionManager,
        SessionStatus,
        StrategySession,
        StrategySessionManager,
    )

    print("[PASS] Session imports OK")

    # Test utils imports
    from dr_manhattan.mcp.utils import McpError, serialize_model, translate_error  # noqa: F401

    print("[PASS] Utils imports OK")

    # Test tool imports
    from dr_manhattan.mcp.tools import (  # noqa: F401
        account_tools,
        exchange_tools,
        market_tools,
        strategy_tools,
        trading_tools,
    )

    print("[PASS] Tool imports OK")


def test_session_managers():
    """Test session manager initialization."""
    print("\nTesting session managers...")

    from dr_manhattan.mcp.session import ExchangeSessionManager, StrategySessionManager

    # Test singleton pattern
    mgr1 = ExchangeSessionManager()
    mgr2 = ExchangeSessionManager()

    assert mgr1 is mgr2, "ExchangeSessionManager not singleton"
    print("[PASS] ExchangeSessionManager singleton OK")

    # Test strategy manager
    strat_mgr1 = StrategySessionManager()
    strat_mgr2 = StrategySessionManager()

    assert strat_mgr1 is strat_mgr2, "StrategySessionManager not singleton"
    print("[PASS] StrategySessionManager singleton OK")


def test_tool_functions():
    """Test tool functions can be called."""
    print("\nTesting tool functions...")

    from dr_manhattan.mcp.tools import exchange_tools

    # Test list_exchanges (doesn't need credentials)
    exchanges = exchange_tools.list_exchanges()

    assert isinstance(exchanges, list), f"list_exchanges returned {type(exchanges)}"
    assert "polymarket" in exchanges, f"polymarket not in exchanges: {exchanges}"

    print(f"[PASS] list_exchanges OK: {exchanges}")


def test_serializer():
    """Test data serialization."""
    print("\nTesting serialization...")

    from datetime import datetime
    from enum import Enum

    from dr_manhattan.mcp.utils import serialize_model

    # Test primitives
    assert serialize_model(123) == 123
    assert serialize_model("test") == "test"
    assert serialize_model(True) is True
    print("[PASS] Primitives OK")

    # Test datetime
    now = datetime.now()
    serialized = serialize_model(now)
    assert isinstance(serialized, str)
    print("[PASS] Datetime OK")

    # Test enum
    class TestEnum(Enum):
        VALUE = "test"

    assert serialize_model(TestEnum.VALUE) == "test"
    print("[PASS] Enum OK")

    # Test dict
    data = {"key": "value", "num": 123}
    assert serialize_model(data) == data
    print("[PASS] Dict OK")

    # Test list
    items = [1, 2, 3]
    assert serialize_model(items) == items
    print("[PASS] List OK")


def test_error_translation():
    """Test error translation."""
    print("\nTesting error translation...")

    from dr_manhattan.base.errors import MarketNotFound, NetworkError
    from dr_manhattan.mcp.utils import McpError, translate_error

    # Test MarketNotFound
    error = MarketNotFound("Market not found")
    mcp_error = translate_error(error, {"exchange": "polymarket"})

    assert isinstance(mcp_error, McpError)
    assert mcp_error.code == -32007
    assert "exchange" in mcp_error.data
    print("[PASS] MarketNotFound translation OK")

    # Test NetworkError
    error = NetworkError("Connection failed")
    mcp_error = translate_error(error)

    assert mcp_error.code == -32002
    print("[PASS] NetworkError translation OK")


def main():
    """Run all tests."""
    print("=" * 60)
    print("Dr. Manhattan MCP Server - Basic Tests")
    print("=" * 60)

    tests = [
        ("Imports", test_imports),
        ("Session Managers", test_session_managers),
        ("Tool Functions", test_tool_functions),
        ("Serialization", test_serializer),
        ("Error Translation", test_error_translation),
    ]

    results = []
    for name, test_func in tests:
        try:
            test_func()
            results.append((name, True))
        except Exception as e:
            print(f"\n[FAIL] {name} crashed: {e}")
            import traceback

            traceback.print_exc()
            results.append((name, False))

    print("\n" + "=" * 60)
    print("Test Results:")
    print("=" * 60)

    for name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"{status:8} {name}")

    print("=" * 60)

    passed = sum(1 for _, r in results if r)
    total = len(results)

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\nAll tests passed!")
        return 0
    else:
        print(f"\n{total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
