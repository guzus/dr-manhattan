"""Data serialization utilities."""

from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List


def serialize_model(obj: Any) -> Any:
    """
    Serialize dr-manhattan models to JSON-compatible dict.

    Args:
        obj: Object to serialize

    Returns:
        JSON-compatible dict, list, or primitive
    """
    # Handle None
    if obj is None:
        return None

    # Handle primitives
    if isinstance(obj, (str, int, float, bool)):
        return obj

    # Handle datetime
    if isinstance(obj, datetime):
        return obj.isoformat()

    # Handle Enum
    if isinstance(obj, Enum):
        return obj.value

    # Handle lists/tuples
    if isinstance(obj, (list, tuple)):
        return [serialize_model(item) for item in obj]

    # Handle dicts
    if isinstance(obj, dict):
        return {key: serialize_model(value) for key, value in obj.items()}

    # Handle dataclasses
    if is_dataclass(obj):
        return {key: serialize_model(value) for key, value in asdict(obj).items()}

    # Handle objects with __dict__
    if hasattr(obj, "__dict__"):
        return {
            key: serialize_model(value)
            for key, value in obj.__dict__.items()
            if not key.startswith("_")
        }

    # Fallback: convert to string
    return str(obj)
