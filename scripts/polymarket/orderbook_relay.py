#!/usr/bin/env python3
"""Run a local Polymarket orderbook websocket relay."""

from __future__ import annotations

import argparse
import asyncio
import signal

import websockets

from dr_manhattan.marketdata import PolymarketOrderbookRelay


async def main_async(args: argparse.Namespace) -> None:
    relay = PolymarketOrderbookRelay(
        verbose=args.verbose,
        refresh_on_client_subscribe=not args.no_refresh_on_client_subscribe,
        stats_interval_sec=args.stats_interval_sec,
    )
    await relay.start()
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signame in ("SIGINT", "SIGTERM"):
        loop.add_signal_handler(getattr(signal, signame), stop_event.set)

    async with websockets.serve(
        relay.handle_client,
        args.host,
        args.port,
        ping_interval=10,
        ping_timeout=5,
        close_timeout=2,
        max_size=10 * 1024 * 1024,
        compression=None,
    ):
        print(f"polymarket_relay_listening host={args.host} port={args.port}", flush=True)
        await stop_event.wait()
    await relay.stop()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Polymarket orderbook websocket relay")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--no-refresh-on-client-subscribe",
        action="store_true",
        help="Subscribe only newly requested assets instead of refreshing the upstream batch.",
    )
    parser.add_argument("--stats-interval-sec", type=float, default=30.0)
    return parser.parse_args()


def main() -> int:
    asyncio.run(main_async(parse_args()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
