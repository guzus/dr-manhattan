"""Spawn an egress-firewalled E2B sandbox and run the live QA driver inside it.

Runner-side half of the live QA lane (.github/workflows/qa-live.yml). The sandbox
is the isolation boundary: semi-trusted code (a PR branch, agent-authored changes)
executes inside a Firecracker microVM whose egress is deny-all plus an explicit
per-tier allowlist, and the only credentials that ever enter it are Kalshi DEMO
credentials (mock funds). E2B_API_KEY itself stays on the runner.

Environment contract (all optional unless noted):
  E2B_API_KEY                     required; consumed by the e2b SDK on the runner
  QA_REPO_URL                     clone URL (default: this repo on GitHub)
  QA_GIT_REF                      branch / tag / SHA to check out (default: main)
  QA_TIERS                        forwarded to run_live_qa.py --tiers (default: tier1)
  QA_VENUES                       forwarded to run_live_qa.py --venues when set
  QA_FIREWALL                     strict (default) | off. "off" is an explicit
                                  escape hatch for debugging only - it spawns with
                                  unrestricted egress and prints a loud warning.
  QA_SANDBOX_TIMEOUT_S            budget for the QA command itself (default: 1800;
                                  the sandbox TTL adds clone + setup + slack on top)
  KALSHI_QA_DEMO_API_KEY_ID       demo credentials, forwarded ONLY to the QA
  KALSHI_QA_DEMO_PRIVATE_KEY_PEM  command inside the sandbox

The egress allowlist is domain-based (E2B evaluates domains for ports 80/443), so
venues on non-standard ports (Opinion at proxy.opinion.trade:8443) are excluded
from firewalled runs - see run_live_qa.py. Firewall semantics reference:
https://e2b.dev/docs/sandbox/internet-access

    uv run --with 'e2b==2.34.*' python scripts/qa/spawn_qa_sandbox.py

The pin matters: the network kwarg is a runtime-unvalidated TypedDict, so an SDK
with different field names could silently drop the firewall; 2.34.x is the version
this configuration was verified against (build_network_config compiles it to
deny_out 0.0.0.0/0 + the allowlist).

Exit code mirrors the in-sandbox QA driver (0 pass, 1 fail, 2 refused/config).
"""

import os
import shlex
import sys

REPO_URL_DEFAULT = "https://github.com/guzus/dr-manhattan.git"
REPO_DIR = "/home/user/repo"
REPORT_PATH = f"{REPO_DIR}/qa-report.json"
CLONE_TIMEOUT_S = 600
SETUP_TIMEOUT_S = 900

# Toolchain endpoints every sandbox run needs: clone the repo, install uv, let uv
# fetch a CPython build and resolve wheels from the lockfile.
ALLOW_TOOLCHAIN = [
    "github.com",
    "codeload.github.com",
    "objects.githubusercontent.com",
    "raw.githubusercontent.com",
    "pypi.org",
    "files.pythonhosted.org",
]

# tier1: public, keyless market-data reads. api.predict.fun is deliberately absent:
# Predict.fun requires an API key even for market reads, so it is not part of the
# keyless tier (re-add alongside a PREDICTFUN QA credential if that changes).
ALLOW_TIER1 = [
    "gamma-api.polymarket.com",
    "clob.polymarket.com",
    "data-api.polymarket.com",
    "api.elections.kalshi.com",
    "api.limitless.exchange",
]

# tier2: the Kalshi DEMO host only. The production Kalshi host is already present
# via tier1 public reads; demo credentials cannot authenticate against it.
ALLOW_TIER2 = [
    "demo-api.kalshi.co",
]


def build_allowlist(tiers: str) -> list:
    allow = list(ALLOW_TOOLCHAIN)
    if "tier1" in tiers:
        allow += ALLOW_TIER1
    if "tier2" in tiers:
        allow += ALLOW_TIER2
    return allow


def main() -> None:
    if not os.environ.get("E2B_API_KEY"):
        print("E2B_API_KEY is not set; cannot spawn a sandbox.", file=sys.stderr)
        sys.exit(2)

    try:
        from e2b import CommandExitException, Sandbox
    except ImportError:
        print(
            "The e2b SDK is not installed. Run via: uv run --with 'e2b==2.34.*' python "
            "scripts/qa/spawn_qa_sandbox.py",
            file=sys.stderr,
        )
        sys.exit(2)

    repo_url = os.environ.get("QA_REPO_URL", REPO_URL_DEFAULT)
    git_ref = os.environ.get("QA_GIT_REF", "main")
    tiers = os.environ.get("QA_TIERS", "tier1")
    venues = os.environ.get("QA_VENUES", "")
    firewall = os.environ.get("QA_FIREWALL", "strict").lower()
    timeout_s = int(os.environ.get("QA_SANDBOX_TIMEOUT_S", "1800"))
    # The sandbox TTL starts at creation, so it must cover the whole clone + setup +
    # QA sequence, not just the QA command's own budget.
    sandbox_ttl_s = CLONE_TIMEOUT_S + SETUP_TIMEOUT_S + timeout_s + 120

    create_kwargs = {"timeout": sandbox_ttl_s}
    if firewall == "off":
        print("WARNING: QA_FIREWALL=off - sandbox egress is UNRESTRICTED (debug only).")
    else:
        allowlist = build_allowlist(tiers)
        # Deny everything, then allow the explicit list. E2B evaluates allow rules
        # with precedence over deny rules; domain rules cover ports 80/443.
        create_kwargs["network"] = {
            "deny_out": lambda ctx: [ctx.all_traffic],
            "allow_out": allowlist,
        }
        print(f"Egress firewall: deny-all + allowlist ({len(allowlist)} hosts)")
        for host in allowlist:
            print(f"  allow {host}")

    print(f"Spawning sandbox (timeout {timeout_s}s) for {repo_url} @ {git_ref} ...")
    try:
        sandbox = Sandbox.create(**create_kwargs)
    except TypeError as exc:
        # Do NOT fall back to an unfirewalled sandbox: a silent fallback would erase
        # the guarantee this lane exists to provide. Fail loudly instead.
        print(
            "Sandbox.create rejected the network configuration - the installed e2b SDK "
            f"may predate egress firewall support ({exc}). Refusing to run without the "
            "firewall; set QA_FIREWALL=off explicitly if you need a debug run.",
            file=sys.stderr,
        )
        sys.exit(2)

    exit_code = 1
    try:

        def run(cmd: str, timeout: int = CLONE_TIMEOUT_S, envs: dict = None) -> object:
            print(f"$ {cmd}", flush=True)
            try:
                result = sandbox.commands.run(cmd, timeout=timeout, envs=envs or {})
            except CommandExitException as exc:
                # The SDK raises on any non-zero exit; the exception carries the same
                # exit_code/stdout/stderr surface. Treat it as a result so failing QA
                # runs still reach the report-retrieval path and keep their exit code.
                result = exc
            if result.stdout:
                print(result.stdout, end="", flush=True)
            if result.stderr:
                print(result.stderr, end="", file=sys.stderr, flush=True)
            return result

        clone = run(
            f"git clone --depth 50 {shlex.quote(repo_url)} {REPO_DIR} && "
            f"cd {REPO_DIR} && (git checkout {shlex.quote(git_ref)} || "
            f"(git fetch --depth 1 origin {shlex.quote(git_ref)} && git checkout FETCH_HEAD))"
        )
        if clone.exit_code != 0:
            print("Repository checkout failed inside the sandbox.", file=sys.stderr)
            sys.exit(1)

        setup = run(
            f"cd {REPO_DIR} && pip install --quiet uv && uv python install 3.12 && uv sync",
            timeout=SETUP_TIMEOUT_S,
        )
        if setup.exit_code != 0:
            print("Dependency setup failed inside the sandbox.", file=sys.stderr)
            sys.exit(1)

        qa_cmd = (
            f"cd {REPO_DIR} && uv run python scripts/qa/run_live_qa.py --tiers {shlex.quote(tiers)}"
        )
        if venues:
            qa_cmd += f" --venues {shlex.quote(venues)}"
        qa_cmd += f" --json-out {REPORT_PATH}"

        # Demo credentials are injected only into this command's environment - they
        # are not part of the sandbox definition and never leave this process's env.
        qa_envs = {}
        for name in ("KALSHI_QA_DEMO_API_KEY_ID", "KALSHI_QA_DEMO_PRIVATE_KEY_PEM"):
            value = os.environ.get(name, "")
            if value:
                qa_envs[name] = value

        qa = run(qa_cmd, timeout=timeout_s, envs=qa_envs)
        exit_code = qa.exit_code

        try:
            report = sandbox.files.read(REPORT_PATH)
            with open("qa-report.json", "w", encoding="utf-8") as fh:
                fh.write(report)
            print("Report written to qa-report.json")
        except Exception as exc:
            print(f"Could not retrieve {REPORT_PATH}: {exc}", file=sys.stderr)
    finally:
        try:
            sandbox.kill()
        except Exception:
            pass

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
