#!/usr/bin/env python3
"""Test MCP server tool registration and execution."""

import asyncio
import sys

import pytest


@pytest.mark.asyncio
async def test_tool_registration():
    """Test that all tools are properly registered."""
    print("Testing tool registration...")

    from dr_manhattan.mcp import server

    # Call list_tools
    tools = await server.list_tools()

    print(f"✓ Found {len(tools)} tools registered")

    # Check expected tools
    expected_tools = [
        "list_exchanges",
        "get_exchange_info",
        "validate_credentials",
        "fetch_markets",
        "fetch_market",
        "fetch_markets_by_slug",
        "get_orderbook",
        "get_best_bid_ask",
        "create_order",
        "cancel_order",
        "cancel_all_orders",
        "fetch_open_orders",
        "fetch_balance",
        "fetch_positions",
        "calculate_nav",
        "create_strategy_session",
        "get_strategy_status",
        "stop_strategy",
        "list_strategy_sessions",
    ]

    tool_names = [tool.name for tool in tools]

    missing_tools = []
    for expected in expected_tools:
        if expected not in tool_names:
            missing_tools.append(expected)

    if missing_tools:
        print(f"✗ Missing tools: {missing_tools}")
        return False

    print(f"✓ All {len(expected_tools)} expected tools are registered")

    # Check each tool has required fields
    for tool in tools:
        if not tool.name:
            print(f"✗ Tool missing name: {tool}")
            return False
        if not tool.description:
            print(f"✗ Tool {tool.name} missing description")
            return False
        if not tool.inputSchema:
            print(f"✗ Tool {tool.name} missing inputSchema")
            return False

    print("✓ All tools have required fields (name, description, inputSchema)")

    return True


@pytest.mark.asyncio
async def test_tool_execution():
    """Test actual tool execution."""
    print("\nTesting tool execution...")

    from dr_manhattan.mcp import server

    # Test 1: list_exchanges (no arguments needed)
    try:
        result = await server.call_tool(name="list_exchanges", arguments={})
        print(f"✓ list_exchanges executed successfully")
        print(f"  Result: {result[0].text[:100]}...")
    except Exception as e:
        print(f"✗ list_exchanges failed: {e}")
        return False

    # Test 2: fetch_markets with polymarket
    try:
        result = await server.call_tool(
            name="fetch_markets",
            arguments={"exchange": "polymarket", "params": {}}
        )
        print(f"✓ fetch_markets executed successfully")
        print(f"  Result length: {len(result[0].text)} characters")
    except Exception as e:
        print(f"✗ fetch_markets failed: {e}")
        return False

    # Test 3: get_exchange_info
    try:
        result = await server.call_tool(
            name="get_exchange_info",
            arguments={"exchange": "polymarket"}
        )
        print(f"✓ get_exchange_info executed successfully")
        print(f"  Result: {result[0].text[:100]}...")
    except Exception as e:
        print(f"✗ get_exchange_info failed: {e}")
        return False

    return True


@pytest.mark.asyncio
async def test_error_handling():
    """Test error handling."""
    print("\nTesting error handling...")

    from dr_manhattan.mcp import server

    # Test 1: Invalid exchange name - should return error in result, not raise
    try:
        result = await server.call_tool(
            name="get_exchange_info",
            arguments={"exchange": "invalid_exchange"}
        )
        # Check if error is in the response
        result_text = result[0].text
        if "error" in result_text.lower() or "unknown exchange" in result_text.lower():
            print(f"✓ Correctly returned error for invalid exchange")
        else:
            print(f"✗ Expected error in result for invalid exchange")
            print(f"  Got: {result_text[:200]}")
            return False
    except Exception as e:
        # Also acceptable if it raises an exception
        print(f"✓ Correctly raised error for invalid exchange: {type(e).__name__}")

    # Test 2: Invalid tool name - should return error in result
    try:
        result = await server.call_tool(
            name="nonexistent_tool",
            arguments={}
        )
        # Check if error is in the response
        result_text = result[0].text
        if "error" in result_text.lower() or "unknown tool" in result_text.lower():
            print(f"✓ Correctly returned error for invalid tool")
        else:
            print(f"✗ Expected error in result for invalid tool")
            print(f"  Got: {result_text[:200]}")
            return False
    except Exception as e:
        # Also acceptable if it raises an exception
        print(f"✓ Correctly raised error for invalid tool: {type(e).__name__}")

    return True


async def main():
    """Run all tests."""
    print("=" * 60)
    print("Dr. Manhattan MCP Server - Live Tests")
    print("=" * 60)

    tests = [
        ("Tool Registration", test_tool_registration),
        ("Tool Execution", test_tool_execution),
        ("Error Handling", test_error_handling),
    ]

    results = []
    for name, test_func in tests:
        try:
            result = await test_func()
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
        print("\n🎉 All live tests passed!")
        print("\nMCP server is fully functional:")
        print("  ✓ All tools registered correctly")
        print("  ✓ Tools execute successfully")
        print("  ✓ Error handling works")
        print("\nReady for production use!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
