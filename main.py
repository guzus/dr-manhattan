"""
Polymarket LLM Agent Trading Bot

메인 진입점
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

import structlog
from dotenv import load_dotenv

from config.settings import get_settings
from src.scheduler import TradingLoop

# Configure logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.dev.ConsoleRenderer(colors=True),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


async def main():
    """메인 함수"""
    # Load environment variables
    load_dotenv()

    settings = get_settings()

    logger.info(
        "Starting Polymarket Trading Bot",
        mode=settings.trading_mode,
        model=settings.openai_model,
        interval_minutes=settings.execution_interval_minutes,
    )

    # Create trading loop
    trading_loop = TradingLoop(
        openai_api_key=settings.openai_api_key,
        initial_balance=settings.demo_initial_balance,
        interval_minutes=settings.execution_interval_minutes,
        max_markets_per_cycle=5,
        demo_mode=(settings.trading_mode == "demo"),
    )

    try:
        # Run a single cycle for testing
        logger.info("Running single trading cycle...")
        decisions = await trading_loop.run_once()

        logger.info(
            "Trading cycle completed",
            total_decisions=len(decisions),
            trades=[
                {
                    "market": d.market_id[:20],
                    "decision": d.decision,
                    "confidence": d.confidence,
                    "size": f"${d.position_size_usd:.2f}",
                }
                for d in decisions
                if d.should_trade
            ],
        )

        # Print status
        status = trading_loop.get_status()
        logger.info("Bot status", **status)

    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    finally:
        await trading_loop.close()

    logger.info("Bot shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
