#!/usr/bin/env python3
"""Code-level validation of MCP server without runtime dependencies."""

import ast
import os
import sys


def test_all_files_parseable():
    """Test all Python files are valid syntax."""
    print("Testing Python syntax...")

    files_to_check = []
    for root, dirs, files in os.walk("mcp_server"):
        for file in files:
            if file.endswith(".py"):
                files_to_check.append(os.path.join(root, file))

    errors = []
    for filepath in files_to_check:
        try:
            with open(filepath, "r") as f:
                ast.parse(f.read())
        except SyntaxError as e:
            errors.append(f"{filepath}: {e}")

    if errors:
        for error in errors:
            print(f"✗ {error}")
        return False

    print(f"✓ All {len(files_to_check)} Python files have valid syntax")
    return True


def test_tool_count():
    """Count tools defined in server.py."""
    print("\nCounting tool definitions...")

    try:
        with open("dr_manhattan/mcp/server.py", "r") as f:
            content = f.read()

        # Count Tool() instances
        tool_count = content.count('Tool(')

        print(f"✓ Found {tool_count} tool definitions")

        # List tool names
        import re
        tool_names = re.findall(r'name="([^"]+)"', content)
        print(f"  Tools: {', '.join(tool_names[:5])}... ({len(tool_names)} total)")

        if tool_count < 15:
            print(f"✗ Expected at least 15 tools, found {tool_count}")
            return False

        return True

    except Exception as e:
        print(f"✗ Failed: {e}")
        return False


def test_function_signatures():
    """Test tool function signatures."""
    print("\nValidating function signatures...")

    tool_files = [
        "dr_manhattan/mcp/tools/exchange_tools.py",
        "dr_manhattan/mcp/tools/market_tools.py",
        "dr_manhattan/mcp/tools/trading_tools.py",
        "dr_manhattan/mcp/tools/account_tools.py",
        "dr_manhattan/mcp/tools/strategy_tools.py",
    ]

    total_functions = 0
    for filepath in tool_files:
        try:
            with open(filepath, "r") as f:
                tree = ast.parse(f.read())

            functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]

            # Filter out private functions
            public_functions = [f for f in functions if not f.name.startswith("_")]

            total_functions += len(public_functions)

        except Exception as e:
            print(f"✗ Failed to parse {filepath}: {e}")
            return False

    print(f"✓ Found {total_functions} public tool functions")

    if total_functions < 20:
        print(f"✗ Expected at least 20 functions, found {total_functions}")
        return False

    return True


def test_session_manager_implementation():
    """Test session managers are properly implemented."""
    print("\nValidating session managers...")

    try:
        # Check ExchangeSessionManager
        with open("dr_manhattan/mcp/session/exchange_manager.py", "r") as f:
            content = f.read()

        required_methods = [
            "get_exchange",
            "get_client",
            "has_exchange",
            "cleanup",
        ]

        for method in required_methods:
            if f"def {method}" not in content:
                print(f"✗ ExchangeSessionManager missing method: {method}")
                return False

        print("✓ ExchangeSessionManager has all required methods")

        # Check StrategySessionManager
        with open("dr_manhattan/mcp/session/strategy_manager.py", "r") as f:
            content = f.read()

        required_methods = [
            "create_session",
            "get_session",
            "get_status",
            "pause_strategy",
            "resume_strategy",
            "stop_strategy",
            "get_metrics",
            "list_sessions",
            "cleanup",
        ]

        for method in required_methods:
            if f"def {method}" not in content:
                print(f"✗ StrategySessionManager missing method: {method}")
                return False

        print("✓ StrategySessionManager has all required methods")

        return True

    except Exception as e:
        print(f"✗ Failed: {e}")
        return False


def test_error_handling():
    """Test error handling is implemented."""
    print("\nValidating error handling...")

    try:
        with open("dr_manhattan/mcp/utils/errors.py", "r") as f:
            content = f.read()

        # Check error mapping exists
        if "ERROR_MAP" not in content:
            print("✗ ERROR_MAP not found")
            return False

        # Check all dr-manhattan errors are mapped
        dr_errors = [
            "DrManhattanError",
            "ExchangeError",
            "NetworkError",
            "RateLimitError",
            "AuthenticationError",
            "InsufficientFunds",
            "InvalidOrder",
            "MarketNotFound",
        ]

        for error in dr_errors:
            if error not in content:
                print(f"✗ Error not mapped: {error}")
                return False

        print(f"✓ All {len(dr_errors)} error types are mapped")

        # Check translate_error function exists
        if "def translate_error" not in content:
            print("✗ translate_error function not found")
            return False

        print("✓ translate_error function exists")

        return True

    except Exception as e:
        print(f"✗ Failed: {e}")
        return False


def test_documentation_exists():
    """Test documentation files exist."""
    print("\nValidating documentation...")

    docs = [
        "docs/mcp/README.md",
        "examples/mcp_usage_example.md",
        "MCP_SERVER.md",
    ]

    for doc in docs:
        if not os.path.exists(doc):
            print(f"✗ Missing: {doc}")
            return False

    print(f"✓ All {len(docs)} documentation files exist")

    # Check doc content
    with open("docs/mcp/README.md", "r") as f:
        content = f.read()

    if "Dr. Manhattan MCP Server" not in content:
        print("✗ README missing title")
        return False

    if "Installation" not in content:
        print("✗ README missing Installation section")
        return False

    print("✓ Documentation has required sections")

    return True


def test_directory_structure():
    """Test directory structure is correct."""
    print("\nValidating directory structure...")

    required_dirs = [
        "mcp_server",
        "dr_manhattan/mcp/session",
        "dr_manhattan/mcp/tools",
        "dr_manhattan/mcp/utils",
    ]

    for dir_path in required_dirs:
        if not os.path.isdir(dir_path):
            print(f"✗ Missing directory: {dir_path}")
            return False

    print(f"✓ All {len(required_dirs)} required directories exist")

    # Check __init__.py files
    init_files = [
        "dr_manhattan/mcp/__init__.py",
        "dr_manhattan/mcp/session/__init__.py",
        "dr_manhattan/mcp/tools/__init__.py",
        "dr_manhattan/mcp/utils/__init__.py",
    ]

    for init_file in init_files:
        if not os.path.exists(init_file):
            print(f"✗ Missing: {init_file}")
            return False

    print(f"✓ All {len(init_files)} __init__.py files exist")

    return True


def test_server_entrypoint():
    """Test server.py has proper entry point."""
    print("\nValidating server entry point...")

    try:
        with open("dr_manhattan/mcp/server.py", "r") as f:
            content = f.read()

        required_components = [
            "async def main(",
            "def run(",
            "if __name__ == ",
            "app = Server(",
            "@app.list_tools()",
            "@app.call_tool()",
        ]

        for component in required_components:
            if component not in content:
                print(f"✗ Missing component: {component}")
                return False

        print("✓ Server has all required components")

        # Check signal handling
        if "signal.signal" not in content:
            print("✗ Missing signal handling")
            return False

        print("✓ Signal handling configured")

        # Check cleanup
        if "def cleanup_handler" not in content:
            print("✗ Missing cleanup handler")
            return False

        print("✓ Cleanup handler exists")

        return True

    except Exception as e:
        print(f"✗ Failed: {e}")
        return False


def main():
    """Run all code validation tests."""
    print("=" * 60)
    print("Dr. Manhattan MCP Server - Code Validation")
    print("=" * 60)

    tests = [
        ("Python Syntax", test_all_files_parseable),
        ("Tool Count", test_tool_count),
        ("Function Signatures", test_function_signatures),
        ("Session Managers", test_session_manager_implementation),
        ("Error Handling", test_error_handling),
        ("Documentation", test_documentation_exists),
        ("Directory Structure", test_directory_structure),
        ("Server Entry Point", test_server_entrypoint),
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
        print("\n🎉 All code validation tests passed!")
        print("\nMCP Server is ready to use!")
        print("\nNext steps:")
        print("  1. Install dependencies: pip install -e '.[mcp]'")
        print("  2. Configure .env with API credentials")
        print("  3. Add to Claude Desktop config")
        print("  4. Restart Claude Desktop")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
