from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Literal
from pathlib import Path


# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent


class Settings(BaseSettings):
    # Trading Mode
    trading_mode: Literal["demo", "live"] = "demo"

    # OpenAI
    openai_api_key: str = Field(default="")
    openai_model: str = "gpt-4o-mini"

    # Polymarket
    polymarket_host: str = "https://clob.polymarket.com"
    polymarket_private_key: str = ""
    polymarket_chain_id: int = 137

    # Database - SQLite by default (local file in data/ directory)
    database_url: str = f"sqlite+aiosqlite:///{PROJECT_ROOT}/data/trading.db"

    # Demo Trading
    demo_initial_balance: float = 1000.0

    # Trading Parameters
    execution_interval_minutes: int = 15
    max_positions: int = 10
    max_position_size_pct: float = 10.0  # 단일 포지션 최대 10%
    daily_loss_limit_pct: float = 5.0
    weekly_loss_limit_pct: float = 10.0
    max_drawdown_pct: float = 20.0

    # Strategy Parameters
    min_edge_threshold: float = 0.05  # 최소 5% edge 필요
    kelly_fraction: float = 0.25  # Quarter Kelly
    min_liquidity: float = 50000.0
    min_volume_24h: float = 10000.0
    max_spread: float = 0.05

    # Market Categories
    allowed_categories: list[str] = ["politics", "sports", "crypto"]

    # API Server
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# Global settings instance
_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
