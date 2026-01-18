"""
Copytrading bot implementation.

Monitors a target wallet's trades and mirrors them on your account.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

from dr_manhattan import Polymarket
from dr_manhattan.exchanges.polymarket import PublicTrade
from dr_manhattan.models import Market
from dr_manhattan.models.order import OrderSide
from dr_manhattan.utils.logger import Colors

from .notifications import NotificationHandler, NullNotifier
from .types import BotConfig, CopyStats, TradeInfo

logger = logging.getLogger(__name__)


class CopytradingBot:
    """
    Copytrading bot that monitors a target wallet and mirrors trades.

    Features:
    - Polls target wallet trades via Polymarket Data API
    - Mirrors trades with configurable size scaling
    - Tracks copied trades to avoid duplicates
    - Supports market filtering
    - Pluggable notification system
    """

    def __init__(
        self,
        exchange: Polymarket,
        config: BotConfig,
        notifier: Optional[NotificationHandler] = None,
    ) -> None:
        """
        Initialize copytrading bot.

        Args:
            exchange: Authenticated Polymarket exchange
            config: Bot configuration
            notifier: Optional notification handler
        """
        self._exchange = exchange
        self._config = config
        self._notifier = notifier or NullNotifier()

        self._is_running = False
        self._copied_trades: Set[str] = set()
        self._stats = CopyStats()
        self._market_cache: Dict[str, Market] = {}
        self._last_poll_time: Optional[datetime] = None

    @property
    def config(self) -> BotConfig:
        """Get bot configuration"""
        return self._config

    @property
    def stats(self) -> CopyStats:
        """Get current statistics"""
        return self._stats

    @property
    def is_running(self) -> bool:
        """Check if bot is running"""
        return self._is_running

    def _get_trade_id(self, trade: PublicTrade) -> str:
        """Generate unique ID for a trade"""
        return f"{trade.transaction_hash}_{trade.outcome_index}"

    def _create_trade_info(self, trade: PublicTrade) -> TradeInfo:
        """Create TradeInfo from PublicTrade"""
        return TradeInfo(
            trade_id=self._get_trade_id(trade),
            side=trade.side,
            size=trade.size,
            outcome=trade.outcome or f"idx:{trade.outcome_index}",
            price=trade.price,
            market_slug=trade.slug or trade.event_slug or "",
            condition_id=trade.condition_id or "",
            timestamp=trade.timestamp,
        )

    def _should_copy_trade(self, trade: PublicTrade) -> bool:
        """Check if trade should be copied"""
        trade_id = self._get_trade_id(trade)

        if trade_id in self._copied_trades:
            return False

        if trade.size < self._config.min_trade_size:
            logger.debug(f"Skipping small trade: {trade.size}")
            return False

        if self._config.market_filter:
            slug = trade.event_slug or trade.slug or ""
            if not any(f.lower() in slug.lower() for f in self._config.market_filter):
                return False

        return True

    def _get_market(self, trade: PublicTrade) -> Optional[Market]:
        """Get market data for a trade"""
        condition_id = trade.condition_id
        if not condition_id:
            return None

        if condition_id in self._market_cache:
            return self._market_cache[condition_id]

        try:
            slug = trade.event_slug or trade.slug
            if slug:
                markets = self._exchange.fetch_markets_by_slug(slug)
                for market in markets:
                    self._market_cache[market.id] = market
                    if market.id == condition_id:
                        return market

            market = self._exchange.fetch_market(condition_id)
            self._market_cache[condition_id] = market
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
                token_ids = self._exchange.fetch_token_ids(market.id)
                market.metadata["clobTokenIds"] = token_ids
            except Exception as e:
                logger.warning(f"Failed to fetch token IDs: {e}")
                return None

        for i, out in enumerate(outcomes):
            if out.lower() == outcome.lower():
                return token_ids[i] if i < len(token_ids) else None

        return None

    def _execute_copy_trade(self, trade: PublicTrade, trade_info: TradeInfo) -> bool:
        """Execute a copy of the target's trade"""
        market = self._get_market(trade)
        if not market:
            logger.error(f"Cannot find market for trade: {trade.condition_id}")
            self._notifier.notify_error(
                f"Cannot find market: {trade.condition_id}",
                "execute_copy_trade",
            )
            return False

        outcome = trade.outcome
        if not outcome:
            outcome = (
                market.outcomes[trade.outcome_index] if trade.outcome_index is not None else None
            )

        if not outcome:
            logger.error("Cannot determine outcome for trade")
            return False

        token_id = self._get_token_id(market, outcome)
        if not token_id:
            logger.error(f"Cannot find token ID for outcome: {outcome}")
            return False

        side = OrderSide.BUY if trade.side.upper() == "BUY" else OrderSide.SELL
        size = trade.size * self._config.scale_factor
        price = trade.price

        if size > self._config.max_position:
            size = self._config.max_position
            logger.warning(f"Capped trade size to max_position: {self._config.max_position}")

        try:
            order = self._exchange.create_order(
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

            self._notifier.notify_trade_copied(trade_info, size)
            return True

        except Exception as e:
            logger.error(f"Failed to execute copy trade: {e}")
            self._notifier.notify_error(str(e), "execute_copy_trade")
            return False

    def _poll_trades(self) -> List[PublicTrade]:
        """Poll for new trades from target wallet"""
        try:
            trades = self._exchange.fetch_public_trades(
                user=self._config.target_wallet,
                limit=50,
                taker_only=True,
            )

            if self._last_poll_time:
                trades = [t for t in trades if t.timestamp > self._last_poll_time]

            self._last_poll_time = datetime.now(timezone.utc)
            return trades

        except Exception as e:
            logger.warning(f"Failed to fetch trades: {e}")
            return []

    def _process_trades(self, trades: List[PublicTrade]) -> None:
        """Process new trades from target wallet"""
        for trade in trades:
            self._stats.trades_detected += 1
            trade_info = self._create_trade_info(trade)

            if not self._should_copy_trade(trade):
                self._stats.trades_skipped += 1
                continue

            logger.info(
                f"\n{Colors.bold('New Trade Detected:')} "
                f"{Colors.cyan(trade_info.side_upper)} {trade.size:.2f} "
                f"{Colors.magenta(trade_info.outcome[:20])} "
                f"@ {Colors.yellow(f'{trade.price:.4f}')} "
                f"[{Colors.gray(trade_info.market_slug or '')}]"
            )

            self._notifier.notify_trade_detected(trade_info)

            if self._execute_copy_trade(trade, trade_info):
                self._copied_trades.add(trade_info.trade_id)
                self._stats.trades_copied += 1
                self._stats.total_volume += trade.size * self._config.scale_factor
            else:
                self._stats.trades_failed += 1

    def _get_uptime_str(self) -> str:
        """Get formatted uptime string"""
        elapsed = (datetime.now(timezone.utc) - self._stats.start_time).total_seconds()
        return f"{int(elapsed // 60)}m {int(elapsed % 60)}s"

    def _log_status(self) -> None:
        """Log current status"""
        uptime_str = self._get_uptime_str()

        logger.info(
            f"\n[{time.strftime('%H:%M:%S')}] "
            f"{Colors.bold('Status:')} "
            f"Detected: {Colors.cyan(str(self._stats.trades_detected))} | "
            f"Copied: {Colors.green(str(self._stats.trades_copied))} | "
            f"Skipped: {Colors.gray(str(self._stats.trades_skipped))} | "
            f"Failed: {Colors.red(str(self._stats.trades_failed))} | "
            f"Volume: {Colors.yellow(f'${self._stats.total_volume:.2f}')} | "
            f"Uptime: {Colors.gray(uptime_str)}"
        )

    def _log_startup(self, balance: float) -> None:
        """Log startup information"""
        logger.info(f"\n{Colors.bold('Copytrading Bot Started')}")
        logger.info(f"Target: {Colors.cyan(self._config.target_wallet)}")
        logger.info(f"Scale: {Colors.yellow(f'{self._config.scale_factor}x')}")
        logger.info(f"Interval: {Colors.gray(f'{self._config.poll_interval}s')}")
        logger.info(f"Max Position: {Colors.blue(f'{self._config.max_position}')}")

        if self._config.market_filter:
            logger.info(f"Markets: {Colors.magenta(', '.join(self._config.market_filter))}")

        if hasattr(self._notifier, "enabled") and self._notifier.enabled:
            logger.info(f"Telegram: {Colors.green('Enabled')}")

        address = getattr(self._exchange, "_address", None)
        if address:
            logger.info(f"Bot Address: {Colors.cyan(address)}")

        logger.info(f"Balance: {Colors.green(f'${balance:,.2f}')} USDC")

    def _log_summary(self) -> None:
        """Log final summary"""
        duration_str = self._get_uptime_str()

        logger.info(f"\n{Colors.bold('Session Summary')}")
        logger.info(f"Duration: {duration_str}")
        logger.info(f"Trades Detected: {self._stats.trades_detected}")
        logger.info(f"Trades Copied: {Colors.green(str(self._stats.trades_copied))}")
        logger.info(f"Trades Skipped: {self._stats.trades_skipped}")
        logger.info(f"Trades Failed: {Colors.red(str(self._stats.trades_failed))}")
        logger.info(f"Total Volume: {Colors.yellow(f'${self._stats.total_volume:.2f}')}")

        self._notifier.notify_shutdown(self._stats, duration_str)

    def run(self, duration_minutes: Optional[int] = None) -> None:
        """
        Run the copytrading bot.

        Args:
            duration_minutes: Optional duration limit in minutes
        """
        usdc = 0.0
        try:
            balance = self._exchange.fetch_balance()
            usdc = balance.get("USDC", 0.0)
        except Exception as e:
            logger.warning(f"Failed to fetch balance: {e}")

        self._log_startup(usdc)
        self._notifier.notify_startup(
            self._config.target_wallet,
            self._config.scale_factor,
            usdc,
        )

        logger.info(f"\n{Colors.gray('Waiting for trades...')}")

        self._is_running = True
        self._stats = CopyStats()
        start_time = time.time()
        end_time = start_time + (duration_minutes * 60) if duration_minutes else None

        try:
            while self._is_running:
                if end_time and time.time() >= end_time:
                    break

                trades = self._poll_trades()
                if trades:
                    self._process_trades(trades)

                self._log_status()
                time.sleep(self._config.poll_interval)

        except KeyboardInterrupt:
            logger.info("\nStopping...")

        finally:
            self._is_running = False
            self._log_summary()

    def stop(self) -> None:
        """Stop the bot"""
        self._is_running = False
