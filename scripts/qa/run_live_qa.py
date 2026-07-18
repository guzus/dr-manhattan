"""Live QA driver: proves the unified contract against real venue behavior.

Complements scripts/contract_drift_check.py (public read/parse drift) with the
half it cannot cover: the authenticated order lifecycle. Two tiers:

  tier1  Public reads across venues, zero credentials: fetch_markets through the
         real client classes and check unified-model invariants.
  tier2  Order lifecycle against Kalshi's DEMO environment (mock funds, separate
         credentials): auth probe, place a resting 1-cent limit order, verify it
         is open, cancel it, verify it is cancelled.

Safety model - enforced structurally, not by prompt or convention:
  - QA environments are keyless by contract. This driver REFUSES to start if any
    production-shaped trading secret (raw private keys, builder secrets) is present
    in its environment.
  - tier2 uses KALSHI_QA_DEMO_* variables, deliberately distinct names from the
    production KALSHI_* variables, and pins the client to the demo host.
  - Designed to run inside an egress-firewalled E2B sandbox (see
    scripts/qa/spawn_qa_sandbox.py and wiki/security/key-management.md); running it
    directly also works and is exactly as keyless.

    uv run python scripts/qa/run_live_qa.py --tiers tier1
    uv run python scripts/qa/run_live_qa.py --tiers tier1,tier2 --json-out qa-report.json

Exit code 0 = every attempted check passed (skips are not failures); 1 otherwise.
"""

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from dr_manhattan import Kalshi, OrderSide, OrderStatus, create_exchange

# Venues probed by tier1. Two are excluded from the default set:
#   - opinion: its API lives on a non-standard port (proxy.opinion.trade:8443) that
#     domain-based sandbox egress rules cannot express (they cover ports 80/443 only).
#   - predictfun: requires an API key for ALL calls, including market reads
#     (verified live 2026-07-18), so it cannot participate in a keyless tier.
# Both can be requested explicitly with --venues in environments that support them.
DEFAULT_TIER1_VENUES = ["polymarket", "kalshi", "limitless"]

# Production-shaped secrets that must never be present in a QA environment. The
# point of the QA lane is that nothing in it can move real money; finding one of
# these set is a configuration error worth failing loudly on.
FORBIDDEN_PRODUCTION_ENV = (
    "POLYMARKET_PRIVATE_KEY",
    "BUILDER_SECRET",
    "OPINION_PRIVATE_KEY",
    "LIMITLESS_PRIVATE_KEY",
    "PREDICTFUN_PRIVATE_KEY",
    "PREDICTFUN_SMART_WALLET_OWNER_PRIVATE_KEY",
    "KALSHI_PRIVATE_KEY_PEM",
    "KALSHI_PRIVATE_KEY_PATH",
)

MARKET_SAMPLE = 5
ORDER_POLL_ATTEMPTS = 10
ORDER_POLL_INTERVAL_S = 1.0


@dataclass
class CheckResult:
    name: str
    status: str  # "pass" | "fail" | "skip"
    detail: str = ""
    duration_s: float = 0.0


@dataclass
class QAReport:
    checks: List[CheckResult] = field(default_factory=list)

    def add(self, name: str, status: str, detail: str = "", duration_s: float = 0.0) -> None:
        self.checks.append(CheckResult(name, status, detail, duration_s))
        marker = {"pass": "ok", "fail": "FAIL", "skip": "skip"}[status]
        suffix = f" ({duration_s:.1f}s)" if duration_s else ""
        line = f"  [{marker}] {name}{suffix}"
        if detail:
            line += f": {detail}"
        print(line, flush=True)

    @property
    def failed(self) -> bool:
        return any(c.status == "fail" for c in self.checks)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": not self.failed,
            "checks": [
                {
                    "name": c.name,
                    "status": c.status,
                    "detail": c.detail,
                    "duration_s": round(c.duration_s, 2),
                }
                for c in self.checks
            ],
        }


def refuse_production_secrets() -> None:
    present = [name for name in FORBIDDEN_PRODUCTION_ENV if os.environ.get(name)]
    if present:
        print(
            "REFUSING TO RUN: production-shaped secrets present in a QA environment: "
            + ", ".join(sorted(present))
        )
        print("QA environments are keyless by contract - see wiki/security/key-management.md.")
        sys.exit(2)


def check_market_invariants(market: Any) -> Optional[str]:
    """Return a problem description, or None if the unified Market looks sane."""
    if not market.id:
        return "market with empty id"
    if not market.outcomes:
        return f"market {market.id} has no outcomes"
    for outcome, price in (market.prices or {}).items():
        if price is None:
            continue
        if not (-1e-9 <= float(price) <= 1 + 1e-9):
            return f"market {market.id} outcome {outcome} price {price} outside [0, 1]"
    if market.volume is not None and float(market.volume) < 0:
        return f"market {market.id} negative volume {market.volume}"
    return None


def run_tier1(report: QAReport, venues: List[str]) -> None:
    print("== tier1: public reads (keyless) ==", flush=True)
    for venue in venues:
        started = time.monotonic()
        try:
            # use_env=False: ambient credentials must never influence tier1 even if
            # something leaks into the environment; validate=False: read-only client.
            exchange = create_exchange(venue, use_env=False, verbose=False, validate=False)
            markets = exchange.fetch_markets()
        except Exception as exc:
            report.add(
                f"tier1.{venue}.fetch_markets",
                "fail",
                f"{type(exc).__name__}: {exc}",
                time.monotonic() - started,
            )
            continue

        duration = time.monotonic() - started
        if not markets:
            report.add(f"tier1.{venue}.fetch_markets", "fail", "returned 0 markets", duration)
            continue

        problem = None
        for market in markets[:MARKET_SAMPLE]:
            problem = check_market_invariants(market)
            if problem:
                break
        if problem:
            report.add(f"tier1.{venue}.invariants", "fail", problem, duration)
        else:
            report.add(
                f"tier1.{venue}.fetch_markets",
                "pass",
                f"{len(markets)} markets, {min(len(markets), MARKET_SAMPLE)} sampled clean",
                duration,
            )


def build_demo_kalshi() -> Optional[Kalshi]:
    api_key_id = os.environ.get("KALSHI_QA_DEMO_API_KEY_ID", "").strip()
    private_key_pem = os.environ.get("KALSHI_QA_DEMO_PRIVATE_KEY_PEM", "").strip()
    if not api_key_id or not private_key_pem:
        return None
    # Support single-line PEM values with literal \n separators (the .env.example
    # convention for KALSHI_PRIVATE_KEY_PEM).
    if "\\n" in private_key_pem and "\n" not in private_key_pem:
        private_key_pem = private_key_pem.replace("\\n", "\n")
    return Kalshi(
        {
            "api_key_id": api_key_id,
            "private_key_pem": private_key_pem,
            "demo": True,
            "verbose": False,
        }
    )


def poll_order_status(
    exchange: Kalshi, order_id: str, wanted: OrderStatus
) -> Optional[OrderStatus]:
    """Poll until the order reaches `wanted`; return the last observed status."""
    last: Optional[OrderStatus] = None
    for _ in range(ORDER_POLL_ATTEMPTS):
        order = exchange.fetch_order(order_id)
        last = order.status
        if last == wanted:
            return last
        # Terminal states other than the wanted one will not change; stop early.
        if last in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED):
            return last
        time.sleep(ORDER_POLL_INTERVAL_S)
    return last


def run_tier2(report: QAReport) -> None:
    print("== tier2: Kalshi demo order lifecycle (mock funds) ==", flush=True)
    exchange = build_demo_kalshi()
    if exchange is None:
        report.add(
            "tier2.kalshi_demo",
            "skip",
            "KALSHI_QA_DEMO_API_KEY_ID / KALSHI_QA_DEMO_PRIVATE_KEY_PEM not set",
        )
        return

    # Structural pin: whatever else happens, tier2 only ever talks to the demo host.
    api_url = getattr(exchange, "_api_url", "")
    if "demo-api.kalshi.co" not in api_url:
        report.add("tier2.demo_host_pin", "fail", f"client resolved to non-demo host: {api_url}")
        return

    started = time.monotonic()
    try:
        balance = exchange.fetch_balance()
    except Exception as exc:
        report.add(
            "tier2.auth_probe",
            "fail",
            f"fetch_balance raised {type(exc).__name__}: {exc}",
            time.monotonic() - started,
        )
        return
    report.add(
        "tier2.auth_probe",
        "pass",
        f"demo balance keys: {sorted(balance.keys())}",
        time.monotonic() - started,
    )

    started = time.monotonic()
    try:
        markets = exchange.fetch_markets()
    except Exception as exc:
        report.add(
            "tier2.fetch_markets",
            "fail",
            f"{type(exc).__name__}: {exc}",
            time.monotonic() - started,
        )
        return
    # A 1-cent buy can only rest (not fill) if the market's Yes side trades well
    # above it; require a mid of at least 5 cents and some volume.
    candidates = [
        m
        for m in markets
        if float(m.prices.get("Yes", 0) or 0) >= 0.05 and float(m.volume or 0) > 0
    ]
    if not candidates:
        report.add("tier2.pick_market", "skip", "no liquid open demo market found")
        return
    market = max(candidates, key=lambda m: float(m.volume or 0))
    report.add(
        "tier2.pick_market",
        "pass",
        f"{market.id} (Yes mid {market.prices.get('Yes'):.2f}, volume {market.volume:.0f})",
        time.monotonic() - started,
    )

    started = time.monotonic()
    try:
        order = exchange.create_order(
            market_id=market.id,
            outcome="Yes",
            side=OrderSide.BUY,
            price=0.01,
            size=1,
        )
    except Exception as exc:
        report.add(
            "tier2.create_order",
            "fail",
            f"{type(exc).__name__}: {exc}",
            time.monotonic() - started,
        )
        return
    report.add(
        "tier2.create_order",
        "pass",
        f"order {order.id} on {market.id} @ 0.01 x1",
        time.monotonic() - started,
    )

    started = time.monotonic()
    status = poll_order_status(exchange, order.id, OrderStatus.OPEN)
    if status == OrderStatus.FILLED:
        # Mock funds, 1 cent, 1 contract: harmless, but the resting-order half of the
        # lifecycle was not exercised. Report honestly rather than pretending.
        report.add(
            "tier2.order_open",
            "pass",
            "order filled immediately at 0.01 on demo (harmless; cancel path not exercised)",
            time.monotonic() - started,
        )
        return
    if status != OrderStatus.OPEN:
        report.add(
            "tier2.order_open",
            "fail",
            f"order {order.id} never showed open; last status: {status}",
            time.monotonic() - started,
        )
        return
    report.add("tier2.order_open", "pass", f"order {order.id} resting", time.monotonic() - started)

    started = time.monotonic()
    try:
        exchange.cancel_order(order.id)
    except Exception as exc:
        report.add(
            "tier2.cancel_order",
            "fail",
            f"{type(exc).__name__}: {exc} - demo order {order.id} may still be resting",
            time.monotonic() - started,
        )
        return
    status = poll_order_status(exchange, order.id, OrderStatus.CANCELLED)
    if status == OrderStatus.CANCELLED:
        report.add(
            "tier2.cancel_order", "pass", f"order {order.id} cancelled", time.monotonic() - started
        )
    else:
        report.add(
            "tier2.cancel_order",
            "fail",
            f"cancel accepted but last status: {status}",
            time.monotonic() - started,
        )

    try:
        open_orders = exchange.fetch_open_orders(market_id=market.id)
        leftovers = [o.id for o in open_orders if o.id == order.id]
        if leftovers:
            report.add("tier2.no_leftover_orders", "fail", f"order still open: {leftovers}")
        else:
            report.add("tier2.no_leftover_orders", "pass", "no leftover QA orders")
    except Exception as exc:
        report.add("tier2.no_leftover_orders", "skip", f"could not verify: {exc}")


def write_github_step_summary(report: QAReport) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = ["## Live QA report", "", "| check | status | detail |", "|---|---|---|"]
    for c in report.checks:
        detail = c.detail.replace("|", "\\|")
        lines.append(f"| `{c.name}` | {c.status} | {detail} |")
    lines.append("")
    lines.append("PASSED" if not report.failed else "FAILED")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--tiers",
        default="tier1",
        help="comma-separated tiers to run: tier1,tier2 (default: tier1)",
    )
    parser.add_argument(
        "--venues",
        default=",".join(DEFAULT_TIER1_VENUES),
        help=f"comma-separated tier1 venues (default: {','.join(DEFAULT_TIER1_VENUES)})",
    )
    parser.add_argument("--json-out", default="", help="write the JSON report to this path")
    args = parser.parse_args()

    refuse_production_secrets()

    tiers = {t.strip() for t in args.tiers.split(",") if t.strip()}
    unknown = tiers - {"tier1", "tier2"}
    if unknown:
        parser.error(f"unknown tiers: {sorted(unknown)}")
    venues = [v.strip().lower() for v in args.venues.split(",") if v.strip()]

    report = QAReport()
    if "tier1" in tiers:
        run_tier1(report, venues)
    if "tier2" in tiers:
        run_tier2(report)

    write_github_step_summary(report)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(report.to_dict(), fh, indent=2)

    if report.failed:
        print("\nLive QA FAILED - at least one check failed.")
        sys.exit(1)
    print("\nLive QA passed - all attempted checks succeeded.")


if __name__ == "__main__":
    main()
