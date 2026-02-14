import asyncio
import json
import logging
import os
import threading
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, Dict, List, Set, Tuple

import boto3
import pyarrow as pa
import pyarrow.parquet as pq
import websockets
from dateutil import parser as date_parser
from models import (
    EVENT_BOOK,
    EVENT_LAST_TRADE_PRICE,
    EVENT_PRICE_CHANGE,
    EVENT_TICK_SIZE_CHANGE,
    EVENT_TYPES,
    AssetMeta,
    MarketConfig,
    SharedState,
)

from dr_manhattan.exchanges.polymarket import Polymarket

# ========== LOGGING CONFIG ==========

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ========== CONFIG ==========

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
S3_BUCKET = os.getenv("S3_BUCKET")
POLL_INTERVAL_SEC = 60 * 3
WS_PING_INTERVAL_SEC = 20
WS_RECONNECT_DELAY_SEC = 3
WS_NO_ASSETS_SLEEP_SEC = 15


# ========== MARKET CONFIG ==========

MARKET_CONFIG: List[MarketConfig] = [
    # ===== BTC =====
    MarketConfig(
        name="btc_1h",
        slug="1H",
        keywords=["bitcoin", "up or down"],
        rule="current_and_previous",
        window_minutes=60 * 2,
        prefix="crypto/BTC/freq=1H",
    ),
    MarketConfig(
        name="btc_1d",
        slug="today",
        keywords=["bitcoin", "up or down"],
        rule="current_and_previous",
        window_minutes=60 * 24 * 2,
        prefix="crypto/BTC/freq=1D",
    ),
    # ===== ETH =====
    MarketConfig(
        name="eth_1h",
        slug="1H",
        keywords=["ethereum", "up or down"],
        rule="current_and_previous",
        window_minutes=60 * 2,
        prefix="crypto/ETH/freq=1H",
    ),
    MarketConfig(
        name="eth_1d",
        slug="today",
        keywords=["ethereum", "up or down"],
        rule="current_and_previous",
        window_minutes=60 * 24 * 2,
        prefix="crypto/ETH/freq=1D",
    ),
    # ===== SOL =====
    MarketConfig(
        name="sol_1h",
        slug="1H",
        keywords=["solana", "up or down"],
        rule="current_and_previous",
        window_minutes=60 * 2,
        prefix="crypto/SOL/freq=1H",
    ),
    MarketConfig(
        name="sol_1d",
        slug="today",
        keywords=["solana", "up or down"],
        rule="current_and_previous",
        window_minutes=60 * 24 * 2,
        prefix="crypto/SOL/freq=1D",
    ),
    # ===== XRP =====
    MarketConfig(
        name="xrp_1h",
        slug="1H",
        keywords=["xrp", "up or down"],
        rule="current_and_previous",
        window_minutes=60 * 2,
        prefix="crypto/XRP/freq=1H",
    ),
    MarketConfig(
        name="xrp_1d",
        slug="today",
        keywords=["xrp", "up or down"],
        rule="current_and_previous",
        window_minutes=60 * 24 * 2,
        prefix="crypto/XRP/freq=1D",
    ),
    # ===== EPL =====
    MarketConfig(
        name="tottenham_epl_win",
        slug="EPL",
        keywords=["will", "win on", "tottenham"],
        rule="current_and_previous",
        window_minutes=60 * 24 * 2,
        prefix="sports/EPL/team=tottenham",
    ),
    MarketConfig(
        name="manchester_united_epl_win",
        slug="EPL",
        keywords=["will", "win on", "manchester united"],
        rule="current_and_previous",
        window_minutes=60 * 24 * 2,
        prefix="sports/EPL/team=manchester_united",
    ),
]


# ========== TIME FORMATTER ==========


def normalize_close_time(raw: Any) -> str:
    if raw is None:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    if isinstance(raw, str):
        try:
            dt = date_parser.parse(raw)
        except Exception:
            # Return original string if parsing fails
            return raw
    else:
        if isinstance(raw, datetime):
            dt = raw
        elif isinstance(raw, (int, float)):
            # Assume epoch timestamp
            dt = datetime.fromtimestamp(float(raw), tz=timezone.utc)
        else:
            # For other types, try once more by casting to string
            try:
                dt = date_parser.parse(str(raw))
            except Exception:
                return str(raw)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ========== METADATA HELPERS ==========


def parse_json_list_string(value: str) -> List[str]:
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [str(x) for x in parsed]
        return [str(parsed)]
    except Exception:
        parts = [p.strip() for p in value.split(",")]
        return [p for p in parts if p]


def get_clob_ids_from_metadata(metadata: Dict[str, Any]) -> List[str]:
    raw = metadata.get("clobTokenIds", "")
    if isinstance(raw, str):
        clob_ids = parse_json_list_string(raw)
    elif isinstance(raw, (list, tuple)):
        clob_ids = [str(x) for x in raw]
    else:
        clob_ids = []
    return clob_ids


def get_outcomes_from_metadata(market: Any, metadata: Dict[str, Any]) -> List[str]:
    raw = metadata.get("outcomes") or getattr(market, "outcomes", None)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                outcomes = [str(x) for x in parsed]
            else:
                outcomes = [str(parsed)]
        except Exception:
            outcomes = [raw]
    elif isinstance(raw, (list, tuple)):
        outcomes = [str(x) for x in raw]
    else:
        outcomes = ["Up", "Down"]
    if not outcomes:
        outcomes = ["Up", "Down"]
    return outcomes


def is_market_in_window(close_time_str: str, window_minutes: int, now: datetime) -> bool:
    """
    In Polymarket EPL etc., close_time may be the game start time,
    so we only check whether 'current time is after close_time - window'.
    We don't set an upper bound (now <= close_dt).
    Actual termination status is handled by the API's closed=False filter.
    """
    try:
        close_dt = date_parser.parse(close_time_str)
    except Exception:
        logger.warning("failed to parse close_time: %s", close_time_str)
        return False

    if close_dt.tzinfo is None:
        close_dt = close_dt.replace(tzinfo=timezone.utc)
    else:
        close_dt = close_dt.astimezone(timezone.utc)

    window = timedelta(minutes=window_minutes)
    start_dt = close_dt - window

    return start_dt <= now


# ========== MARKET FETCH ==========


def get_open_market(exchange, slug: str, keywords: List[str]):
    tag = exchange.get_tag_by_slug(slug)
    if not tag:
        logger.debug("[poll] no tag found for slug=%s", slug)
        return []
    markets = exchange.search_markets(
        limit=1000,
        tag_id=tag.id,
        closed=False,
        keywords=keywords,
        log=False,
    )
    return markets


# ========== PARQUET + S3 SINK ==========


class ParquetSink:
    def __init__(self, s3_bucket: str | None = S3_BUCKET, flush_every_rows: int = 1000):
        self.s3_bucket = s3_bucket
        self.s3_client = boto3.client("s3") if s3_bucket else None
        self.flush_every_rows = flush_every_rows

        self._locks: Dict[str, threading.Lock] = {}
        self._writers: Dict[str, pq.ParquetWriter] = {}
        self._schemas: Dict[str, pa.Schema] = {}
        self._buffers: Dict[str, List[dict]] = {}

    def _get_lock(self, path: str) -> threading.Lock:
        return self._locks.setdefault(path, threading.Lock())

    def _tmp_path(self, meta: AssetMeta, event_type: str) -> str:
        sanitized_prefix = meta.prefix.replace("/", "_")
        safe_close = meta.close_time_str.replace(":", "-")
        filename = (
            f"{sanitized_prefix}_{meta.freq}_{safe_close}_{meta.outcome}_{event_type}.parquet"
        )
        return os.path.join("/tmp", filename)

    def _s3_key(self, meta: AssetMeta, event_type: str) -> str:
        dt = date_parser.parse(meta.close_time_str)
        year = dt.strftime("%Y")
        month = dt.strftime("%m")
        day = dt.strftime("%d")
        return "/".join(
            [
                meta.prefix,
                f"year={year}",
                f"month={month}",
                f"day={day}",
                meta.close_time_str,
                meta.outcome,
                f"{event_type}.parquet",
            ]
        )

    def _open_writer_if_needed(self, path: str, first_row: Dict[str, Any]):
        if path in self._writers:
            return
        table = pa.Table.from_pylist([first_row])
        schema = table.schema
        writer = pq.ParquetWriter(path, schema, compression="snappy")
        self._writers[path] = writer
        self._schemas[path] = schema
        self._buffers[path] = []
        logger.debug("[parquet] writer opened %s", path)

    def _flush_unlocked(self, path: str):
        buf = self._buffers.get(path)
        writer = self._writers.get(path)
        schema = self._schemas.get(path)
        if not buf or not writer:
            return
        table = pa.Table.from_pylist(buf, schema=schema)
        writer.write_table(table)
        buf.clear()

    def write_event(self, meta: AssetMeta, event_type: str, row: Dict[str, Any]):
        path = self._tmp_path(meta, event_type)
        lock = self._get_lock(path)
        with lock:
            self._open_writer_if_needed(path, row)
            buf = self._buffers[path]
            buf.append(row)
            if len(buf) >= self.flush_every_rows:
                self._flush_unlocked(path)

    def batch_write(self, items: List[Tuple[AssetMeta, str, Dict[str, Any]]]):
        """Write a batch of (meta, event_type, row) tuples."""
        for meta, event_type, row in items:
            self.write_event(meta, event_type, row)

    def flush_all(self):
        """Fix #6: Flush all open writer buffers."""
        for path in list(self._writers.keys()):
            lock = self._get_lock(path)
            with lock:
                self._flush_unlocked(path)

    def finalize_asset(self, meta: AssetMeta):
        for event_type in EVENT_TYPES:
            path = self._tmp_path(meta, event_type)

            if path not in self._writers and not os.path.exists(path):
                continue

            lock = self._get_lock(path)
            with lock:
                writer = self._writers.pop(path, None)
                schema = self._schemas.pop(path, None)
                buf = self._buffers.pop(path, None)

                if writer:
                    if buf and schema:
                        table = pa.Table.from_pylist(buf, schema=schema)
                        writer.write_table(table)
                    writer.close()

            # Fix #2: Remove lock entry after finalize
            self._locks.pop(path, None)

            if not os.path.exists(path):
                continue

            if self.s3_client and self.s3_bucket:
                key = self._s3_key(meta, event_type)
                for attempt in range(5):
                    try:
                        self.s3_client.upload_file(path, self.s3_bucket, key)
                        logger.info("[s3] uploaded -> %s/%s", self.s3_bucket, key)
                        os.remove(path)
                        break
                    except Exception as e:
                        wait = min(2**attempt, 30)
                        logger.warning(
                            "[s3] upload failed attempt %d: %s; retry in %ds",
                            attempt + 1,
                            e,
                            wait,
                        )
                        time.sleep(wait)
                else:
                    logger.error("[s3] giving up for %s (kept locally)", path)
            else:
                try:
                    os.remove(path)
                except FileNotFoundError:
                    pass

    def cleanup_stale_locks(self):
        """Fix #2: Remove lock entries for paths that no longer have writers."""
        stale = [p for p in self._locks if p not in self._writers]
        for p in stale:
            del self._locks[p]
        if stale:
            logger.debug("[parquet] cleaned %d stale locks", len(stale))


parquet_sink = ParquetSink()


# ========== WRITE QUEUE (Fix #3) ==========


write_queue: asyncio.Queue[Tuple[AssetMeta, str, Dict[str, Any]]] = asyncio.Queue()


async def writer_loop():
    """Single writer loop: drains queue in batches, writes via single thread."""
    while True:
        batch: List[Tuple[AssetMeta, str, Dict[str, Any]]] = []
        # Block until at least one item
        item = await write_queue.get()
        batch.append(item)
        # Drain up to 100 more without blocking
        for _ in range(100):
            try:
                batch.append(write_queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        await asyncio.to_thread(parquet_sink.batch_write, batch)


# ========== PERIODIC MAINTENANCE LOOPS ==========


async def dedup_cleanup_loop(state: SharedState):
    """Fix #1: Periodically clean expired TTL dedup entries."""
    while True:
        await asyncio.sleep(60)
        async with state.lock:
            for dedup in state.seen_event_hashes.values():
                dedup.cleanup()


async def flush_loop():
    """Fix #6: Periodically flush all open parquet writer buffers."""
    while True:
        await asyncio.sleep(60)
        await asyncio.to_thread(parquet_sink.flush_all)


async def lock_cleanup_loop():
    """Fix #2: Periodically clean stale lock entries."""
    while True:
        await asyncio.sleep(300)
        await asyncio.to_thread(parquet_sink.cleanup_stale_locks)


# ========== WS MESSAGE HANDLERS ==========


async def handle_book(msg: dict, state: SharedState):
    asset_id = msg.get("asset_id")
    if not asset_id:
        return
    event_hash = msg.get("hash")

    async with state.lock:
        meta = state.asset_meta.get(asset_id)
        if not meta:
            return
        if event_hash and not state.mark_event_seen(EVENT_BOOK, asset_id, event_hash):
            return

    row = {
        "asset_id": asset_id,
        "market": msg.get("market"),
        "timestamp_ms": int(msg.get("timestamp", "0")),
        "hash": event_hash,
        "bids": json.dumps(msg.get("bids", msg.get("buys", []))),
        "asks": json.dumps(msg.get("asks", msg.get("sells", []))),
    }
    await write_queue.put((meta, EVENT_BOOK, row))


async def handle_price_change(msg: dict, state: SharedState):
    ts = int(msg.get("timestamp", "0"))
    market = msg.get("market")
    price_changes = msg.get("price_changes", [])
    rows_by_asset: Dict[str, List[dict]] = {}

    for pc in price_changes:
        asset_id = pc.get("asset_id")
        if not asset_id:
            continue
        row = {
            "asset_id": asset_id,
            "market": market,
            "timestamp_ms": ts,
            "price": pc.get("price"),
            "size": pc.get("size"),
            "side": pc.get("side"),
            "hash": pc.get("hash"),
            "best_bid": pc.get("best_bid"),
            "best_ask": pc.get("best_ask"),
        }
        rows_by_asset.setdefault(asset_id, []).append(row)

    async with state.lock:
        meta_map = dict(state.asset_meta)

        for asset_id, rows in list(rows_by_asset.items()):
            meta = meta_map.get(asset_id)
            if not meta:
                del rows_by_asset[asset_id]
                continue

            filtered = []
            for row in rows:
                event_hash = row.get("hash")
                if event_hash and not state.mark_event_seen(
                    EVENT_PRICE_CHANGE, asset_id, event_hash
                ):
                    continue
                filtered.append(row)

            if not filtered:
                del rows_by_asset[asset_id]
            else:
                rows_by_asset[asset_id] = filtered

    for asset_id, rows in rows_by_asset.items():
        meta = meta_map.get(asset_id)
        if not meta:
            continue
        for row in rows:
            await write_queue.put((meta, EVENT_PRICE_CHANGE, row))


async def handle_tick_size_change(msg: dict, state: SharedState):
    asset_id = msg.get("asset_id")
    if not asset_id:
        return

    event_hash = msg.get("hash")

    async with state.lock:
        meta = state.asset_meta.get(asset_id)
        if not meta:
            return
        if event_hash and not state.mark_event_seen(EVENT_TICK_SIZE_CHANGE, asset_id, event_hash):
            return

    row = {
        "asset_id": asset_id,
        "market": msg.get("market"),
        "timestamp_ms": int(msg.get("timestamp", "0")),
        "old_tick_size": msg.get("old_tick_size"),
        "new_tick_size": msg.get("new_tick_size"),
        "hash": event_hash,
    }
    await write_queue.put((meta, EVENT_TICK_SIZE_CHANGE, row))


async def handle_last_trade_price(msg: dict, state: SharedState):
    asset_id = msg.get("asset_id")
    if not asset_id:
        return

    event_hash = msg.get("hash")

    async with state.lock:
        meta = state.asset_meta.get(asset_id)
        if not meta:
            return
        if event_hash and not state.mark_event_seen(EVENT_LAST_TRADE_PRICE, asset_id, event_hash):
            return

    row = {
        "asset_id": asset_id,
        "market": msg.get("market"),
        "timestamp_ms": int(msg.get("timestamp", "0")),
        "price": msg.get("price"),
        "size": msg.get("size"),
        "side": msg.get("side"),
        "fee_rate_bps": msg.get("fee_rate_bps"),
        "hash": event_hash,
    }
    await write_queue.put((meta, EVENT_LAST_TRADE_PRICE, row))


async def dispatch_message(msg: dict, state: SharedState):
    event_type = msg.get("event_type")
    if event_type == EVENT_BOOK:
        await handle_book(msg, state)
    elif event_type == EVENT_PRICE_CHANGE:
        await handle_price_change(msg, state)
    elif event_type == EVENT_TICK_SIZE_CHANGE:
        await handle_tick_size_change(msg, state)
    elif event_type == EVENT_LAST_TRADE_PRICE:
        await handle_last_trade_price(msg, state)


async def dispatch_raw(raw: str, state: SharedState):
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        return

    if isinstance(msg, list):
        for item in msg:
            if isinstance(item, dict):
                await dispatch_message(item, state)
        return

    if isinstance(msg, dict):
        await dispatch_message(msg, state)


# ========== MARKET POLL LOOP ==========


async def poll_markets_loop(state: SharedState):
    exchange = Polymarket()
    while True:
        try:
            now = datetime.now(UTC)

            # Fix #5: Group configs by slug to avoid duplicate API calls
            slug_groups: Dict[str, List[MarketConfig]] = defaultdict(list)
            for cfg in MARKET_CONFIG:
                slug_groups[cfg.slug].append(cfg)

            # One API call per slug, collecting common keywords
            slug_markets: Dict[str, List[Any]] = {}
            for slug, cfgs in slug_groups.items():
                common_keywords = set.intersection(*(set(cfg.keywords) for cfg in cfgs))
                markets = await asyncio.to_thread(
                    get_open_market,
                    exchange,
                    slug,
                    list(common_keywords),
                )
                slug_markets[slug] = list(markets)

            new_asset_meta: Dict[str, AssetMeta] = {}
            new_asset_ids: Set[str] = set()

            for slug, cfgs in slug_groups.items():
                all_markets = slug_markets.get(slug, [])
                for cfg in cfgs:
                    # Filter markets for this specific config's keywords
                    keyword_lowers = [k.lower() for k in cfg.keywords]
                    matched_markets = []
                    for m in all_markets:
                        question = (getattr(m, "question", "") or "").lower()
                        metadata = getattr(m, "metadata", {}) or {}
                        search_text = (
                            question + " " + (metadata.get("description", "") or "").lower()
                        )
                        if all(kw in search_text for kw in keyword_lowers):
                            matched_markets.append(m)

                    rule = cfg.rule
                    window_minutes = cfg.window_minutes
                    prefix = cfg.prefix
                    freq = cfg.freq or cfg.slug

                    for m in matched_markets:
                        question = getattr(m, "question", "")
                        market_id = getattr(m, "condition_id", None) or getattr(m, "id", "")
                        metadata = getattr(m, "metadata", {}) or {}
                        close_time_raw = metadata.get("endDate")
                        close_time_str = normalize_close_time(close_time_raw)

                        if rule == "current_and_previous" and window_minutes:
                            if not is_market_in_window(close_time_str, window_minutes, now):
                                continue

                        clob_ids = get_clob_ids_from_metadata(metadata)
                        outcomes = get_outcomes_from_metadata(m, metadata)

                        for idx, asset_id in enumerate(clob_ids):
                            if idx < len(outcomes):
                                outcome_name = outcomes[idx]
                            else:
                                outcome_name = "Up" if idx == 0 else "Down"

                            meta = AssetMeta(
                                asset_id=str(asset_id),
                                market_id=str(market_id),
                                question=str(question),
                                close_time_str=close_time_str,
                                outcome=str(outcome_name),
                                freq=str(freq),
                                prefix=str(prefix),
                            )
                            new_asset_meta[meta.asset_id] = meta
                            new_asset_ids.add(meta.asset_id)

            removed_metas: List[AssetMeta] = []

            async with state.lock:
                old_asset_ids = state.desired_asset_ids
                old_asset_meta = state.asset_meta
                if new_asset_ids != old_asset_ids:
                    added_ids = new_asset_ids - old_asset_ids
                    removed_ids = old_asset_ids - new_asset_ids

                    for aid in added_ids:
                        meta = new_asset_meta.get(aid)
                        if meta:
                            logger.info(
                                "[poll] NEW subscribed: %s | %s",
                                meta.question,
                                meta.outcome,
                            )

                    for aid in removed_ids:
                        meta = old_asset_meta.get(aid)
                        if meta:
                            logger.info(
                                "[poll] unsubscribed: %s | %s",
                                meta.question,
                                meta.outcome,
                            )
                            removed_metas.append(meta)

                    state.desired_asset_ids = new_asset_ids
                    state.asset_meta = new_asset_meta
                    # Fix #4: Signal via event instead of bool flag
                    state.resubscribe_event.set()
                    logger.info("[poll] updated markets; %d assets", len(new_asset_ids))

            for meta in removed_metas:
                await asyncio.to_thread(parquet_sink.finalize_asset, meta)

        except Exception:
            logger.exception("[poll] error while fetching markets")

        await asyncio.sleep(POLL_INTERVAL_SEC)


# ========== WEBSOCKET WORKER ==========


class WebSocketWorker:
    def __init__(self, state: SharedState, asset_ids: List[str], generation: int):
        self.state = state
        self.asset_ids = asset_ids
        self.generation = generation
        self.ws: websockets.WebSocketClientProtocol | None = None
        self.ready = asyncio.Event()
        self.running = True

    async def run(self):
        try:
            async with websockets.connect(
                WS_URL,
                ping_interval=None,
                ping_timeout=None,
            ) as ws:
                self.ws = ws
                logger.info(
                    "[ws] connecting gen=%s (%d assets)",
                    self.generation,
                    len(self.asset_ids),
                )

                # (Keep existing field name as requested)
                sub_msg = {
                    "type": "MARKET",
                    "assets_ids": self.asset_ids,
                }
                await ws.send(json.dumps(sub_msg))
                self.ready.set()

                async def ping_loop():
                    try:
                        while self.running:
                            await ws.send("PING")
                            await asyncio.sleep(WS_PING_INTERVAL_SEC)
                    except Exception:
                        logger.warning("[ws] ping_loop gen=%s error", self.generation)

                ping_task = asyncio.create_task(ping_loop())

                try:
                    async for raw in ws:
                        if not self.running:
                            break
                        await dispatch_raw(raw, self.state)
                finally:
                    ping_task.cancel()

        except Exception:
            logger.exception("[ws] worker gen=%s error", self.generation)
            if not self.ready.is_set():
                self.ready.set()
        finally:
            self.running = False

    async def stop(self):
        self.running = False
        if self.ws is not None:
            try:
                await self.ws.close()
            except Exception:
                pass


# ========== WS MANAGER ==========


async def manage_ws_connections(state: SharedState):
    worker: WebSocketWorker | None = None
    worker_task: asyncio.Task | None = None
    generation = 0

    while True:
        async with state.lock:
            asset_ids = list(state.desired_asset_ids)
            state.subscribed_asset_ids = set(asset_ids)
            state.resubscribe_event.clear()

        if not asset_ids:
            logger.info("[ws] no assets to subscribe, waiting...")
            await asyncio.sleep(WS_NO_ASSETS_SLEEP_SEC)
            continue

        generation += 1
        logger.info("[ws] starting worker gen=%s (%d assets)", generation, len(asset_ids))

        new_worker = WebSocketWorker(state, asset_ids, generation)
        new_task = asyncio.create_task(new_worker.run())

        await new_worker.ready.wait()
        if not new_worker.running and new_task.done():
            logger.warning("[ws] worker gen=%s failed during startup", generation)
            await asyncio.sleep(WS_RECONNECT_DELAY_SEC)
            continue

        logger.info("[ws] worker gen=%s READY", generation)

        if worker is not None:
            logger.info("[ws] stopping old worker gen=%s", worker.generation)
            await worker.stop()
            if worker_task is not None:
                try:
                    await asyncio.wait_for(worker_task, timeout=5)
                except asyncio.TimeoutError:
                    logger.warning("[ws] old worker gen=%s timeout", worker.generation)

        worker = new_worker
        worker_task = new_task

        # Fix #4: Wait on event instead of polling every 1 second
        while True:
            try:
                await asyncio.wait_for(state.resubscribe_event.wait(), timeout=5.0)
                # Event was set -> need to resubscribe
                logger.info("[ws] subscription change detected → rolling worker")
                break
            except asyncio.TimeoutError:
                # No signal, just check worker health
                if not worker.running or worker_task.done():
                    logger.warning("[ws] worker gen=%s stopped; restarting", worker.generation)
                    await asyncio.sleep(WS_RECONNECT_DELAY_SEC)
                    break


# ========== MAIN ==========


async def main():
    state = SharedState()
    tasks = [
        asyncio.create_task(poll_markets_loop(state)),
        asyncio.create_task(manage_ws_connections(state)),
        asyncio.create_task(writer_loop()),  # Fix #3
        asyncio.create_task(dedup_cleanup_loop(state)),  # Fix #1
        asyncio.create_task(flush_loop()),  # Fix #6
        asyncio.create_task(lock_cleanup_loop()),  # Fix #2
    ]
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
