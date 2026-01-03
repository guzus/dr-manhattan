"""Test session managers."""

import pytest

from dr_manhattan.mcp.session import (
    ExchangeSessionManager,
    StrategySessionManager,
)


class TestExchangeSessionManager:
    """Test ExchangeSessionManager."""

    def test_singleton_pattern(self):
        """Test manager is singleton."""
        mgr1 = ExchangeSessionManager()
        mgr2 = ExchangeSessionManager()
        assert mgr1 is mgr2

    def test_initialization(self):
        """Test manager initializes correctly."""
        mgr = ExchangeSessionManager()
        assert hasattr(mgr, "_exchanges")
        assert hasattr(mgr, "_clients")
        assert isinstance(mgr._exchanges, dict)
        assert isinstance(mgr._clients, dict)

    def test_has_exchange(self):
        """Test has_exchange method."""
        mgr = ExchangeSessionManager()
        mgr.cleanup()  # Clear any existing exchanges from previous tests
        # Initially no exchanges loaded
        assert not mgr.has_exchange("polymarket")

    def test_cleanup_no_crash(self):
        """Test cleanup doesn't crash."""
        mgr = ExchangeSessionManager()
        # Should not raise any exceptions
        mgr.cleanup()


class TestStrategySessionManager:
    """Test StrategySessionManager."""

    def test_singleton_pattern(self):
        """Test manager is singleton."""
        mgr1 = StrategySessionManager()
        mgr2 = StrategySessionManager()
        assert mgr1 is mgr2

    def test_initialization(self):
        """Test manager initializes correctly."""
        mgr = StrategySessionManager()
        assert hasattr(mgr, "_sessions")
        assert isinstance(mgr._sessions, dict)

    def test_list_sessions_empty(self):
        """Test listing sessions when none exist."""
        mgr = StrategySessionManager()
        mgr.cleanup()  # Clear any existing sessions
        sessions = mgr.list_sessions()
        assert isinstance(sessions, dict)

    def test_get_nonexistent_session(self):
        """Test getting non-existent session raises error."""
        mgr = StrategySessionManager()
        with pytest.raises(ValueError, match="Session not found"):
            mgr.get_session("nonexistent-id")

    def test_cleanup_no_crash(self):
        """Test cleanup doesn't crash."""
        mgr = StrategySessionManager()
        # Should not raise any exceptions
        mgr.cleanup()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
