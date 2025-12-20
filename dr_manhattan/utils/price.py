def round_to_tick_size(price: float, tick_size: float) -> float:
    """
    Round a price to the nearest valid tick increment.

    Args:
        price: The price to round
        tick_size: The minimum tick size

    Returns:
        Price rounded to nearest tick

    Example:
        >>> round_to_tick_size(0.1234, 0.01)
        0.12
    """
    if tick_size <= 0:
        raise ValueError("tick_size must be positive")

    return round(price / tick_size) * tick_size


def is_valid_price(price: float, tick_size: float) -> bool:
    """
    Check if a price is valid for the given tick size.

    Args:
        price: Price to check
        tick_size: Minimum tick size

    Returns:
        True if price is valid
    """
    if tick_size <= 0:
        raise ValueError("tick_size must be positive")

    rounded = round_to_tick_size(price, tick_size)
    return abs(price - rounded) < (tick_size / 10)
