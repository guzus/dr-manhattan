"""Contract-drift check: the test that fires when an exchange changes its API.

Hits the LIVE public endpoints, runs the real responses through the parsers, and
reports two kinds of drift:
  - HARD (exit 1): fetch failed, parse raised, a unified invariant broke, or a field
    the committed fixture had has DISAPPEARED (the parser may depend on it).
  - INFO: new fields appeared since the fixture (additive; usually harmless).

Hermetic tests prove the parser is correct against a *snapshot*; this proves the
snapshot still matches *today's* API. Run on a schedule (see
.github/workflows/contract-drift.yml) so a breaking upstream change pages us before
it loses money in production, not after.

    uv run python scripts/contract_drift_check.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from contract_probes import PROBES, assert_market_invariants  # noqa: E402

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
SHAPE_SAMPLE = 5


def _union_keys(raw_markets):
    keys = set()
    for raw in raw_markets[:SHAPE_SAMPLE]:
        if isinstance(raw, dict):
            keys |= set(raw.keys())
    return keys


def check(probe):
    """Return (hard_problems, info_notes) for one exchange."""
    problems = []
    notes = []

    try:
        live = probe.fetch_raw()
    except Exception as exc:
        return [f"FETCH FAILED: {exc}"], notes
    if not live:
        return ["LIVE endpoint returned 0 markets"], notes

    try:
        markets = probe.parse(live)
    except Exception as exc:
        problems.append(f"PARSE RAISED: {type(exc).__name__}: {exc}")
        markets = []

    if not markets and not problems:
        problems.append(f"parsed 0 markets from {len(live)} live responses")

    for market in markets:
        try:
            assert_market_invariants(market)
        except AssertionError as exc:
            problems.append(f"INVARIANT BROKEN ({market.id}): {exc}")

    fixture_path = FIXTURE_DIR / f"{probe.id}_markets.json"
    if fixture_path.exists():
        fixture_keys = _union_keys(json.loads(fixture_path.read_text()))
        live_keys = _union_keys(live)
        removed = fixture_keys - live_keys
        added = live_keys - fixture_keys
        if removed:
            problems.append(
                f"FIELDS REMOVED vs fixture (parser may rely on these): {sorted(removed)}"
            )
        if added:
            notes.append(f"new fields since fixture: {sorted(added)}")
    else:
        notes.append("no committed fixture; shape-diff skipped")

    return problems, notes


def main():
    any_drift = False
    for probe in PROBES:
        print(f"== {probe.id} ==")
        problems, notes = check(probe)
        for note in notes:
            print(f"  [info] {note}")
        if problems:
            any_drift = True
            for problem in problems:
                print(f"  [DRIFT] {problem}")
        else:
            print("  ok")

    if any_drift:
        print("\nContract drift detected - a parser or exchange schema needs attention.")
        sys.exit(1)
    print("\nAll probed exchange contracts intact.")


if __name__ == "__main__":
    main()
