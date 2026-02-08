from __future__ import annotations

from typing import Any, Dict, List

import requests

from ...base.errors import ExchangeError


class PolymarketBridge:
    """Bridge API mixin: cross-chain asset transfers (read-only)."""

    BRIDGE_URL = "https://bridge.polymarket.com"

    def fetch_supported_assets(self) -> List[Dict]:
        """
        Fetch supported bridge assets.

        Returns:
            List of supported asset dictionaries
        """

        @self._retry_on_failure
        def _fetch():
            resp = requests.get(
                f"{self.BRIDGE_URL}/supported-assets", timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get("supportedAssets", [])
            return []

        return _fetch()

    def fetch_bridge_status(self, address: str) -> Dict:
        """
        Fetch bridge transaction status.

        Args:
            address: Wallet address to check

        Returns:
            Bridge status dictionary
        """

        @self._retry_on_failure
        def _fetch():
            resp = requests.get(
                f"{self.BRIDGE_URL}/status/{address}", timeout=self.timeout
            )
            resp.raise_for_status()
            return resp.json()

        return _fetch()
