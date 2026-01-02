"""Exchange management tools."""

from typing import Any, Dict

from dr_manhattan.base import list_exchanges as dr_list_exchanges

from ..session import ExchangeSessionManager
from ..utils import serialize_model, translate_error

# Get session manager
exchange_manager = ExchangeSessionManager()


def list_exchanges() -> list[str]:
    """
    List all available exchanges.

    Mirrors: dr_manhattan.base.exchange_factory.list_exchanges()

    Returns:
        List of exchange names: ["polymarket", "opinion", "limitless"]
    """
    try:
        return dr_list_exchanges()
    except Exception as e:
        raise translate_error(e) from e


def get_exchange_info(exchange: str) -> Dict[str, Any]:
    """
    Get exchange metadata and capabilities.

    Mirrors: Exchange.describe()

    Args:
        exchange: Exchange name (polymarket, opinion, limitless)

    Returns:
        Exchange metadata dictionary with id, name, capabilities

    Example:
        >>> get_exchange_info("polymarket")
        {
            "id": "polymarket",
            "name": "Polymarket",
            "has": {
                "fetch_markets": True,
                "websocket": True,
                ...
            }
        }
    """
    try:
        exch = exchange_manager.get_exchange(exchange)
        info = exch.describe()

        # Add exchange-specific info
        info["supported_intervals"] = getattr(exch, "SUPPORTED_INTERVALS", [])

        return serialize_model(info)

    except Exception as e:
        raise translate_error(e, {"exchange": exchange}) from e


def validate_credentials(exchange: str) -> Dict[str, Any]:
    """
    Validate exchange credentials without trading.

    Args:
        exchange: Exchange name

    Returns:
        Validation result with address and balance accessibility

    Example:
        >>> validate_credentials("polymarket")
        {
            "valid": True,
            "address": "0x...",
            "balance_accessible": True
        }
    """
    try:
        # Create exchange with validation
        exch = exchange_manager.get_exchange(exchange, validate=True)

        # Try to fetch balance
        balance_accessible = False
        try:
            exch.fetch_balance()
            balance_accessible = True
        except Exception:
            pass

        # Get address if available
        address = getattr(exch, "_address", None)

        return {
            "valid": True,
            "exchange": exchange,
            "address": address,
            "balance_accessible": balance_accessible,
        }

    except Exception as e:
        return {
            "valid": False,
            "exchange": exchange,
            "error": str(e),
        }
