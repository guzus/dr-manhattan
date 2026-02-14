"""
Polymarket bot classification utilities.

Analysis-only: feature engineering, clustering, bot scoring.
Data fetching uses dr_manhattan.Polymarket directly.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import entropy as scipy_entropy
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.ensemble import IsolationForest
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

FEATURE_COLS = [
    'n_trades', 'trades_per_hour', 'median_interval_sec', 'cv_interval',
    'min_interval_sec', 'mean_size', 'cv_size', 'pct_round_sizes',
    'hour_entropy', 'pct_zero_seconds', 'active_hours',
    'n_markets', 'market_concentration', 'buy_ratio',
    'mean_price', 'distance_from_mid', 'pct_extreme_prices',
    'has_name', 'has_bio', 'total_volume_usd',
]


# ─────────────────────────────────────────────
# Per-Wallet Feature Engineering
# ─────────────────────────────────────────────
def compute_wallet_features(wallet_trades: pd.DataFrame) -> dict:
    """Compute ~20 behavioral features for a single wallet's trades."""
    df = wallet_trades.sort_values('timestamp').reset_index(drop=True)
    n = len(df)

    # ── Frequency ──
    ts = df['timestamp']
    if n >= 2:
        intervals = ts.diff().dt.total_seconds().dropna()
        intervals = intervals[intervals >= 0]
        median_interval = intervals.median() if len(intervals) > 0 else np.nan
        mean_interval = intervals.mean() if len(intervals) > 0 else np.nan
        std_interval = intervals.std() if len(intervals) > 0 else np.nan
        cv_interval = (std_interval / mean_interval) if mean_interval > 0 else np.nan
        min_interval = intervals.min() if len(intervals) > 0 else np.nan
    else:
        median_interval = np.nan
        cv_interval = np.nan
        min_interval = np.nan

    span_h = (ts.max() - ts.min()).total_seconds() / 3600
    trades_per_hour = n / max(span_h, 1 / 3600)

    # ── Size ──
    sizes = df['size']
    mean_size = sizes.mean()
    cv_size = (sizes.std() / mean_size) if mean_size > 0 else np.nan
    pct_round_sizes = ((sizes % 1 == 0) | (sizes % 5 == 0) | (sizes % 10 == 0)).mean()

    # ── Timing ──
    hours = ts.dt.hour
    hour_counts = hours.value_counts(normalize=True).reindex(range(24), fill_value=0)
    hour_entropy = scipy_entropy(hour_counts.values + 1e-10)
    pct_zero_seconds = (ts.dt.second == 0).mean()
    active_hours = (hour_counts > 0).sum()

    # ── Market ──
    n_markets = df['condition_id'].nunique()
    mc = df['condition_id'].value_counts(normalize=True)
    market_concentration = (mc ** 2).sum()  # HHI
    buy_ratio = (df['side'].str.upper() == 'BUY').mean()

    # ── Price ──
    prices = df['price']
    mean_price = prices.mean()
    distance_from_mid = (prices - 0.5).abs().mean()
    pct_extreme_prices = ((prices < 0.1) | (prices > 0.9)).mean()

    # ── Profile ──
    has_name = int(df['name'].notna().any() and df['name'].iloc[0] not in ('', None))
    has_bio = int(df['bio'].notna().any() and df['bio'].iloc[0] not in ('', None))

    # ── Volume ──
    total_volume_usd = (df['size'] * df['price']).sum()

    return {
        'n_trades': n,
        'trades_per_hour': trades_per_hour,
        'median_interval_sec': median_interval,
        'cv_interval': cv_interval,
        'min_interval_sec': min_interval,
        'mean_size': mean_size,
        'cv_size': cv_size,
        'pct_round_sizes': pct_round_sizes,
        'hour_entropy': hour_entropy,
        'pct_zero_seconds': pct_zero_seconds,
        'active_hours': active_hours,
        'n_markets': n_markets,
        'market_concentration': market_concentration,
        'buy_ratio': buy_ratio,
        'mean_price': mean_price,
        'distance_from_mid': distance_from_mid,
        'pct_extreme_prices': pct_extreme_prices,
        'has_name': has_name,
        'has_bio': has_bio,
        'total_volume_usd': total_volume_usd,
    }


def build_group_features(
    trades_df: pd.DataFrame,
    min_trades: int = 5,
) -> pd.DataFrame:
    """Compute features for every qualifying wallet in a trades DataFrame."""
    if len(trades_df) == 0:
        return pd.DataFrame()

    rows = []
    for wallet, wdf in trades_df.groupby('proxy_wallet'):
        if len(wdf) < min_trades:
            continue
        feats = compute_wallet_features(wdf)
        feats['proxy_wallet'] = wallet
        rows.append(feats)

    if not rows:
        return pd.DataFrame()

    fdf = pd.DataFrame(rows).set_index('proxy_wallet')
    fdf = fdf.fillna(fdf.median(numeric_only=True))
    return fdf


# ─────────────────────────────────────────────
# Clustering
# ─────────────────────────────────────────────
def run_clustering(
    features_df: pd.DataFrame,
    group_name: str,
    max_k: int = 8,
) -> pd.DataFrame:
    """K-Means with auto K selection (silhouette) + PCA 2D projection."""
    if len(features_df) < 4:
        print(f"  [{group_name}] too few wallets ({len(features_df)}), skipping")
        features_df['cluster'] = 0
        features_df['pca_x'] = 0.0
        features_df['pca_y'] = 0.0
        return features_df

    cols = [c for c in FEATURE_COLS if c in features_df.columns]
    X = features_df[cols].values

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    X_scaled = np.nan_to_num(X_scaled, nan=0.0, posinf=0.0, neginf=0.0)

    upper_k = min(max_k, len(features_df) - 1)
    best_k, best_score = 2, -1
    scores: dict[int, float] = {}

    for k in range(2, upper_k + 1):
        km = KMeans(n_clusters=k, n_init=10, random_state=42)
        labels = km.fit_predict(X_scaled)
        if len(set(labels)) < 2:
            continue
        sc = silhouette_score(X_scaled, labels)
        scores[k] = sc
        if sc > best_score:
            best_score = sc
            best_k = k

    print(f"  [{group_name}] silhouette: {scores}")
    print(f"  [{group_name}] best K={best_k} (score={best_score:.3f})")

    km_final = KMeans(n_clusters=best_k, n_init=10, random_state=42)
    features_df['cluster'] = km_final.fit_predict(X_scaled)

    pca = PCA(n_components=2, random_state=42)
    coords = pca.fit_transform(X_scaled)
    features_df['pca_x'] = coords[:, 0]
    features_df['pca_y'] = coords[:, 1]
    print(f"  [{group_name}] PCA var explained: {pca.explained_variance_ratio_}")

    return features_df


# ─────────────────────────────────────────────
# Bot Characterization (cluster-level, z-score)
# ─────────────────────────────────────────────

# higher value → more bot-like
_BOT_HIGH = [
    'n_trades', 'trades_per_hour', 'n_markets', 'active_hours',
    'hour_entropy', 'total_volume_usd',
]
# lower value → more bot-like
_BOT_LOW = [
    'median_interval_sec', 'min_interval_sec', 'cv_size', 'market_concentration',
]


def characterize_cluster(
    cluster_df: pd.DataFrame,
    group_df: pd.DataFrame,
) -> tuple[str, float, list[str]]:
    """Z-score composite bot scoring for a cluster.

    Compares cluster mean to group distribution. Uses magnitude of
    deviation so marginal differences score low, extreme outliers high.
    """
    score = 0.0
    reasons: list[str] = []

    def _z(col: str) -> float:
        std = group_df[col].std()
        if std == 0:
            return 0.0
        return (cluster_df[col].mean() - group_df[col].mean()) / std

    # ── Bot signals ──
    for col in _BOT_HIGH:
        if col not in group_df.columns:
            continue
        zs = _z(col)
        if zs > 0.5:
            score += min(zs, 3.0)
            reasons.append(f'{col} z=+{zs:.1f}')

    for col in _BOT_LOW:
        if col not in group_df.columns:
            continue
        zs = _z(col)
        if zs < -0.5:
            score += min(abs(zs), 3.0)
            reasons.append(f'{col} z={zs:.1f}')

    has_prof = cluster_df[['has_name', 'has_bio']].mean().mean()
    if has_prof < 0.15:
        score += 0.5
        reasons.append(f'no profile ({has_prof:.2f})')

    # ── Human signals ──
    for col in ['n_trades', 'n_markets']:
        zs = _z(col)
        if zs < -0.5:
            score -= min(abs(zs), 2.0)
            reasons.append(f'low {col} z={zs:.1f}')

    zs_int = _z('median_interval_sec')
    if zs_int > 0.5:
        score -= min(zs_int, 2.0)
        reasons.append(f'slow interval z=+{zs_int:.1f}')

    score = round(score, 1)

    if score >= 3.0:
        label = 'BOT'
    elif score >= 1.0:
        label = 'MIXED'
    else:
        label = 'HUMAN'

    return label, score, reasons


def label_clusters(
    features_df: pd.DataFrame,
    group_desc: str,
) -> tuple[pd.DataFrame, dict[int, str]]:
    """Run characterize_cluster on each cluster, add bot_label column."""
    labels: dict[int, str] = {}

    print(f"\n[{group_desc}]")
    for c in sorted(features_df['cluster'].unique()):
        cdf = features_df[features_df['cluster'] == c]
        label, score, reasons = characterize_cluster(cdf, features_df)
        labels[c] = label
        print(f"  Cluster {c} ({len(cdf)} wallets): {label} (score={score})")
        for r in reasons:
            print(f"    - {r}")

    features_df['bot_label'] = features_df['cluster'].map(labels)
    return features_df, labels


# ─────────────────────────────────────────────
# Per-Wallet Bot Detection
# ─────────────────────────────────────────────
def compute_bot_score(features_df: pd.DataFrame) -> pd.DataFrame:
    """Compute per-wallet bot_score using z-scores relative to group.

    Returns features_df with added columns: bot_score, bot_label.
    """
    cols = [c for c in FEATURE_COLS if c in features_df.columns]
    scaled = features_df[cols].copy()
    means = scaled.mean()
    stds = scaled.std().replace(0, np.nan)

    zdf = (scaled - means) / stds
    zdf = zdf.fillna(0.0)

    score = pd.Series(0.0, index=features_df.index)

    # high value → bot
    for col in _BOT_HIGH:
        if col in zdf.columns:
            z = zdf[col].clip(-3, 3)
            score += z.clip(lower=0)

    # low value → bot (flip sign)
    for col in _BOT_LOW:
        if col in zdf.columns:
            z = zdf[col].clip(-3, 3)
            score -= z.clip(upper=0)

    # no profile bonus
    no_prof = ((features_df['has_name'] < 0.5) & (features_df['has_bio'] < 0.5)).astype(float)
    score += no_prof * 0.5

    features_df['bot_score'] = score.round(2)
    features_df['bot_label'] = pd.cut(
        score, bins=[-np.inf, 2.0, 5.0, np.inf], labels=['HUMAN', 'MIXED', 'BOT'],
    )
    return features_df


def run_isolation_forest(features_df: pd.DataFrame, contamination: float = 0.1) -> pd.DataFrame:
    """Run Isolation Forest anomaly detection. Adds if_score and if_anomaly columns."""
    cols = [c for c in FEATURE_COLS if c in features_df.columns]
    X = StandardScaler().fit_transform(features_df[cols].values)
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

    iso = IsolationForest(contamination=contamination, random_state=42, n_estimators=200)
    features_df['if_anomaly'] = iso.fit_predict(X)  # 1=normal, -1=anomaly
    features_df['if_score'] = -iso.decision_function(X)  # higher = more anomalous
    features_df['if_score'] = features_df['if_score'].round(4)
    return features_df
