# Polymarket Informed Trader Tool Outputs

This folder contains generated artifacts from running the example backtester.

## Naming

- `*_expiry_cap.png` + `expiry_cap_summary.csv`
  - Hold-to-expiry settlement backtest (`--hold-to-expiry`)
  - Cash-constrained sizing
  - Settings used when generated: `fee_bps=8`, `slippage_bps=50`

- `*_expiry_fee0.png` + `expiry_cap_fee0_summary.csv`
  - Hold-to-expiry settlement backtest (`--hold-to-expiry`)
  - Cash-constrained sizing
  - Settings used when generated: `fee_bps=0`, `slippage_bps=50`

- `*_exit_sweep_top1000_fee0_slip50.csv`
  - Exit-mode sweep comparing `60m`, `240m`, and `expiry`
  - Settings used when generated: `fee_bps=0`, `slippage_bps=50`

- `exit_sweep_top1000_fee0_slip50_all.csv`
  - Concatenation of the per-category sweep CSVs.

- `exit_sweep_top1000_fee0_slip50_return_pivot.csv`
  - Pivoted view of `return_pct` by category and exit mode.
