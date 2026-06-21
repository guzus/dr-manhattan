"""Tests for Predict.fun exchange implementation."""

from datetime import datetime, timezone

from dr_manhattan.exchanges.predictfun import PredictFun


def test_parse_market_sets_normalized_times():
    """Test Predict.fun parser maps API time fields to Market accessors."""
    exchange = PredictFun({})

    market = exchange._parse_market(
        {
            "id": 483522,
            "title": "World Cup match?",
            "outcomes": [
                {"name": "Team A", "onChainId": "1"},
                {"name": "Team B", "onChainId": "2"},
            ],
            "startTime": "2026-06-21T16:00:00Z",
            "expirationTimestamp": 1782144000000,
            "status": "REGISTERED",
            "decimalPrecision": 2,
        }
    )

    assert market.start_time == datetime(2026, 6, 21, 16, 0, tzinfo=timezone.utc)
    assert market.end_time == datetime.fromtimestamp(1782144000, timezone.utc)
    assert market.close_time == market.end_time


def test_parse_category_as_market_sets_normalized_times():
    """Test Predict.fun category fallback builds a complete Market with timing."""
    exchange = PredictFun({})

    market = exchange._parse_category_as_market(
        {
            "id": 1,
            "title": "World Cup category market?",
            "slug": "world-cup-category",
            "outcomes": [
                {"name": "Yes", "onChainId": "1"},
                {"name": "No", "onChainId": "2"},
            ],
            "endTime": "2026-06-22T00:00:00Z",
            "decimalPrecision": 3,
        }
    )

    assert market.id == "1"
    assert market.end_time == datetime(2026, 6, 22, 0, 0, tzinfo=timezone.utc)
    assert market.tick_size == 0.001
