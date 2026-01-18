"""
Polymarket Copytrading Bot

Monitors a target wallet's trades and mirrors them on your account.

Usage:
    uv run python -m examples.copytrading --target <wallet_address>
    uv run python -m examples.copytrading --target <wallet_address> --scale 0.5
    uv run python -m examples.copytrading --target <wallet_address> --telegram

Programmatic Usage:
    from examples.copytrading import CopytradingBot, BotConfig
    from dr_manhattan import Polymarket

    exchange = Polymarket({"private_key": "..."})
    config = BotConfig(target_wallet="0x...")

    bot = CopytradingBot(exchange, config)
    bot.run()
"""

from .bot import CopytradingBot
from .notifications import (
    NotificationHandler,
    NullNotifier,
    TelegramNotifier,
    create_notifier,
)
from .types import BotConfig, CopyStats, TradeAction, TradeInfo

__all__ = [
    # Bot
    "CopytradingBot",
    # Types
    "BotConfig",
    "CopyStats",
    "TradeAction",
    "TradeInfo",
    # Notifications
    "NotificationHandler",
    "TelegramNotifier",
    "NullNotifier",
    "create_notifier",
]
