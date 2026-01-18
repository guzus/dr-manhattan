"""
Message formatting utilities for Telegram.

Provides HTML and Markdown formatting helpers for building messages.
"""

import html
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union


def escape_html(text: str) -> str:
    """Escape HTML special characters"""
    return html.escape(str(text))


def bold(text: str) -> str:
    """Format text as bold (HTML)"""
    return f"<b>{escape_html(text)}</b>"


def italic(text: str) -> str:
    """Format text as italic (HTML)"""
    return f"<i>{escape_html(text)}</i>"


def code(text: str) -> str:
    """Format text as inline code (HTML)"""
    return f"<code>{escape_html(text)}</code>"


def pre(text: str, language: Optional[str] = None) -> str:
    """Format text as code block (HTML)"""
    if language:
        return f'<pre><code class="language-{escape_html(language)}">{escape_html(text)}</code></pre>'
    return f"<pre>{escape_html(text)}</pre>"


def link(text: str, url: str) -> str:
    """Format text as hyperlink (HTML)"""
    return f'<a href="{escape_html(url)}">{escape_html(text)}</a>'


def mention(text: str, user_id: int) -> str:
    """Format text as user mention (HTML)"""
    return f'<a href="tg://user?id={user_id}">{escape_html(text)}</a>'


def strikethrough(text: str) -> str:
    """Format text as strikethrough (HTML)"""
    return f"<s>{escape_html(text)}</s>"


def underline(text: str) -> str:
    """Format text as underline (HTML)"""
    return f"<u>{escape_html(text)}</u>"


def spoiler(text: str) -> str:
    """Format text as spoiler (HTML)"""
    return f'<span class="tg-spoiler">{escape_html(text)}</span>'


def blockquote(text: str) -> str:
    """Format text as blockquote (HTML)"""
    return f"<blockquote>{escape_html(text)}</blockquote>"


@dataclass
class TableRow:
    """Table row data"""

    cells: List[str]
    bold_first: bool = False


def table(
    rows: Sequence[Union[Tuple[str, ...], List[str], TableRow]],
    header: Optional[Sequence[str]] = None,
    separator: str = " | ",
) -> str:
    """
    Format data as a simple text table.

    Args:
        rows: List of rows (tuples/lists of cell values)
        header: Optional header row
        separator: Column separator

    Returns:
        Formatted table as monospace text
    """
    lines: List[str] = []

    if header:
        lines.append(separator.join(bold(h) for h in header))
        lines.append("-" * 20)

    for row in rows:
        if isinstance(row, TableRow):
            cells = row.cells
            if row.bold_first and cells:
                cells = [bold(cells[0])] + [code(c) for c in cells[1:]]
            else:
                cells = [code(c) for c in cells]
        else:
            cells = [code(str(c)) for c in row]
        lines.append(separator.join(cells))

    return "\n".join(lines)


def key_value(
    data: Dict[str, Any],
    separator: str = ": ",
    bold_keys: bool = True,
) -> str:
    """
    Format key-value pairs.

    Args:
        data: Dictionary of key-value pairs
        separator: Separator between key and value
        bold_keys: Whether to bold the keys

    Returns:
        Formatted key-value pairs
    """
    lines: List[str] = []

    for key, value in data.items():
        key_str = bold(key) if bold_keys else escape_html(key)
        value_str = code(str(value))
        lines.append(f"{key_str}{separator}{value_str}")

    return "\n".join(lines)


def bullet_list(items: Sequence[str], bullet: str = "-") -> str:
    """
    Format items as a bullet list.

    Args:
        items: List of items
        bullet: Bullet character

    Returns:
        Formatted bullet list
    """
    return "\n".join(f"{bullet} {escape_html(item)}" for item in items)


def numbered_list(items: Sequence[str], start: int = 1) -> str:
    """
    Format items as a numbered list.

    Args:
        items: List of items
        start: Starting number

    Returns:
        Formatted numbered list
    """
    return "\n".join(f"{i}. {escape_html(item)}" for i, item in enumerate(items, start))


def progress_bar(
    current: float,
    total: float,
    width: int = 10,
    filled: str = "█",
    empty: str = "░",
) -> str:
    """
    Create a text progress bar.

    Args:
        current: Current value
        total: Total value
        width: Bar width in characters
        filled: Character for filled portion
        empty: Character for empty portion

    Returns:
        Progress bar string
    """
    if total <= 0:
        ratio = 0.0
    else:
        ratio = min(1.0, max(0.0, current / total))

    filled_width = int(ratio * width)
    empty_width = width - filled_width

    bar = filled * filled_width + empty * empty_width
    percentage = ratio * 100

    return f"{bar} {percentage:.1f}%"


class MessageBuilder:
    """
    Fluent message builder for constructing formatted messages.

    Example:
        msg = (MessageBuilder()
            .title("Alert")
            .field("Status", "OK")
            .field("Count", 42)
            .newline()
            .text("Details here")
            .build())
    """

    def __init__(self) -> None:
        self._parts: List[str] = []

    def text(self, text: str, escape: bool = True) -> "MessageBuilder":
        """Add plain text"""
        self._parts.append(escape_html(text) if escape else text)
        return self

    def raw(self, text: str) -> "MessageBuilder":
        """Add raw HTML (no escaping)"""
        self._parts.append(text)
        return self

    def title(self, text: str) -> "MessageBuilder":
        """Add a bold title"""
        self._parts.append(bold(text))
        return self

    def subtitle(self, text: str) -> "MessageBuilder":
        """Add an italic subtitle"""
        self._parts.append(italic(text))
        return self

    def field(self, key: str, value: Any, inline: bool = False) -> "MessageBuilder":
        """Add a key-value field"""
        separator = ": " if inline else "\n"
        if not inline:
            self._parts.append(f"{bold(key)}: {code(str(value))}")
        else:
            self._parts.append(f"{bold(key)}: {code(str(value))}")
        return self

    def fields(self, data: Dict[str, Any]) -> "MessageBuilder":
        """Add multiple key-value fields"""
        for key, value in data.items():
            self.field(key, value)
            self.newline()
        return self

    def code_block(self, text: str, language: Optional[str] = None) -> "MessageBuilder":
        """Add a code block"""
        self._parts.append(pre(text, language))
        return self

    def inline_code(self, text: str) -> "MessageBuilder":
        """Add inline code"""
        self._parts.append(code(text))
        return self

    def link_text(self, text: str, url: str) -> "MessageBuilder":
        """Add a hyperlink"""
        self._parts.append(link(text, url))
        return self

    def newline(self, count: int = 1) -> "MessageBuilder":
        """Add newlines"""
        self._parts.append("\n" * count)
        return self

    def separator(self, char: str = "-", width: int = 20) -> "MessageBuilder":
        """Add a separator line"""
        self._parts.append(char * width)
        return self

    def bullet(self, items: Sequence[str]) -> "MessageBuilder":
        """Add a bullet list"""
        self._parts.append(bullet_list(items))
        return self

    def numbered(self, items: Sequence[str], start: int = 1) -> "MessageBuilder":
        """Add a numbered list"""
        self._parts.append(numbered_list(items, start))
        return self

    def progress(
        self,
        current: float,
        total: float,
        label: Optional[str] = None,
    ) -> "MessageBuilder":
        """Add a progress bar"""
        bar = progress_bar(current, total)
        if label:
            self._parts.append(f"{escape_html(label)}: {bar}")
        else:
            self._parts.append(bar)
        return self

    def build(self) -> str:
        """Build the final message"""
        return "".join(self._parts)

    def __str__(self) -> str:
        return self.build()
