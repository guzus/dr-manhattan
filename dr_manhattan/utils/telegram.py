"""
Telegram Bot Integration

Simple Telegram notification module using the Bot API.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger(__name__)


@dataclass
class TelegramConfig:
    """Telegram bot configuration"""

    bot_token: str
    chat_id: str
    parse_mode: str = "HTML"
    disable_notification: bool = False


class TelegramBot:
    """
    Simple Telegram bot for sending notifications.

    Usage:
        bot = TelegramBot(token="your_bot_token", chat_id="your_chat_id")
        bot.send("Hello from Dr. Manhattan!")
    """

    BASE_URL = "https://api.telegram.org/bot{token}/{method}"

    def __init__(
        self,
        token: str,
        chat_id: str,
        parse_mode: str = "HTML",
        disable_notification: bool = False,
        timeout: int = 10,
    ):
        """
        Initialize Telegram bot.

        Args:
            token: Bot token from @BotFather
            chat_id: Chat ID to send messages to
            parse_mode: Message parse mode (HTML, Markdown, MarkdownV2)
            disable_notification: Send messages silently
            timeout: Request timeout in seconds
        """
        self.token = token
        self.chat_id = chat_id
        self.parse_mode = parse_mode
        self.disable_notification = disable_notification
        self.timeout = timeout
        self._enabled = bool(token and chat_id)

    @property
    def enabled(self) -> bool:
        """Check if bot is configured and enabled"""
        return self._enabled

    def _request(self, method: str, data: dict) -> Optional[dict]:
        """Make API request to Telegram"""
        if not self._enabled:
            return None

        url = self.BASE_URL.format(token=self.token, method=method)

        try:
            response = requests.post(url, json=data, timeout=self.timeout)
            result = response.json()

            if not result.get("ok"):
                logger.warning(f"Telegram API error: {result.get('description')}")
                return None

            return result.get("result")

        except requests.Timeout:
            logger.warning("Telegram request timed out")
            return None
        except requests.RequestException as e:
            logger.warning(f"Telegram request failed: {e}")
            return None
        except Exception as e:
            logger.warning(f"Telegram error: {e}")
            return None

    def send(
        self,
        text: str,
        parse_mode: Optional[str] = None,
        disable_notification: Optional[bool] = None,
    ) -> bool:
        """
        Send a text message.

        Args:
            text: Message text
            parse_mode: Override default parse mode
            disable_notification: Override default notification setting

        Returns:
            True if message sent successfully
        """
        if not self._enabled:
            return False

        data = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode or self.parse_mode,
            "disable_notification": disable_notification
            if disable_notification is not None
            else self.disable_notification,
        }

        result = self._request("sendMessage", data)
        return result is not None

    def send_trade_notification(
        self,
        side: str,
        size: float,
        outcome: str,
        price: float,
        market: str = "",
        is_copy: bool = True,
    ) -> bool:
        """
        Send a trade notification with formatted message.

        Args:
            side: BUY or SELL
            size: Trade size
            outcome: Outcome name
            price: Trade price
            market: Market name/slug
            is_copy: Whether this is a copied trade
        """
        side_emoji = "🟢" if side.upper() == "BUY" else "🔴"
        action = "Copied" if is_copy else "Detected"

        text = (
            f"{side_emoji} <b>Trade {action}</b>\n"
            f"Side: <code>{side.upper()}</code>\n"
            f"Size: <code>{size:.2f}</code>\n"
            f"Outcome: <code>{outcome}</code>\n"
            f"Price: <code>{price:.4f}</code>"
        )

        if market:
            text += f"\nMarket: <code>{market}</code>"

        return self.send(text)

    def send_status(
        self,
        trades_detected: int,
        trades_copied: int,
        trades_failed: int,
        total_volume: float,
        uptime: str,
    ) -> bool:
        """Send a status update notification"""
        text = (
            f"📊 <b>Copytrading Status</b>\n"
            f"Detected: <code>{trades_detected}</code>\n"
            f"Copied: <code>{trades_copied}</code>\n"
            f"Failed: <code>{trades_failed}</code>\n"
            f"Volume: <code>${total_volume:.2f}</code>\n"
            f"Uptime: <code>{uptime}</code>"
        )

        return self.send(text)

    def send_error(self, error: str, context: str = "") -> bool:
        """Send an error notification"""
        text = f"⚠️ <b>Error</b>\n<code>{error}</code>"
        if context:
            text += f"\nContext: <code>{context}</code>"

        return self.send(text)

    def send_startup(
        self,
        target_wallet: str,
        scale_factor: float,
        balance: float,
    ) -> bool:
        """Send startup notification"""
        text = (
            f"🚀 <b>Copytrading Bot Started</b>\n"
            f"Target: <code>{target_wallet[:8]}...{target_wallet[-6:]}</code>\n"
            f"Scale: <code>{scale_factor}x</code>\n"
            f"Balance: <code>${balance:,.2f}</code>"
        )

        return self.send(text)

    def send_shutdown(self, stats: dict) -> bool:
        """Send shutdown notification with final stats"""
        text = (
            f"🛑 <b>Copytrading Bot Stopped</b>\n"
            f"Trades Copied: <code>{stats.get('copied', 0)}</code>\n"
            f"Trades Failed: <code>{stats.get('failed', 0)}</code>\n"
            f"Total Volume: <code>${stats.get('volume', 0):.2f}</code>\n"
            f"Duration: <code>{stats.get('duration', 'N/A')}</code>"
        )

        return self.send(text)
