"""
Terminal UI utilities for interactive prompts.
"""

from typing import List, Optional, TypeVar

from .logger import Colors

T = TypeVar("T")


def prompt_selection(
    items: List[T],
    title: str = "Select an option:",
    format_item: Optional[callable] = None,
    allow_quit: bool = True,
) -> Optional[T]:
    """
    Prompt user to select an item from a list.

    Args:
        items: List of items to choose from
        title: Title to display above the list
        format_item: Optional function to format each item for display.
                     Receives (index, item) and returns a string.
        allow_quit: Whether to show quit option

    Returns:
        Selected item, or None if user quits
    """
    if not items:
        return None

    if len(items) == 1:
        return items[0]

    print(f"\n{Colors.bold(title)}")

    for i, item in enumerate(items):
        if format_item:
            display = format_item(i, item)
        else:
            display = str(item)
        print(f"  {Colors.cyan(str(i))} - {display}")

    if allow_quit:
        print(f"  {Colors.cyan('q')} - Quit")

    while True:
        try:
            prompt = f"\n{Colors.bold('Enter choice:')} "
            choice = input(prompt).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return None

        if allow_quit and choice == "q":
            return None

        try:
            idx = int(choice)
            if 0 <= idx < len(items):
                return items[idx]
        except ValueError:
            pass

        max_idx = len(items) - 1
        quit_msg = " or 'q'" if allow_quit else ""
        print(f"  Invalid. Enter 0-{max_idx}{quit_msg}.")


def prompt_market_selection(markets: List) -> Optional[str]:
    """
    Prompt user to select a market from a list.

    Args:
        markets: List of Market objects

    Returns:
        Selected market ID, or None if user quits
    """
    from ..models.market import Market

    def format_market(i: int, market: Market) -> str:
        price = market.prices.get("Yes", 0)
        question = market.question
        if len(question) > 70:
            question = question[:70] + "..."
        return f"Yes: {Colors.yellow(f'{price:.2%}')}\n      {Colors.magenta(question)}"

    selected = prompt_selection(
        items=markets,
        title="Multiple markets found. Select one:",
        format_item=format_market,
        allow_quit=True,
    )

    return selected.id if selected else None


def prompt_confirm(message: str, default: bool = False) -> bool:
    """
    Prompt user for yes/no confirmation.

    Args:
        message: Question to ask
        default: Default value if user just presses enter

    Returns:
        True for yes, False for no
    """
    suffix = "[Y/n]" if default else "[y/N]"
    prompt = f"{message} {suffix} "

    try:
        response = input(prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False

    if not response:
        return default

    return response in ("y", "yes")
