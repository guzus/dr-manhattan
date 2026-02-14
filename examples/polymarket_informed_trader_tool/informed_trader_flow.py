"""Informed-trader-flow detection and backtesting utilities for Polymarket trade data."""

from __future__ import annotations

import heapq
from dataclasses import dataclass, replace
from itertools import product
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

import numpy as np
import pandas as pd

from dr_manhattan import Polymarket
from dr_manhattan.exchanges.polymarket.polymarket_core import PublicTrade


@dataclass(frozen=True)
class InformedTraderFlowConfig:
    """Configuration for informed-trader-flow feature engineering and signal generation."""

    horizon_minutes: int = 30
    lookback_trades: int = 40
    signal_threshold: float = 0.28
    cooldown_minutes: int = 45
    min_wallet_history: int = 0
    min_trade_notional: float = 150.0
    prior_count: float = 8.0
    edge_vol_floor: float = 0.01
    burst_half_life_minutes: float = 25.0
    flow_weight: float = 0.30
    skill_weight: float = 0.45
    conviction_weight: float = 0.15
    burst_weight: float = 0.10
    long_only: bool = False


@dataclass(frozen=True)
class BacktestConfig:
    """Configuration for buy-after-signal backtests."""

    holding_minutes: int = 60
    take_profit: float | None = 0.10
    stop_loss: float | None = 0.08
    position_size: float = 500.0
    fee_bps: float = 0.0
    slippage_bps: float = 50.0
    initial_capital: float = 10_000.0
    # In binary markets, "short" is modeled as buying the opposite outcome token.
    allow_short: bool = True
    # If True, ignore holding_minutes/TP/SL and hold until market expiry (settlement payout 0/1).
    # Requires passing `settlements=` into backtest().
    hold_to_expiry: bool = False


@dataclass(frozen=True)
class InformedTraderSignal:
    """A single informed-trader-flow signal emitted from trade-flow features."""

    timestamp: pd.Timestamp
    asset: str
    condition_id: str
    outcome: str | None
    side: str
    score: float
    direction_score: float
    flow_ratio: float
    wallet_skill: float
    conviction_score: float
    trigger_wallet: str
    trigger_notional: float
    trigger_price: float
    slug: str | None = None


@dataclass(frozen=True)
class BacktestTrade:
    """A completed backtest trade created from a signal."""

    asset: str
    side: str
    signal_time: pd.Timestamp
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    raw_return: float
    net_return: float
    pnl: float
    reason: str
    score: float
    view_asset: str | None = None
    view_side: str | None = None
    view_outcome: str | None = None
    traded_outcome: str | None = None


@dataclass(frozen=True)
class BacktestResult:
    """Aggregated backtest statistics and completed trades."""

    total_pnl: float
    ending_capital: float
    return_pct: float
    n_trades: int
    win_rate: float
    avg_return: float
    sharpe: float
    max_drawdown: float
    profit_factor: float
    trades: List[BacktestTrade]


@dataclass(frozen=True)
class OptimizationResult:
    """Train/test optimization output and leaderboard."""

    best_config: InformedTraderFlowConfig
    best_train: BacktestResult
    best_test: BacktestResult
    split_time: pd.Timestamp
    leaderboard: pd.DataFrame


class PolymarketInformedTraderTool:
    """Detect likely informed trader flow from Polymarket public trades and backtest signals."""

    _FEATURE_COLUMNS = {
        "informed_trader_score",
        "direction_score",
        "flow_ratio",
        "wallet_skill",
        "conviction_score",
    }

    _DEFAULT_GRID: Dict[str, Sequence[Any]] = {
        "signal_threshold": (0.20, 0.26, 0.32),
        "lookback_trades": (20, 35, 50),
        "horizon_minutes": (20, 30, 45),
        "cooldown_minutes": (20, 45),
        "min_wallet_history": (0, 1, 2),
    }

    def __init__(self, config: InformedTraderFlowConfig | None = None):
        self.config = config or InformedTraderFlowConfig()

    @staticmethod
    def fetch_trades(
        exchange: Polymarket,
        *,
        market: str | None = None,
        limit: int = 5_000,
        offset: int = 0,
        side: str | None = None,
    ) -> pd.DataFrame:
        """Fetch and normalize public trades from Polymarket."""
        resolved_market = market
        if market:
            market_id = str(market)
            if not _looks_like_condition_id(market_id):
                try:
                    resolved = exchange.fetch_market(market_id)
                    resolved_market = str(resolved.metadata.get("conditionId", resolved.id))
                except Exception:
                    # If it's an event slug, fetch all markets for the event and combine trades.
                    try:
                        event_markets = exchange.fetch_markets_by_slug(market_id)
                    except Exception:
                        event_markets = []

                    if event_markets:
                        side_filter = side.upper() if side else None
                        per_market = max(1, int(limit) // len(event_markets))
                        frames: List[pd.DataFrame] = []
                        for event_market in event_markets:
                            condition_id = str(
                                event_market.metadata.get("conditionId", event_market.id)
                            )
                            raw = exchange.fetch_public_trades(
                                market=condition_id,
                                limit=per_market,
                                offset=offset,
                                side=side_filter,
                                as_dataframe=True,
                            )
                            df = PolymarketInformedTraderTool.prepare_trades(raw)
                            df["event_slug"] = market_id
                            df["market_slug"] = str(event_market.metadata.get("slug", ""))
                            frames.append(df)

                        combined = (
                            pd.concat(frames, ignore_index=True)
                            if frames
                            else pd.DataFrame(columns=["timestamp"])
                        )
                        if not combined.empty and "timestamp" in combined.columns:
                            return combined.sort_values("timestamp").reset_index(drop=True)
                        return combined

                    resolved_market = market_id

        side_filter = side.upper() if side else None
        raw = exchange.fetch_public_trades(
            market=resolved_market,
            limit=limit,
            offset=offset,
            side=side_filter,
            as_dataframe=True,
        )
        return PolymarketInformedTraderTool.prepare_trades(raw)

    @staticmethod
    def prepare_trades(
        trades: pd.DataFrame | Iterable[Mapping[str, Any]] | Iterable[PublicTrade],
    ) -> pd.DataFrame:
        """Normalize trade data into a canonical DataFrame schema."""
        if isinstance(trades, pd.DataFrame):
            df = trades.copy()
        else:
            records: List[Dict[str, Any]] = []
            for item in trades:
                if isinstance(item, PublicTrade):
                    records.append(
                        {
                            "timestamp": item.timestamp,
                            "side": item.side,
                            "asset": item.asset,
                            "condition_id": item.condition_id,
                            "size": item.size,
                            "price": item.price,
                            "proxy_wallet": item.proxy_wallet,
                            "slug": item.slug,
                            "outcome": item.outcome,
                        }
                    )
                elif isinstance(item, Mapping):
                    records.append(dict(item))
            df = pd.DataFrame(records)

        if df.empty:
            return pd.DataFrame(
                columns=[
                    "timestamp",
                    "asset",
                    "condition_id",
                    "outcome",
                    "side",
                    "size",
                    "price",
                    "proxy_wallet",
                    "slug",
                    "direction",
                    "notional",
                    "signed_notional",
                ]
            )

        rename_map = {
            "proxyWallet": "proxy_wallet",
            "conditionId": "condition_id",
            "eventSlug": "event_slug",
            "transactionHash": "transaction_hash",
            "profileImage": "profile_image",
            "profileImageOptimized": "profile_image_optimized",
        }
        df = df.rename(columns=rename_map)

        for column in ("asset", "condition_id", "outcome", "proxy_wallet", "slug"):
            if column not in df.columns:
                df[column] = ""

        if "timestamp" not in df.columns:
            raise ValueError("Trade data must include a timestamp column.")
        if "side" not in df.columns:
            raise ValueError("Trade data must include a side column.")
        if "size" not in df.columns:
            raise ValueError("Trade data must include a size column.")
        if "price" not in df.columns:
            raise ValueError("Trade data must include a price column.")

        df["side"] = df["side"].astype(str).str.upper()
        df = df[df["side"].isin(("BUY", "SELL"))]

        ts_raw = df["timestamp"]
        parsed_ts = pd.to_datetime(ts_raw, utc=True, errors="coerce")
        numeric_mask = parsed_ts.isna() & ts_raw.astype(str).str.fullmatch(r"\d+")
        if numeric_mask.any():
            numeric = pd.to_numeric(ts_raw[numeric_mask], errors="coerce")
            unit = "ms" if float(numeric.max(skipna=True)) > 1e11 else "s"
            parsed_ts.loc[numeric_mask] = pd.to_datetime(
                numeric, unit=unit, utc=True, errors="coerce"
            )
        df["timestamp"] = parsed_ts

        df["size"] = pd.to_numeric(df["size"], errors="coerce")
        df["price"] = pd.to_numeric(df["price"], errors="coerce")
        df = df.dropna(subset=["timestamp", "size", "price"])
        df = df[(df["size"] > 0) & (df["price"] > 0)]

        df["asset"] = df["asset"].astype(str)
        df["condition_id"] = df["condition_id"].astype(str)
        df["proxy_wallet"] = df["proxy_wallet"].astype(str)
        df["outcome"] = df["outcome"].astype(str)
        df["slug"] = df["slug"].replace("", np.nan)

        df["direction"] = np.where(df["side"].eq("BUY"), 1.0, -1.0)
        df["notional"] = (df["size"] * df["price"]).abs()
        df["signed_notional"] = df["direction"] * df["notional"]

        return _stable_sort_frame(df)

    def engineer_features(
        self,
        trades: pd.DataFrame | Iterable[Mapping[str, Any]] | Iterable[PublicTrade],
        config: InformedTraderFlowConfig | None = None,
    ) -> pd.DataFrame:
        """Build informed-trader-flow features from normalized trade data."""
        cfg = config or self.config
        df = self.prepare_trades(trades)

        if df.empty:
            return df

        if cfg.lookback_trades < 2:
            raise ValueError("lookback_trades must be at least 2")

        df = self._add_forward_returns(df, cfg.horizon_minutes)
        df = self._add_wallet_skill_online(df, cfg)

        log_notional = np.log1p(df["notional"])
        hist_mean = (
            df.groupby("asset", sort=False)["notional"]
            .transform(lambda s: np.log1p(s).shift(1).expanding().mean())
            .fillna(log_notional.median())
        )
        hist_std = (
            df.groupby("asset", sort=False)["notional"]
            .transform(lambda s: np.log1p(s).shift(1).expanding().std(ddof=0))
            .fillna(log_notional.std(ddof=0) if len(log_notional) > 1 else 0.0)
        )

        conviction_z = (log_notional - hist_mean) / (hist_std + 0.25)
        conviction_z = conviction_z.replace([np.inf, -np.inf], 0.0).fillna(0.0)
        df["conviction_z"] = conviction_z
        df["conviction_score"] = np.clip(np.tanh(conviction_z / 2.0), 0.0, 1.0)

        prev_trade_ts = df.groupby(["proxy_wallet", "asset"], sort=False)["timestamp"].shift(1)
        minutes_since_last = (df["timestamp"] - prev_trade_ts).dt.total_seconds() / 60.0
        df["burst_score"] = np.exp(
            -minutes_since_last.fillna(np.inf) / max(cfg.burst_half_life_minutes, 1e-6)
        )

        df["skill_weighted_flow"] = df["signed_notional"] * df["wallet_skill"].clip(lower=0.0)
        df["conviction_weighted_flow"] = df["signed_notional"] * df["conviction_score"]
        df["burst_weighted_flow"] = df["signed_notional"] * df["burst_score"]

        rolling_cols = [
            "signed_notional",
            "notional",
            "skill_weighted_flow",
            "conviction_weighted_flow",
            "burst_weighted_flow",
        ]
        rolled = (
            df.groupby("asset", sort=False)[rolling_cols]
            .rolling(window=cfg.lookback_trades, min_periods=2)
            .sum()
            .reset_index(level=0, drop=True)
        )
        for col in rolling_cols:
            df[f"{col}_roll"] = rolled[col]

        denom = df["notional_roll"].abs().clip(lower=1e-8)
        df["flow_ratio"] = (df["signed_notional_roll"] / denom).clip(-1.0, 1.0)
        df["skill_flow_ratio"] = (df["skill_weighted_flow_roll"] / denom).clip(-1.0, 1.0)
        df["conviction_flow_ratio"] = (df["conviction_weighted_flow_roll"] / denom).clip(-1.0, 1.0)
        df["burst_flow_ratio"] = (df["burst_weighted_flow_roll"] / denom).clip(-1.0, 1.0)

        total_weight = cfg.flow_weight + cfg.skill_weight + cfg.conviction_weight + cfg.burst_weight
        if total_weight <= 0:
            raise ValueError("Flow weights must sum to a positive number.")

        df["direction_score"] = (
            cfg.flow_weight * df["flow_ratio"]
            + cfg.skill_weight * df["skill_flow_ratio"]
            + cfg.conviction_weight * df["conviction_flow_ratio"]
            + cfg.burst_weight * df["burst_flow_ratio"]
        ) / total_weight
        df["informed_trader_score"] = df["direction_score"].abs()
        df["signal_side"] = np.where(df["direction_score"] >= 0, "long", "short")
        df["eligible_signal"] = (
            (df["notional"] >= cfg.min_trade_notional)
            & (df["wallet_obs"] >= cfg.min_wallet_history)
            & df["informed_trader_score"].notna()
        )

        return _stable_sort_frame(df)

    def detect_signals(
        self,
        trades: pd.DataFrame | Iterable[Mapping[str, Any]] | Iterable[PublicTrade],
        config: InformedTraderFlowConfig | None = None,
    ) -> List[InformedTraderSignal]:
        """Detect informed trader signals from trades or precomputed feature frames."""
        cfg = config or self.config
        features = self._ensure_feature_frame(trades, cfg)
        if features.empty:
            return []
        return self._detect_signals_from_features(features, cfg)

    def backtest(
        self,
        trades: pd.DataFrame | Iterable[Mapping[str, Any]] | Iterable[PublicTrade],
        *,
        signals: Sequence[InformedTraderSignal] | None = None,
        detector_config: InformedTraderFlowConfig | None = None,
        backtest_config: BacktestConfig | None = None,
        start_time: pd.Timestamp | str | None = None,
        end_time: pd.Timestamp | str | None = None,
        settlements: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> BacktestResult:
        """Backtest buy-after-informed-trader-flow signals and compute total PnL."""
        det_cfg = detector_config or self.config
        bt_cfg = backtest_config or BacktestConfig()
        features = self._ensure_feature_frame(trades, det_cfg)
        if features.empty:
            return self._empty_backtest(bt_cfg.initial_capital)

        if signals is None:
            signals = self._detect_signals_from_features(features, det_cfg)
        return self._backtest_on_features(
            features,
            list(signals),
            bt_cfg,
            start_time=start_time,
            end_time=end_time,
            settlements=settlements,
        )

    def optimize_strategy(
        self,
        trades: pd.DataFrame | Iterable[Mapping[str, Any]] | Iterable[PublicTrade],
        *,
        param_grid: Mapping[str, Sequence[Any]] | None = None,
        train_ratio: float = 0.70,
        backtest_config: BacktestConfig | None = None,
        settlements: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> OptimizationResult:
        """Grid-search strategy settings and return the strongest train/test setup."""
        if train_ratio <= 0 or train_ratio >= 1:
            raise ValueError("train_ratio must be in (0, 1)")

        bt_cfg = backtest_config or BacktestConfig()
        base = self.prepare_trades(trades)
        if base.empty:
            raise ValueError("No trades available for optimization.")

        split_idx = max(1, min(len(base) - 1, int(len(base) * train_ratio)))
        split_time = base.iloc[split_idx]["timestamp"]
        combos = self._expand_param_grid(param_grid)
        rows: List[Dict[str, Any]] = []

        best_score = -np.inf
        best_config = self.config
        best_train = self._empty_backtest(bt_cfg.initial_capital)
        best_test = self._empty_backtest(bt_cfg.initial_capital)

        for params in combos:
            cfg = replace(self.config, **params)
            features = self.engineer_features(base, cfg)
            signals = self._detect_signals_from_features(features, cfg)
            train_result = self._backtest_on_features(
                features, signals, bt_cfg, end_time=split_time, settlements=settlements
            )
            test_result = self._backtest_on_features(
                features, signals, bt_cfg, start_time=split_time, settlements=settlements
            )

            objective = self._objective(train_result, test_result, bt_cfg)
            row = {
                **params,
                "objective": objective,
                "train_total_pnl": train_result.total_pnl,
                "train_trades": train_result.n_trades,
                "test_total_pnl": test_result.total_pnl,
                "test_trades": test_result.n_trades,
                "test_win_rate": test_result.win_rate,
                "test_max_drawdown": test_result.max_drawdown,
            }
            rows.append(row)

            if objective > best_score:
                best_score = objective
                best_config = cfg
                best_train = train_result
                best_test = test_result

        leaderboard = (
            pd.DataFrame(rows)
            .sort_values(["objective", "test_total_pnl"], ascending=[False, False])
            .reset_index(drop=True)
        )
        return OptimizationResult(
            best_config=best_config,
            best_train=best_train,
            best_test=best_test,
            split_time=split_time,
            leaderboard=leaderboard,
        )

    def rank_wallets(
        self,
        trades: pd.DataFrame | Iterable[Mapping[str, Any]] | Iterable[PublicTrade],
        *,
        top_n: int = 20,
        config: InformedTraderFlowConfig | None = None,
    ) -> pd.DataFrame:
        """Rank wallets by realized edge and current informed trader score."""
        cfg = config or self.config
        features = self._ensure_feature_frame(trades, cfg)
        if features.empty:
            return pd.DataFrame(
                columns=[
                    "wallet",
                    "trades",
                    "recent_skill",
                    "avg_skill",
                    "realized_edge",
                    "realized_win_rate",
                    "total_notional",
                    "informed_trader_rank_score",
                ]
            )

        realized = features[features["signed_forward_return"].notna()].copy()
        if realized.empty:
            return pd.DataFrame(
                columns=[
                    "wallet",
                    "trades",
                    "recent_skill",
                    "avg_skill",
                    "realized_edge",
                    "realized_win_rate",
                    "total_notional",
                    "informed_trader_rank_score",
                ]
            )

        grouped = realized.groupby("proxy_wallet", sort=False)
        summary = grouped.agg(
            trades=("proxy_wallet", "size"),
            recent_skill=("wallet_skill", "last"),
            avg_skill=("wallet_skill", "mean"),
            realized_edge=("signed_forward_return", "mean"),
            realized_win_rate=("signed_forward_return", lambda s: float((s > 0).mean())),
            total_notional=("notional", "sum"),
        )
        summary = summary[summary["trades"] >= cfg.min_wallet_history].copy()
        if summary.empty:
            return summary.reset_index().rename(columns={"proxy_wallet": "wallet"})

        summary["informed_trader_rank_score"] = (
            0.45 * summary["recent_skill"].clip(lower=0.0)
            + 0.35 * summary["realized_edge"].clip(lower=0.0)
            + 0.20 * np.log1p(summary["total_notional"])
        )
        summary = summary.sort_values("informed_trader_rank_score", ascending=False).head(top_n)
        return summary.reset_index().rename(columns={"proxy_wallet": "wallet"})

    def market_informed_trader_metrics(
        self,
        trades: pd.DataFrame | Iterable[Mapping[str, Any]] | Iterable[PublicTrade],
        *,
        signals: Sequence[InformedTraderSignal] | None = None,
        config: InformedTraderFlowConfig | None = None,
    ) -> pd.DataFrame:
        """Summarize per-market informed-trader participation metrics."""
        cfg = config or self.config
        features = self._ensure_feature_frame(trades, cfg)
        columns = [
            "condition_id",
            "slug",
            "trades",
            "assets",
            "market_wallets",
            "informed_trader_wallets",
            "informed_trader_wallet_share",
            "informed_trader_signals",
            "signals_per_informed_trader_wallet",
        ]
        if features.empty:
            return pd.DataFrame(columns=columns)
        if "condition_id" not in features.columns:
            raise ValueError("Feature frame must include condition_id for market metrics.")
        if "proxy_wallet" not in features.columns:
            raise ValueError("Feature frame must include proxy_wallet for informed-trader metrics.")

        base = features.copy()
        base["condition_id"] = base["condition_id"].astype(str)
        base["proxy_wallet"] = base["proxy_wallet"].astype(str)
        if "slug" not in base.columns:
            base["slug"] = ""
        base["slug"] = base["slug"].astype(str).replace("nan", "")

        if signals is None:
            signals = self._detect_signals_from_features(base, cfg)

        informed_trader_wallets_by_cid: dict[str, set[str]] = {}
        informed_trader_signal_count_by_cid: dict[str, int] = {}
        for signal in signals:
            cid = str(signal.condition_id)
            informed_trader_wallets_by_cid.setdefault(cid, set()).add(str(signal.trigger_wallet))
            informed_trader_signal_count_by_cid[cid] = (
                informed_trader_signal_count_by_cid.get(cid, 0) + 1
            )

        rows: list[dict[str, Any]] = []
        for cid, subset in base.groupby("condition_id", sort=False):
            slug_series = subset["slug"].replace("", np.nan).dropna().astype(str)
            slug = str(slug_series.value_counts().idxmax()) if not slug_series.empty else ""

            market_wallets = int(subset["proxy_wallet"].nunique())
            informed_trader_wallets = int(len(informed_trader_wallets_by_cid.get(str(cid), set())))
            informed_trader_signals = int(informed_trader_signal_count_by_cid.get(str(cid), 0))
            informed_trader_wallet_share = (
                float(informed_trader_wallets / market_wallets) if market_wallets > 0 else 0.0
            )
            signals_per_informed_trader_wallet = (
                float(informed_trader_signals / informed_trader_wallets)
                if informed_trader_wallets > 0
                else 0.0
            )

            rows.append(
                {
                    "condition_id": str(cid),
                    "slug": slug,
                    "trades": int(len(subset)),
                    "assets": int(subset["asset"].nunique()) if "asset" in subset.columns else 0,
                    "market_wallets": market_wallets,
                    "informed_trader_wallets": informed_trader_wallets,
                    "informed_trader_wallet_share": informed_trader_wallet_share,
                    "informed_trader_signals": informed_trader_signals,
                    "signals_per_informed_trader_wallet": signals_per_informed_trader_wallet,
                }
            )

        if not rows:
            return pd.DataFrame(columns=columns)

        return (
            pd.DataFrame(rows)
            .sort_values(
                ["informed_trader_wallets", "informed_trader_signals", "trades"],
                ascending=[False, False, False],
            )
            .reset_index(drop=True)
        )

    def plot_informed_trader_backtest(
        self,
        trades: pd.DataFrame | Iterable[Mapping[str, Any]] | Iterable[PublicTrade],
        *,
        signals: Sequence[InformedTraderSignal] | None = None,
        result: BacktestResult | None = None,
        detector_config: InformedTraderFlowConfig | None = None,
        backtest_config: BacktestConfig | None = None,
        output_path: str | Path | None = None,
        top_assets: int = 2,
        combine_assets: bool = False,
        settlements: Mapping[str, Mapping[str, Any]] | None = None,
    ):
        """
        Visualize informed trader signals and backtest performance.

        Produces:
        1) Equity curve by completed backtest trades
        2) Price + signal markers (+ informed trader score) for top traded assets

        Notes:
        - For binary markets, a "short" signal is plotted on the opposite outcome token
          (i.e., BUY NO to express short YES).
        """
        cfg = detector_config or self.config
        bt_cfg = backtest_config or BacktestConfig()
        features = self._ensure_feature_frame(trades, cfg)
        if signals is None:
            signals = self._detect_signals_from_features(features, cfg)
        if result is None:
            result = self._backtest_on_features(
                features, list(signals), bt_cfg, settlements=settlements
            )

        import matplotlib.pyplot as plt

        opposite_asset, opposite_outcome = _build_binary_opposites(features)

        signal_rows = pd.DataFrame(
            [
                {
                    "signal_ts": s.timestamp,
                    "condition_id": s.condition_id,
                    "view_asset": s.asset,
                    "view_outcome": s.outcome,
                    "view_side": s.side,
                    "score": s.score,
                }
                for s in signals
            ]
        )

        if signal_rows.empty:
            asset_counts = features["asset"].value_counts()
            assets = list(asset_counts.head(max(1, top_assets)).index)
            marker_rows = signal_rows
        else:
            signal_rows["traded_asset"] = signal_rows["view_asset"]
            signal_rows["traded_outcome"] = signal_rows["view_outcome"]
            signal_rows["traded_side"] = signal_rows["view_side"]

            short_mask = signal_rows["view_side"] == "short"
            if short_mask.any():
                traded_assets = []
                traded_outcomes = []
                for row in signal_rows.loc[short_mask].itertuples(index=False):
                    key = (str(row.condition_id), str(row.view_asset))
                    traded_assets.append(opposite_asset.get(key))
                    if row.view_outcome is None:
                        traded_outcomes.append(None)
                    else:
                        traded_outcomes.append(
                            opposite_outcome.get((str(row.condition_id), str(row.view_outcome)))
                        )
                signal_rows.loc[short_mask, "traded_asset"] = traded_assets
                signal_rows.loc[short_mask, "traded_outcome"] = traded_outcomes
                signal_rows.loc[short_mask, "traded_side"] = "long"

            # Drop signals we can't plot as executable (no opposite token in provided data).
            marker_rows = signal_rows.dropna(subset=["traded_asset"]).copy()

            # Lookup marker timestamps/prices on the traded token series (forward in time).
            marker_rows["marker_ts"] = pd.to_datetime(marker_rows["signal_ts"], utc=True)
            marker_rows["marker_price"] = np.nan
            for asset, subset in marker_rows.groupby("traded_asset", sort=False):
                series = features[features["asset"] == asset][["timestamp", "price"]].sort_values(
                    "timestamp"
                )
                if series.empty:
                    continue
                targets = subset[["marker_ts"]].rename(columns={"marker_ts": "target_ts"})
                lookup = series.rename(columns={"timestamp": "series_ts", "price": "series_price"})
                merged = pd.merge_asof(
                    targets.sort_values("target_ts"),
                    lookup,
                    left_on="target_ts",
                    right_on="series_ts",
                    direction="forward",
                )
                marker_rows.loc[subset.index, "marker_ts"] = merged["series_ts"].to_numpy()
                marker_rows.loc[subset.index, "marker_price"] = merged["series_price"].to_numpy()

            marker_rows = marker_rows.dropna(subset=["marker_ts", "marker_price"])

            asset_counts = marker_rows["traded_asset"].value_counts()
            long_counts = marker_rows[marker_rows["view_side"] == "long"][
                "traded_asset"
            ].value_counts()
            short_counts = marker_rows[marker_rows["view_side"] == "short"][
                "traded_asset"
            ].value_counts()

            # Pick assets so we show shorts when they exist (common issue: top-N by count are all longs).
            if top_assets <= 0:
                top_assets = 1

            if top_assets == 1:
                assets = list(asset_counts.head(1).index)
            else:
                assets = []
                for a in long_counts.index:
                    if a in assets:
                        continue
                    assets.append(a)
                    if len(assets) >= max(1, top_assets - 1):
                        break

                if len(assets) < top_assets:
                    for a in short_counts.index:
                        if a in assets:
                            continue
                        assets.append(a)
                        break

                if len(assets) < top_assets:
                    for a in asset_counts.index:
                        if a in assets:
                            continue
                        assets.append(a)
                        if len(assets) >= top_assets:
                            break

        n_rows = 2 if combine_assets else 1 + len(assets)
        fig, axes = plt.subplots(n_rows, 1, figsize=(14, max(5, 4 * n_rows)))
        if n_rows == 1:
            axes = [axes]

        equity_ax = axes[0]
        if result.trades:
            trade_df = pd.DataFrame(
                [
                    {
                        "exit_time": t.exit_time,
                        "pnl": t.pnl,
                    }
                    for t in result.trades
                ]
            ).sort_values("exit_time")
            trade_df["equity"] = bt_cfg.initial_capital + trade_df["pnl"].cumsum()
            equity_ax.plot(
                trade_df["exit_time"],
                trade_df["equity"],
                color="#1565C0",
                linewidth=2.0,
                label="Equity",
            )
            equity_ax.axhline(
                bt_cfg.initial_capital, color="#666666", linestyle="--", linewidth=1.0
            )
            equity_ax.set_title(
                (
                    f"Backtest Equity Curve | Trades: {result.n_trades} | "
                    f"PnL: {result.total_pnl:,.2f} | Return: {result.return_pct * 100:.2f}%"
                ),
                fontsize=12,
            )
            equity_ax.legend(loc="best")
        else:
            equity_ax.set_title("Backtest Equity Curve (no completed trades)", fontsize=12)
            equity_ax.axhline(
                bt_cfg.initial_capital, color="#666666", linestyle="--", linewidth=1.0
            )
        equity_ax.set_ylabel("Capital")
        equity_ax.grid(alpha=0.25)

        if combine_assets:
            ax = axes[1]
            ax2 = ax.twinx()

            palette = plt.get_cmap("tab10")
            added_long_label = False
            added_short_label = False
            added_score_label = False

            for idx, asset in enumerate(assets):
                asset_df = features[features["asset"] == asset].sort_values("timestamp")
                if asset_df.empty:
                    continue

                base_price = float(asset_df["price"].iloc[0])
                base_price = base_price if base_price > 0 else 1.0

                slug_series = asset_df["slug"].dropna().astype(str)
                slug = slug_series.value_counts().idxmax() if not slug_series.empty else asset[:12]

                outcome_series = asset_df["outcome"].replace("nan", np.nan).dropna().astype(str)
                outcome = (
                    outcome_series.value_counts().idxmax()
                    if not outcome_series.empty
                    else "outcome"
                )

                color = palette(idx % 10)
                ax.plot(
                    asset_df["timestamp"],
                    asset_df["price"] / base_price,
                    color=color,
                    linewidth=1.4,
                    label=f"{slug} [{outcome}]",
                )

                asset_signals = marker_rows[marker_rows["traded_asset"] == asset]
                if not asset_signals.empty:
                    long_view = asset_signals[asset_signals["view_side"] == "long"]
                    short_view = asset_signals[asset_signals["view_side"] == "short"]
                    if not long_view.empty:
                        ax.scatter(
                            long_view["marker_ts"],
                            long_view["marker_price"] / base_price,
                            marker="^",
                            s=45,
                            color="#2E7D32",
                            edgecolors=color,
                            linewidths=0.6,
                            label="Long signal" if not added_long_label else "_nolegend_",
                            zorder=3,
                        )
                        added_long_label = True
                    if not short_view.empty:
                        ax.scatter(
                            short_view["marker_ts"],
                            short_view["marker_price"] / base_price,
                            marker="v",
                            s=45,
                            color="#C62828",
                            edgecolors=color,
                            linewidths=0.6,
                            label="Short signal" if not added_short_label else "_nolegend_",
                            zorder=3,
                        )
                        added_short_label = True

                ax2.plot(
                    asset_df["timestamp"],
                    asset_df["informed_trader_score"],
                    color="#F9A825",
                    linewidth=1.0,
                    alpha=0.35,
                    label="Informed trader score" if not added_score_label else "_nolegend_",
                )
                added_score_label = True

            ax2.axhline(cfg.signal_threshold, color="#EF6C00", linestyle="--", linewidth=1.0)
            ax.set_title("Combined: Indexed Price (t0=1.0) + Informed Trader Signals")
            ax.set_ylabel("Indexed Price")
            ax2.set_ylabel("Informed Trader Score")
            ax2.set_ylim(bottom=0)
            ax.grid(alpha=0.20)

            handles, labels = ax.get_legend_handles_labels()
            handles2, labels2 = ax2.get_legend_handles_labels()
            ax.legend(handles + handles2, labels + labels2, loc="upper left", fontsize=8)
        else:
            for i, asset in enumerate(assets, start=1):
                ax = axes[i]
                asset_df = features[features["asset"] == asset].sort_values("timestamp")
                if asset_df.empty:
                    ax.set_title(f"Asset {asset} (no data)")
                    continue

                ax.plot(
                    asset_df["timestamp"],
                    asset_df["price"],
                    color="#1E88E5",
                    linewidth=1.2,
                    label="Price",
                )

                asset_signals = marker_rows[marker_rows["traded_asset"] == asset]
                if not asset_signals.empty:
                    long_view = asset_signals[asset_signals["view_side"] == "long"]
                    short_view = asset_signals[asset_signals["view_side"] == "short"]
                    if not long_view.empty:
                        ax.scatter(
                            long_view["marker_ts"],
                            long_view["marker_price"],
                            marker="^",
                            s=45,
                            color="#2E7D32",
                            label="Long signal",
                            zorder=3,
                        )
                    if not short_view.empty:
                        ax.scatter(
                            short_view["marker_ts"],
                            short_view["marker_price"],
                            marker="v",
                            s=45,
                            color="#C62828",
                            label="Short signal",
                            zorder=3,
                        )

                ax2 = ax.twinx()
                ax2.plot(
                    asset_df["timestamp"],
                    asset_df["informed_trader_score"],
                    color="#F9A825",
                    linewidth=1.0,
                    alpha=0.8,
                    label="Informed trader score",
                )
                ax2.axhline(cfg.signal_threshold, color="#EF6C00", linestyle="--", linewidth=1.0)
                ax2.set_ylabel("Informed Trader Score")
                ax2.set_ylim(bottom=0)

                ax.set_title(f"Asset {asset}: Price + Informed Trader Signals")
                ax.set_ylabel("Price")
                ax.grid(alpha=0.20)

                handles, labels = ax.get_legend_handles_labels()
                handles2, labels2 = ax2.get_legend_handles_labels()
                ax.legend(handles + handles2, labels + labels2, loc="upper left", fontsize=8)

        fig.tight_layout()
        if output_path:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(path, dpi=150, bbox_inches="tight")
        return fig

    def _add_forward_returns(self, df: pd.DataFrame, horizon_minutes: int) -> pd.DataFrame:
        out = df.sort_values("timestamp").reset_index(drop=True).copy()
        if horizon_minutes <= 0:
            out["future_price"] = out["price"]
            out["forward_return"] = 0.0
            out["signed_forward_return"] = 0.0
            return out

        horizon = pd.Timedelta(minutes=horizon_minutes)
        groups: List[pd.DataFrame] = []

        for _, asset_df in out.groupby("asset", sort=False):
            g = asset_df.sort_values("timestamp").reset_index(drop=True).copy()
            targets = pd.DataFrame({"target_ts": g["timestamp"] + horizon})
            lookup = g[["timestamp", "price"]].rename(
                columns={"timestamp": "future_ts", "price": "future_price"}
            )
            merged = pd.merge_asof(
                targets,
                lookup,
                left_on="target_ts",
                right_on="future_ts",
                direction="forward",
            )
            g["future_price"] = merged["future_price"].to_numpy()
            groups.append(g)

        out = pd.concat(groups, ignore_index=True).sort_values("timestamp").reset_index(drop=True)
        out["forward_return"] = np.where(
            out["future_price"].notna(),
            (out["future_price"] - out["price"]) / out["price"].clip(lower=1e-8),
            np.nan,
        )
        out["signed_forward_return"] = out["direction"] * out["forward_return"]
        return out

    def _add_wallet_skill_online(
        self, df: pd.DataFrame, config: InformedTraderFlowConfig
    ) -> pd.DataFrame:
        out = df.sort_values("timestamp").reset_index(drop=True).copy()

        wallet_skill = np.zeros(len(out), dtype=float)
        wallet_obs = np.zeros(len(out), dtype=int)
        wallet_edge = np.zeros(len(out), dtype=float)
        wallet_vol = np.zeros(len(out), dtype=float)

        stats: Dict[str, tuple[int, float, float]] = {}
        pending: List[tuple[int, str, float]] = []
        horizon_ns = int(pd.Timedelta(minutes=max(config.horizon_minutes, 0)).value)

        ts_ns = out["timestamp"].astype("int64").to_numpy()
        wallets = out["proxy_wallet"].astype(str).to_numpy()
        realized = out["signed_forward_return"].to_numpy(dtype=float)

        for i, current_ns in enumerate(ts_ns):
            while pending and pending[0][0] <= current_ns:
                _, wallet, value = heapq.heappop(pending)
                if np.isnan(value):
                    continue
                n, mean, m2 = stats.get(wallet, (0, 0.0, 0.0))
                n += 1
                delta = value - mean
                mean += delta / n
                delta2 = value - mean
                m2 += delta * delta2
                stats[wallet] = (n, mean, m2)

            wallet = wallets[i]
            n, mean, m2 = stats.get(wallet, (0, 0.0, 0.0))
            wallet_obs[i] = n

            vol = np.sqrt(m2 / (n - 1)) if n > 1 else config.edge_vol_floor
            edge = mean
            standardized_edge = edge / (vol + config.edge_vol_floor)
            shrink = n / (n + config.prior_count) if (n + config.prior_count) > 0 else 0.0
            wallet_skill[i] = float(np.tanh(standardized_edge) * shrink)
            wallet_edge[i] = edge
            wallet_vol[i] = vol

            maturity_ns = int(current_ns + horizon_ns)
            heapq.heappush(pending, (maturity_ns, wallet, float(realized[i])))

        out["wallet_obs"] = wallet_obs
        out["wallet_edge"] = wallet_edge
        out["wallet_vol"] = wallet_vol
        out["wallet_skill"] = wallet_skill
        return out

    def _detect_signals_from_features(
        self,
        features: pd.DataFrame,
        config: InformedTraderFlowConfig,
    ) -> List[InformedTraderSignal]:
        signals: List[InformedTraderSignal] = []
        if features.empty:
            return signals

        cooldown_seconds = max(config.cooldown_minutes, 0) * 60.0
        last_signal_ts: Dict[str, pd.Timestamp] = {}

        for row in features.itertuples(index=False):
            if not bool(row.eligible_signal):
                continue
            if float(row.informed_trader_score) < config.signal_threshold:
                continue
            if config.long_only and float(row.direction_score) <= 0:
                continue

            asset = str(row.asset)
            now = pd.Timestamp(row.timestamp)
            last = last_signal_ts.get(asset)
            if last is not None:
                if (now - last).total_seconds() < cooldown_seconds:
                    continue

            side = "long" if float(row.direction_score) >= 0 else "short"
            signal = InformedTraderSignal(
                timestamp=now,
                asset=asset,
                condition_id=str(row.condition_id),
                outcome=None if str(row.outcome) == "nan" else str(row.outcome),
                side=side,
                score=float(row.informed_trader_score),
                direction_score=float(row.direction_score),
                flow_ratio=float(row.flow_ratio),
                wallet_skill=float(row.wallet_skill),
                conviction_score=float(row.conviction_score),
                trigger_wallet=str(row.proxy_wallet),
                trigger_notional=float(row.notional),
                trigger_price=float(row.price),
                slug=None if str(row.slug) == "nan" else str(row.slug),
            )
            signals.append(signal)
            last_signal_ts[asset] = now

        return signals

    def _backtest_on_features(
        self,
        features: pd.DataFrame,
        signals: Sequence[InformedTraderSignal],
        config: BacktestConfig,
        *,
        start_time: pd.Timestamp | str | None = None,
        end_time: pd.Timestamp | str | None = None,
        settlements: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> BacktestResult:
        if features.empty or not signals:
            return self._empty_backtest(config.initial_capital)

        start_ts = _coerce_utc_timestamp(start_time)
        end_ts = _coerce_utc_timestamp(end_time)
        start_ns = int(start_ts.value) if start_ts is not None else None
        end_ns = int(end_ts.value) if end_ts is not None else None

        holding_ns = int(pd.Timedelta(minutes=max(config.holding_minutes, 1)).value)
        one_way_cost = (config.fee_bps + config.slippage_bps) / 10_000.0
        # Treat position_size as the gross cash outlay per trade (inclusive of fees/slippage).
        # Costs reduce effective fill size (and thus returns) but should not allow losses beyond -100%.
        one_way_cost = float(max(0.0, min(one_way_cost, 0.99)))
        entry_multiplier = 1.0 - one_way_cost
        exit_multiplier = 1.0 - one_way_cost

        opposite_asset, opposite_outcome = _build_binary_opposites(features)
        asset_to_outcome: dict[tuple[str, str], str] = {}
        if config.hold_to_expiry and "outcome" in features.columns:
            frame = features[["condition_id", "asset", "outcome"]].copy()
            frame["condition_id"] = frame["condition_id"].astype(str)
            frame["asset"] = frame["asset"].astype(str)
            frame["outcome"] = frame["outcome"].astype(str).replace("nan", np.nan)
            clean = frame.dropna(subset=["outcome"])
            if not clean.empty:
                grouped = clean.groupby(["condition_id", "asset"], sort=False)["outcome"].agg(
                    lambda s: s.value_counts().idxmax()
                )
                asset_to_outcome = {(cid, asset): out for (cid, asset), out in grouped.items()}

        asset_data: Dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for asset, group in features.groupby("asset", sort=False):
            ordered = _stable_sort_frame(group)
            ts = ordered["timestamp"].astype("int64").to_numpy()
            prices = ordered["price"].to_numpy(dtype=float)
            asset_data[str(asset)] = (ts, prices)

        completed: List[BacktestTrade] = []
        blocked_until: Dict[str, int] = {}
        cash = float(config.initial_capital)
        open_positions: List[tuple[int, float]] = []

        for signal in sorted(signals, key=lambda s: s.timestamp):
            signal_ns = int(pd.Timestamp(signal.timestamp).value)
            if start_ns is not None and signal_ns < start_ns:
                continue
            if end_ns is not None and signal_ns >= end_ns:
                continue

            # Free capital from any positions that have exited before this signal.
            while open_positions and open_positions[0][0] <= signal_ns:
                _, proceeds = heapq.heappop(open_positions)
                cash += float(proceeds)

            trade_asset = signal.asset
            trade_side = signal.side
            traded_outcome = signal.outcome

            if signal.side == "short":
                if not config.allow_short:
                    continue
                # Polymarket doesn't support naked shorting; express shorts by buying the opposite
                # outcome token in binary markets.
                key = (signal.condition_id, signal.asset)
                if key in opposite_asset:
                    trade_asset = opposite_asset[key]
                    trade_side = "long"
                    if signal.outcome is not None:
                        traded_outcome = opposite_outcome.get((signal.condition_id, signal.outcome))
                else:
                    # No binary opposite found in the provided data: can't model a real Polymarket short.
                    continue

            asset = trade_asset
            if asset not in asset_data:
                continue
            block_key = signal.condition_id or asset
            if blocked_until.get(block_key, -1) > signal_ns:
                continue

            ts, prices = asset_data[asset]
            entry_idx = int(np.searchsorted(ts, signal_ns, side="left"))
            if entry_idx >= len(ts):
                continue

            entry_time_ns = int(ts[entry_idx])
            entry_price = float(prices[entry_idx])
            if entry_price <= 0:
                continue

            cost = float(config.position_size)
            if not np.isfinite(cost) or cost <= 0:
                continue
            if cash < cost:
                continue
            invest_amount = cost * entry_multiplier
            if invest_amount <= 0:
                continue
            qty = invest_amount / entry_price
            if not np.isfinite(qty) or qty <= 0:
                continue

            if config.hold_to_expiry:
                if settlements is None:
                    raise ValueError(
                        "settlements must be provided when backtest_config.hold_to_expiry=True"
                    )

                settlement = settlements.get(str(signal.condition_id), {})
                winner = settlement.get("winner_outcome")
                expiry = settlement.get("expiry_time")
                if winner is None:
                    continue

                if traded_outcome is None:
                    traded_outcome = asset_to_outcome.get((str(signal.condition_id), asset))
                if traded_outcome is None:
                    continue

                # Hold until expiry and redeem (payout is 1 for winner, 0 otherwise).
                exit_price = 1.0 if str(traded_outcome) == str(winner) else 0.0
                raw_return = (exit_price - entry_price) / entry_price
                if trade_side == "short":
                    raw_return = -raw_return
                proceeds = float(qty * exit_price)
                pnl = float(proceeds - cost)
                net_return = float(pnl / cost) if cost else 0.0
                reason = "expiry"

                exit_time_ns = int(ts[-1])
                if expiry is not None:
                    expiry_ts = pd.Timestamp(expiry)
                    if expiry_ts.tzinfo is None:
                        expiry_ts = expiry_ts.tz_localize("UTC")
                    else:
                        expiry_ts = expiry_ts.tz_convert("UTC")
                    expiry_ns = int(expiry_ts.value)
                    if expiry_ns >= entry_time_ns:
                        exit_time_ns = expiry_ns

                exit_idx = entry_idx
                exit_time = pd.Timestamp(exit_time_ns, unit="ns", tz="UTC")
                exit_price_for_trade = float(exit_price)
            else:
                horizon_ns = entry_time_ns + holding_ns
                horizon_idx = int(np.searchsorted(ts, horizon_ns, side="right") - 1)
                if horizon_idx <= entry_idx:
                    continue

                exit_idx = horizon_idx
                reason = "time"
                path = prices[entry_idx + 1 : horizon_idx + 1]

                if len(path) > 0 and (
                    config.take_profit is not None or config.stop_loss is not None
                ):
                    relative = (path - entry_price) / entry_price
                    # TP/SL should be evaluated on the traded position, not the signal "view".
                    # (Short views are expressed as a long position in the opposite outcome token.)
                    if trade_side == "short":
                        relative = -relative

                    tp_hit = None
                    sl_hit = None
                    if config.take_profit is not None:
                        tp_positions = np.where(relative >= config.take_profit)[0]
                        if len(tp_positions) > 0:
                            tp_hit = int(tp_positions[0])
                    if config.stop_loss is not None:
                        sl_positions = np.where(relative <= -config.stop_loss)[0]
                        if len(sl_positions) > 0:
                            sl_hit = int(sl_positions[0])

                    if tp_hit is not None and sl_hit is not None:
                        hit = min(tp_hit, sl_hit)
                        exit_idx = entry_idx + 1 + hit
                        reason = "take_profit" if tp_hit <= sl_hit else "stop_loss"
                    elif tp_hit is not None:
                        exit_idx = entry_idx + 1 + tp_hit
                        reason = "take_profit"
                    elif sl_hit is not None:
                        exit_idx = entry_idx + 1 + sl_hit
                        reason = "stop_loss"

                exit_price_for_trade = float(prices[exit_idx])
                raw_return = (exit_price_for_trade - entry_price) / entry_price
                if trade_side == "short":
                    raw_return = -raw_return
                proceeds = float(qty * exit_price_for_trade * exit_multiplier)
                pnl = float(proceeds - cost)
                net_return = float(pnl / cost) if cost else 0.0
                exit_time = pd.Timestamp(ts[exit_idx], unit="ns", tz="UTC")

            trade = BacktestTrade(
                asset=asset,
                side=trade_side,
                view_asset=signal.asset,
                view_side=signal.side,
                view_outcome=signal.outcome,
                traded_outcome=traded_outcome,
                signal_time=pd.Timestamp(signal.timestamp),
                entry_time=pd.Timestamp(ts[entry_idx], unit="ns", tz="UTC"),
                exit_time=exit_time,
                entry_price=entry_price,
                exit_price=exit_price_for_trade,
                raw_return=float(raw_return),
                net_return=float(net_return),
                pnl=float(pnl),
                reason=reason,
                score=signal.score,
            )
            completed.append(trade)
            blocked_until[block_key] = int(trade.exit_time.value)
            cash -= cost
            heapq.heappush(open_positions, (int(trade.exit_time.value), proceeds))

        if not completed:
            return self._empty_backtest(config.initial_capital)

        # Settle remaining open positions (latest proceeds are already baked in).
        while open_positions:
            _, proceeds = heapq.heappop(open_positions)
            cash += float(proceeds)

        returns = np.array([t.net_return for t in completed], dtype=float)
        pnls = np.array([t.pnl for t in completed], dtype=float)

        ending_capital = float(cash)
        total_pnl = float(ending_capital - float(config.initial_capital))
        return_pct = float(total_pnl / config.initial_capital) if config.initial_capital else 0.0
        n_trades = len(completed)
        win_rate = float((pnls > 0).mean())
        avg_return = float(returns.mean())
        std_return = float(returns.std(ddof=1)) if n_trades > 1 else 0.0
        sharpe = float((avg_return / std_return) * np.sqrt(n_trades)) if std_return > 0 else 0.0

        gross_profit = float(pnls[pnls > 0].sum())
        gross_loss = float(abs(pnls[pnls < 0].sum()))
        if gross_loss > 0:
            profit_factor = gross_profit / gross_loss
        elif gross_profit > 0:
            profit_factor = float("inf")
        else:
            profit_factor = 0.0

        equity = config.initial_capital
        peak = equity
        max_drawdown = 0.0
        for trade in sorted(completed, key=lambda t: t.exit_time):
            equity += trade.pnl
            peak = max(peak, equity)
            if peak > 0:
                max_drawdown = max(max_drawdown, (peak - equity) / peak)

        return BacktestResult(
            total_pnl=total_pnl,
            ending_capital=ending_capital,
            return_pct=return_pct,
            n_trades=n_trades,
            win_rate=win_rate,
            avg_return=avg_return,
            sharpe=sharpe,
            max_drawdown=float(max_drawdown),
            profit_factor=float(profit_factor),
            trades=completed,
        )

    def _ensure_feature_frame(self, frame: Any, config: InformedTraderFlowConfig) -> pd.DataFrame:
        if isinstance(frame, pd.DataFrame) and self._FEATURE_COLUMNS.issubset(frame.columns):
            return _stable_sort_frame(frame.copy())
        return self.engineer_features(frame, config)

    def _expand_param_grid(
        self, param_grid: Mapping[str, Sequence[Any]] | None
    ) -> List[Dict[str, Any]]:
        fields = set(InformedTraderFlowConfig.__dataclass_fields__.keys())
        grid = dict(param_grid or self._DEFAULT_GRID)
        unknown = sorted(set(grid.keys()) - fields)
        if unknown:
            raise ValueError(f"Unknown optimization parameters: {', '.join(unknown)}")

        keys = sorted(grid.keys())
        values = [grid[k] for k in keys]
        return [dict(zip(keys, combo)) for combo in product(*values)]

    def _objective(
        self,
        train_result: BacktestResult,
        test_result: BacktestResult,
        config: BacktestConfig,
    ) -> float:
        penalty = config.initial_capital * 0.50 * test_result.max_drawdown
        low_sample_penalty = 50.0 if test_result.n_trades < 2 else 0.0
        return (
            test_result.total_pnl
            + 0.25 * train_result.total_pnl
            + 5.0 * test_result.sharpe
            - penalty
            - low_sample_penalty
        )

    @staticmethod
    def _empty_backtest(initial_capital: float) -> BacktestResult:
        return BacktestResult(
            total_pnl=0.0,
            ending_capital=initial_capital,
            return_pct=0.0,
            n_trades=0,
            win_rate=0.0,
            avg_return=0.0,
            sharpe=0.0,
            max_drawdown=0.0,
            profit_factor=0.0,
            trades=[],
        )


def _coerce_utc_timestamp(value: pd.Timestamp | str | None) -> pd.Timestamp | None:
    if value is None:
        return None
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _stable_sort_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Stable, deterministic sort used across the pipeline.

    Sorting only on timestamp can reorder ties differently depending on which rows are present
    (e.g., per-market subsets vs a combined dataset). That can change online wallet-skill updates
    and backtest entry/exit indexing. Use a stable sort with tie-breakers to make runs reproducible.
    """
    if df.empty:
        return df.reset_index(drop=True)

    sort_cols = [
        "timestamp",
        "condition_id",
        "asset",
        "proxy_wallet",
        "side",
        "price",
        "size",
    ]
    sort_cols = [c for c in sort_cols if c in df.columns]
    if not sort_cols:
        return df.reset_index(drop=True)

    return df.sort_values(sort_cols, kind="mergesort").reset_index(drop=True)


def _looks_like_condition_id(value: str) -> bool:
    return value.startswith("0x") and len(value) >= 42


def _build_binary_opposites(
    features: pd.DataFrame,
) -> tuple[dict[tuple[str, str], str], dict[tuple[str, str], str]]:
    """
    Build mappings to express shorts as buying the opposite outcome in binary markets.

    Returns:
    - opposite_asset: (condition_id, asset) -> opposite_asset
    - opposite_outcome: (condition_id, outcome) -> opposite_outcome
    """
    if features.empty or "condition_id" not in features.columns:
        return {}, {}

    opposite_asset: dict[tuple[str, str], str] = {}
    opposite_outcome: dict[tuple[str, str], str] = {}

    if "outcome" not in features.columns:
        return opposite_asset, opposite_outcome

    frame = features[["condition_id", "asset", "outcome"]].copy()
    frame["condition_id"] = frame["condition_id"].astype(str)
    frame["asset"] = frame["asset"].astype(str)
    frame["outcome"] = frame["outcome"].astype(str).replace("nan", np.nan)

    for condition_id, group in frame.groupby("condition_id", sort=False):
        clean = group.dropna(subset=["outcome"])
        if clean.empty:
            continue

        # Dominant outcome label per asset (robust to noisy/missing outcome values).
        asset_to_outcome = clean.groupby("asset", sort=False)["outcome"].agg(
            lambda s: s.value_counts().idxmax()
        )
        assets = list(asset_to_outcome.index)
        outcomes = list(asset_to_outcome.values)

        if len(assets) != 2:
            continue
        if len(set(outcomes)) != 2:
            continue

        a1, a2 = assets
        o1, o2 = outcomes[0], outcomes[1]

        opposite_asset[(condition_id, a1)] = a2
        opposite_asset[(condition_id, a2)] = a1
        opposite_outcome[(condition_id, o1)] = o2
        opposite_outcome[(condition_id, o2)] = o1

    return opposite_asset, opposite_outcome
