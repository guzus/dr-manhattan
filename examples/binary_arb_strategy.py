"""
Binary Arbitrage Alert Bot for Polymarket (dr_manhattan based)

Detects "YES best ask + NO best ask < 1" opportunities using live orderbooks.
- Modes:
    - live: place both legs when edge detected
    - test: log opportunities without sending orders

Usage:
    # Default: monitor a single market
    uv run python examples/binary_arb_alert.py <market_slug_or_url>

    # Option: scan all markets and print top 10 candidates
    uv run python examples/binary_arb_alert.py --scan

    # Option: scan then auto-pick the best candidate to monitor
    uv run python examples/binary_arb_alert.py --scan --auto

    # Mode override (live/test)
    uv run python examples/binary_arb_alert.py <market_slug_or_url> --mode=test

Env:
    export POLYMARKET_PRIVATE_KEY=...
    export POLYMARKET_FUNDER=...
"""

import os
import re
import sys
import time
import asyncio
import threading
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Any
from dotenv import load_dotenv

import dr_manhattan
from dr_manhattan.models import OrderSide
from dr_manhattan.utils import setup_logger
from dr_manhattan.utils.logger import Colors

# py_clob_client for scanning markets
from py_clob_client.client import ClobClient

logger = setup_logger(__name__)


def normalize_slug(slug_or_url: str) -> str:
    s = slug_or_url.strip()
    m = re.search(r"polymarket\.com/event/([a-zA-Z0-9\-]+)", s)
    if m:
        return m.group(1)
    if s.startswith("http://") or s.startswith("https://"):
        s = s.split("?")[0].rstrip("/")
        tail = s.split("/")[-1]
        return tail
    return s


def _extract_binary_yes_no_tokens(market: Dict[str, Any]) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """
    Attempts to pull YES/NO token objects from a market dict returned by CLOB markets endpoint.
    Handles small schema differences safely.
    """
    tokens = market.get("tokens") or market.get("outcomes") or []
    if not isinstance(tokens, list) or len(tokens) != 2:
        return None

    # Common fields: outcome / name / title
    def outcome_name(t: Dict[str, Any]) -> str:
        return str(t.get("outcome") or t.get("name") or t.get("title") or "").lower()

    yes_token = next((t for t in tokens if outcome_name(t) in ("yes", "y")), None)
    no_token = next((t for t in tokens if outcome_name(t) in ("no", "n")), None)

    # Fallback: if the API doesn't label Yes/No clearly, just return in order (still binary)
    if yes_token and no_token:
        return yes_token, no_token
    return tokens[0], tokens[1]


def _extract_token_id(token_obj: Dict[str, Any]) -> Optional[str]:
    """
    Token id key varies: token_id / tokenId / id / asset_id.
    """
    for k in ("token_id", "tokenId", "id", "asset_id", "assetId"):
        v = token_obj.get(k)
        if v:
            return str(v)
    return None


@dataclass
class ScanCandidate:
    slug: Optional[str]
    question: str
    yes_ask: float
    no_ask: float
    total_cost: float
    edge: float


def scan_binary_underround_candidates(
    clob: ClobClient,
    min_edge: float = 0.002,
    max_markets: int = 300,          # very large values may be slow
    top_k: int = 10,
    sleep_between: float = 0.0,      # if worried about rate limits, use 0.01-0.05
) -> List[ScanCandidate]:
    """
    Scans markets using REST endpoints:
      - get_markets() to discover markets/tokens
      - get_order_book(token_id) to get top-of-book asks (candidate selection)

    NOTE: REST orderbook can be stale/laggy vs WS.
          This scan is best used to pick candidates, then you monitor via WS for real execution.
    """
    markets = clob.get_markets()
    data = markets.get("data") or markets.get("markets") or []
    if not isinstance(data, list):
        return []

    candidates: List[ScanCandidate] = []

    for i, m in enumerate(data[:max_markets]):
        pair = _extract_binary_yes_no_tokens(m)
        if not pair:
            continue

        yes_t, no_t = pair
        yes_id = _extract_token_id(yes_t)
        no_id = _extract_token_id(no_t)
        if not yes_id or not no_id:
            continue

        try:
            # get_order_book() returns a dict containing bids/asks lists (L2-ish)
            yes_book = clob.get_order_book(yes_id)
            no_book = clob.get_order_book(no_id)

            yes_asks = yes_book.get("asks") or []
            no_asks = no_book.get("asks") or []
            if not yes_asks or not no_asks:
                continue

            # asks entries commonly like [{"price":"0.45","size":"123"}, ...] or [[price,size], ...]
            def top_ask(asks):
                a0 = asks[0]
                if isinstance(a0, dict):
                    return float(a0.get("price")), float(a0.get("size", 0))
                return float(a0[0]), float(a0[1] if len(a0) > 1 else 0)

            yes_ask, _ = top_ask(yes_asks)
            no_ask, _ = top_ask(no_asks)

            if not (0.0 < yes_ask < 1.0 and 0.0 < no_ask < 1.0):
                continue

            total = yes_ask + no_ask
            edge = 1.0 - total

            if edge >= min_edge:
                question = str(m.get("question") or m.get("title") or m.get("name") or "UNKNOWN")
                slug = m.get("slug") or (m.get("metadata") or {}).get("slug")
                candidates.append(
                    ScanCandidate(
                        slug=slug,
                        question=question,
                        yes_ask=yes_ask,
                        no_ask=no_ask,
                        total_cost=total,
                        edge=edge,
                    )
                )
        except Exception:
            # Keep scanning even if one market fails
            continue
        finally:
            if sleep_between > 0:
                time.sleep(sleep_between)

    candidates.sort(key=lambda c: c.edge, reverse=True)
    return candidates[:top_k]


@dataclass
class ArbSignal:
    yes_ask: float
    no_ask: float
    total_cost: float
    edge: float  # 1 - total_cost


class BinaryArbAlertStrategy:
    def __init__(
        self,
        exchange: dr_manhattan.Polymarket,
        market_slug: str,
        order_size: float = 5.0,
        check_interval: float = 1.0,
        min_edge: float = 0.002,
        min_level_size: float = 1.0,
        cooldown_seconds: float = 10.0,
        tick_infer: bool = True,
        bell: bool = True,
        mode: str = "live",  # "live" or "test"
    ):
        self.exchange = exchange
        self.market_slug = market_slug
        self.order_size = order_size
        self.check_interval = check_interval

        self.min_edge = min_edge
        self.min_level_size = min_level_size
        self.cooldown_seconds = cooldown_seconds
        self.tick_infer = tick_infer
        self.bell = bell

        self.market = None
        self.token_ids: List[str] = []
        self.outcomes: List[str] = []
        self.tick_size: float = 0.01

        self.ws = None
        self.orderbook_manager = None
        self.ws_thread = None

        self.is_running = False
        self._last_alert_ts = 0.0
        self.live_mode = mode.lower() == "live"

    def fetch_market(self) -> bool:
        logger.info(f"Fetching market: {self.market_slug}")
        self.market = self.exchange.fetch_market_by_slug(self.market_slug)

        if not self.market:
            logger.error(f"Failed to fetch market: {self.market_slug}")
            return False

        self.token_ids = self.market.metadata.get("clobTokenIds", [])
        self.outcomes = list(self.market.outcomes or [])

        if len(self.token_ids) != 2 or len(self.outcomes) != 2:
            logger.error("This strategy only supports binary markets (2 outcomes).")
            logger.error(f"token_ids={len(self.token_ids)}, outcomes={len(self.outcomes)}")
            return False

        self.tick_size = self.exchange.get_tick_size(self.market)

        if self.tick_infer and getattr(self.market, "prices", None):
            for _, price in self.market.prices.items():
                if price and price > 0:
                    price_str = f"{price:.4f}"
                    if "." in price_str:
                        decimals = len(price_str.split(".")[1].rstrip("0"))
                        if decimals == 3:
                            self.tick_size = 0.001
                            logger.info("Detected tick size: 0.001 (from market prices)")
                            break

        logger.info(f"\n{Colors.bold('Market:')} {Colors.cyan(self.market.question)}")
        logger.info(
            f"Outcomes: {Colors.magenta(str(self.outcomes))} | "
            f"Tick: {Colors.yellow(str(self.tick_size))} | "
            f"Vol: {Colors.cyan(f'${self.market.volume:,.0f}')}"
        )
        slug = self.market.metadata.get("slug", "")
        if slug:
            logger.info(f"URL: {Colors.gray(f'https://polymarket.com/event/{slug}')}")
        return True

    def setup_websocket(self):
        self.ws = self.exchange.get_websocket()
        self.orderbook_manager = self.ws.get_orderbook_manager()

    def start_websocket(self):
        logger.info("Starting WebSocket (subscribing to BOTH tokens for arb accuracy)...")

        if self.ws.loop is None:
            self.ws.loop = asyncio.new_event_loop()

        async def subscribe_all():
            await self.ws.connect()
            await self.ws.watch_orderbook_by_market(
                self.market.id,
                self.token_ids,
                callback=lambda mid, ob: None,
            )
            await self.ws._receive_loop()

        def run_loop():
            asyncio.set_event_loop(self.ws.loop)
            self.ws.loop.run_until_complete(subscribe_all())

        self.ws_thread = threading.Thread(target=run_loop, daemon=True)
        self.ws_thread.start()
        time.sleep(2)

    def stop_websocket(self):
        try:
            if self.ws:
                self.ws.stop()
        finally:
            if self.ws_thread:
                self.ws_thread.join(timeout=5)

    def _get_best_ask_with_size(self, token_id: str) -> Tuple[Optional[float], Optional[float]]:
        ob = self.orderbook_manager.get(token_id) if self.orderbook_manager else None
        if not ob:
            return None, None
        asks = ob.get("asks", [])
        if not asks:
            return None, None
        best_ask_price, best_ask_size = asks[0]
        try:
            price = float(best_ask_price)
            size = float(best_ask_size)
        except Exception:
            return None, None
        return price, size

    def detect_binary_underround(self) -> Optional[ArbSignal]:
        yes_token = self.token_ids[0]
        no_token = self.token_ids[1]

        yes_ask, yes_sz = self._get_best_ask_with_size(yes_token)
        no_ask, no_sz = self._get_best_ask_with_size(no_token)

        if yes_ask is None or no_ask is None:
            return None
        if not (0.0 < yes_ask < 1.0 and 0.0 < no_ask < 1.0):
            return None

        if yes_sz is not None and yes_sz < self.min_level_size:
            return None
        if no_sz is not None and no_sz < self.min_level_size:
            return None

        total_cost = yes_ask + no_ask
        edge = 1.0 - total_cost

        if edge >= self.min_edge:
            return ArbSignal(yes_ask=yes_ask, no_ask=no_ask, total_cost=total_cost, edge=edge)
        return None

    def _should_alert(self) -> bool:
        now = time.time()
        if now - self._last_alert_ts >= self.cooldown_seconds:
            self._last_alert_ts = now
            return True
        return False

    def _emit_alert(self, signal: ArbSignal):
        edge_bps = signal.edge * 10_000
        msg = (
            f"{Colors.green('ARB!')} "
            f"YES_ask={Colors.yellow(f'{signal.yes_ask:.4f}')} + "
            f"NO_ask={Colors.yellow(f'{signal.no_ask:.4f}')} = "
            f"{Colors.cyan(f'{signal.total_cost:.4f}')} "
            f"→ edge={Colors.green(f'{signal.edge:.4f}')} ({edge_bps:.1f} bps)"
        )
        logger.info(msg)
        if self.bell:
            print("\a", end="")

    def execute_arb(self, signal: ArbSignal):
        yes_outcome = self.outcomes[0]
        no_outcome = self.outcomes[1]
        yes_token = self.token_ids[0]
        no_token = self.token_ids[1]

        yes_price = self.exchange.round_to_tick_size(signal.yes_ask, self.tick_size)
        no_price = self.exchange.round_to_tick_size(signal.no_ask, self.tick_size)

        yes_price = max(0.01, min(0.99, yes_price))
        no_price = max(0.01, min(0.99, no_price))

        size = self.order_size

        if not self.live_mode:
            logger.info(
                f"  (test) would BUY {size:.0f} {Colors.magenta(yes_outcome)} @ {Colors.yellow(f'{yes_price:.4f}')}"
            )
            logger.info(
                f"  (test) would BUY {size:.0f} {Colors.magenta(no_outcome)} @ {Colors.yellow(f'{no_price:.4f}')}"
            )
            return

        try:
            self.exchange.create_order(
                market_id=self.market.id,
                outcome=yes_outcome,
                side=OrderSide.BUY,
                price=yes_price,
                size=size,
                params={"token_id": yes_token},
            )
            logger.info(
                f"  {Colors.gray('→')} {Colors.green('BUY')} {size:.0f} "
                f"{Colors.magenta(yes_outcome)} @ {Colors.yellow(f'{yes_price:.4f}')}"
            )
        except Exception as e:
            logger.error(f"  YES leg failed: {e}")

        try:
            self.exchange.create_order(
                market_id=self.market.id,
                outcome=no_outcome,
                side=OrderSide.BUY,
                price=no_price,
                size=size,
                params={"token_id": no_token},
            )
            logger.info(
                f"  {Colors.gray('→')} {Colors.green('BUY')} {size:.0f} "
                f"{Colors.magenta(no_outcome)} @ {Colors.yellow(f'{no_price:.4f}')}"
            )
        except Exception as e:
            logger.error(f"  NO leg failed: {e}")

    def _has_all_data(self) -> bool:
        if self.orderbook_manager is None:
            return False
        if hasattr(self.orderbook_manager, "has_all_data"):
            return bool(self.orderbook_manager.has_all_data(self.token_ids))
        for tid in self.token_ids:
            ob = self.orderbook_manager.get(tid)
            if not ob or not ob.get("asks"):
                return False
        return True

    def run(self, duration_minutes: Optional[int] = None):
        logger.info(
            f"\n{Colors.bold('Binary Arb Alert:')} "
            f"min_edge={Colors.yellow(f'{self.min_edge:.4f}')} "
            f"| min_top_size={Colors.yellow(f'{self.min_level_size:.1f}')} "
            f"| size={Colors.yellow(f'{self.order_size:.0f}')} "
            f"| interval={Colors.gray(f'{self.check_interval}s')} "
            f"| cooldown={Colors.gray(f'{self.cooldown_seconds}s')}"
        )

        if not self.fetch_market():
            return

        self.setup_websocket()
        self.start_websocket()

        time.sleep(3)

        self.is_running = True
        start_time = time.time()
        end_time = start_time + (duration_minutes * 60) if duration_minutes else None

        try:
            while self.is_running:
                if end_time and time.time() >= end_time:
                    break

                if not self._has_all_data():
                    logger.warning("Missing orderbook data (one or both tokens).")
                    time.sleep(self.check_interval)
                    continue

                signal = self.detect_binary_underround()
                if signal and self._should_alert():
                    self._emit_alert(signal)
                    self.execute_arb(signal)
                else:
                    logger.info("No binary underround detected (YES+NO >= 1 or insufficient size).")

                time.sleep(self.check_interval)

        except KeyboardInterrupt:
            logger.info("\nStopping...")
        finally:
            self.is_running = False
            self.stop_websocket()
            logger.info("Binary arb alert stopped")


def _parse_args(argv: List[str]) -> Dict[str, Any]:
    """
    Minimal flag parser:
      --scan : scan markets and print candidates
      --auto : if used with --scan, auto-pick best candidate slug and start WS monitor
      --mode=live|test or --test : choose execution mode
    """
    flags = {"scan": False, "auto": False, "target": None, "mode": os.getenv("MODE", "live")}
    rest = []
    for a in argv[1:]:
        if a == "--scan":
            flags["scan"] = True
        elif a == "--auto":
            flags["auto"] = True
        elif a.startswith("--mode="):
            flags["mode"] = a.split("=", 1)[1]
        elif a == "--test":
            flags["mode"] = "test"
        else:
            rest.append(a)
    if rest:
        flags["target"] = rest[0]
    return flags


def main() -> int:
    load_dotenv()

    private_key = os.getenv("POLYMARKET_PRIVATE_KEY")
    funder = os.getenv("POLYMARKET_FUNDER")
    if not private_key or not funder:
        logger.error("Missing environment variables!")
        logger.error("Set POLYMARKET_PRIVATE_KEY and POLYMARKET_FUNDER in .env")
        return 1

    args = _parse_args(sys.argv)

    # NEW: scan mode
    if args["scan"]:
        logger.info("Scanning markets via py_clob_client (REST) to find binary underround candidates...")
        clob = ClobClient("https://clob.polymarket.com")

        candidates = scan_binary_underround_candidates(
            clob=clob,
            min_edge=0.002,
            max_markets=300,
            top_k=10,
            sleep_between=0.0,
        )

        if not candidates:
            logger.info("No candidates found in this scan window.")
            logger.info("Tip: increase max_markets, lower min_edge, or retry later.")
            return 0

        logger.info(f"Top {len(candidates)} candidates (REST top-of-book, verify with WS):")
        for c in candidates:
            bps = c.edge * 10_000
            slug_txt = c.slug or "(no slug in response)"
            logger.info(
                f"- edge={c.edge:.4f} ({bps:.1f} bps) | cost={c.total_cost:.4f} "
                f"| YES={c.yes_ask:.4f} NO={c.no_ask:.4f} | slug={slug_txt} | {c.question}"
            )

        if not args["auto"]:
            logger.info("\nRun monitor with a slug, e.g.:")
            logger.info("  uv run python examples/binary_arb_alert.py <slug_from_list>")
            return 0

        best = candidates[0]
        if not best.slug:
            logger.error("Auto mode requires a slug, but the best candidate has no slug field.")
            logger.error("Pick a candidate with a slug from the list and run manually.")
            return 1

        # fall through into monitoring using chosen slug
        market_slug = normalize_slug(best.slug)
        logger.info(f"\nAuto-selected best candidate slug={market_slug}")

    else:
        if not args["target"]:
            logger.error("No market slug provided!")
            logger.error("Usage: uv run python examples/binary_arb_alert.py MARKET_SLUG_OR_URL")
            logger.error("Or:    uv run python examples/binary_arb_alert.py --scan [--auto]")
            return 1
        market_slug = normalize_slug(args["target"])

    exchange = dr_manhattan.Polymarket({
        "private_key": private_key,
        "funder": funder,
        "cache_ttl": 2.0,
        "verbose": True,
    })

    bot = BinaryArbAlertStrategy(
        exchange=exchange,
        market_slug=market_slug,
        order_size=5.0,
        check_interval=5.0,
        min_edge=0.002,
        min_level_size=1.0,
        cooldown_seconds=10.0,
        tick_infer=True,
        bell=True,
        mode=args["mode"],
    )

    bot.run(duration_minutes=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
