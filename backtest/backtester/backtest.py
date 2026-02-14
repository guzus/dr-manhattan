import numpy as np
import pandas as pd


def _align_bool_condition(condition, index: pd.Index, name: str) -> pd.Series:
    """Align condition to index, auto-reindex if needed."""
    if condition is None:
        return pd.Series(False, index=index)

    if isinstance(condition, pd.Series):
        if condition.index.equals(index):
            return condition.fillna(False).astype(bool)
        return condition.reindex(index, fill_value=False).fillna(False).astype(bool)

    arr = np.asarray(condition)
    if arr.ndim != 1 or len(arr) != len(index):
        raise ValueError(f"{name} length must match book_df length")
    return pd.Series(arr, index=index).fillna(False).astype(bool)


def _calc_fee_shares(qty, entry_price, fee_rate=0.25, fee_exponent=2):
    """Polymarket 15-min Crypto variable fee (charged in shares)."""
    p = entry_price
    return qty * fee_rate * (p * (1 - p)) ** fee_exponent


def _build_trades(book_df, up_condition, down_condition, price_bounds, slippage_bps=0):
    """Shared trade construction for both backtest functions.

    slippage_bps: slippage in basis points applied to entry price.
                  e.g. 50 = 0.50% worse execution.
    """
    df = book_df
    pmin, pmax = price_bounds

    if df.index.duplicated().any():
        df = df[~df.index.duplicated(keep='first')]

    required_cols = ['start_time', 'end_time', 'resolved', 'up_best_ask', 'down_best_ask']
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(
            "backtest input must be Polymarket book_df from load_book_df. "
            f"Missing required columns: {missing}"
        )

    slip = slippage_bps / 10_000

    up_settle = (
        df['resolved']
        .astype(str)
        .str.upper()
        .map({'UP': 1.0, 'DOWN': 0.0, 'UNKNOWN': np.nan})
    )

    trades_list = []
    extra_cols = [c for c in ['T', 'S', 'K'] if c in df.columns]

    up_mask = (
        _align_bool_condition(up_condition, df.index, "up_condition")
        if up_condition is not None else None
    )
    down_mask = (
        _align_bool_condition(down_condition, df.index, "down_condition")
        if down_condition is not None else None
    )

    if up_mask is not None and up_mask.any():
        raw_price = df.loc[up_mask, 'up_best_ask']
        up_trade = {
            'side': 'up',
            'entry_price': raw_price * (1 + slip),
            'settlement': up_settle[up_mask],
            'start_time': df.loc[up_mask, 'start_time'],
            'end_time': df.loc[up_mask, 'end_time'],
        }
        for c in extra_cols:
            up_trade[c] = df.loc[up_mask, c]
        trades_list.append(pd.DataFrame(up_trade))

    if down_mask is not None and down_mask.any():
        raw_price = df.loc[down_mask, 'down_best_ask']
        down_trade = {
            'side': 'down',
            'entry_price': raw_price * (1 + slip),
            'settlement': 1 - up_settle[down_mask],
            'start_time': df.loc[down_mask, 'start_time'],
            'end_time': df.loc[down_mask, 'end_time'],
        }
        for c in extra_cols:
            down_trade[c] = df.loc[down_mask, c]
        trades_list.append(pd.DataFrame(down_trade))

    if not trades_list:
        return pd.DataFrame()

    all_trades = pd.concat(trades_list).sort_index()
    all_trades = all_trades.dropna(subset=['entry_price', 'settlement'])
    all_trades = all_trades[(all_trades['entry_price'] >= pmin) & (all_trades['entry_price'] <= pmax)]

    return all_trades


def backtest(book_df, up_condition=None, down_condition=None,
             initial_balance=10000, bet_pct=0.01, price_bounds=(0.01, 0.99),
             fee=True, slippage_bps=0):
    """
    Binary token backtester with position sizing.

    slippage_bps: slippage in basis points (e.g. 50 = 0.50%).
    """
    all_trades = _build_trades(book_df, up_condition, down_condition, price_bounds, slippage_bps)
    if all_trades.empty:
        return pd.DataFrame()

    p = all_trades['entry_price']
    fee_factor = 0.25 * (p * (1 - p)) ** 2 if fee else 0
    net_ret = (1 - fee_factor) * all_trades['settlement'] / p - 1
    win_stats = net_ret.groupby(all_trades['end_time']).agg(['sum', 'count'])
    n_windows = len(win_stats)

    balances = np.empty(n_windows)
    balance = initial_balance
    for i in range(n_windows):
        balances[i] = balance
        balance += balance * bet_pct * win_stats['sum'].iat[i]
        if balance < 0:
            balance = 0.0

    win_balance_map = pd.Series(balances, index=win_stats.index)
    all_trades['balance'] = all_trades['end_time'].map(win_balance_map).values
    all_trades['bet_size'] = all_trades['balance'] * bet_pct
    qty_gross = all_trades['bet_size'] / all_trades['entry_price']
    if fee:
        all_trades['fee'] = _calc_fee_shares(qty_gross, all_trades['entry_price'])
    else:
        all_trades['fee'] = 0.0
    all_trades['qty'] = qty_gross - all_trades['fee']
    all_trades['pnl'] = all_trades['qty'] * all_trades['settlement'] - all_trades['bet_size']

    return all_trades


def backtest_fixed(book_df, up_condition=None, down_condition=None,
                   bet_size=100, price_bounds=(0.01, 0.99), fee=True, slippage_bps=0):
    """
    Binary token backtester with fixed dollar size per signal.

    slippage_bps: slippage in basis points (e.g. 50 = 0.50%).
    """
    all_trades = _build_trades(book_df, up_condition, down_condition, price_bounds, slippage_bps)
    if all_trades.empty:
        return pd.DataFrame()

    all_trades['bet_size'] = bet_size
    qty_gross = bet_size / all_trades['entry_price']
    if fee:
        all_trades['fee'] = _calc_fee_shares(qty_gross, all_trades['entry_price'])
    else:
        all_trades['fee'] = 0.0
    all_trades['qty'] = qty_gross - all_trades['fee']
    all_trades['pnl'] = all_trades['qty'] * all_trades['settlement'] - bet_size

    return all_trades


def backtest_summary(trades):
    """Per-window (per-market) backtest summary."""
    if trades.empty:
        return pd.DataFrame()

    def _agg(g):
        up = g[g['side'] == 'up']
        dn = g[g['side'] == 'down']
        first = g.iloc[0]
        side_is_up = first['side'] == 'up'
        settled_one = first['settlement'] == 1
        if side_is_up:
            resolved = 'UP' if settled_one else 'DOWN'
        else:
            resolved = 'UP' if not settled_one else 'DOWN'
        return pd.Series({
            'resolved':     resolved,
            'total_trades': len(g),
            'up_trades':    len(up),
            'dn_trades':    len(dn),
            'up_avg_entry': up['entry_price'].mean() if len(up) else np.nan,
            'dn_avg_entry': dn['entry_price'].mean() if len(dn) else np.nan,
            'up_pnl':       up['pnl'].sum() if len(up) else 0.0,
            'dn_pnl':       dn['pnl'].sum() if len(dn) else 0.0,
            'total_pnl':    g['pnl'].sum(),
        })

    ws = trades.groupby('end_time').apply(_agg, include_groups=False)

    ws['cum_pnl'] = ws['total_pnl'].cumsum()
    ws['drawdown'] = ws['cum_pnl'].cummax() - ws['cum_pnl']
    ws['win'] = (ws['total_pnl'] > 0)
    ws['win_rate'] = ws['win'].expanding().mean()

    return ws
