"""
Telegram Bot Integration Module

A scalable, type-safe Telegram bot client for sending messages and notifications.

Basic Usage:
    from dr_manhattan.utils.telegram import TelegramBot

    bot = TelegramBot(token="...", chat_id="...")
    bot.send("Hello, World!")

With Message Builder:
    from dr_manhattan.utils.telegram import TelegramBot, MessageBuilder

    msg = (MessageBuilder()
        .title("Status Update")
        .field("CPU", "45%")
        .field("Memory", "2.1GB")
        .build())

    bot.send(msg)

With Formatters:
    from dr_manhattan.utils.telegram import TelegramBot
    from dr_manhattan.utils.telegram.formatters import bold, code, key_value

    bot.send(f"{bold('Alert')}: Server is {code('online')}")
"""

from .bot import TelegramBot
from .formatters import (
    MessageBuilder,
    blockquote,
    bold,
    bullet_list,
    code,
    escape_html,
    italic,
    key_value,
    link,
    mention,
    numbered_list,
    pre,
    progress_bar,
    spoiler,
    strikethrough,
    table,
    underline,
)
from .types import (
    Chat,
    ChatType,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    MessageOptions,
    ParseMode,
    ReplyMarkup,
    SendResult,
    TelegramConfig,
    User,
)

__all__ = [
    # Core
    "TelegramBot",
    # Types
    "TelegramConfig",
    "MessageOptions",
    "SendResult",
    "ParseMode",
    "ChatType",
    "User",
    "Chat",
    "Message",
    "InlineKeyboardButton",
    "InlineKeyboardMarkup",
    "ReplyMarkup",
    # Formatters
    "MessageBuilder",
    "escape_html",
    "bold",
    "italic",
    "code",
    "pre",
    "link",
    "mention",
    "strikethrough",
    "underline",
    "spoiler",
    "blockquote",
    "table",
    "key_value",
    "bullet_list",
    "numbered_list",
    "progress_bar",
]
