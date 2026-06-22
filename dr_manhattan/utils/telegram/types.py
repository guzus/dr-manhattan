"""
Type definitions for Telegram bot integration.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, TypeVar, Union

T = TypeVar("T")

Callback = Callable[[Dict[str, Any]], None]


class ParseMode(str, Enum):
    """Telegram message parse modes"""

    HTML = "HTML"
    MARKDOWN = "Markdown"
    MARKDOWN_V2 = "MarkdownV2"


class ChatType(str, Enum):
    """Telegram chat types"""

    PRIVATE = "private"
    GROUP = "group"
    SUPERGROUP = "supergroup"
    CHANNEL = "channel"


@dataclass(frozen=True)
class TelegramConfig:
    """Configuration for Telegram bot"""

    bot_token: str
    chat_id: str
    parse_mode: ParseMode = ParseMode.HTML
    disable_notification: bool = False
    disable_web_page_preview: bool = True
    timeout: int = 10

    def __post_init__(self) -> None:
        if not self.bot_token:
            raise ValueError("bot_token is required")
        if not self.chat_id:
            raise ValueError("chat_id is required")


@dataclass(frozen=True)
class MessageOptions:
    """Options for sending a message"""

    parse_mode: Optional[ParseMode] = None
    disable_notification: Optional[bool] = None
    disable_web_page_preview: Optional[bool] = None
    reply_to_message_id: Optional[int] = None
    protect_content: bool = False


@dataclass(frozen=True)
class SendResult:
    """Result of sending a message"""

    success: bool
    message_id: Optional[int] = None
    error: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class User:
    """Telegram user"""

    id: int
    is_bot: bool
    first_name: str
    last_name: Optional[str] = None
    username: Optional[str] = None
    language_code: Optional[str] = None


@dataclass(frozen=True)
class Chat:
    """Telegram chat"""

    id: int
    type: ChatType
    title: Optional[str] = None
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None


@dataclass(frozen=True)
class Message:
    """Telegram message"""

    message_id: int
    date: int
    chat: Chat
    from_user: Optional[User] = None
    text: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        """Parse message from API response"""
        chat_data = data.get("chat", {})
        chat = Chat(
            id=chat_data.get("id", 0),
            type=ChatType(chat_data.get("type", "private")),
            title=chat_data.get("title"),
            username=chat_data.get("username"),
            first_name=chat_data.get("first_name"),
            last_name=chat_data.get("last_name"),
        )

        from_data = data.get("from")
        from_user = None
        if from_data:
            from_user = User(
                id=from_data.get("id", 0),
                is_bot=from_data.get("is_bot", False),
                first_name=from_data.get("first_name", ""),
                last_name=from_data.get("last_name"),
                username=from_data.get("username"),
                language_code=from_data.get("language_code"),
            )

        return cls(
            message_id=data.get("message_id", 0),
            date=data.get("date", 0),
            chat=chat,
            from_user=from_user,
            text=data.get("text"),
            raw=data,
        )


@dataclass
class InlineKeyboardButton:
    """Inline keyboard button"""

    text: str
    url: Optional[str] = None
    callback_data: Optional[str] = None


@dataclass
class InlineKeyboardMarkup:
    """Inline keyboard markup"""

    inline_keyboard: List[List[InlineKeyboardButton]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to API format"""
        return {
            "inline_keyboard": [
                [
                    {
                        k: v
                        for k, v in {
                            "text": btn.text,
                            "url": btn.url,
                            "callback_data": btn.callback_data,
                        }.items()
                        if v is not None
                    }
                    for btn in row
                ]
                for row in self.inline_keyboard
            ]
        }


ReplyMarkup = Union[InlineKeyboardMarkup, None]
