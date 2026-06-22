"""
Entry point for running the copytrading bot as a module.

Usage:
    uv run python -m examples.copytrading --target <wallet_address>
"""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
