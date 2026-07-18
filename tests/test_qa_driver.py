"""Unit tests for the pure helpers in the live QA lane (scripts/qa/).

The tripwire test exists because the first review of the lane found a missing
key (POLYMARKET_OPERATOR_KEY) - the exact regression class these guard against.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "qa"))

import run_live_qa  # noqa: E402
import spawn_qa_sandbox  # noqa: E402


class TestTripwire:
    def test_refuses_every_forbidden_name(self, monkeypatch):
        for name in run_live_qa.FORBIDDEN_PRODUCTION_ENV:
            for cleared in run_live_qa.FORBIDDEN_PRODUCTION_ENV:
                monkeypatch.delenv(cleared, raising=False)
            monkeypatch.setenv(name, "0xdeadbeef")
            with pytest.raises(SystemExit) as excinfo:
                run_live_qa.refuse_production_secrets()
            assert excinfo.value.code == 2, name

    def test_operator_key_is_forbidden(self):
        # polymarket_operator.py signs on behalf of every approving user with this.
        assert "POLYMARKET_OPERATOR_KEY" in run_live_qa.FORBIDDEN_PRODUCTION_ENV

    def test_clean_environment_passes(self, monkeypatch):
        for name in run_live_qa.FORBIDDEN_PRODUCTION_ENV:
            monkeypatch.delenv(name, raising=False)
        run_live_qa.refuse_production_secrets()  # must not raise

    def test_demo_names_are_not_forbidden(self):
        assert "KALSHI_QA_DEMO_API_KEY_ID" not in run_live_qa.FORBIDDEN_PRODUCTION_ENV
        assert "KALSHI_QA_DEMO_PRIVATE_KEY_PEM" not in run_live_qa.FORBIDDEN_PRODUCTION_ENV


class TestMarketInvariants:
    @staticmethod
    def market(**overrides):
        base = dict(id="T-1", outcomes=["Yes", "No"], prices={"Yes": 0.4, "No": 0.6}, volume=10.0)
        base.update(overrides)
        return SimpleNamespace(**base)

    def test_clean_market(self):
        assert run_live_qa.check_market_invariants(self.market()) is None

    def test_empty_id(self):
        assert "empty id" in run_live_qa.check_market_invariants(self.market(id=""))

    def test_no_outcomes(self):
        assert "no outcomes" in run_live_qa.check_market_invariants(self.market(outcomes=[]))

    def test_price_out_of_range(self):
        problem = run_live_qa.check_market_invariants(self.market(prices={"Yes": 1.4}))
        assert "outside [0, 1]" in problem

    def test_negative_volume(self):
        assert "negative volume" in run_live_qa.check_market_invariants(self.market(volume=-1))


class TestNormalizePem:
    def test_expands_literal_newlines(self):
        assert run_live_qa.normalize_pem("a\\nb\\nc") == "a\nb\nc"

    def test_leaves_real_newlines_alone(self):
        assert run_live_qa.normalize_pem("a\nb") == "a\nb"
        # Mixed content (real newlines present) is left untouched.
        assert run_live_qa.normalize_pem("a\\nb\nc") == "a\\nb\nc"


class TestAllowlist:
    def test_tier1_excludes_demo_host(self):
        allow = spawn_qa_sandbox.build_allowlist("tier1")
        assert "demo-api.kalshi.co" not in allow
        assert "api.elections.kalshi.com" in allow
        assert "pypi.org" in allow

    def test_tier2_adds_only_demo_host(self):
        tier1 = set(spawn_qa_sandbox.build_allowlist("tier1"))
        both = set(spawn_qa_sandbox.build_allowlist("tier1,tier2"))
        assert both - tier1 == {"demo-api.kalshi.co"}

    def test_keyless_tier_has_no_predictfun(self):
        # Predict.fun requires an API key for all calls, so it cannot be reachable
        # from the keyless tier's firewall.
        assert "api.predict.fun" not in spawn_qa_sandbox.build_allowlist("tier1")
