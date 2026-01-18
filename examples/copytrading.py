"""
Polymarket Copytrading Bot

Monitors a target wallet's trades and mirrors them on your account.
Uses dr-manhattan's unified API for Polymarket trading.

Usage:
    uv run python examples/copytrading.py --target <wallet_address>
    uv run python examples/copytrading.py --target <wallet_address> --scale 0.5
    uv run python examples/copytrading.py --target <wallet_address> --telegram
"""

import argparse
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

from dotenv import load_dotenv

from dr_manhattan import Polymarket
from dr_manhattan.exchanges.polymarket import PublicTrade
from dr_manhattan.models import Market
from dr_manhattan.models.order import OrderSide
from dr_manhattan.utils import TelegramBot, setup_logger
from dr_manhattan.utils.logger import Colors
from dr_manhattan.utils.telegram import MessageBuilder, bold, code

logger = setup_logger(__name__)


@dataclass
class CopyStats:
    """Statistics for copytrading session"""

    trades_detected: int = 0
    trades_copied: int = 0
    trades_skipped: int = 0
    trades_failed: int = 0
    total_volume: float = 0.0
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class CopytradingBot:
    """
    Copytrading bot that monitors a target wallet and mirrors trades.

    Features:
    - Polls target wallet trades via Polymarket Data API
    - Mirrors trades with configurable size scaling
    - Tracks copied trades to avoid duplicates
    - Supports market filtering
    - Telegram notifications for trades and status
    """

    def __init__(
        self,
        exchange: Polymarket,
        target_wallet: str,
        scale_factor: float = 1.0,
        poll_interval: float = 5.0,
        max_position: float = 100.0,
        min_trade_size: float = 1.0,
        market_filter: Optional[List[str]] = None,
        telegram: Optional[TelegramBot] = None,
    ):
        """
        Initialize copytrading bot.

        Args:
            exchange: Authenticated Polymarket exchange
            target_wallet: Target wallet address to copy
            scale_factor: Multiply target trade sizes by this factor
            poll_interval: Seconds between polling for new trades
            max_position: Maximum position size per outcome
            min_trade_size: Minimum trade size to copy
            market_filter: List of market slugs/IDs to filter (None = all)
            telegram: Optional TelegramBot for notifications
        """
        self.exchange = exchange
        self.target_wallet = target_wallet
        self.scale_factor = scale_factor
        self.poll_interval = poll_interval
        self.max_position = max_position
        self.min_trade_size = min_trade_size
        self.market_filter = market_filter
        self.telegram = telegram

        self.is_running = False
        self.copied_trades: Set[str] = set()
        self.stats = CopyStats()
        self.market_cache: Dict[str, Market] = {}
        self.last_poll_time: Optional[datetime] = None

    def _get_trade_id(self, trade: PublicTrade) -> str:
        """Generate unique ID for a trade"""
        return f"{trade.transaction_hash}_{trade.outcome_index}"

    def _should_copy_trade(self, trade: PublicTrade) -> bool:
        """Check if trade should be copied"""
        trade_id = self._get_trade_id(trade)

        if trade_id in self.copied_trades:
            return False

        if trade.size < self.min_trade_size:
            logger.debug(f"Skipping small trade: {trade.size}")
            return False

        if self.market_filter:
            slug = trade.event_slug or trade.slug or ""
            if not any(f.lower() in slug.lower() for f in self.market_filter):
                return False

        return True

    def _get_market(self, trade: PublicTrade) -> Optional[Market]:
        """Get market data for a trade"""
        condition_id = trade.condition_id
        if not condition_id:
            return None

        if condition_id in self.market_cache:
            return self.market_cache[condition_id]

        try:
            slug = trade.event_slug or trade.slug
            if slug:
                markets = self.exchange.fetch_markets_by_slug(slug)
                for market in markets:
                    self.market_cache[market.id] = market
                    if market.id == condition_id:
                        return market

            market = self.exchange.fetch_market(condition_id)
            self.market_cache[condition_id] = market
            return market
        except Exception as e:
            logger.warning(f"Failed to fetch market {condition_id}: {e}")
            return None

    def _get_token_id(self, market: Market, outcome: str) -> Optional[str]:
        """Get token ID for an outcome"""
        token_ids = market.metadata.get("clobTokenIds", [])
        outcomes = market.outcomes

        if not token_ids or len(token_ids) != len(outcomes):
            try:
                token_ids = self.exchange.fetch_token_ids(market.id)
                market.metadata["clobTokenIds"] = token_ids
            except Exception as e:
                logger.warning(f"Failed to fetch token IDs: {e}")
                return None

        for i, out in enumerate(outcomes):
            if out.lower() == outcome.lower():
                return token_ids[i] if i < len(token_ids) else None

        return None

    def _notify_trade(
        self,
        side: str,
        size: float,
        outcome: str,
        price: float,
        market: str,
        is_copy: bool,
    ) -> None:
        """Send trade notification via Telegram"""
        if not self.telegram:
            return

        emoji = "🟢" if side.upper() == "BUY" else "🔴"
        action = "Copied" if is_copy else "Detected"

        msg = (
            MessageBuilder()
            .title(f"{emoji} Trade {action}")
            .newline()
            .field("Side", side.upper())
            .newline()
            .field("Size", f"{size:.2f}")
            .newline()
            .field("Outcome", outcome)
            .newline()
            .field("Price", f"{price:.4f}")
        )

        if market:
            msg.newline().field("Market", market)

        self.telegram.send(msg.build())

    def _notify_error(self, error: str, context: str = "") -> None:
        """Send error notification via Telegram"""
        if not self.telegram:
            return

        msg = MessageBuilder().title("⚠️ Error").newline().raw(code(error))

        if context:
            msg.newline().field("Context", context)

        self.telegram.send(msg.build())

    def _execute_copy_trade(self, trade: PublicTrade) -> bool:
        """Execute a copy of the target's trade"""
        market = self._get_market(trade)
        if not market:
            logger.error(f"Cannot find market for trade: {trade.condition_id}")
            self._notify_error(f"Cannot find market: {trade.condition_id}", "execute_copy_trade")
            return False

        outcome = trade.outcome
        if not outcome:
            outcome = market.outcomes[trade.outcome_index] if trade.outcome_index is not None else None

        if not outcome:
            logger.error("Cannot determine outcome for trade")
            return False

        token_id = self._get_token_id(market, outcome)
        if not token_id:
            logger.error(f"Cannot find token ID for outcome: {outcome}")
            return False

        side = OrderSide.BUY if trade.side.upper() == "BUY" else OrderSide.SELL
        size = trade.size * self.scale_factor
        price = trade.price

        if size > self.max_position:
            size = self.max_position
            logger.warning(f"Capped trade size to max_position: {self.max_position}")

        try:
            order = self.exchange.create_order(
                market_id=market.id,
                outcome=outcome,
                side=side,
                price=price,
                size=size,
                params={"token_id": token_id},
            )

            side_colored = Colors.green("BUY") if side == OrderSide.BUY else Colors.red("SELL")
            logger.info(
                f"  {Colors.cyan('COPIED')} {side_colored} {size:.2f} "
                f"{Colors.magenta(outcome[:20])} @ {Colors.yellow(f'{price:.4f}')} "
                f"[{Colors.gray(order.id[:8] + '...')}]"
            )

            self._notify_trade(
                side=side.value,
                size=size,
                outcome=outcome,
                price=price,
                market=trade.slug or trade.event_slug or "",
                is_copy=True,
            )

            return True

        except Exception as e:
            logger.error(f"Failed to execute copy trade: {e}")
            self._notify_error(str(e), "execute_copy_trade")
            return False

    def _poll_trades(self) -> List[PublicTrade]:
        """Poll for new trades from target wallet"""
        try:
            trades = self.exchange.fetch_public_trades(
                user=self.target_wallet,
                limit=50,
                taker_only=True,
            )

            if self.last_poll_time:
                trades = [t for t in trades if t.timestamp > self.last_poll_time]

            self.last_poll_time = datetime.now(timezone.utc)
            return trades

        except Exception as e:
            logger.warning(f"Failed to fetch trades: {e}")
            return []

    def _process_trades(self, trades: List[PublicTrade]) -> None:
        """Process new trades from target wallet"""
        for trade in trades:
            self.stats.trades_detected += 1

            if not self._should_copy_trade(trade):
                self.stats.trades_skipped += 1
                continue

            trade_id = self._get_trade_id(trade)
            side_str = trade.side.upper()
            outcome_str = trade.outcome or f"idx:{trade.outcome_index}"

            logger.info(
                f"\n{Colors.bold('New Trade Detected:')} "
                f"{Colors.cyan(side_str)} {trade.size:.2f} {Colors.magenta(outcome_str[:20])} "
                f"@ {Colors.yellow(f'{trade.price:.4f}')} [{Colors.gray(trade.slug or '')}]"
            )

            self._notify_trade(
                side=side_str,
                size=trade.size,
                outcome=outcome_str,
                price=trade.price,
                market=trade.slug or trade.event_slug or "",
                is_copy=False,
            )

            if self._execute_copy_trade(trade):
                self.copied_trades.add(trade_id)
                self.stats.trades_copied += 1
                self.stats.total_volume += trade.size * self.scale_factor
            else:
                self.stats.trades_failed += 1

    def _get_uptime_str(self) -> str:
        """Get formatted uptime string"""
        elapsed = (datetime.now(timezone.utc) - self.stats.start_time).total_seconds()
        return f"{int(elapsed // 60)}m {int(elapsed % 60)}s"

    def log_status(self) -> None:
        """Log current status"""
        uptime_str = self._get_uptime_str()

        logger.info(
            f"\n[{time.strftime('%H:%M:%S')}] "
            f"{Colors.bold('Status:')} "
            f"Detected: {Colors.cyan(str(self.stats.trades_detected))} | "
            f"Copied: {Colors.green(str(self.stats.trades_copied))} | "
            f"Skipped: {Colors.gray(str(self.stats.trades_skipped))} | "
            f"Failed: {Colors.red(str(self.stats.trades_failed))} | "
            f"Volume: {Colors.yellow(f'${self.stats.total_volume:.2f}')} | "
            f"Uptime: {Colors.gray(uptime_str)}"
        )

    def run(self, duration_minutes: Optional[int] = None) -> None:
        """Run the copytrading bot"""
        logger.info(f"\n{Colors.bold('Copytrading Bot Started')}")
        logger.info(f"Target: {Colors.cyan(self.target_wallet)}")
        logger.info(f"Scale: {Colors.yellow(f'{self.scale_factor}x')}")
        logger.info(f"Interval: {Colors.gray(f'{self.poll_interval}s')}")
        logger.info(f"Max Position: {Colors.blue(f'{self.max_position}')}")

        if self.market_filter:
            logger.info(f"Markets: {Colors.magenta(', '.join(self.market_filter))}")

        if self.telegram and self.telegram.enabled:
            logger.info(f"Telegram: {Colors.green('Enabled')}")

        address = getattr(self.exchange, "_address", None)
        if address:
            logger.info(f"Bot Address: {Colors.cyan(address)}")

        usdc = 0.0
        try:
            balance = self.exchange.fetch_balance()
            usdc = balance.get("USDC", 0.0)
            logger.info(f"Balance: {Colors.green(f'${usdc:,.2f}')} USDC")
        except Exception as e:
            logger.warning(f"Failed to fetch balance: {e}")

        if self.telegram:
            wallet_short = f"{self.target_wallet[:8]}...{self.target_wallet[-6:]}"
            msg = (
                MessageBuilder()
                .title("🚀 Copytrading Bot Started")
                .newline()
                .field("Target", wallet_short)
                .newline()
                .field("Scale", f"{self.scale_factor}x")
                .newline()
                .field("Balance", f"${usdc:,.2f}")
                .build()
            )
            self.telegram.send(msg)

        logger.info(f"\n{Colors.gray('Waiting for trades...')}")

        self.is_running = True
        self.stats = CopyStats()
        start_time = time.time()
        end_time = start_time + (duration_minutes * 60) if duration_minutes else None

        try:
            while self.is_running:
                if end_time and time.time() >= end_time:
                    break

                trades = self._poll_trades()
                if trades:
                    self._process_trades(trades)

                self.log_status()
                time.sleep(self.poll_interval)

        except KeyboardInterrupt:
            logger.info("\nStopping...")

        finally:
            self.is_running = False
            self._log_summary()

    def _log_summary(self) -> None:
        """Log final summary"""
        duration_str = self._get_uptime_str()

        logger.info(f"\n{Colors.bold('Session Summary')}")
        logger.info(f"Duration: {duration_str}")
        logger.info(f"Trades Detected: {self.stats.trades_detected}")
        logger.info(f"Trades Copied: {Colors.green(str(self.stats.trades_copied))}")
        logger.info(f"Trades Skipped: {self.stats.trades_skipped}")
        logger.info(f"Trades Failed: {Colors.red(str(self.stats.trades_failed))}")
        logger.info(f"Total Volume: {Colors.yellow(f'${self.stats.total_volume:.2f}')}")

        if self.telegram:
            msg = (
                MessageBuilder()
                .title("🛑 Copytrading Bot Stopped")
                .newline()
                .field("Trades Copied", str(self.stats.trades_copied))
                .newline()
                .field("Trades Failed", str(self.stats.trades_failed))
                .newline()
                .field("Total Volume", f"${self.stats.total_volume:.2f}")
                .newline()
                .field("Duration", duration_str)
                .build()
            )
            self.telegram.send(msg)

    def stop(self) -> None:
        """Stop the bot"""
        self.is_running = False


def parse_args() -> argparse.Namespace:
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description="Polymarket Copytrading Bot")
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


def main() -> int:
    """Entry point"""
    load_dotenv()
    args = parse_args()

    private_key = os.getenv("POLYMARKET_PRIVATE_KEY") or os.getenv("PRIVATE_KEY")
    if not private_key:
        logger.error("POLYMARKET_PRIVATE_KEY or PRIVATE_KEY required in environment")
        return 1

    funder = os.getenv("POLYMARKET_FUNDER") or os.getenv("FUNDER")

    try:
        exchange = Polymarket({
            "private_key": private_key,
            "funder": funder,
            "verbose": False,
        })
    except Exception as e:
        logger.error(f"Failed to initialize exchange: {e}")
        return 1

    telegram = None
    if args.telegram:
        if not args.telegram_token or not args.telegram_chat_id:
            logger.error("Telegram enabled but TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
            return 1
        telegram = TelegramBot(
            token=args.telegram_token,
            chat_id=args.telegram_chat_id,
        )
        if not telegram.enabled:
            logger.warning("Telegram bot not properly configured")
            telegram = None

    bot = CopytradingBot(
        exchange=exchange,
        target_wallet=args.target,
        scale_factor=args.scale,
        poll_interval=args.interval,
        max_position=args.max_position,
        min_trade_size=args.min_size,
        market_filter=args.markets,
        telegram=telegram,
    )

    bot.run(duration_minutes=args.duration)
    return 0


if __name__ == "__main__":
    sys.exit(main())
