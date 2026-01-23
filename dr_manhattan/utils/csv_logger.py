"""CSV logger for strategy execution tracking."""

import csv
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from ..models.nav import NAV
from ..models.order import Order


class CSVLogger:
    """
    Logs strategy execution data to CSV file.

    Records NAV, positions, delta, and orders at each tick.
    File format: logs/{strategy_name}_{market_id}_{timestamp}.csv
    """

    def __init__(
        self,
        strategy_name: str,
        market_id: str,
        outcomes: List[str],
        log_dir: str = "logs",
    ):
        """
        Initialize CSV logger.

        Args:
            strategy_name: Name of the strategy
            market_id: Market ID being traded
            outcomes: List of outcome names
            log_dir: Directory to store log files
        """
        self.strategy_name = strategy_name
        self.market_id = market_id
        self.outcomes = outcomes
        self.log_dir = Path(log_dir)

        # Create logs directory if it doesn't exist
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename with timestamp
        start_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{strategy_name}_{market_id[:8]}_{start_time}.csv"
        self.filepath = self.log_dir / filename

        # Initialize CSV file with headers
        self._write_header()

    def _write_header(self):
        """Write CSV header row."""
        headers = [
            "timestamp",
            "nav",
            "cash",
            "positions_value",
            "delta",
            "num_open_orders",
        ]

        # Add dynamic outcome columns
        for outcome in self.outcomes:
            # Sanitize outcome name for column header
            safe_name = outcome.replace(" ", "_").replace(",", "").lower()[:20]
            headers.append(f"{safe_name}_qty")
            headers.append(f"{safe_name}_value")

        with open(self.filepath, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)

    def log_snapshot(
        self,
        nav: NAV,
        positions: Dict[str, float],
        orders: List[Order],
        delta: float,
    ):
        """
        Log current state snapshot.

        Args:
            nav: NAV object with breakdown
            positions: Dict mapping outcome to position size
            orders: List of open orders
            delta: Current delta value
        """
        row = [
            datetime.now().isoformat(),
            round(nav.nav, 2),
            round(nav.cash, 2),
            round(nav.positions_value, 2),
            round(delta, 2),
            len(orders),
        ]

        # Add position data for each outcome
        for outcome in self.outcomes:
            position_size = positions.get(outcome, 0.0)

            # Find position value from NAV breakdown
            position_value = 0.0
            for pos_breakdown in nav.positions:
                if pos_breakdown.outcome == outcome:
                    position_value = pos_breakdown.value
                    break

            row.append(round(position_size, 2))
            row.append(round(position_value, 2))

        # Write row to CSV
        with open(self.filepath, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(row)

    def get_filepath(self) -> str:
        """Get the full path to the CSV file."""
        return str(self.filepath.absolute())
