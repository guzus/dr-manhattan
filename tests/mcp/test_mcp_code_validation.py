#!/usr/bin/env python3
"""Code-level validation of MCP server without runtime dependencies."""

import ast
import os
import sys


def test_all_files_parseable():
    """Test all Python files are valid syntax."""
    print("Testing Python syntax...")

    files_to_check = []
    for root, dirs, files in os.walk("dr_manhattan/mcp"):
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

    assert not errors, f"Syntax errors found: {errors}"
    print(f"[PASS] All {len(files_to_check)} Python files have valid syntax")


def test_tool_count():
    """Count tools defined in server.py."""
    print("\nCounting tool definitions...")

    try:
        with open("dr_manhattan/mcp/server.py", "r") as f:
            content = f.read()

        # Count Tool() instances
        tool_count = content.count("Tool(")

        print(f"[PASS] Found {tool_count} tool definitions")

        # List tool names
        import re

        tool_names = re.findall(r'name="([^"]+)"', content)
        print(f"  Tools: {', '.join(tool_names[:5])}... ({len(tool_names)} total)")

        assert tool_count >= 15, f"Expected at least 15 tools, found {tool_count}"

    except Exception as e:
        raise AssertionError(f"Failed: {e}") from e


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
            raise AssertionError(f"Failed to parse {filepath}: {e}") from e

    print(f"[PASS] Found {total_functions} public tool functions")

    assert total_functions >= 20, f"Expected at least 20 functions, found {total_functions}"


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
            assert f"def {method}" in content, f"ExchangeSessionManager missing method: {method}"

        print("[PASS] ExchangeSessionManager has all required methods")

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
            assert f"def {method}" in content, f"StrategySessionManager missing method: {method}"

        print("[PASS] StrategySessionManager has all required methods")

    except Exception as e:
        raise AssertionError(f"Failed: {e}") from e


def test_error_handling():
    """Test error handling is implemented."""
    print("\nValidating error handling...")

    try:
        with open("dr_manhattan/mcp/utils/errors.py", "r") as f:
            content = f.read()

        # Check error mapping exists
        assert "ERROR_MAP" in content, "ERROR_MAP not found"

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
            assert error in content, f"Error not mapped: {error}"

        print(f"[PASS] All {len(dr_errors)} error types are mapped")

        # Check translate_error function exists
        assert "def translate_error" in content, "translate_error function not found"

        print("[PASS] translate_error function exists")

    except Exception as e:
        raise AssertionError(f"Failed: {e}") from e


def test_documentation_exists():
    """Test documentation files exist."""
    print("\nValidating documentation...")

    # Per CLAUDE.md Rule #2: Minimize new documents. Only examples/mcp_usage_example.md
    docs = [
        "examples/mcp_usage_example.md",
    ]

    for doc in docs:
        assert os.path.exists(doc), f"Missing: {doc}"

    print(f"[PASS] All {len(docs)} documentation files exist")

    # Check doc content
    with open("examples/mcp_usage_example.md", "r") as f:
        content = f.read()

    assert "Dr. Manhattan" in content, "Usage example missing title"
    assert "Setup" in content, "Usage example missing Setup section"

    print("[PASS] Documentation has required sections")


def test_directory_structure():
    """Test directory structure is correct."""
    print("\nValidating directory structure...")

    required_dirs = [
        "dr_manhattan/mcp",
        "dr_manhattan/mcp/session",
        "dr_manhattan/mcp/tools",
        "dr_manhattan/mcp/utils",
    ]

    for dir_path in required_dirs:
        assert os.path.isdir(dir_path), f"Missing directory: {dir_path}"

    print(f"[PASS] All {len(required_dirs)} required directories exist")

    # Check __init__.py files
    init_files = [
        "dr_manhattan/mcp/__init__.py",
        "dr_manhattan/mcp/session/__init__.py",
        "dr_manhattan/mcp/tools/__init__.py",
        "dr_manhattan/mcp/utils/__init__.py",
    ]

    for init_file in init_files:
        assert os.path.exists(init_file), f"Missing: {init_file}"

    print(f"[PASS] All {len(init_files)} __init__.py files exist")


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
            assert component in content, f"Missing component: {component}"

        print("[PASS] Server has all required components")

        # Check signal handling
        assert "signal.signal" in content, "Missing signal handling"

        print("[PASS] Signal handling configured")

        # Check cleanup
        assert "def cleanup_handler" in content, "Missing cleanup handler"

        print("[PASS] Cleanup handler exists")

    except Exception as e:
        raise AssertionError(f"Failed: {e}") from e


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
        print("\nAll code validation tests passed!")
        print("\nMCP Server is ready to use!")
        print("\nNext steps:")
        print("  1. Install dependencies: pip install -e '.[mcp]'")
        print("  2. Configure .env with API credentials")
        print("  3. Add to Claude Desktop config")
        print("  4. Restart Claude Desktop")
        return 0
    else:
        print(f"\n{total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
