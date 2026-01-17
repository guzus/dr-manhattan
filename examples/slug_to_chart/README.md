# Slug to Chart

Generate Bloomberg-style price charts from prediction market data.

## Supported Exchanges

| Exchange | Intervals | Notes |
|----------|-----------|-------|
| Polymarket | 1m, 1h, 6h, 1d, 1w, max | Default exchange |
| Limitless | 1m, 1h, 1d, 1w | Short-term markets |
| Opinion | 1m, 1h, 1d, 1w, max | Requires authentication |

## Usage

```bash
uv run python -m examples.slug_to_chart <slug> [options]
```

## Options

| Option | Description | Default |
|--------|-------------|---------|
| `--exchange`, `-e` | Exchange (polymarket, limitless, opinion) | `polymarket` |
| `--output`, `-o` | Output image path | `<slug>.png` |
| `--interval`, `-i` | Price history interval | `max` |
| `--fidelity`, `-f` | Number of data points (Polymarket only) | `300` |
| `--top`, `-t` | Show only top N outcomes by price | All |
| `--min-price`, `-m` | Min price threshold 0-1 to include | `0.001` (0.1%) |
| `--subtitle`, `-s` | Chart subtitle | None |

## Examples

```bash
# Polymarket (default)
uv run python -m examples.slug_to_chart who-will-trump-nominate-as-fed-chair

# Limitless
uv run python -m examples.slug_to_chart --exchange limitless will-trump-fire-jerome-powell

# Opinion (search by query)
uv run python -m examples.slug_to_chart --exchange opinion "fed rate"

# With options
uv run python -m examples.slug_to_chart fed-decision-in-january --top 4 -o chart.png

# Full URL also works
uv run python -m examples.slug_to_chart "https://polymarket.com/event/who-will-trump-nominate-as-fed-chair"
```

## Example Output

![Fed Chair Chart](../fed_chair_chart.png)

## Features

- Bloomberg-style chart design with clean aesthetics
- Multi-exchange support (Polymarket, Limitless, Opinion)
- Smart x-axis date formatting based on data range
- Multi-line legend for many outcomes
- Diagonal line markers in legend
- "dr-manhattan" watermark
- Binary markets show only "Yes" outcome
- Automatic label extraction from market questions
