"""
Exchange configuration models.
"""

from dataclasses import asdict, dataclass
from typing import Dict, Optional


@dataclass
class BaseExchangeConfig:
    """Base configuration for all exchanges."""

    verbose: bool = True

    def to_dict(self) -> Dict:
        """Convert to dict, excluding None values."""
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class PolymarketConfig(BaseExchangeConfig):
    """Configuration for Polymarket exchange."""

    private_key: str = ""
    funder: str = ""
    api_key: Optional[str] = None
    cache_ttl: float = 2.0


@dataclass
class OpinionConfig(BaseExchangeConfig):
    """Configuration for Opinion exchange."""

    api_key: str = ""
    private_key: str = ""
    multi_sig_addr: str = ""


@dataclass
class LimitlessConfig(BaseExchangeConfig):
    """Configuration for Limitless exchange."""

    private_key: str = ""


# Union type for any exchange config
ExchangeConfig = PolymarketConfig | OpinionConfig | LimitlessConfig
