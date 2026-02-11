# Polymarket Insider Flow (Examples Only)

Local-only tooling for detecting statistically unusual flow in Polymarket public trades and
backtesting "buy-after-signal" strategies.

## Run (Single Market / Event)

```bash
uv run python examples/polymarket_insider_tool/polymarket_insider_backtest.py \
  --market claude-5-released-by \
  --limit 2000 \
  --plot --plot-combined --plot-assets 2 \
  --plot-path /tmp/claude5_event_combined.png
```

## Run (Top-Volume Closed Politics Markets)

Polymarket category fields are not reliable on the Gamma `/markets` response; use the Gamma tag.

```bash
uv run python examples/polymarket_insider_tool/polymarket_insider_backtest.py \
  --tag-slug politics --closed-only --top-markets 50 \
  --opened-within-years 2 \
  --hold-to-expiry \
  --limit 1500 --workers 4 \
  --save-market-summary /tmp/politics_top50_closed_summary.csv \
  --plot --plot-combined --plot-assets 2 \
  --plot-path /tmp/politics_top50_closed_plot.png
```

## Notes

- Shorts are modeled the Polymarket way: "short YES" is "buy NO" (binary only).
- Backtests assume conservative execution by default: `fee_bps=0` and `slippage_bps=50` per side
  (override via CLI flags). Costs reduce effective fills so losses do not exceed -100%.
- Sizing is `--position-size` USD per trade (gross cash outlay). No leverage is assumed:
  trades are skipped if there is not enough free cash, and cash is tied up until the modeled exit.
- `--hold-to-expiry` ignores `--holding-minutes`/TP/SL and settles at payout (0/1) on resolved markets.
- This is a statistical heuristic; it does not identify real-world people.
