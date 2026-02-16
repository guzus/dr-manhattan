---
name: slug-to-chart
description: Generate Bloomberg-style price charts from prediction market data. Use when the user wants to visualize market prices, compare outcomes across exchanges (Polymarket, Limitless, Opinion), or create PNG charts showing price history for prediction market tokens.
license: Apache-2.0
compatibility: Requires Python >= 3.11 and uv. Requires network access for exchange APIs.
metadata:
  author: guzus
  version: "1.0"
---

# Slug to Chart

Generate Bloomberg-style price charts from prediction market data across multiple exchanges.

## Overview

This skill allows you to create professional, Bloomberg-style PNG charts that visualize price history for prediction markets. It supports multiple exchanges (Polymarket, Limitless, Opinion) and can display price movements for individual outcomes or compare multiple outcomes in a single chart.

## When to use this skill

Use this skill when the user wants to:
- Visualize price history for a prediction market
- Compare outcome prices across time
- Identify price trends or patterns
- Generate charts for market analysis or reporting
- Highlight price differences across multiple outcomes or markets
- Create professional visualizations of prediction market data

## Supported Exchanges

| Exchange | Intervals | Notes |
|----------|-----------|-------|
| Polymarket | 1m, 1h, 6h, 1d, 1w, max | Default exchange, most features |
| Limitless | 1m, 1h, 1d, 1w | Short-term markets |
| Opinion | 1m, 1h, 1d, 1w, max | May require authentication for some markets |

## Usage

### Basic Usage

To generate a chart, run the slug_to_chart module with a market slug:

```bash
uv run python -m examples.slug_to_chart <slug>
```

The slug can be:
- A market slug (e.g., `who-will-trump-nominate-as-fed-chair`)
- A full market URL (e.g., `https://polymarket.com/event/who-will-trump-nominate-as-fed-chair`)
- A search query for Opinion exchange (when using `--exchange opinion`)

### Examples

**Polymarket (default exchange):**
```bash
uv run python -m examples.slug_to_chart who-will-trump-nominate-as-fed-chair
```

**Limitless exchange:**
```bash
uv run python -m examples.slug_to_chart --exchange limitless will-trump-fire-jerome-powell
```

**Opinion exchange (search by query):**
```bash
uv run python -m examples.slug_to_chart --exchange opinion "fed rate"
```

**With custom output file:**
```bash
uv run python -m examples.slug_to_chart fed-decision-in-january -o my_chart.png
```

**Show only top 4 outcomes:**
```bash
uv run python -m examples.slug_to_chart fed-decision-in-january --top 4
```

**With custom subtitle:**
```bash
uv run python -m examples.slug_to_chart fed-decision --subtitle "Market Analysis - Jan 2026"
```

## Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--exchange` | `-e` | Exchange (polymarket, limitless, opinion) | `polymarket` |
| `--output` | `-o` | Output image path | `<slug>.png` |
| `--interval` | `-i` | Price history interval (1m, 1h, 6h, 1d, 1w, max) | `max` |
| `--fidelity` | `-f` | Number of data points (Polymarket only) | `300` |
| `--top` | `-t` | Show only top N outcomes by price | All outcomes |
| `--min-price` | `-m` | Min price threshold 0-1 to include outcome | `0.001` (0.1%) |
| `--subtitle` | `-s` | Chart subtitle | None |

## Chart Features

The generated charts include:
- **Bloomberg-style design** with clean, professional aesthetics
- **Multi-exchange support** for Polymarket, Limitless, and Opinion
- **Smart x-axis formatting** that adapts based on data range (hours, days, weeks, months)
- **Multi-line legend** that wraps to multiple rows when needed
- **Diagonal line markers** in legend for easy outcome identification
- **"dr-manhattan" watermark** in the footer
- **Binary market optimization** - shows only "Yes" outcome for Yes/No markets
- **Automatic label extraction** from market questions
- **Color-coded outcomes** using distinct, high-contrast colors

## Output

The skill generates a PNG image file with:
- Chart title (market question)
- Optional subtitle
- Price history lines for each outcome (0-100% scale)
- Legend with color-coded outcome labels
- X-axis with smart date formatting
- Y-axis showing percentage probabilities
- Source attribution and dr-manhattan branding

## Implementation Details

The skill uses three main components from the `examples.slug_to_chart` module:

1. **fetcher.py** - Fetches price history data from exchanges
   - Handles exchange-specific API differences
   - Normalizes intervals across exchanges
   - Filters and sorts outcomes by price

2. **chart.py** - Generates Bloomberg-style charts
   - Uses matplotlib for chart generation
   - Applies professional styling and formatting
   - Handles multi-line legends and smart axis formatting

3. **labels.py** - Extracts short labels from market questions
   - Simplifies long market questions for legend display

## Tips for Best Results

1. **For multi-outcome markets**: Use `--top N` to show only the most relevant outcomes
2. **For noisy data**: Increase `--min-price` to filter out low-probability outcomes
3. **For detailed analysis**: Use shorter intervals like `1h` or `1d` instead of `max`
4. **For Polymarket**: Adjust `--fidelity` to control data point density (higher = more detailed)
5. **For comparison**: Generate multiple charts with different time intervals to see both long-term trends and recent activity

## Troubleshooting

**No price data available:**
- Verify the slug/URL is correct
- Try searching with a keyword instead of exact slug
- Check that the market exists on the specified exchange

**Interval not supported:**
- The skill will automatically fall back to a supported interval
- Check the "Supported Exchanges" table for available intervals per exchange

**Too many outcomes:**
- Use `--top N` to limit the number of lines
- Increase `--min-price` to filter out unlikely outcomes
- Consider filtering to binary markets only

## Example Workflow

When a user asks "Show me a chart of the Fed chair nomination market":

1. Identify this as a chart generation request
2. Determine the exchange (default to Polymarket unless specified)
3. Search for or identify the market slug
4. Run the command:
   ```bash
   uv run python -m examples.slug_to_chart who-will-trump-nominate-as-fed-chair
   ```
5. Present the generated PNG file to the user
6. Optionally, analyze the chart data to provide insights about price trends

## Related Documentation

- See [README.md](README.md) for detailed module documentation
- See [SKILL.md](../../SKILL.md) for dr-manhattan API and MCP tools reference
