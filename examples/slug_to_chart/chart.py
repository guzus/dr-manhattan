"""Bloomberg-style chart generation."""

from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from .labels import extract_short_label

DEFAULT_COLORS = [
    "#FF8C00",  # Dark orange
    "#000000",  # Black
    "#1E90FF",  # Dodger blue
    "#32CD32",  # Lime green
    "#DC143C",  # Crimson
    "#9370DB",  # Medium purple
    "#20B2AA",  # Light sea green
    "#FF69B4",  # Hot pink
]


def generate_chart(
    title: str,
    price_data: dict[str, pd.DataFrame],
    output_path: Path,
    subtitle: str | None = None,
) -> None:
    """Generate a Bloomberg-style price chart."""
    plt.rcParams["font.family"] = ["Arial", "Helvetica", "DejaVu Sans", "sans-serif"]

    fig = plt.figure(figsize=(10, 8), facecolor="white")
    ax = fig.add_axes([0.08, 0.12, 0.82, 0.58])
    ax.set_facecolor("white")

    labels_list = []
    colors_list = []

    for i, (label, df) in enumerate(price_data.items()):
        color = DEFAULT_COLORS[i % len(DEFAULT_COLORS)]
        prices_pct = df["price"] * 100

        ax.plot(df["timestamp"], prices_pct, color=color, linewidth=2.5, solid_capstyle="round")

        short_label = extract_short_label(label)
        labels_list.append(short_label)
        colors_list.append(color)

    # Y-axis
    ax.set_ylim(-2, 102)
    ax.set_yticks([0, 20, 40, 60, 80, 100])
    ax.yaxis.tick_right()
    ax.yaxis.set_label_position("right")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{int(x)}%"))

    # X-axis - smart formatting based on data range
    all_timestamps = pd.concat([df["timestamp"] for df in price_data.values()])
    date_range = (all_timestamps.max() - all_timestamps.min()).days

    if date_range > 365:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    elif date_range > 90:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
        ax.xaxis.set_major_locator(mdates.MonthLocator())
    elif date_range > 30:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
    else:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=max(1, date_range // 7)))

    # Grid
    ax.grid(True, axis="y", linestyle="-", linewidth=0.8, color="#e0e0e0", zorder=0)
    ax.grid(False, axis="x")

    # Remove spines
    for spine in ax.spines.values():
        spine.set_visible(False)

    # Tick styling
    ax.tick_params(axis="both", which="both", length=0)
    ax.tick_params(axis="x", colors="#333333", labelsize=12)
    ax.tick_params(axis="y", colors="#333333", labelsize=12)

    # Title
    fig.text(
        0.08, 0.92, title, fontsize=22, fontweight="bold", color="#000000", va="top", ha="left"
    )

    # Subtitle
    legend_y = 0.84
    if subtitle:
        fig.text(0.08, 0.86, subtitle, fontsize=14, color="#666666", va="top", ha="left")
        legend_y = 0.79

    # Legend with diagonal markers
    legend_x = 0.08
    for label, color in zip(labels_list, colors_list):
        line_ax = fig.add_axes([legend_x, legend_y - 0.01, 0.02, 0.025])
        line_ax.plot([0, 1], [0, 1], color=color, linewidth=3, solid_capstyle="round")
        line_ax.set_xlim(0, 1)
        line_ax.set_ylim(0, 1)
        line_ax.axis("off")

        fig.text(
            legend_x + 0.025, legend_y, label, fontsize=12, color="#333333", va="center", ha="left"
        )
        legend_x += 0.025 + len(label) * 0.008 + 0.03

    # Footer
    fig.text(0.08, 0.03, "Source: Polymarket", fontsize=11, color="#666666", va="bottom", ha="left")
    fig.text(
        0.92,
        0.03,
        "dr-manhattan",
        fontsize=11,
        fontweight="bold",
        color="#333333",
        va="bottom",
        ha="right",
    )

    plt.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="white", pad_inches=0.3)
    plt.close()

    print(f"Chart saved to: {output_path}")
