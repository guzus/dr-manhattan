#!/usr/bin/env python3
"""Polymarket informed-trader-flow tracker + backtester CLI."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

# Keep this script runnable directly (no `-m`) by importing sibling module.
from informed_trader_flow import (
    BacktestConfig,
    InformedTraderFlowConfig,
    PolymarketInformedTraderTool,
)

from dr_manhattan import Polymarket


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Polymarket informed-trader-flow detector and backtester"
    )
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
    parser.add_argument(
        "--fresh-wallet-window-hours",
        type=float,
        default=24.0,
        help=(
            "Heuristic fresh-wallet window in hours (based on first trade seen in the "
            "fetched dataset). Set negative to disable."
        ),
    )
    parser.add_argument(
        "--fresh-wallet-max-trades",
        type=int,
        default=3,
        help="Max trades in-sample for a wallet to be flagged as fresh.",
    )

    parser.add_argument("--holding-minutes", type=int, default=60, help="Backtest holding time")
    parser.add_argument("--take-profit", type=float, default=0.10, help="Take profit ratio")
    parser.add_argument("--stop-loss", type=float, default=0.08, help="Stop loss ratio")
    parser.add_argument("--position-size", type=float, default=500.0, help="USD size per trade")
    parser.add_argument("--fee-bps", type=float, default=0.0, help="Per-side fee in bps")
    parser.add_argument("--slippage-bps", type=float, default=50.0, help="Per-side slippage in bps")
    parser.add_argument("--initial-capital", type=float, default=10000.0, help="Starting capital")
    parser.add_argument(
        "--hold-to-expiry",
        action="store_true",
        help="Hold each position until market expiry and settle at payout (0/1). Requires resolved markets.",
    )
    parser.add_argument(
        "--sweep-exits",
        type=str,
        default=None,
        help=(
            "Optional exit-mode sweep. Comma-separated list of holding minutes plus optional token "
            "'expiry' (e.g. '60,240,expiry'). Runs multiple backtests on the same fetched trades "
            "and prints/saves a comparison table."
        ),
    )
    parser.add_argument(
        "--sweep-no-tp-sl",
        action="store_true",
        help="When using --sweep-exits, disable take-profit/stop-loss so exits are purely time-based.",
    )
    parser.add_argument(
        "--sweep-save",
        type=Path,
        default=None,
        help="Optional CSV path to save --sweep-exits results.",
    )
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
        default=Path("informed_trader_backtest.png"),
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


def build_detector_config(args: argparse.Namespace) -> InformedTraderFlowConfig:
    return InformedTraderFlowConfig(
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
        hold_to_expiry=bool(args.hold_to_expiry),
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


def _infer_settlement(market) -> tuple[str, dict]:
    """Infer expiry time and winner outcome from a Polymarket Gamma Market object."""
    meta = getattr(market, "metadata", {}) or {}
    condition_id = str(meta.get("conditionId", getattr(market, "id", ""))).strip()

    expiry_time = (
        _coerce_utc(meta.get("closedTime"))
        or _coerce_utc(meta.get("endDate"))
        or _coerce_utc(meta.get("endDateIso"))
        or _coerce_utc(getattr(market, "close_time", None))
    )

    outcomes = meta.get("outcomes") or getattr(market, "outcomes", None) or []
    prices_raw = meta.get("outcomePrices")
    prices_list = None
    if isinstance(prices_raw, str):
        try:
            prices_list = json.loads(prices_raw)
        except Exception:
            prices_list = None
    elif isinstance(prices_raw, list):
        prices_list = prices_raw

    winner = None
    if outcomes and prices_list and len(outcomes) == len(prices_list):
        try:
            floats = [float(p) for p in prices_list]
            max_idx = int(max(range(len(floats)), key=lambda i: floats[i]))
            max_val = floats[max_idx]
            others = [floats[i] for i in range(len(floats)) if i != max_idx]
            if max_val >= 0.999 and all(v <= 0.001 for v in others):
                winner = str(outcomes[max_idx])
        except Exception:
            winner = None

    if winner is None:
        prices = getattr(market, "prices", {}) or {}
        if prices:
            best_outcome, best_price = max(prices.items(), key=lambda kv: float(kv[1] or 0))
            try:
                if float(best_price) >= 0.999:
                    winner = str(best_outcome)
            except Exception:
                pass

    return condition_id, {"expiry_time": expiry_time, "winner_outcome": winner}


def main() -> None:
    args = parse_args()

    exchange = Polymarket({"timeout": 30})
    detector_config = build_detector_config(args)
    backtest_config = build_backtest_config(args)
    tool = PolymarketInformedTraderTool(detector_config)

    if args.market and (args.tag_slug or args.tag_id):
        raise SystemExit("Use either --market or --tag-slug/--tag-id (not both).")

    if not args.market and not (args.tag_slug or args.tag_id):
        raise SystemExit("Provide --market or --tag-slug/--tag-id.")

    if args.market:
        print("Fetching trades from Polymarket Data API...")
        try:
            trades = tool.fetch_trades(
                exchange,
                market=args.market,
                limit=args.limit,
                offset=args.offset,
            )
        except Exception as e:
            raise SystemExit(
                f"Failed to fetch trades for market={args.market}: {type(e).__name__}: {e}"
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
        # With extra client-side filters (e.g., opened-within-years), we may need to scan
        # far more markets than we intend to backtest.
        multiplier = 30 if opened_after is not None else 12
        max_scan_limit = max(5_000, int(args.top_markets) * multiplier)
        scan_limit = min(scan_limit, max_scan_limit)

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
            err = None
            try:
                df = tool.fetch_trades(
                    exchange,
                    market=cid,
                    limit=args.limit,
                    offset=args.offset,
                )
            except Exception as e:
                df = pd.DataFrame()
                err = f"{type(e).__name__}: {e}"
            # Some Data-API responses omit slug/title for older markets; fill best-effort.
            if not df.empty:
                slug = str(mkt.metadata.get("slug", "")).strip()
                if slug:
                    df["slug"] = df["slug"].fillna(slug)
            return (mkt, df, err)

        frames = []
        markets_meta = []
        fetch_errors: list[str] = []
        workers = max(1, int(args.workers))
        if workers == 1:
            for mkt in markets:
                mkt, df, err = _fetch_one(mkt)
                if err is not None:
                    fetch_errors.append(
                        f"{str(mkt.metadata.get('slug', '')) or mkt.id} ({mkt.metadata.get('conditionId', mkt.id)}): {err}"
                    )
                if not df.empty:
                    frames.append(df)
                markets_meta.append(mkt)
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
                futures = [ex.submit(_fetch_one, mkt) for mkt in markets]
                for fut in concurrent.futures.as_completed(futures):
                    mkt, df, err = fut.result()
                    if err is not None:
                        fetch_errors.append(
                            f"{str(mkt.metadata.get('slug', '')) or mkt.id} ({mkt.metadata.get('conditionId', mkt.id)}): {err}"
                        )
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

        if fetch_errors:
            n_show = min(5, len(fetch_errors))
            print(f"Trade fetch errors: {len(fetch_errors)} (showing {n_show})")
            for msg in fetch_errors[:n_show]:
                print(f"  - {msg}")

        print(
            f"Fetched {len(trades):,} trades across {trades['asset'].nunique()} assets "
            f"({trades['condition_id'].nunique()} condition_ids)."
        )

    sweep_tokens = []
    if args.sweep_exits:
        sweep_tokens = [t.strip().lower() for t in str(args.sweep_exits).split(",") if t.strip()]

    need_expiry = bool(args.hold_to_expiry) or ("expiry" in sweep_tokens)

    settlements = None
    if need_expiry:
        condition_ids = sorted(set(trades["condition_id"].astype(str)))
        inferred: dict[str, dict] = {}

        if markets_meta is not None:
            for mkt in markets_meta:
                cid, info = _infer_settlement(mkt)
                if cid:
                    inferred[cid] = info
        else:
            workers = max(1, int(args.workers))

            def _fetch_market(cid: str):
                try:
                    return exchange.fetch_market(cid)
                except Exception:
                    return None

            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
                for mkt in ex.map(_fetch_market, condition_ids):
                    if mkt is None:
                        continue
                    cid, info = _infer_settlement(mkt)
                    if cid:
                        inferred[cid] = info

        settlements = {cid: inferred.get(cid, {}) for cid in condition_ids}
        resolved = sum(
            1 for cid in condition_ids if settlements[cid].get("winner_outcome") is not None
        )
        print(
            f"Expiry settlement mode enabled: resolved={resolved}/{len(condition_ids)} condition_ids "
            f"(unresolved will be skipped)."
        )

    if args.optimize:
        print("Running parameter optimization...")
        optimization = tool.optimize_strategy(
            trades,
            train_ratio=args.train_ratio,
            backtest_config=backtest_config,
            settlements=settlements,
        )
        best_cfg = optimization.best_config
        print("Best detector config:")
        print(asdict(best_cfg))
        print_backtest_summary("Train Backtest", optimization.best_train)
        print_backtest_summary("Test Backtest", optimization.best_test)

        detector_config = best_cfg
        tool = PolymarketInformedTraderTool(best_cfg)

    # Engineer features once so signals/backtests/plots are consistent and deterministic.
    features = tool.engineer_features(trades, detector_config)
    signals = tool.detect_signals(features, detector_config)
    result = None
    if not args.sweep_exits:
        result = tool.backtest(
            features,
            signals=signals,
            detector_config=detector_config,
            backtest_config=backtest_config,
            settlements=settlements,
        )

    fresh_window_hours = (
        None if float(args.fresh_wallet_window_hours) < 0 else float(args.fresh_wallet_window_hours)
    )
    wallets = tool.rank_wallets(
        features,
        top_n=args.top_wallets,
        config=detector_config,
        fresh_window_hours=fresh_window_hours,
        fresh_max_trades=args.fresh_wallet_max_trades,
    )

    print(f"\nDetected informed trader signals: {len(signals)}")

    if args.sweep_exits:
        rows = []
        for tok in sweep_tokens:
            if tok in ("expiry", "settle", "settlement"):
                cfg = backtest_config
                cfg = BacktestConfig(
                    holding_minutes=cfg.holding_minutes,
                    take_profit=None if args.sweep_no_tp_sl else cfg.take_profit,
                    stop_loss=None if args.sweep_no_tp_sl else cfg.stop_loss,
                    position_size=cfg.position_size,
                    fee_bps=cfg.fee_bps,
                    slippage_bps=cfg.slippage_bps,
                    initial_capital=cfg.initial_capital,
                    allow_short=cfg.allow_short,
                    hold_to_expiry=True,
                )
                label = "expiry"
                bt = tool.backtest(
                    features,
                    signals=signals,
                    detector_config=detector_config,
                    backtest_config=cfg,
                    settlements=settlements,
                )
            else:
                try:
                    minutes = int(tok)
                except Exception:
                    raise SystemExit(
                        f"Invalid --sweep-exits token: {tok!r} (expected int minutes or 'expiry')"
                    )
                cfg = backtest_config
                cfg = BacktestConfig(
                    holding_minutes=minutes,
                    take_profit=None if args.sweep_no_tp_sl else cfg.take_profit,
                    stop_loss=None if args.sweep_no_tp_sl else cfg.stop_loss,
                    position_size=cfg.position_size,
                    fee_bps=cfg.fee_bps,
                    slippage_bps=cfg.slippage_bps,
                    initial_capital=cfg.initial_capital,
                    allow_short=cfg.allow_short,
                    hold_to_expiry=False,
                )
                label = f"{minutes}m"
                bt = tool.backtest(
                    features,
                    signals=signals,
                    detector_config=detector_config,
                    backtest_config=cfg,
                )

            rows.append(
                {
                    "exit_mode": label,
                    "holding_minutes": None if label == "expiry" else int(label.rstrip("m")),
                    "fee_bps": float(backtest_config.fee_bps),
                    "slippage_bps": float(backtest_config.slippage_bps),
                    "position_size": float(backtest_config.position_size),
                    "initial_capital": float(backtest_config.initial_capital),
                    "signals": int(len(signals)),
                    "bt_trades": int(bt.n_trades),
                    "total_pnl": float(bt.total_pnl),
                    "ending_capital": float(bt.ending_capital),
                    "return_pct": float(bt.return_pct),
                    "win_rate": float(bt.win_rate),
                    "sharpe": float(bt.sharpe),
                    "max_drawdown": float(bt.max_drawdown),
                    "profit_factor": float(bt.profit_factor),
                }
            )
            print_backtest_summary(f"Sweep Backtest ({label})", bt)

        sweep_df = (
            pd.DataFrame(rows).sort_values("return_pct", ascending=False).reset_index(drop=True)
        )
        print("\nSweep Comparison (sorted by return_pct):")
        display_cols = [
            "exit_mode",
            "bt_trades",
            "total_pnl",
            "return_pct",
            "win_rate",
            "max_drawdown",
            "profit_factor",
        ]
        print(sweep_df[display_cols].to_string(index=False, float_format=lambda v: f"{v:,.4f}"))

        if args.sweep_save:
            args.sweep_save.parent.mkdir(parents=True, exist_ok=True)
            sweep_df.to_csv(args.sweep_save, index=False)
            print(f"\nSaved sweep results to {args.sweep_save}")
    else:
        assert result is not None
        print_backtest_summary("Full Backtest", result)

    if not wallets.empty:
        print("\nTop wallets by informed trader rank:")
        display_cols = [
            "wallet",
            "trades",
            "recent_skill",
            "realized_edge",
            "realized_win_rate",
            "total_notional",
            "informed_trader_rank_score",
            "age_hours_in_sample",
            "fresh_in_sample",
        ]
        print(wallets[display_cols].to_string(index=False, float_format=lambda v: f"{v:,.4f}"))
    else:
        print("\nNo wallets met minimum history constraints.")

    if args.save_signals:
        signals_df = pd.DataFrame([asdict(signal) for signal in signals])
        signals_df.to_csv(args.save_signals, index=False)
        print(f"\nSaved signals to {args.save_signals}")

    if args.save_backtest_trades:
        if result is None:
            raise SystemExit(
                "--save-backtest-trades requires a single backtest run (disable --sweep-exits)."
            )
        bt_df = pd.DataFrame([asdict(trade) for trade in result.trades])
        bt_df.to_csv(args.save_backtest_trades, index=False)
        print(f"Saved backtest trades to {args.save_backtest_trades}")

    if args.save_market_summary and markets_meta is not None:
        # Compute per-market results using the (global) wallet-skill features we already engineered.
        market_rows = []
        signals_by_condition: dict[str, list] = {}
        for s in signals:
            signals_by_condition.setdefault(str(s.condition_id), []).append(s)

        informed_metrics = tool.market_informed_trader_metrics(
            features,
            signals=signals,
            config=detector_config,
            fresh_window_hours=fresh_window_hours,
            fresh_max_trades=args.fresh_wallet_max_trades,
        )
        informed_metrics_by_cid = (
            informed_metrics.set_index("condition_id", drop=False)
            if not informed_metrics.empty
            else pd.DataFrame()
        )

        meta_by_cid = {}
        for mkt in markets_meta:
            cid = str(mkt.metadata.get("conditionId", "")).strip()
            if cid:
                meta_by_cid[cid] = mkt

        if "condition_id" not in features.columns:
            raise SystemExit("Internal error: engineered features are missing condition_id.")
        features = features.copy()
        features["condition_id"] = features["condition_id"].astype(str)

        for cid, subset in features.groupby("condition_id", sort=False):
            mkt = meta_by_cid.get(str(cid))
            if mkt is None:
                continue
            m_signals = signals_by_condition.get(str(cid), [])
            if not informed_metrics_by_cid.empty and str(cid) in informed_metrics_by_cid.index:
                m_metrics = informed_metrics_by_cid.loc[str(cid)]
                market_wallets = int(m_metrics["market_wallets"])
                informed_trader_wallets = int(m_metrics["informed_trader_wallets"])
                informed_trader_wallet_share = float(m_metrics["informed_trader_wallet_share"])
                informed_trader_signals = int(m_metrics["informed_trader_signals"])
                signals_per_informed_trader_wallet = float(
                    m_metrics["signals_per_informed_trader_wallet"]
                )
                fresh_informed_trader_wallets = int(m_metrics["fresh_informed_trader_wallets"])
                fresh_informed_trader_wallet_share = float(
                    m_metrics["fresh_informed_trader_wallet_share"]
                )
            else:
                market_wallets = int(subset["proxy_wallet"].nunique())
                informed_trader_wallets = int(len({str(s.trigger_wallet) for s in m_signals}))
                informed_trader_wallet_share = (
                    float(informed_trader_wallets / market_wallets) if market_wallets > 0 else 0.0
                )
                informed_trader_signals = int(len(m_signals))
                signals_per_informed_trader_wallet = (
                    float(informed_trader_signals / informed_trader_wallets)
                    if informed_trader_wallets > 0
                    else 0.0
                )
                fresh_informed_trader_wallets = 0
                fresh_informed_trader_wallet_share = 0.0

            m_result = tool.backtest(
                subset,
                signals=m_signals,
                detector_config=detector_config,
                backtest_config=backtest_config,
                settlements=settlements,
            )
            market_rows.append(
                {
                    "slug": str(mkt.metadata.get("slug", "")),
                    "condition_id": str(cid),
                    "volume": float(getattr(mkt, "volume", 0.0) or 0.0),
                    "question": str(getattr(mkt, "question", "")),
                    "trades_fetched": int(len(subset)),
                    "assets": int(subset["asset"].nunique()),
                    "signals": int(len(m_signals)),
                    "market_wallets": market_wallets,
                    "informed_trader_wallets": informed_trader_wallets,
                    "informed_trader_wallet_share": informed_trader_wallet_share,
                    "informed_trader_signals": informed_trader_signals,
                    "signals_per_informed_trader_wallet": signals_per_informed_trader_wallet,
                    "fresh_informed_trader_wallets": fresh_informed_trader_wallets,
                    "fresh_informed_trader_wallet_share": fresh_informed_trader_wallet_share,
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
        if result is None:
            raise SystemExit("--plot requires a single backtest run (disable --sweep-exits).")
        tool.plot_informed_trader_backtest(
            features,
            signals=signals,
            result=result,
            detector_config=detector_config,
            backtest_config=backtest_config,
            output_path=args.plot_path,
            top_assets=args.plot_assets,
            combine_assets=args.plot_combined,
            settlements=settlements,
        )
        print(f"Saved plot to {args.plot_path}")


if __name__ == "__main__":
    main()
