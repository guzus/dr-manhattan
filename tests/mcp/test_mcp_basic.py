#!/usr/bin/env python3
"""Basic MCP server functionality test."""

import sys


def test_imports():
    """Test all imports work."""
    print("Testing imports...")

    try:
        # Test session imports
        from dr_manhattan.mcp.session import (
            ExchangeSessionManager,
            StrategySessionManager,
            StrategySession,
            SessionStatus,
        )
        print("✓ Session imports OK")

        # Test utils imports
        from dr_manhattan.mcp.utils import translate_error, McpError, serialize_model
        print("✓ Utils imports OK")

        # Test tool imports
        from dr_manhattan.mcp.tools import (
            exchange_tools,
            market_tools,
            trading_tools,
            account_tools,
            strategy_tools,
        )
        print("✓ Tool imports OK")

        return True

    except ImportError as e:
        print(f"✗ Import failed: {e}")
        return False


def test_session_managers():
    """Test session manager initialization."""
    print("\nTesting session managers...")

    try:
        from dr_manhattan.mcp.session import ExchangeSessionManager, StrategySessionManager

        # Test singleton pattern
        mgr1 = ExchangeSessionManager()
        mgr2 = ExchangeSessionManager()

        if mgr1 is not mgr2:
            print("✗ ExchangeSessionManager not singleton")
            return False
        print("✓ ExchangeSessionManager singleton OK")

        # Test strategy manager
        strat_mgr1 = StrategySessionManager()
        strat_mgr2 = StrategySessionManager()

        if strat_mgr1 is not strat_mgr2:
            print("✗ StrategySessionManager not singleton")
            return False
        print("✓ StrategySessionManager singleton OK")

        return True

    except Exception as e:
        print(f"✗ Session manager test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_tool_functions():
    """Test tool functions can be called."""
    print("\nTesting tool functions...")

    try:
        from dr_manhattan.mcp.tools import exchange_tools

        # Test list_exchanges (doesn't need credentials)
        exchanges = exchange_tools.list_exchanges()

        if not isinstance(exchanges, list):
            print(f"✗ list_exchanges returned {type(exchanges)}")
            return False

        if "polymarket" not in exchanges:
            print(f"✗ polymarket not in exchanges: {exchanges}")
            return False

        print(f"✓ list_exchanges OK: {exchanges}")
        return True

    except Exception as e:
        print(f"✗ Tool function test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_serializer():
    """Test data serialization."""
    print("\nTesting serialization...")

    try:
        from dr_manhattan.mcp.utils import serialize_model
        from datetime import datetime
        from enum import Enum

        # Test primitives
        assert serialize_model(123) == 123
        assert serialize_model("test") == "test"
        assert serialize_model(True) == True
        print("✓ Primitives OK")

        # Test datetime
        now = datetime.now()
        serialized = serialize_model(now)
        assert isinstance(serialized, str)
        print("✓ Datetime OK")

        # Test enum
        class TestEnum(Enum):
            VALUE = "test"

        assert serialize_model(TestEnum.VALUE) == "test"
        print("✓ Enum OK")

        # Test dict
        data = {"key": "value", "num": 123}
        assert serialize_model(data) == data
        print("✓ Dict OK")

        # Test list
        items = [1, 2, 3]
        assert serialize_model(items) == items
        print("✓ List OK")

        return True

    except Exception as e:
        print(f"✗ Serializer test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_error_translation():
    """Test error translation."""
    print("\nTesting error translation...")

    try:
        from dr_manhattan.mcp.utils import translate_error, McpError
        from dr_manhattan.base.errors import MarketNotFound, NetworkError

        # Test MarketNotFound
        error = MarketNotFound("Market not found")
        mcp_error = translate_error(error, {"exchange": "polymarket"})

        assert isinstance(mcp_error, McpError)
        assert mcp_error.code == -32007
        assert "exchange" in mcp_error.data
        print("✓ MarketNotFound translation OK")

        # Test NetworkError
        error = NetworkError("Connection failed")
        mcp_error = translate_error(error)

        assert mcp_error.code == -32002
        print("✓ NetworkError translation OK")

        return True

    except Exception as e:
        print(f"✗ Error translation test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


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
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n✗ {name} crashed: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    print("\n" + "=" * 60)
    print("Test Results:")
    print("=" * 60)

    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status:8} {name}")

    print("=" * 60)

    passed = sum(1 for _, r in results if r)
    total = len(results)

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
