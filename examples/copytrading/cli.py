"""
Command-line interface for the copytrading bot.
"""

import argparse
import os
import sys
from typing import Optional

from dotenv import load_dotenv

from dr_manhattan import Polymarket
from dr_manhattan.utils import setup_logger

from .bot import CopytradingBot
from .notifications import create_notifier
from .types import BotConfig

logger = setup_logger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Polymarket Copytrading Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --target 0x123...abc
  %(prog)s --target 0x123...abc --scale 0.5
  %(prog)s --target 0x123...abc --telegram --markets fed-decision

Environment Variables:
  POLYMARKET_PRIVATE_KEY  Your wallet private key
  POLYMARKET_FUNDER       Proxy wallet funder address (optional)
  TELEGRAM_BOT_TOKEN      Telegram bot token (optional)
  TELEGRAM_CHAT_ID        Telegram chat ID (optional)
        """,
    )

    parser.add_argument(
        "-t",
        "--target",
        required=True,
        help="Target wallet address to copy trades from",
    )
    parser.add_argument(
        "-s",
        "--scale",
        type=float,
        default=float(os.getenv("SCALE_FACTOR", "1.0")),
        help="Scale factor for trade sizes (default: 1.0)",
    )
    parser.add_argument(
        "-i",
        "--interval",
        type=float,
        default=float(os.getenv("POLL_INTERVAL", "5")),
        help="Poll interval in seconds (default: 5)",
    )
    parser.add_argument(
        "--max-position",
        type=float,
        default=float(os.getenv("MAX_POSITION", "100")),
        help="Maximum position size (default: 100)",
    )
    parser.add_argument(
        "--min-size",
        type=float,
        default=float(os.getenv("MIN_TRADE_SIZE", "1")),
        help="Minimum trade size to copy (default: 1)",
    )
    parser.add_argument(
        "-m",
        "--markets",
        nargs="*",
        default=None,
        help="Filter to specific market slugs",
    )
    parser.add_argument(
        "-d",
        "--duration",
        type=int,
        default=None,
        help="Duration in minutes (default: indefinite)",
    )
    parser.add_argument(
        "--telegram",
        action="store_true",
        help="Enable Telegram notifications",
    )
    parser.add_argument(
        "--telegram-token",
        default=os.getenv("TELEGRAM_BOT_TOKEN"),
        help="Telegram bot token (or set TELEGRAM_BOT_TOKEN)",
    )
    parser.add_argument(
        "--telegram-chat-id",
        default=os.getenv("TELEGRAM_CHAT_ID"),
        help="Telegram chat ID (or set TELEGRAM_CHAT_ID)",
    )

    return parser.parse_args()


def create_exchange() -> Optional[Polymarket]:
    """Create and authenticate Polymarket exchange"""
    private_key = os.getenv("POLYMARKET_PRIVATE_KEY") or os.getenv("PRIVATE_KEY")
    if not private_key:
        logger.error("POLYMARKET_PRIVATE_KEY or PRIVATE_KEY required in environment")
        return None

    funder = os.getenv("POLYMARKET_FUNDER") or os.getenv("FUNDER")

    try:
        return Polymarket(
            {
                "private_key": private_key,
                "funder": funder,
                "verbose": False,
            }
        )
    except Exception as e:
        logger.error(f"Failed to initialize exchange: {e}")
        return None


def main() -> int:
    """Entry point"""
    load_dotenv()
    args = parse_args()

    exchange = create_exchange()
    if not exchange:
        return 1

    telegram_token = None
    telegram_chat_id = None

    if args.telegram:
        if not args.telegram_token or not args.telegram_chat_id:
            logger.error("Telegram enabled but TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
            return 1
        telegram_token = args.telegram_token
        telegram_chat_id = args.telegram_chat_id

    notifier = create_notifier(telegram_token, telegram_chat_id)

    config = BotConfig(
        target_wallet=args.target,
        scale_factor=args.scale,
        poll_interval=args.interval,
        max_position=args.max_position,
        min_trade_size=args.min_size,
        market_filter=args.markets,
    )

    bot = CopytradingBot(
        exchange=exchange,
        config=config,
        notifier=notifier,
    )

    bot.run(duration_minutes=args.duration)
    return 0


if __name__ == "__main__":
    sys.exit(main())
