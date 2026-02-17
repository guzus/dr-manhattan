"""
Notification handlers for the copytrading bot.

Provides a clean interface for sending notifications via Telegram.
"""

from typing import Optional, Protocol

from dr_manhattan.utils.telegram import MessageBuilder, TelegramBot, code

from .types import CopyStats, TradeInfo


class NotificationHandler(Protocol):
    """Protocol for notification handlers"""

    def notify_startup(
        self,
        target_wallet: str,
        scale_factor: float,
        balance: float,
    ) -> None:
        """Send startup notification"""
        ...

    def notify_shutdown(self, stats: CopyStats, duration: str) -> None:
        """Send shutdown notification"""
        ...

    def notify_trade_detected(self, trade: TradeInfo) -> None:
        """Send trade detected notification"""
        ...

    def notify_trade_copied(self, trade: TradeInfo, scaled_size: float) -> None:
        """Send trade copied notification"""
        ...

    def notify_error(self, error: str, context: str) -> None:
        """Send error notification"""
        ...


class TelegramNotifier:
    """Telegram notification handler for copytrading bot"""

    def __init__(self, bot: TelegramBot) -> None:
        self._bot = bot

    @property
    def enabled(self) -> bool:
        """Check if notifications are enabled"""
        return self._bot.enabled

    def notify_startup(
        self,
        target_wallet: str,
        scale_factor: float,
        balance: float,
    ) -> None:
        """Send startup notification"""
        wallet_short = f"{target_wallet[:8]}...{target_wallet[-6:]}"
        msg = (
            MessageBuilder()
            .title("Copytrading Bot Started")
            .newline()
            .field("Target", wallet_short)
            .newline()
            .field("Scale", f"{scale_factor}x")
            .newline()
            .field("Balance", f"${balance:,.2f}")
            .build()
        )
        self._bot.send(msg)

    def notify_shutdown(self, stats: CopyStats, duration: str) -> None:
        """Send shutdown notification"""
        msg = (
            MessageBuilder()
            .title("Copytrading Bot Stopped")
            .newline()
            .field("Trades Copied", str(stats.trades_copied))
            .newline()
            .field("Trades Failed", str(stats.trades_failed))
            .newline()
            .field("Total Volume", f"${stats.total_volume:.2f}")
            .newline()
            .field("Duration", duration)
            .build()
        )
        self._bot.send(msg)

    def notify_trade_detected(self, trade: TradeInfo) -> None:
        """Send trade detected notification"""
        self._send_trade_notification(trade, is_copy=False)

    def notify_trade_copied(self, trade: TradeInfo, scaled_size: float) -> None:
        """Send trade copied notification"""
        self._send_trade_notification(trade, is_copy=True, size_override=scaled_size)

    def _send_trade_notification(
        self,
        trade: TradeInfo,
        is_copy: bool,
        size_override: Optional[float] = None,
    ) -> None:
        """Send a trade notification"""
        emoji = "+" if trade.is_buy else "-"
        action = "Copied" if is_copy else "Detected"
        size = size_override if size_override is not None else trade.size

        msg = (
            MessageBuilder()
            .title(f"{emoji} Trade {action}")
            .newline()
            .field("Side", trade.side_upper)
            .newline()
            .field("Size", f"{size:.2f}")
            .newline()
            .field("Outcome", trade.outcome)
            .newline()
            .field("Price", f"{trade.price:.4f}")
        )

        if trade.market_slug:
            msg.newline().field("Market", trade.market_slug)

        self._bot.send(msg.build())

    def notify_error(self, error: str, context: str = "") -> None:
        """Send error notification"""
        msg = MessageBuilder().title("Error").newline().raw(code(error))

        if context:
            msg.newline().field("Context", context)

        self._bot.send(msg.build())


class NullNotifier:
    """Null notification handler that does nothing"""

    @property
    def enabled(self) -> bool:
        return False

    def notify_startup(
        self,
        target_wallet: str,
        scale_factor: float,
        balance: float,
    ) -> None:
        pass

    def notify_shutdown(self, stats: CopyStats, duration: str) -> None:
        pass

    def notify_trade_detected(self, trade: TradeInfo) -> None:
        pass

    def notify_trade_copied(self, trade: TradeInfo, scaled_size: float) -> None:
        pass

    def notify_error(self, error: str, context: str = "") -> None:
        pass


def create_notifier(
    telegram_token: Optional[str] = None,
    telegram_chat_id: Optional[str] = None,
) -> NotificationHandler:
    """
    Create a notification handler.

    Returns TelegramNotifier if credentials provided, else NullNotifier.
    """
    if telegram_token and telegram_chat_id:
        bot = TelegramBot(token=telegram_token, chat_id=telegram_chat_id)
        if bot.enabled:
            return TelegramNotifier(bot)

    return NullNotifier()
