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

## Latest Results Snapshot (February 14, 2026)

Run setup used for this snapshot:
- top markets per category: `1000`
- filters: `--closed-only --opened-within-years 2`
- fetch settings: `--limit 500 --workers 8`
- categories: `politics`, `sports`, `finance`, `geopolitics`, `tech`

Metric definitions:
- `market_wallets`: unique wallets that traded in a market
- `insider_wallets`: unique wallets that triggered at least one insider signal in a market
- `insider_wallet_share`: `insider_wallets / market_wallets`
- `avg insider %`: mean of `insider_wallet_share` across markets in a category

Category-level insider participation (top-1000 run):

| Category | Avg insider % | Weighted insider % |
| --- | ---: | ---: |
| sports | 11.49% | 5.68% |
| finance | 9.91% | 5.31% |
| politics | 5.85% | 4.66% |
| tech | 5.61% | 3.62% |
| geopolitics | 5.28% | 4.46% |

Notes:
- `Weighted insider %` is computed as `sum(insider_wallets) / sum(market_wallets)` within each category.
- Per-category market summaries for this run were saved to `/tmp/insider_category_summaries_top1000/*_top1000_summary.csv`.

## Notes

- Shorts are modeled the Polymarket way: "short YES" is "buy NO" (binary only).
- Backtests assume conservative execution by default: `fee_bps=0` and `slippage_bps=50` per side
  (override via CLI flags). Costs reduce effective fills so losses do not exceed -100%.
- Sizing is `--position-size` USD per trade (gross cash outlay). No leverage is assumed:
  trades are skipped if there is not enough free cash, and cash is tied up until the modeled exit.
- `--hold-to-expiry` ignores `--holding-minutes`/TP/SL and settles at payout (0/1) on resolved markets.
- This is a statistical heuristic; it does not identify real-world people.
