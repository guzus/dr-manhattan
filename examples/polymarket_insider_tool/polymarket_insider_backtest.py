#!/usr/bin/env python3
"""Polymarket insider-flow tracker + backtester CLI."""

from __future__ import annotations

import argparse
import concurrent.futures
from dataclasses import asdict
from pathlib import Path

import pandas as pd

# Keep this script runnable directly (no `-m`) by importing sibling module.
from insider_flow import (
    BacktestConfig,
    InsiderFlowConfig,
    PolymarketInsiderTool,
)

from dr_manhattan import Polymarket


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Polymarket insider-flow detector and backtester")
    parser.add_argument(
        "--market",
        type=str,
        default=None,
        help="Condition ID, Gamma ID, market slug, or event slug (optional)",
    )
    parser.add_argument(
        "--tag-slug",
        type=str,
        default=None,
        help="Gamma tag slug (e.g., politics). If set (or --tag-id), scans markets by tag instead of a single market.",
    )
    parser.add_argument(
        "--tag-id",
        type=int,
        default=None,
        help="Gamma tag ID. If set (or --tag-slug), scans markets by tag instead of a single market.",
    )
    parser.add_argument(
        "--top-markets",
        type=int,
        default=50,
        help="How many top-volume markets to scan when using --tag-slug/--tag-id",
    )
    parser.add_argument(
        "--closed-only",
        action="store_true",
        help="Only include closed/expired markets when scanning a tag",
    )
    parser.add_argument(
        "--opened-within-years",
        type=int,
        default=None,
        help="Only include markets opened within the last N years (uses createdAt/startDate metadata)",
    )
    parser.add_argument(
        "--include-non-binary",
        action="store_true",
        help="Include non-binary (multi-outcome) markets when scanning a tag",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Concurrent workers when scanning a tag (trade fetch is IO-bound)",
    )
    parser.add_argument("--limit", type=int, default=2500, help="Number of trades to fetch")
    parser.add_argument("--offset", type=int, default=0, help="Trade pagination offset")
    parser.add_argument("--horizon-minutes", type=int, default=30, help="Wallet edge horizon")
    parser.add_argument("--lookback-trades", type=int, default=40, help="Flow lookback window")
    parser.add_argument("--signal-threshold", type=float, default=0.28, help="Signal threshold")
    parser.add_argument(
        "--cooldown-minutes", type=int, default=45, help="Min minutes between signals"
    )
    parser.add_argument(
        "--min-wallet-history", type=int, default=0, help="Min matured wallet trades"
    )
    parser.add_argument(
        "--min-trade-notional", type=float, default=150.0, help="Signal min notional"
    )

    parser.add_argument("--holding-minutes", type=int, default=60, help="Backtest holding time")
    parser.add_argument("--take-profit", type=float, default=0.10, help="Take profit ratio")
    parser.add_argument("--stop-loss", type=float, default=0.08, help="Stop loss ratio")
    parser.add_argument("--position-size", type=float, default=500.0, help="USD size per trade")
    parser.add_argument("--fee-bps", type=float, default=8.0, help="Per-side fee in bps")
    parser.add_argument("--slippage-bps", type=float, default=4.0, help="Per-side slippage in bps")
    parser.add_argument("--initial-capital", type=float, default=10000.0, help="Starting capital")
    parser.add_argument(
        "--long-only",
        action="store_true",
        help="Only take long signals (skip negative-direction signals)",
    )

    parser.add_argument(
        "--optimize",
        action="store_true",
        help="Run grid-search optimization and use best config",
    )
    parser.add_argument(
        "--train-ratio",
        type=float,
        default=0.70,
        help="Chronological train ratio for optimization",
    )
    parser.add_argument("--top-wallets", type=int, default=10, help="Top wallets to print")
    parser.add_argument(
        "--plot",
        action="store_true",
        help="Create visualization PNG (equity curve + signal charts)",
    )
    parser.add_argument(
        "--plot-path",
        type=Path,
        default=Path("insider_backtest.png"),
        help="Output file for plot when --plot is used",
    )
    parser.add_argument(
        "--plot-assets",
        type=int,
        default=2,
        help="Number of top-signaled assets to visualize",
    )
    parser.add_argument(
        "--plot-combined",
        action="store_true",
        help="Combine selected assets into one chart (indexed price) instead of one subplot per asset",
    )
    parser.add_argument(
        "--save-signals", type=Path, default=None, help="Optional CSV path for signals"
    )
    parser.add_argument(
        "--save-backtest-trades",
        type=Path,
        default=None,
        help="Optional CSV path for completed backtest trades",
    )
    parser.add_argument(
        "--save-market-summary",
        type=Path,
        default=None,
        help="Optional CSV path for per-market sweep results (tag scan only)",
    )
    return parser.parse_args()


def build_detector_config(args: argparse.Namespace) -> InsiderFlowConfig:
    return InsiderFlowConfig(
        horizon_minutes=args.horizon_minutes,
        lookback_trades=args.lookback_trades,
        signal_threshold=args.signal_threshold,
        cooldown_minutes=args.cooldown_minutes,
        min_wallet_history=args.min_wallet_history,
        min_trade_notional=args.min_trade_notional,
        long_only=args.long_only,
    )


def build_backtest_config(args: argparse.Namespace) -> BacktestConfig:
    return BacktestConfig(
        holding_minutes=args.holding_minutes,
        take_profit=args.take_profit,
        stop_loss=args.stop_loss,
        position_size=args.position_size,
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
        initial_capital=args.initial_capital,
        allow_short=not args.long_only,
    )


def print_backtest_summary(title: str, result) -> None:
    print(f"\n{title}")
    print(f"  Trades: {result.n_trades}")
    print(f"  Total PnL: ${result.total_pnl:,.2f}")
    print(f"  Ending Capital: ${result.ending_capital:,.2f}")
    print(f"  Return: {result.return_pct * 100:.2f}%")
    print(f"  Win Rate: {result.win_rate * 100:.1f}%")
    print(f"  Sharpe (trade-level): {result.sharpe:.2f}")
    print(f"  Max Drawdown: {result.max_drawdown * 100:.2f}%")
    print(f"  Profit Factor: {result.profit_factor:.2f}")


def _coerce_utc(value: object) -> pd.Timestamp | None:
    if value is None:
        return None
    try:
        ts = pd.to_datetime(value, utc=True, errors="coerce")
    except Exception:
        return None
    if ts is pd.NaT:
        return None
    if isinstance(ts, pd.DatetimeIndex):
        if len(ts) == 0:
            return None
        ts = ts[0]
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def main() -> None:
    args = parse_args()

    exchange = Polymarket({"timeout": 30})
    detector_config = build_detector_config(args)
    backtest_config = build_backtest_config(args)
    tool = PolymarketInsiderTool(detector_config)

    if args.market and (args.tag_slug or args.tag_id):
        raise SystemExit("Use either --market or --tag-slug/--tag-id (not both).")

    if not args.market and not (args.tag_slug or args.tag_id):
        raise SystemExit("Provide --market or --tag-slug/--tag-id.")

    if args.market:
        print("Fetching trades from Polymarket Data API...")
        trades = tool.fetch_trades(
            exchange,
            market=args.market,
            limit=args.limit,
            offset=args.offset,
        )
        if trades.empty:
            print("No trades found for the provided filters.")
            return
        print(f"Fetched {len(trades):,} trades across {trades['asset'].nunique()} assets.")
        markets_meta = None
    else:
        tag_id = args.tag_id
        if tag_id is None:
            tag = exchange.get_tag_by_slug(str(args.tag_slug).strip())
            tag_id = int(tag.id)

        now = pd.Timestamp.now(tz="UTC")
        opened_after = None
        if args.opened_within_years is not None:
            opened_after = now - pd.DateOffset(years=max(0, int(args.opened_within_years)))

        closed_param = True if args.closed_only else None
        scan_limit = max(200, int(args.top_markets) * 6)
        max_scan_limit = 5_000

        markets = []
        candidates = []
        while True:
            candidates = exchange.search_markets(
                limit=scan_limit,
                order="volume",
                ascending=False,
                closed=closed_param,
                tag_id=tag_id,
            )
            if not candidates:
                break

            markets = []
            seen_conditions = set()
            for m in candidates:
                if args.closed_only and bool(m.metadata.get("closed")) is not True:
                    continue
                if opened_after is not None:
                    meta = m.metadata
                    opened_ts = (
                        _coerce_utc(meta.get("createdAt"))
                        or _coerce_utc(meta.get("startDate"))
                        or _coerce_utc(meta.get("startDateIso"))
                    )
                    if opened_ts is None or opened_ts < opened_after:
                        continue
                if not args.include_non_binary and not m.is_binary:
                    continue
                condition_id = str(m.metadata.get("conditionId", "")).strip()
                if not condition_id:
                    continue
                if condition_id in seen_conditions:
                    continue
                seen_conditions.add(condition_id)
                markets.append(m)
                if len(markets) >= int(args.top_markets):
                    break

            # If we have enough markets, stop. Otherwise, try a deeper pull.
            if len(markets) >= int(args.top_markets):
                break
            if scan_limit >= max_scan_limit:
                break
            if len(candidates) < scan_limit:
                break
            scan_limit = min(max_scan_limit, int(scan_limit * 1.5))

        if not candidates:
            raise SystemExit("No markets returned for the provided tag filters.")

        if not markets:
            raise SystemExit("No markets matched filters after client-side screening.")

        print(
            f"Scanning {len(markets)} markets by tag (tag_id={tag_id}, closed_only={args.closed_only}, "
            f"binary_only={not args.include_non_binary}, opened_after={opened_after.date() if opened_after is not None else None})."
        )

        def _fetch_one(mkt):
            cid = str(mkt.metadata.get("conditionId", mkt.id))
            df = tool.fetch_trades(
                exchange,
                market=cid,
                limit=args.limit,
                offset=args.offset,
            )
            # Some Data-API responses omit slug/title for older markets; fill best-effort.
            if not df.empty:
                slug = str(mkt.metadata.get("slug", "")).strip()
                if slug:
                    df["slug"] = df["slug"].fillna(slug)
            return (mkt, df)

        frames = []
        markets_meta = []
        workers = max(1, int(args.workers))
        if workers == 1:
            for mkt in markets:
                mkt, df = _fetch_one(mkt)
                if not df.empty:
                    frames.append(df)
                markets_meta.append(mkt)
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
                futures = [ex.submit(_fetch_one, mkt) for mkt in markets]
                for fut in concurrent.futures.as_completed(futures):
                    mkt, df = fut.result()
                    if not df.empty:
                        frames.append(df)
                    markets_meta.append(mkt)

        trades = (
            pd.concat(frames, ignore_index=True).sort_values("timestamp").reset_index(drop=True)
            if frames
            else pd.DataFrame()
        )
        if trades.empty:
            raise SystemExit("No trades found across scanned markets (try higher --limit).")

        print(
            f"Fetched {len(trades):,} trades across {trades['asset'].nunique()} assets "
            f"({trades['condition_id'].nunique()} condition_ids)."
        )

    if args.optimize:
        print("Running parameter optimization...")
        optimization = tool.optimize_strategy(
            trades,
            train_ratio=args.train_ratio,
            backtest_config=backtest_config,
        )
        best_cfg = optimization.best_config
        print("Best detector config:")
        print(asdict(best_cfg))
        print_backtest_summary("Train Backtest", optimization.best_train)
        print_backtest_summary("Test Backtest", optimization.best_test)

        detector_config = best_cfg
        tool = PolymarketInsiderTool(best_cfg)

    # Engineer features once so signals/backtests/plots are consistent and deterministic.
    features = tool.engineer_features(trades, detector_config)
    signals = tool.detect_signals(features, detector_config)
    result = tool.backtest(
        features,
        signals=signals,
        detector_config=detector_config,
        backtest_config=backtest_config,
    )

    wallets = tool.rank_wallets(features, top_n=args.top_wallets, config=detector_config)

    print(f"\nDetected insider signals: {len(signals)}")
    print_backtest_summary("Full Backtest", result)

    if not wallets.empty:
        print("\nTop wallets by insider rank:")
        display_cols = [
            "wallet",
            "trades",
            "recent_skill",
            "realized_edge",
            "realized_win_rate",
            "total_notional",
            "insider_rank_score",
        ]
        print(wallets[display_cols].to_string(index=False, float_format=lambda v: f"{v:,.4f}"))
    else:
        print("\nNo wallets met minimum history constraints.")

    if args.save_signals:
        signals_df = pd.DataFrame([asdict(signal) for signal in signals])
        signals_df.to_csv(args.save_signals, index=False)
        print(f"\nSaved signals to {args.save_signals}")

    if args.save_backtest_trades:
        bt_df = pd.DataFrame([asdict(trade) for trade in result.trades])
        bt_df.to_csv(args.save_backtest_trades, index=False)
        print(f"Saved backtest trades to {args.save_backtest_trades}")

    if args.save_market_summary and markets_meta is not None:
        # Compute per-market results using the (global) wallet-skill features we already engineered.
        market_rows = []
        signals_by_condition: dict[str, list] = {}
        for s in signals:
            signals_by_condition.setdefault(str(s.condition_id), []).append(s)

        for mkt in markets_meta:
            cid = str(mkt.metadata.get("conditionId", "")).strip()
            if not cid:
                continue
            subset = features[features["condition_id"].astype(str) == cid].copy()
            if subset.empty:
                continue
            m_signals = signals_by_condition.get(cid, [])
            m_result = tool.backtest(
                subset,
                signals=m_signals,
                detector_config=detector_config,
                backtest_config=backtest_config,
            )
            market_rows.append(
                {
                    "slug": str(mkt.metadata.get("slug", "")),
                    "condition_id": cid,
                    "volume": float(getattr(mkt, "volume", 0.0) or 0.0),
                    "question": str(getattr(mkt, "question", "")),
                    "trades_fetched": int(len(subset)),
                    "assets": int(subset["asset"].nunique()),
                    "signals": int(len(m_signals)),
                    "bt_trades": int(m_result.n_trades),
                    "pnl": float(m_result.total_pnl),
                    "return_pct": float(m_result.return_pct),
                    "win_rate": float(m_result.win_rate),
                    "max_drawdown": float(m_result.max_drawdown),
                    "profit_factor": float(m_result.profit_factor),
                }
            )

        if market_rows:
            summary = (
                pd.DataFrame(market_rows)
                .sort_values(["pnl", "signals"], ascending=[False, False])
                .reset_index(drop=True)
            )
            summary.to_csv(args.save_market_summary, index=False)
            print(f"Saved per-market summary to {args.save_market_summary}")

    if args.plot:
        tool.plot_insider_backtest(
            features,
            signals=signals,
            result=result,
            detector_config=detector_config,
            backtest_config=backtest_config,
            output_path=args.plot_path,
            top_assets=args.plot_assets,
            combine_assets=args.plot_combined,
        )
        print(f"Saved plot to {args.plot_path}")


if __name__ == "__main__":
    main()
