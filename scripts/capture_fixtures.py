"""Capture golden fixtures of real public market-data responses.

Hand-written mock dicts encode our *assumption* of an API's shape; golden fixtures
encode the API's *reality*. The fixtures saved here pin each parser against a real
response and are replayed hermetically by tests/test_fixtures.py.

Refresh manually (and review the diff) when an exchange legitimately changes schema:

    uv run python scripts/capture_fixtures.py
"""

import json
from pathlib import Path

from contract_probes import PROBES

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
SAMPLE_SIZE = 5


def main() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for probe in PROBES:
        try:
            raw = probe.fetch_raw()[:SAMPLE_SIZE]
        except Exception as exc:  # network/shape failure - skip, don't kill the run
            print(f"[skip] {probe.id}: {exc}")
            continue
        if not raw:
            print(f"[skip] {probe.id}: endpoint returned 0 markets")
            continue

        path = FIXTURE_DIR / f"{probe.id}_markets.json"
        path.write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n")

        # Sanity-check that what we captured actually parses.
        markets = probe.parse(raw)
        print(
            f"[ok] {probe.id}: saved {len(raw)} raw markets, parsed {len(markets)} -> {path.name}"
        )


if __name__ == "__main__":
    main()
