"""FastAPI server for strategy dashboard."""

import csv
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

app = FastAPI(title="Dr. Manhattan Strategy Dashboard")

LOGS_DIR = Path("logs")


@app.get("/")
async def root():
    """Serve the dashboard HTML."""
    dashboard_path = Path(__file__).parent / "dashboard.html"
    if not dashboard_path.exists():
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return FileResponse(dashboard_path)


@app.get("/api/strategies")
async def list_strategies() -> List[Dict[str, str]]:
    """
    List all available strategy log files.

    Returns:
        List of dicts with id, name, market_id, and start_time
    """
    if not LOGS_DIR.exists():
        return []

    strategies = []
    for csv_file in LOGS_DIR.glob("*.csv"):
        # Parse filename: {strategy_name}_{market_id}_{timestamp}.csv
        parts = csv_file.stem.split("_")
        if len(parts) >= 3:
            strategy_name = parts[0]
            market_id = parts[1]
            timestamp_str = "_".join(parts[2:])

            # Parse timestamp
            try:
                start_time = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                start_time_str = start_time.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                start_time_str = timestamp_str

            strategies.append({
                "id": csv_file.stem,
                "name": strategy_name,
                "market_id": market_id,
                "start_time": start_time_str,
                "filename": csv_file.name,
            })

    # Sort by start_time descending (newest first)
    strategies.sort(key=lambda x: x["start_time"], reverse=True)
    return strategies


def _validate_strategy_id(strategy_id: str) -> bool:
    """Validate strategy_id to prevent path traversal attacks."""
    return bool(re.match(r"^[a-zA-Z0-9_-]+$", strategy_id))


@app.get("/api/strategy/{strategy_id}/data")
async def get_strategy_data(strategy_id: str) -> Dict:
    """
    Get time series data for a strategy.

    Args:
        strategy_id: Strategy ID (filename without .csv)

    Returns:
        Dict with timestamps and data arrays
    """
    if not _validate_strategy_id(strategy_id):
        raise HTTPException(status_code=400, detail="Invalid strategy ID")

    csv_file = LOGS_DIR / f"{strategy_id}.csv"
    if not csv_file.exists():
        raise HTTPException(status_code=404, detail="Strategy not found")

    # Read CSV data
    timestamps = []
    nav_data = []
    cash_data = []
    positions_value_data = []
    delta_data = []
    num_orders_data = []
    positions = {}  # outcome -> [values]

    with open(csv_file, "r") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames

        # Find outcome columns
        outcome_columns = [col for col in headers if col.endswith("_qty")]

        for row in reader:
            timestamps.append(row["timestamp"])
            nav_data.append(float(row["nav"]))
            cash_data.append(float(row["cash"]))
            positions_value_data.append(float(row["positions_value"]))
            delta_data.append(float(row["delta"]))
            num_orders_data.append(int(row["num_open_orders"]))

            # Parse position data
            for col in outcome_columns:
                outcome_name = col.replace("_qty", "")
                if outcome_name not in positions:
                    positions[outcome_name] = []
                positions[outcome_name].append(float(row[col]))

    # Calculate statistics
    initial_nav = nav_data[0] if nav_data else 0
    current_nav = nav_data[-1] if nav_data else 0
    pnl = current_nav - initial_nav
    pnl_pct = (pnl / initial_nav * 100) if initial_nav > 0 else 0
    max_nav = max(nav_data) if nav_data else 0
    min_nav = min(nav_data) if nav_data else 0
    avg_delta = sum(delta_data) / len(delta_data) if delta_data else 0

    return {
        "timestamps": timestamps,
        "nav": nav_data,
        "cash": cash_data,
        "positions_value": positions_value_data,
        "delta": delta_data,
        "num_orders": num_orders_data,
        "positions": positions,
        "stats": {
            "initial_nav": round(initial_nav, 2),
            "current_nav": round(current_nav, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "max_nav": round(max_nav, 2),
            "min_nav": round(min_nav, 2),
            "avg_delta": round(avg_delta, 2),
            "total_ticks": len(timestamps),
        },
    }


def main():
    """Run the dashboard server."""
    import uvicorn

    print("Starting Dr. Manhattan Strategy Dashboard...")
    print("Open http://localhost:8000 in your browser")
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
