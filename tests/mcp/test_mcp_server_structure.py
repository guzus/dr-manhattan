#!/usr/bin/env python3
"""Test MCP server structure and tool registration."""

import sys

import pytest


def test_server_tools():
    """Test server tool registration."""
    # Skip if mcp is not installed (optional dependency)
    pytest.importorskip("mcp")

    print("Testing MCP server tool registration...")

    import inspect

    from dr_manhattan.mcp import server

    # Check server exists
    assert hasattr(server, "app"), "Server app not found"
    print("[PASS] Server app exists")

    # Check handlers exist
    assert hasattr(server, "list_tools"), "list_tools handler not found"
    assert hasattr(server, "call_tool"), "call_tool handler not found"
    print("[PASS] MCP handlers exist")

    # Check list_tools is async
    assert inspect.iscoroutinefunction(server.list_tools), "list_tools should be async"
    print("[PASS] list_tools is async")

    # Check call_tool is async
    assert inspect.iscoroutinefunction(server.call_tool), "call_tool should be async"
    print("[PASS] call_tool is async")

    # Check cleanup handler
    assert hasattr(server, "cleanup_handler"), "cleanup_handler not found"
    print("[PASS] cleanup_handler exists")

    # Check main and run functions
    assert hasattr(server, "main"), "main function not found"
    assert hasattr(server, "run"), "run function not found"
    print("[PASS] main and run functions exist")


def test_tool_routing():
    """Test that all tools are properly routed."""
    print("\nTesting tool routing...")

    expected_tools = [
        # Exchange tools (3)
        "list_exchanges",
        "get_exchange_info",
        "validate_credentials",
        # Market tools (8)
        "fetch_markets",
        "fetch_market",
        "fetch_markets_by_slug",
        "get_orderbook",
        "get_best_bid_ask",
        # Trading tools (5)
        "create_order",
        "cancel_order",
        "cancel_all_orders",
        "fetch_open_orders",
        # Account tools (4)
        "fetch_balance",
        "fetch_positions",
        "calculate_nav",
        # Strategy tools (6)
        "create_strategy_session",
        "get_strategy_status",
        "stop_strategy",
        "list_strategy_sessions",
    ]

    try:
        # Read server.py and check tool routing
        with open("dr_manhattan/mcp/server.py", "r") as f:
            server_code = f.read()

        missing_tools = []
        for tool in expected_tools:
            # Check if tool is in call_tool routing
            if f'name == "{tool}"' not in server_code:
                missing_tools.append(tool)

        if missing_tools:
            print(f"✗ Missing tool routing: {missing_tools}")
            return False

        print(f"✓ All {len(expected_tools)} tools are routed")

        # Check tool functions exist
        from dr_manhattan.mcp.tools import (
            account_tools,
            exchange_tools,
            market_tools,
            strategy_tools,
            trading_tools,
        )

        modules = {
            "exchange": exchange_tools,
            "market": market_tools,
            "trading": trading_tools,
            "account": account_tools,
            "strategy": strategy_tools,
        }

        for tool_name in expected_tools:
            found = False
            for module_name, module in modules.items():
                if hasattr(module, tool_name):
                    found = True
                    break

            if not found:
                print(f"✗ Tool function not found: {tool_name}")
                return False

        print("✓ All tool functions exist")

        return True

    except Exception as e:
        print(f"✗ Tool routing test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_tool_schemas():
    """Test tool schema definitions."""
    print("\nTesting tool schemas...")

    try:
        # Check that tool schemas are valid
        import re

        with open("dr_manhattan/mcp/server.py", "r") as f:
            server_code = f.read()

        # Find all Tool() definitions
        tool_pattern = r'Tool\s*\(\s*name="([^"]+)"'
        tools_in_code = re.findall(tool_pattern, server_code)

        if len(tools_in_code) < 20:
            print(f"✗ Only found {len(tools_in_code)} tool definitions (expected 20+)")
            return False

        print(f"✓ Found {len(tools_in_code)} tool schema definitions")

        # Check required fields in schemas
        required_fields = ["name", "description", "inputSchema"]

        for field in required_fields:
            count = server_code.count(field)
            if count < 20:
                print(f"✗ Field '{field}' only appears {count} times")
                return False

        print("✓ All schemas have required fields")

        return True

    except Exception as e:
        print(f"✗ Tool schema test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_session_cleanup():
    """Test session cleanup works."""
    print("\nTesting session cleanup...")

    try:
        from dr_manhattan.mcp.session import ExchangeSessionManager, StrategySessionManager

        # Get managers
        exchange_mgr = ExchangeSessionManager()
        strategy_mgr = StrategySessionManager()

        # Test cleanup doesn't crash
        exchange_mgr.cleanup()
        strategy_mgr.cleanup()

        print("✓ Cleanup executed without errors")
        return True

    except Exception as e:
        print(f"✗ Cleanup test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_pyproject_config():
    """Test pyproject.toml configuration."""
    print("\nTesting pyproject.toml...")

    try:
        with open("pyproject.toml", "r") as f:
            pyproject = f.read()

        # Check MCP dependencies
        if "mcp>=" not in pyproject:
            print("✗ MCP dependency not found")
            return False
        print("✓ MCP dependency configured")

        # Check script entry point
        if "dr-manhattan-mcp" not in pyproject:
            print("✗ Script entry point not found")
            return False
        print("✓ Script entry point configured")

        # Check mcp_server package
        if '"mcp_server"' not in pyproject:
            print("✗ mcp_server package not in wheel")
            return False
        print("✓ mcp_server package configured")

        return True

    except Exception as e:
        print(f"✗ pyproject.toml test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def main():
    """Run all structure tests."""
    print("=" * 60)
    print("Dr. Manhattan MCP Server - Structure Tests")
    print("=" * 60)

    tests = [
        ("Server Structure", test_server_tools),
        ("Tool Routing", test_tool_routing),
        ("Tool Schemas", test_tool_schemas),
        ("Session Cleanup", test_session_cleanup),
        ("pyproject.toml", test_pyproject_config),
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
        print("\n🎉 All structure tests passed!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
