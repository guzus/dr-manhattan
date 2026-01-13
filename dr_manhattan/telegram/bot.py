"""
Telegram bot for querying Polymarket markets and prices.

Commands:
    /start - Welcome message and usage instructions
    /help - Show available commands
    /search <query> - Search markets by keyword
    /price <slug_or_url> - Get real-time price for a market
    /markets - List trending markets by volume
    /market <slug_or_url> - Get detailed market info
"""

import logging
import os
import sys
from typing import Optional

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from ..base.exchange_factory import create_exchange
from ..exchanges.polymarket import Polymarket

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Telegram bot token from environment
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")


class PolymarketBot:
    """Telegram bot for Polymarket market queries."""

    def __init__(self, token: str):
        """Initialize the bot with a Telegram token."""
        self.token = token
        self._exchange: Optional[Polymarket] = None

    @property
    def exchange(self) -> Polymarket:
        """Lazily initialize the Polymarket exchange."""
        if self._exchange is None:
            self._exchange = create_exchange("polymarket", validate=False)
        return self._exchange

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        welcome_message = """Welcome to the Polymarket Bot!

I can help you query prediction markets on Polymarket.

Available commands:
/search <query> - Search markets (e.g., /search bitcoin)
/price <slug_or_url> - Get real-time price for a market
/markets - List trending markets by volume
/market <slug_or_url> - Get detailed market info
/help - Show this help message

Example:
/search president
/price fed-decision-in-december
/markets"""
        await update.message.reply_text(welcome_message)

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command."""
        help_text = """Polymarket Bot Commands:

/start - Welcome message
/help - Show this help

Market Discovery:
/search <query> - Search markets by keyword
/markets - List top 10 trending markets

Price & Details:
/price <slug_or_url> - Get current prices
/market <slug_or_url> - Get detailed market info

Examples:
/search bitcoin price
/price fed-decision-in-december
/market https://polymarket.com/event/bitcoin-above-100k"""
        await update.message.reply_text(help_text)

    async def search(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /search command - search markets by query."""
        if not context.args:
            await update.message.reply_text(
                "Usage: /search <query>\nExample: /search bitcoin"
            )
            return

        query = " ".join(context.args)
        await update.message.reply_text(f"Searching for '{query}'...")

        try:
            markets = self.exchange.search_markets(
                query=query,
                limit=10,
                closed=False,
                min_liquidity=1000,
            )

            if not markets:
                await update.message.reply_text(f"No markets found for '{query}'")
                return

            response_lines = [f"Found {len(markets)} markets for '{query}':\n"]

            for i, market in enumerate(markets, 1):
                # Get the best price info
                prices_str = ""
                if market.prices:
                    price_parts = []
                    for outcome, price in list(market.prices.items())[:2]:
                        pct = price * 100
                        price_parts.append(f"{outcome}: {pct:.1f}%")
                    prices_str = " | ".join(price_parts)

                # Format volume
                volume_str = self._format_volume(market.volume)

                # Get slug for easy reference
                slug = market.metadata.get("slug", market.id[:20])

                line = f"{i}. {market.question[:80]}"
                if prices_str:
                    line += f"\n   {prices_str}"
                line += f"\n   Vol: {volume_str} | Slug: {slug}\n"
                response_lines.append(line)

            await update.message.reply_text("\n".join(response_lines))

        except Exception as e:
            logger.error(f"Search error: {e}")
            await update.message.reply_text(f"Error searching markets: {str(e)[:100]}")

    async def price(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /price command - get real-time prices for a market."""
        if not context.args:
            await update.message.reply_text(
                "Usage: /price <slug_or_url>\n"
                "Example: /price fed-decision-in-december\n"
                "Or: /price https://polymarket.com/event/fed-decision"
            )
            return

        identifier = context.args[0]
        slug = Polymarket.parse_market_identifier(identifier)

        await update.message.reply_text(f"Fetching prices for '{slug}'...")

        try:
            markets = self.exchange.fetch_markets_by_slug(slug)

            if not markets:
                await update.message.reply_text(f"No market found for '{slug}'")
                return

            response_lines = []

            for market in markets:
                response_lines.append(f"Market: {market.question}\n")

                if market.prices:
                    response_lines.append("Current Prices:")
                    for outcome, price in market.prices.items():
                        pct = price * 100
                        # Create a simple bar visualization
                        bar_len = int(pct / 5)
                        bar = "#" * bar_len + "-" * (20 - bar_len)
                        response_lines.append(f"  {outcome}: {pct:.1f}% [{bar}]")
                else:
                    response_lines.append("  No price data available")

                response_lines.append("")

            await update.message.reply_text("\n".join(response_lines))

        except Exception as e:
            logger.error(f"Price fetch error: {e}")
            await update.message.reply_text(f"Error fetching price: {str(e)[:100]}")

    async def markets(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /markets command - list trending markets."""
        await update.message.reply_text("Fetching trending markets...")

        try:
            markets = self.exchange.search_markets(
                limit=10,
                closed=False,
                order="volume",
                ascending=False,
                min_liquidity=10000,
            )

            if not markets:
                await update.message.reply_text("No trending markets found")
                return

            response_lines = ["Top 10 Trending Markets by Volume:\n"]

            for i, market in enumerate(markets, 1):
                # Get prices
                prices_str = ""
                if market.prices:
                    price_parts = []
                    for outcome, price in list(market.prices.items())[:2]:
                        pct = price * 100
                        price_parts.append(f"{outcome}: {pct:.1f}%")
                    prices_str = " | ".join(price_parts)

                volume_str = self._format_volume(market.volume)
                slug = market.metadata.get("slug", "")

                line = f"{i}. {market.question[:70]}"
                if prices_str:
                    line += f"\n   {prices_str}"
                line += f"\n   Volume: {volume_str}"
                if slug:
                    line += f" | /price {slug}"
                line += "\n"
                response_lines.append(line)

            await update.message.reply_text("\n".join(response_lines))

        except Exception as e:
            logger.error(f"Markets fetch error: {e}")
            await update.message.reply_text(f"Error fetching markets: {str(e)[:100]}")

    async def market_detail(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /market command - get detailed market info."""
        if not context.args:
            await update.message.reply_text(
                "Usage: /market <slug_or_url>\n"
                "Example: /market fed-decision-in-december"
            )
            return

        identifier = context.args[0]
        slug = Polymarket.parse_market_identifier(identifier)

        await update.message.reply_text(f"Fetching details for '{slug}'...")

        try:
            markets = self.exchange.fetch_markets_by_slug(slug)

            if not markets:
                await update.message.reply_text(f"No market found for '{slug}'")
                return

            for market in markets:
                response_lines = [
                    f"Market: {market.question}\n",
                ]

                # Description (truncated)
                if market.description:
                    desc = market.description[:200]
                    if len(market.description) > 200:
                        desc += "..."
                    response_lines.append(f"Description: {desc}\n")

                # Outcomes and prices
                response_lines.append("Outcomes:")
                for outcome in market.outcomes:
                    price = market.prices.get(outcome, 0)
                    pct = price * 100
                    response_lines.append(f"  - {outcome}: {pct:.1f}%")

                response_lines.append("")

                # Stats
                response_lines.append("Stats:")
                response_lines.append(f"  Volume: {self._format_volume(market.volume)}")
                response_lines.append(
                    f"  Liquidity: {self._format_volume(market.liquidity)}"
                )

                if market.close_time:
                    response_lines.append(
                        f"  Closes: {market.close_time.strftime('%Y-%m-%d %H:%M UTC')}"
                    )

                response_lines.append(f"  Status: {'Open' if market.is_open else 'Closed'}")

                # Link
                if slug:
                    response_lines.append(f"\nLink: https://polymarket.com/event/{slug}")

                await update.message.reply_text("\n".join(response_lines))

        except Exception as e:
            logger.error(f"Market detail error: {e}")
            await update.message.reply_text(f"Error fetching market: {str(e)[:100]}")

    def _format_volume(self, volume: float) -> str:
        """Format volume for display."""
        if volume >= 1_000_000:
            return f"${volume / 1_000_000:.1f}M"
        elif volume >= 1_000:
            return f"${volume / 1_000:.1f}K"
        else:
            return f"${volume:.0f}"

    def run(self) -> None:
        """Run the bot."""
        if not self.token:
            logger.error("TELEGRAM_BOT_TOKEN not set")
            sys.exit(1)

        application = Application.builder().token(self.token).build()

        # Register handlers
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("search", self.search))
        application.add_handler(CommandHandler("price", self.price))
        application.add_handler(CommandHandler("markets", self.markets))
        application.add_handler(CommandHandler("market", self.market_detail))

        logger.info("Starting Polymarket Telegram bot...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)


def main() -> None:
    """Entry point for the Telegram bot."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Error: TELEGRAM_BOT_TOKEN environment variable not set")
        print("Set it with: export TELEGRAM_BOT_TOKEN=your_token_here")
        sys.exit(1)

    bot = PolymarketBot(token)
    bot.run()


if __name__ == "__main__":
    main()
