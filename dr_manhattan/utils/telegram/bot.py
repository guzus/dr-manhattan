"""
Core Telegram Bot implementation.

A generic, type-safe Telegram bot client for sending messages and notifications.
"""

import json
import logging
from typing import Any, Dict, List, Optional

import requests

from .types import (
    InlineKeyboardMarkup,
    MessageOptions,
    ParseMode,
    ReplyMarkup,
    SendResult,
    TelegramConfig,
)

logger = logging.getLogger(__name__)


class TelegramBot:
    """
    Generic Telegram bot client for sending messages.

    This is a low-level, type-safe client that can be used for any purpose.
    For domain-specific formatting, use the formatters module.

    Example:
        bot = TelegramBot(token="...", chat_id="...")
        result = bot.send("Hello, World!")
        if result.success:
            print(f"Message sent: {result.message_id}")
    """

    BASE_URL = "https://api.telegram.org/bot{token}/{method}"

    def __init__(
        self,
        token: str,
        chat_id: str,
        parse_mode: ParseMode = ParseMode.HTML,
        disable_notification: bool = False,
        disable_web_page_preview: bool = True,
        timeout: int = 10,
    ) -> None:
        """
        Initialize Telegram bot.

        Args:
            token: Bot token from @BotFather
            chat_id: Default chat ID to send messages to
            parse_mode: Default parse mode for messages
            disable_notification: Send messages silently by default
            disable_web_page_preview: Disable link previews by default
            timeout: Request timeout in seconds
        """
        self._config = TelegramConfig(
            bot_token=token,
            chat_id=chat_id,
            parse_mode=parse_mode,
            disable_notification=disable_notification,
            disable_web_page_preview=disable_web_page_preview,
            timeout=timeout,
        )

    @classmethod
    def from_config(cls, config: TelegramConfig) -> "TelegramBot":
        """Create bot from config object"""
        return cls(
            token=config.bot_token,
            chat_id=config.chat_id,
            parse_mode=config.parse_mode,
            disable_notification=config.disable_notification,
            disable_web_page_preview=config.disable_web_page_preview,
            timeout=config.timeout,
        )

    @property
    def enabled(self) -> bool:
        """Check if bot is configured and enabled"""
        return bool(self._config.bot_token and self._config.chat_id)

    @property
    def config(self) -> TelegramConfig:
        """Get current configuration"""
        return self._config

    def _build_url(self, method: str) -> str:
        """Build API URL for method"""
        return self.BASE_URL.format(token=self._config.bot_token, method=method)

    def _request(
        self,
        method: str,
        data: Dict[str, Any],
    ) -> SendResult:
        """Make API request to Telegram"""
        if not self.enabled:
            return SendResult(success=False, error="Bot not configured")

        url = self._build_url(method)

        try:
            response = requests.post(url, json=data, timeout=self._config.timeout)
            result = response.json()

            if not result.get("ok"):
                error_msg = result.get("description", "Unknown error")
                logger.warning(f"Telegram API error: {error_msg}")
                return SendResult(success=False, error=error_msg, raw=result)

            return SendResult(
                success=True,
                message_id=result.get("result", {}).get("message_id"),
                raw=result.get("result"),
            )

        except requests.Timeout:
            logger.warning("Telegram request timed out")
            return SendResult(success=False, error="Request timed out")
        except requests.RequestException as e:
            logger.warning(f"Telegram request failed: {e}")
            return SendResult(success=False, error=str(e))
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse Telegram response: {e}")
            return SendResult(success=False, error=f"Invalid response: {e}")
        except Exception as e:
            logger.warning(f"Telegram error: {e}")
            return SendResult(success=False, error=str(e))

    def send(
        self,
        text: str,
        chat_id: Optional[str] = None,
        options: Optional[MessageOptions] = None,
        reply_markup: Optional[ReplyMarkup] = None,
    ) -> SendResult:
        """
        Send a text message.

        Args:
            text: Message text (supports HTML/Markdown based on parse_mode)
            chat_id: Override default chat ID
            options: Message options (parse_mode, notifications, etc.)
            reply_markup: Optional inline keyboard

        Returns:
            SendResult with success status and message ID
        """
        if not text:
            return SendResult(success=False, error="Empty message")

        opts = options or MessageOptions()

        data: Dict[str, Any] = {
            "chat_id": chat_id or self._config.chat_id,
            "text": text,
            "parse_mode": (opts.parse_mode or self._config.parse_mode).value,
            "disable_notification": (
                opts.disable_notification
                if opts.disable_notification is not None
                else self._config.disable_notification
            ),
            "disable_web_page_preview": (
                opts.disable_web_page_preview
                if opts.disable_web_page_preview is not None
                else self._config.disable_web_page_preview
            ),
        }

        if opts.reply_to_message_id:
            data["reply_to_message_id"] = opts.reply_to_message_id

        if opts.protect_content:
            data["protect_content"] = True

        if reply_markup:
            if isinstance(reply_markup, InlineKeyboardMarkup):
                data["reply_markup"] = reply_markup.to_dict()

        return self._request("sendMessage", data)

    def send_photo(
        self,
        photo: str,
        caption: Optional[str] = None,
        chat_id: Optional[str] = None,
        options: Optional[MessageOptions] = None,
    ) -> SendResult:
        """
        Send a photo.

        Args:
            photo: Photo URL or file_id
            caption: Optional caption
            chat_id: Override default chat ID
            options: Message options
        """
        opts = options or MessageOptions()

        data: Dict[str, Any] = {
            "chat_id": chat_id or self._config.chat_id,
            "photo": photo,
        }

        if caption:
            data["caption"] = caption
            data["parse_mode"] = (opts.parse_mode or self._config.parse_mode).value

        return self._request("sendPhoto", data)

    def send_document(
        self,
        document: str,
        caption: Optional[str] = None,
        chat_id: Optional[str] = None,
        options: Optional[MessageOptions] = None,
    ) -> SendResult:
        """
        Send a document.

        Args:
            document: Document URL or file_id
            caption: Optional caption
            chat_id: Override default chat ID
            options: Message options
        """
        opts = options or MessageOptions()

        data: Dict[str, Any] = {
            "chat_id": chat_id or self._config.chat_id,
            "document": document,
        }

        if caption:
            data["caption"] = caption
            data["parse_mode"] = (opts.parse_mode or self._config.parse_mode).value

        return self._request("sendDocument", data)

    def edit_message(
        self,
        message_id: int,
        text: str,
        chat_id: Optional[str] = None,
        options: Optional[MessageOptions] = None,
        reply_markup: Optional[ReplyMarkup] = None,
    ) -> SendResult:
        """
        Edit an existing message.

        Args:
            message_id: ID of message to edit
            text: New message text
            chat_id: Override default chat ID
            options: Message options
            reply_markup: Optional inline keyboard
        """
        opts = options or MessageOptions()

        data: Dict[str, Any] = {
            "chat_id": chat_id or self._config.chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": (opts.parse_mode or self._config.parse_mode).value,
        }

        if reply_markup:
            if isinstance(reply_markup, InlineKeyboardMarkup):
                data["reply_markup"] = reply_markup.to_dict()

        return self._request("editMessageText", data)

    def delete_message(
        self,
        message_id: int,
        chat_id: Optional[str] = None,
    ) -> SendResult:
        """
        Delete a message.

        Args:
            message_id: ID of message to delete
            chat_id: Override default chat ID
        """
        data = {
            "chat_id": chat_id or self._config.chat_id,
            "message_id": message_id,
        }

        return self._request("deleteMessage", data)

    def get_me(self) -> Optional[Dict[str, Any]]:
        """Get bot information"""
        result = self._request("getMe", {})
        return result.raw if result.success else None

    def send_chat_action(
        self,
        action: str = "typing",
        chat_id: Optional[str] = None,
    ) -> SendResult:
        """
        Send chat action (typing indicator, etc.)

        Args:
            action: Action type (typing, upload_photo, upload_document, etc.)
            chat_id: Override default chat ID
        """
        data = {
            "chat_id": chat_id or self._config.chat_id,
            "action": action,
        }

        return self._request("sendChatAction", data)

    def send_batch(
        self,
        messages: List[str],
        chat_id: Optional[str] = None,
        options: Optional[MessageOptions] = None,
        delay_ms: int = 0,
    ) -> List[SendResult]:
        """
        Send multiple messages.

        Args:
            messages: List of message texts
            chat_id: Override default chat ID
            options: Message options
            delay_ms: Delay between messages in milliseconds (0 = no delay)

        Returns:
            List of SendResult for each message
        """
        import time

        results: List[SendResult] = []

        for i, text in enumerate(messages):
            result = self.send(text, chat_id=chat_id, options=options)
            results.append(result)

            if delay_ms > 0 and i < len(messages) - 1:
                time.sleep(delay_ms / 1000)

        return results
