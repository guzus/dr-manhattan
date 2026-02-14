"""Tests for insider-flow detection and backtesting."""

from __future__ import annotations

import matplotlib
import pandas as pd

from examples.polymarket_insider_tool.insider_flow import (
    BacktestConfig,
    InsiderFlowConfig,
    PolymarketInsiderTool,
)

matplotlib.use("Agg")


def _build_synthetic_trades() -> pd.DataFrame:
    rows = []
    base = pd.Timestamp("2025-01-01T00:00:00Z")
    price = 0.50

    insider_points = {10: 0.36, 30: 0.39, 50: 0.42, 70: 0.44}
    jump_points = {12: 0.62, 32: 0.66, 52: 0.69, 72: 0.71}

    for i in range(90):
        ts = base + pd.Timedelta(minutes=5 * i)
        if i in insider_points:
            price = insider_points[i]
            wallet = "0xinsider"
            side = "BUY"
            size = 4000
        elif i in jump_points:
            price = jump_points[i]
            wallet = "0xfollowers"
            side = "BUY"
            size = 1200
        else:
            wallet = f"0xnoise{i % 6}"
            side = "BUY" if i % 2 == 0 else "SELL"
            size = 120 + (i % 4) * 20
            drift = 0.0025 if side == "BUY" else -0.0022
            price = max(0.08, min(0.92, price + drift))

        rows.append(
            {
                "timestamp": ts,
                "asset": "token_yes_a",
                "condition_id": "market_a",
                "outcome": "Yes",
                "side": side,
                "size": size,
                "price": price,
                "proxy_wallet": wallet,
                "slug": "synthetic-insider-a",
            }
        )

    price_b = 0.48
    for i in range(90):
        ts = base + pd.Timedelta(minutes=5 * i)
        side = "BUY" if i % 3 == 0 else "SELL"
        size = 100 + (i % 5) * 15
        price_b = max(0.10, min(0.90, price_b + (0.0015 if side == "BUY" else -0.0016)))
        rows.append(
            {
                "timestamp": ts,
                "asset": "token_yes_b",
                "condition_id": "market_b",
                "outcome": "Yes",
                "side": side,
                "size": size,
                "price": price_b,
                "proxy_wallet": f"0xnoise_b{i % 7}",
                "slug": "synthetic-noise-b",
            }
        )

    return pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)


def test_detect_signals_and_wallet_ranking():
    trades = _build_synthetic_trades()
    config = InsiderFlowConfig(
        horizon_minutes=10,
        lookback_trades=8,
        signal_threshold=0.20,
        cooldown_minutes=10,
        min_wallet_history=1,
        min_trade_notional=250.0,
        long_only=True,
    )
    tool = PolymarketInsiderTool(config)

    signals = tool.detect_signals(trades)
    assert len(signals) >= 2
    assert all(signal.side == "long" for signal in signals)
    assert any(signal.trigger_wallet == "0xinsider" for signal in signals)

    ranked = tool.rank_wallets(trades, top_n=5)
    assert not ranked.empty
    assert ranked.iloc[0]["wallet"] == "0xinsider"


def test_market_insider_metrics_counts_unique_insider_wallets():
    trades = _build_synthetic_trades()
    config = InsiderFlowConfig(
        horizon_minutes=10,
        lookback_trades=8,
        signal_threshold=0.20,
        cooldown_minutes=10,
        min_wallet_history=1,
        min_trade_notional=250.0,
        long_only=True,
    )
    tool = PolymarketInsiderTool(config)

    features = tool.engineer_features(trades, config)
    signals = tool.detect_signals(features, config)
    metrics = tool.market_insider_metrics(features, signals=signals, config=config)

    assert not metrics.empty
    assert {"condition_id", "market_wallets", "insider_wallets", "insider_wallet_share"}.issubset(
        metrics.columns
    )

    market_a = metrics[metrics["condition_id"] == "market_a"]
    assert not market_a.empty
    row_a = market_a.iloc[0]
    assert int(row_a["insider_wallets"]) >= 1
    assert int(row_a["market_wallets"]) >= int(row_a["insider_wallets"])
    expected_share = float(row_a["insider_wallets"]) / float(row_a["market_wallets"])
    assert abs(float(row_a["insider_wallet_share"]) - expected_share) < 1e-12


def test_backtest_positive_pnl_on_informed_flow():
    trades = _build_synthetic_trades()
    detector_config = InsiderFlowConfig(
        horizon_minutes=10,
        lookback_trades=8,
        signal_threshold=0.20,
        cooldown_minutes=10,
        min_wallet_history=1,
        min_trade_notional=250.0,
        long_only=True,
    )
    backtest_config = BacktestConfig(
        holding_minutes=20,
        take_profit=0.15,
        stop_loss=0.10,
        position_size=1000.0,
        fee_bps=2.0,
        slippage_bps=2.0,
        initial_capital=20000.0,
    )
    tool = PolymarketInsiderTool(detector_config)

    signals = tool.detect_signals(trades)
    result = tool.backtest(
        trades,
        signals=signals,
        detector_config=detector_config,
        backtest_config=backtest_config,
    )

    assert result.n_trades > 0
    assert result.total_pnl > 0
    assert result.win_rate > 0.5
    assert result.ending_capital > backtest_config.initial_capital


def test_optimizer_returns_valid_best_configuration():
    trades = _build_synthetic_trades()
    base_config = InsiderFlowConfig(
        horizon_minutes=10,
        lookback_trades=8,
        signal_threshold=0.20,
        cooldown_minutes=10,
        min_wallet_history=1,
        min_trade_notional=250.0,
        long_only=True,
    )
    backtest_config = BacktestConfig(
        holding_minutes=20,
        take_profit=0.15,
        stop_loss=0.10,
        position_size=800.0,
        fee_bps=2.0,
        slippage_bps=2.0,
        initial_capital=20000.0,
    )
    tool = PolymarketInsiderTool(base_config)
    grid = {
        "signal_threshold": (0.18, 0.24, 0.30),
        "lookback_trades": (6, 10),
        "cooldown_minutes": (5, 15),
        "min_wallet_history": (1, 2),
    }

    optimization = tool.optimize_strategy(
        trades,
        param_grid=grid,
        train_ratio=0.7,
        backtest_config=backtest_config,
    )

    assert not optimization.leaderboard.empty
    assert optimization.best_config.signal_threshold in grid["signal_threshold"]
    assert optimization.best_test.n_trades >= 1
    assert optimization.best_test.total_pnl == optimization.leaderboard.iloc[0]["test_total_pnl"]


def test_plot_insider_backtest_saves_png(tmp_path):
    trades = _build_synthetic_trades()
    detector_config = InsiderFlowConfig(
        horizon_minutes=10,
        lookback_trades=8,
        signal_threshold=0.20,
        cooldown_minutes=10,
        min_wallet_history=1,
        min_trade_notional=250.0,
        long_only=True,
    )
    backtest_config = BacktestConfig(
        holding_minutes=20,
        take_profit=0.15,
        stop_loss=0.10,
        position_size=1000.0,
        fee_bps=2.0,
        slippage_bps=2.0,
        initial_capital=20000.0,
    )
    tool = PolymarketInsiderTool(detector_config)
    signals = tool.detect_signals(trades)
    result = tool.backtest(
        trades,
        signals=signals,
        detector_config=detector_config,
        backtest_config=backtest_config,
    )

    out = tmp_path / "insider_plot.png"
    fig = tool.plot_insider_backtest(
        trades,
        signals=signals,
        result=result,
        detector_config=detector_config,
        backtest_config=backtest_config,
        output_path=out,
        top_assets=2,
    )

    assert fig is not None
    assert out.exists()
    assert out.stat().st_size > 0
