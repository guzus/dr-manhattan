"""Golden-fixture parsing tests.

Replays REAL captured public API responses (tests/fixtures/*.json) through each
exchange's parser and asserts the unified Market contract. Hermetic: parsing does
not touch the network (verified - _parse_market is pure for the probed exchanges),
so this runs in normal CI. The fixtures are reality snapshots captured by
scripts/capture_fixtures.py; the live counterpart is scripts/contract_drift_check.py.

This is the test that catches "a parser silently breaks on the real response shape"
- the failure mode that hand-written mock dicts cannot, because they encode our
assumption of the shape rather than the API's actual output.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from contract_probes import PROBES_BY_ID, assert_market_invariants  # noqa: E402

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def _fixture_exchange_ids():
    return sorted(p.stem[: -len("_markets")] for p in FIXTURE_DIR.glob("*_markets.json"))


@pytest.mark.parametrize("exchange_id", _fixture_exchange_ids())
def test_parser_handles_real_response(exchange_id):
    probe = PROBES_BY_ID[exchange_id]
    raw = json.loads((FIXTURE_DIR / f"{exchange_id}_markets.json").read_text())
    assert raw, f"{exchange_id}: empty fixture"

    markets = probe.parse(raw)

    assert markets, f"{exchange_id}: parsed 0 markets from {len(raw)} raw responses"
    for market in markets:
        assert_market_invariants(market)


def test_fixtures_exist_for_probed_exchanges():
    """Guard against a probe being added without a committed fixture (or vice versa)."""
    have = set(_fixture_exchange_ids())
    expected = set(PROBES_BY_ID)
    missing = expected - have
    msg = f"probes without committed fixtures: {sorted(missing)} (run capture_fixtures.py)"
    assert not missing, msg
