"""Session data models."""

import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class SessionStatus(Enum):
    """Strategy session status."""

    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class StrategySession:
    """Represents a running strategy session."""

    id: str
    strategy_type: str
    exchange_name: str
    market_id: str
    strategy: Any  # Strategy instance
    thread: Optional[threading.Thread] = None
    status: SessionStatus = SessionStatus.RUNNING
    created_at: datetime = field(default_factory=datetime.now)
    error: Optional[str] = None
    metrics: Dict[str, Any] = field(default_factory=dict)

    def is_alive(self) -> bool:
        """Check if strategy thread is alive."""
        return self.thread and self.thread.is_alive()
