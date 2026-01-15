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


@dataclass
class PredictFunConfig(BaseExchangeConfig):
    """Configuration for Predict.fun exchange."""

    api_key: str = ""
    private_key: str = ""  # Privy wallet private key (EOA)
    smart_wallet_owner_private_key: str = ""  # Smart wallet owner's private key
    use_smart_wallet: bool = False
    smart_wallet_address: str = ""  # Predict Account (deposit address)
    testnet: bool = False


@dataclass
class KalshiConfig(BaseExchangeConfig):
    """Configuration for Kalshi exchange."""

    api_key_id: str = ""
    private_key_path: str = ""
    private_key_pem: str = ""
    demo: bool = False


# Union type for any exchange config
ExchangeConfig = (
    PolymarketConfig | OpinionConfig | LimitlessConfig | PredictFunConfig | KalshiConfig
)
